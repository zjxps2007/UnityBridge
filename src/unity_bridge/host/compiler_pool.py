"""Opt-in two-worker experiment. The production default stays one worker."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time

from .compiler import CompilerError, CompilerWorker


def create_compiler(executable):
    if os.environ.get('UNITY_BRIDGE_EXPERIMENTAL_COMPILER_WORKERS') == '2':
        return CompilerPool(executable)
    return CompilerWorker(executable)


class CompilerPool:
    """Foreground always has the primary; only a prepared secondary speculates.

    One additional context at a time is prepared, using an innocuous snippet that
    never goes to Unity. Retirement detaches an idle child before closing it, so
    the idle reaper cannot stop a child that has just accepted a new request.
    """
    def __init__(self, executable, *, worker_factory=CompilerWorker, idle_seconds=30.):
        self.executable, self.factory = executable, worker_factory
        # Bound parallel reference IO across both experimental workers.
        self.environment = {'UNITY_BRIDGE_REFERENCE_PARALLELISM': '2' if (os.cpu_count() or 1) >= 4 else '1'}
        self.primary = worker_factory(executable, environment=self.environment)
        self.secondary = None
        self.ready_key = None
        self.busy = False
        self.last_used = 0.
        self.idle_seconds = idle_seconds
        self.condition = threading.Condition()
        self.closed = False
        self.reaper = threading.Thread(target=self._retire_idle, name='unity-compiler-retirement', daemon=True)
        self.reaper.start()

    @property
    def last_info(self):
        with self.condition:
            return dict(self.primary.last_info, secondary_prepared=self.ready_key is not None,
                        worker_count=1 + int(self.secondary is not None))

    def can_prepare(self, context):
        key = self._key({'operation': 'compile', 'references': context.references,
                         'reference_generation': context.compiler_reference_generation,
                         'project_id': context.project_id, 'language_version': context.language_version})
        with self.condition:
            return self.secondary is not None and self.ready_key == key and not self.busy

    @staticmethod
    def _key(payload):
        if payload.get('operation') != 'compile':
            return None
        context = {key: payload.get(key) for key in ('references', 'reference_generation', 'project_id', 'language_version')}
        return hashlib.sha256(json.dumps(context, sort_keys=True).encode()).digest()

    def start(self):
        self.primary.start()

    def warmup(self):
        return self.primary.warmup()

    def prewarm(self):
        return self.primary.prewarm()

    def request(self, payload, *, deadline, background=False):
        key = self._key(payload)
        worker = self.primary
        with self.condition:
            if self.closed:
                raise CompilerError('compiler_unavailable', 'Compiler pool is closed')
            if background and key is not None and self.ready_key == key and self.secondary is not None and not self.busy:
                worker = self.secondary
                self.busy = True
        if worker is not self.primary:
            try:
                return worker.request(payload, deadline=deadline, background=True)
            except CompilerError:
                with self.condition:
                    self.ready_key = None
                raise
            finally:
                with self.condition:
                    self.busy = False
                    self.last_used = time.perf_counter()
                    self.condition.notify_all()
        result = worker.request(payload, deadline=deadline, background=background)
        if key is not None:
            self._prepare(payload, key)
        return result

    def _prepare(self, payload, key):
        with self.condition:
            if self.closed or self.busy or self.ready_key == key:
                return
            if self.secondary is None:
                self.secondary = self.factory(self.executable, environment=self.environment)
            worker = self.secondary
            self.busy, self.ready_key = True, None
        def prepare():
            ready = False
            try:
                worker.start()
                worker.warmup()
                worker.request(dict(payload, code='return null;', usings=[], parent_request_id=None),
                               deadline=time.perf_counter() + 30., background=True)
                ready = True
            except Exception:
                pass  # An experimental warmup failure cannot fail foreground work.
            finally:
                with self.condition:
                    self.ready_key = key if ready and not self.closed else None
                    self.busy = False
                    self.last_used = time.perf_counter()
                    self.condition.notify_all()
        threading.Thread(target=prepare, name='unity-compiler-secondary-prepare', daemon=True).start()

    def _retire_idle(self):
        while True:
            with self.condition:
                if self.closed:
                    return
                remaining = self.idle_seconds - (time.perf_counter() - self.last_used)
                if self.secondary is None or self.busy or remaining > 0:
                    self.condition.wait(max(.01, remaining) if self.secondary is not None and not self.busy else self.idle_seconds)
                    continue
                worker, self.secondary = self.secondary, None
                self.ready_key = None
            worker.close()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
            while self.busy:
                self.condition.wait(.1)
            worker = self.secondary
        self.primary.close()
        if worker is not None:
            worker.close()
        self.reaper.join(2)
