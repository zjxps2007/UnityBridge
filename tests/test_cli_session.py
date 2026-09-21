import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class SessionTests(unittest.TestCase):
    def env(self):
        return dict(os.environ, PYTHONPATH=str(ROOT / "src"), UNITY_BRIDGE_SKIP_UPDATE_CHECK="1")

    def test_disabled_updates_and_local_queries_do_not_import_updater_or_adapter(self):
        code = ("import sys; from unity_bridge.cli import main; "
                "main(['--json','--instances-dir','missing-fixture-directory','instances']); "
                "assert 'unity_bridge._cli.updates' not in sys.modules; "
                "assert 'urllib.request' not in sys.modules; "
                "assert 'unity_bridge.adapter' not in sys.modules")
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=self.env(), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_session_flushes_before_eof_and_survives_bad_requests(self):
        process = subprocess.Popen([sys.executable, "-m", "unity_bridge", "--json", "--instances-dir",
                                    "missing-fixture-directory", "session"], env=self.env(), cwd=ROOT,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8")
        try:
            requests = [('{bad}\n', 2), (json.dumps({"id": "first", "args": ["instances"]}) + "\n", 0),
                        (json.dumps({"id": 2, "args": ["update", "--check"]}) + "\n", 2),
                        (json.dumps({"id": 3, "args": ["exec", "--stdin"]}) + "\n", 2),
                        (json.dumps({"id": "last", "args": ["instances"]}) + "\n", 0)]
            import queue
            import threading
            lines = queue.Queue()
            def read():
                for line in process.stdout:
                    lines.put(line)
            threading.Thread(target=read, daemon=True).start()
            for raw, expected in requests:
                process.stdin.write(raw)
                process.stdin.flush()
                result = json.loads(lines.get(timeout=10))
                self.assertEqual(result["exit_code"], expected, result)
                if expected == 0:
                    self.assertEqual(result["result"], [])
                    self.assertIsNone(result["error"])
                self.assertIsNone(process.poll())
            process.stdin.close()
            self.assertEqual(process.wait(timeout=10), 0)
            self.assertEqual(process.stderr.read(), "")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def test_public_lazy_exports_preserve_api_identity(self):
        import unity_bridge
        from unity_bridge import adapter, client
        for name in unity_bridge.__all__:
            if name == "__version__":
                continue
            module = adapter if name in {"UnityActionResult", "UnityBridgeAdapter"} else client
            self.assertIs(getattr(unity_bridge, name), getattr(module, name))
            self.assertIn(name, dir(unity_bridge))

    def test_invalid_utf8_code_file_does_not_close_either_session_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'invalid.cs'
            path.write_bytes(b'\xff')
            raw = ''.join(json.dumps(value) + '\n' for value in (
                {'id': 'bad-file', 'args': ['exec', '--code-file', str(path)]},
                {'id': 'after-error', 'args': ['instances']}))
            for window in (1, 4):
                with self.subTest(window=window):
                    response = subprocess.run([sys.executable, '-B', '-m', 'unity_bridge', '--instances-dir',
                                               'missing-fixture-directory', 'session', '--pipeline', str(window)],
                                              input=raw, env=self.env(), cwd=ROOT, capture_output=True,
                                              text=True, encoding='utf-8', timeout=10)
                    self.assertEqual(response.returncode, 0, response.stderr)
                    rows = [json.loads(line) for line in response.stdout.splitlines()]
                    self.assertEqual([(r['id'], r['exit_code']) for r in rows], [('bad-file', 2), ('after-error', 0)])
                    self.assertEqual(rows[1]['result'], [])


if __name__ == "__main__":
    unittest.main()
