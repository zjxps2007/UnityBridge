from pathlib import Path
import sys
import tempfile
import time
import unittest

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


if __name__ == "__main__":
    unittest.main()
