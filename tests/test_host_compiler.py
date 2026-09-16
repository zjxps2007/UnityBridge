from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from unity_bridge.host.compiler import CompilerError, CompilerWorker


WORKER = '''import json,sys,time
for line in sys.stdin:
    value=json.loads(line)
    if value.get('operation')=='slow': time.sleep(10)
    if value.get('operation')=='exit': sys.exit(1)
    result={'protocol':1,'request_id':value['request_id'],'success':True,'compiler_version':'fixture'}
    if value.get('operation')=='error': result.update(success=False,error_code='compile_error',error='Compile error: fixture',diagnostics=[{'id':'CS0001'}])
    print(json.dumps(result),flush=True)
'''


class CompilerWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="host-compiler-")
        self.addCleanup(self.temp.cleanup)
        script = Path(self.temp.name) / "worker.py"
        script.write_text(WORKER)
        self.worker = CompilerWorker(sys.executable, argv=[sys.executable, "-u", str(script)])
        self.addCleanup(self.worker.close)

    def test_ping_reuses_process_and_compiler_error_preserves_worker(self):
        result = self.worker.prewarm()
        pid = self.worker.process.pid
        self.assertEqual(result["compiler_version"], "fixture")
        with self.assertRaises(CompilerError) as failed:
            self.worker.request({"operation": "error"}, deadline=time.monotonic() + 2)
        self.assertEqual(failed.exception.code, "compile_error")
        self.assertEqual(failed.exception.diagnostics, [{"id": "CS0001"}])
        self.worker.prewarm()
        self.assertEqual(self.worker.process.pid, pid)

    def test_timeout_kills_worker_then_next_request_starts_a_new_worker(self):
        self.worker.prewarm()
        first_process = self.worker.process
        with self.assertRaises(CompilerError) as failed:
            self.worker.request({"operation": "slow"}, deadline=time.monotonic() + .1)
        self.assertEqual(failed.exception.code, "compiler_timeout")
        self.assertIsNotNone(first_process.poll())
        self.assertIsNone(self.worker.process)
        self.assertTrue(self.worker.prewarm()["success"])

    def test_exited_worker_does_not_hang_and_can_restart(self):
        with self.assertRaises(CompilerError) as failed:
            self.worker.request({"operation": "exit"}, deadline=time.monotonic() + 2)
        self.assertEqual(failed.exception.code, "compiler_exited")
        self.assertTrue(self.worker.prewarm()["success"])

    def test_deadline_covers_blocked_write_when_worker_does_not_read_stdin(self):
        original_argv = self.worker.argv
        self.worker.argv = [sys.executable, "-u", "-c", "import time; time.sleep(10)"]
        started = time.monotonic()
        with self.assertRaises(CompilerError) as failed:
            self.worker.request({"operation": "compile", "code": "x" * (1024 * 1024)},
                                deadline=time.monotonic() + .15)
        self.assertEqual(failed.exception.code, "compiler_timeout")
        self.assertLess(time.monotonic() - started, 3)
        self.assertIsNone(self.worker.process)
        self.worker.argv = original_argv
        self.assertTrue(self.worker.prewarm()["success"])

    def test_started_watchdog_finishes_before_request_releases_worker(self):
        self.worker.prewarm()
        callback_started = threading.Event()
        callback_release = threading.Event()
        cancellation_requested = threading.Event()
        request_finished = threading.Event()
        errors = []

        class StartedWatchdog(threading.Thread):
            # Simulate Timer.run having passed its cancellation check just before
            # the response arrives, but not yet entered the timeout callback.
            def __init__(self, interval, callback):
                super().__init__()
                self.callback = callback

            def run(self):
                callback_started.set()
                callback_release.wait(5)
                self.callback()

            def start(self):
                super().start()
                if not callback_started.wait(2):
                    raise RuntimeError("Fixture watchdog did not start")

            def cancel(self):
                cancellation_requested.set()

        def request():
            try:
                self.worker.prewarm()
            except CompilerError as exc:
                errors.append(exc)
            finally:
                request_finished.set()

        with patch("unity_bridge.host.compiler.threading.Timer", StartedWatchdog):
            thread = threading.Thread(target=request)
            thread.start()
            try:
                self.assertTrue(cancellation_requested.wait(2))
                self.assertFalse(request_finished.wait(.1), "Started timeout callback must finish before another request can use the worker")
                self.assertTrue(self.worker.lock.locked())
            finally:
                callback_release.set()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual([error.code for error in errors], ["compiler_timeout"])
        self.assertIsNone(self.worker.process)
        self.assertTrue(self.worker.prewarm()["success"])


if __name__ == "__main__":
    unittest.main()
