"""Opt-in stage timings; no code, parameters, results, or credentials are logged."""
import os

_directory = os.environ.get('UNITY_BRIDGE_TIMING_DIR')
if _directory:
    from threading import Lock
    _write_lock = Lock()


def mark(stage, request_id=None, *, parent_request_id=None):
    if not _directory:
        return
    import json
    import time
    from pathlib import Path
    try:
        directory = Path(_directory)
        directory.mkdir(parents=True, exist_ok=True)
        # One append per event, separate files per process. No stdout changes.
        value = {'stage': stage, 'pid': os.getpid(), 'ns': time.perf_counter_ns(),
                 'unix_ns': time.time_ns(), 'request_id': request_id}
        if parent_request_id is not None:
            value['parent_request_id'] = parent_request_id
        # Windows append handles do not make separate threads' writes atomic.
        # Keep complete JSONL records together; the disabled path imports no locks.
        with _write_lock:
            with (directory / f'{os.getpid()}.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(value) + '\n')
    except OSError:
        pass  # Diagnostics must not affect command semantics.
