"""A serialized, restartable Roslyn JSONL worker; no Unity code executes here."""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .transport import MAX_MESSAGE_BYTES
from .._timing import mark


class CompilerError(Exception):
    def __init__(self, code: str, message: str, diagnostics: list | None = None):
        super().__init__(message)
        self.code = code
        self.diagnostics = diagnostics or []


class CompilerWorker:
    def __init__(self, executable: str, *, argv: list[str] | None = None):
        self.argv = argv or [str(Path(executable).resolve())]
        self.lock = threading.Lock()
        self.priority_lock = threading.Lock()
        self.foreground_waiters = 0
        self.process: subprocess.Popen | None = None
        self.responses: queue.Queue = queue.Queue()
        self.stderr_tail = ""
        self.last_info: dict[str, Any] = {}

    def _start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self._stop()
        self.responses = queue.Queue()
        self.stderr_tail = ""
        try:
            mark('compiler_spawn_begin')
            self.process = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                            bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            raise CompilerError("compiler_unavailable", "Could not start the bundled C# compiler") from exc
        process, responses = self.process, self.responses
        mark('compiler_spawn_end')

        def read_stdout():
            try:
                while True:
                    line = process.stdout.readline(MAX_MESSAGE_BYTES + 1)
                    if not line:
                        break
                    if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES or not line.endswith("\n"):
                        responses.put(CompilerError("compiler_protocol", "Compiler returned an oversized response"))
                        return
                    try:
                        responses.put(json.loads(line))
                    except ValueError:
                        responses.put(CompilerError("compiler_protocol", "Compiler returned invalid JSON"))
                        return
            except (OSError, ValueError):
                pass
            finally:
                responses.put(CompilerError("compiler_exited", "Compiler exited before returning a result"))

        def read_stderr():
            try:
                for line in process.stderr:
                    self.stderr_tail = (self.stderr_tail + line)[-8192:]
            except (OSError, ValueError):
                pass

        threading.Thread(target=read_stdout, name="unity-compiler-output", daemon=True).start()
        threading.Thread(target=read_stderr, name="unity-compiler-errors", daemon=True).start()

    def _stop(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    def start(self) -> None:
        """Start the runtime without waiting for project metadata or a compile."""
        with self.lock:
            self._start()

    def request(self, payload: dict[str, Any], *, deadline: float, background: bool = False) -> dict[str, Any]:
        """Use an absolute time.perf_counter() deadline, including queue time."""
        remaining = deadline - time.perf_counter()
        if background:
            # Background preparation never joins the queue ahead of real work.
            with self.priority_lock:
                acquired = remaining > 0 and not self.foreground_waiters and self.lock.acquire(blocking=False)
            if not acquired:
                raise CompilerError("prewarm_deferred", "Compiler is serving an execution request")
        else:
            with self.priority_lock:
                self.foreground_waiters += 1
            try:
                acquired = remaining > 0 and self.lock.acquire(timeout=max(0, remaining))
            finally:
                with self.priority_lock:
                    self.foreground_waiters -= 1
        if not acquired:
            raise CompilerError("expired", "Request expired before the compiler was available")
        try:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise CompilerError("expired", "Request expired before compilation")
            compile_deadline = min(deadline, time.perf_counter() + 30.)
            self._start()
            request_id = uuid.uuid4().hex
            mark('compiler_request_begin', request_id)
            message = dict(payload, protocol=1, request_id=request_id)
            raw = json.dumps(message, ensure_ascii=False)
            if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
                raise CompilerError("compile_error", "Compiler input exceeds the message size limit")
            timed_out = threading.Event()
            process = self.process

            def kill_hung_worker():
                # Pipe writes can block before responses.get() is reached. Killing
                # this captured child also releases a writer blocked on a full pipe.
                timed_out.set()
                try:
                    process.kill()
                except OSError:
                    pass

            watchdog = threading.Timer(max(.001, compile_deadline - time.perf_counter()), kill_hung_worker)
            watchdog.daemon = True
            watchdog.start()
            try:
                process.stdin.write(raw + "\n")
                process.stdin.flush()
                response = self.responses.get(timeout=max(.001, compile_deadline - time.perf_counter()))
            except (OSError, BrokenPipeError, queue.Empty) as exc:
                self._stop()
                raise CompilerError("compiler_timeout", "Compiler failed to respond within its time limit") from exc
            finally:
                watchdog.cancel()
                # cancel() cannot stop a callback that has already started. Join
                # before releasing the worker so it cannot kill the next request.
                watchdog.join()
            if timed_out.is_set():
                self._stop()
                raise CompilerError("compiler_timeout", "Compiler failed to respond within its time limit")
            if isinstance(response, Exception):
                self._stop()
                raise response
            if (not isinstance(response, dict) or response.get("protocol") != 1
                    or response.get("request_id") != request_id):
                self._stop()
                raise CompilerError("compiler_protocol", "Compiler returned a mismatched response")
            if not response.get("success"):
                raise CompilerError(str(response.get("error_code", "compile_error")),
                                    str(response.get("error", "Compilation failed")), response.get("diagnostics"))
            self.last_info = {key: response[key] for key in
                              ("compiler_version", "cache_hit", "base_cache_hit", "emit_reused", "assembly_name") if key in response}
            mark('compiler_request_end', request_id)
            return response
        finally:
            self.lock.release()

    def prewarm(self) -> dict[str, Any]:
        return self.request({"operation": "ping"}, deadline=time.perf_counter() + 30)

    def warmup(self) -> dict[str, Any]:
        return self.request({"operation": "warmup"}, deadline=time.perf_counter() + 30, background=True)

    def close(self) -> None:
        with self.lock:
            self._stop()
