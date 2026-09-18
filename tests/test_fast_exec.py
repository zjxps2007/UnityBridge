"""Exercise the lightweight Python entry point against the actual host queues."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity_bridge import __version__
from unity_bridge._wire import read_frame, write_frame
from unity_bridge.host import cli_server
from unity_bridge.host.cli_request import execute_cli
from unity_bridge.host.registry import atomic_json, endpoint_path, read_json, register_launcher
from tests import test_host_service


class FastExecTests(unittest.TestCase):
    def setUp(self):
        executable = os.environ.get("UNITY_BRIDGE_TEST_CLI_EXE")
        self.executable = str(Path(executable).resolve()) if executable else None
        self.fixture = test_host_service.HostServiceTests()
        self.addCleanup(self.fixture.doCleanups)
        def register(executable, worker, **kwargs):
            return register_launcher(self.executable or executable, worker,
                                     **dict(kwargs, version=__version__, python_module=not self.executable))
        with patch("tests.test_host_service.register_launcher", side_effect=register):
            self.fixture.setUp()
        self.fixture.snapshot["connectorVersion"] = __version__
        self.fixture.publish_snapshot()

    def command(self, *args, env=None, stdin=None, cwd=None, check_imports=False):
        fixture = self.fixture
        environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8", UNITY_BRIDGE_SKIP_UPDATE_CHECK="1",
                           UNITY_BRIDGE_HOST_HOME=str(fixture.root))
        environment.update(env or {})
        prefix = [self.executable] if self.executable else [sys.executable, "-B", "-m", "unity_bridge"]
        if check_imports and not self.executable:
            prefix = [sys.executable, "-B", "-c", (
                "import sys; from unity_bridge._bootstrap import main; result=main(sys.argv[1:]); "
                "assert 'unity_bridge.cli' not in sys.modules; "
                "assert 'unity_bridge.client' not in sys.modules; "
                "assert 'unity_bridge.adapter' not in sys.modules; "
                "assert 'argparse' not in sys.modules; raise SystemExit(result)")]
        return subprocess.run(prefix + ["--instances-dir", str(fixture.instances), "--json", *args],
                              cwd=cwd or ROOT, env=environment, input=stdin, text=True, encoding="utf-8",
                              capture_output=True, timeout=10)

    def request(self, **changes):
        return dict({"cli_protocol": 1, "version": __version__, "argv": ["--json", "exec", "--code", "sample"],
                     "cwd": str(self.fixture.directory), "instances_dir": str(self.fixture.instances),
                     "code": "sample", "deadline_unix_ms": int(time.time() * 1000) + 2000}, **changes)

    def test_real_fast_entry_skips_full_cli_and_preserves_result(self):
        with patch.object(cli_server, "execute_cli", wraps=execute_cli) as calls:
            fast = self.command("exec", "--code", "return 42;", "--using", "System", check_imports=True)
            slow = self.command("exec", "--code", "return 42;", "--using", "System",
                                env={"UNITY_BRIDGE_DISABLE_FAST_EXEC": "1"})
        self.assertEqual(fast.returncode, 0, fast.stderr)
        self.assertEqual(slow.returncode, 0, slow.stderr)
        self.assertEqual(json.loads(fast.stdout), json.loads(slow.stdout))
        self.assertEqual(calls.call_count, 1)
        self.assertEqual(self.fixture.executed, ["return 42;"] * 2)

    def test_relative_file_and_unicode_stdin(self):
        code = 'return "한글 😀";\n'
        path = self.fixture.directory / "sample code.cs"
        path.write_text(code, encoding="utf-8")
        file_result = self.command("exec", "--file", path.name, cwd=self.fixture.directory, check_imports=True)
        stdin_result = self.command("exec", "--stdin", stdin=code, check_imports=True)
        for result in (file_result, stdin_result):
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["params"]["code"], code)
        self.assertEqual(self.fixture.executed, [code, code])

    def test_dial_failure_falls_back_before_dispatch_and_preserves_stdin(self):
        path = endpoint_path(self.fixture.root, self.fixture.descriptor["runtimeId"])
        endpoint = read_json(path)
        with socket.socket() as unused:
            unused.bind(("127.0.0.1", 0))
            endpoint["cliPort"] = unused.getsockname()[1]
            atomic_json(path, endpoint)
            result = self.command("exec", "--stdin", stdin="only-once")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fixture.executed, ["only-once"])

    def test_disconnect_after_execution_is_unknown_and_never_replayed(self):
        def disconnect(connection, data, deadline):
            connection.shutdown(socket.SHUT_RDWR)
            raise OSError("Lost response fixture")
        with patch.object(cli_server, "write_frame", side_effect=disconnect):
            result = self.command("exec", "--code", "one-mutation")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["data"]["completion"], "unknown")
        self.assertEqual(self.fixture.executed, ["one-mutation"])
        self.assertEqual(len(self.fixture.compiler.calls), 1)

    def test_concurrent_requests_keep_outputs_separate(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = [pool.submit(self.command, "exec", "--code", text) for text in ("first", "second")]
            results = [job.result() for job in pending]
        self.assertEqual([json.loads(result.stdout)["data"] for result in results], ["first", "second"])
        self.assertEqual(len(self.fixture.executed), 2)

    def test_original_deadline_prevents_expired_exec(self):
        response = execute_cli(self.fixture.service, self.request(deadline_unix_ms=int(time.time() * 1000) - 1))
        self.assertEqual(response["exit_code"], 1)
        value = json.loads(response["stdout"])
        self.assertEqual(value["data"]["reason"], "expired")
        self.assertEqual(self.fixture.executed, [])
        self.assertEqual(self.fixture.compiler.calls, [])

    def test_timeout_during_compilation_never_executes_late(self):
        self.fixture.compiler.release.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.command, "--timeout-ms", "150", "exec", "--code", "must-not-execute")
            self.assertTrue(self.fixture.compiler.started.wait(3))
            result = pending.result(timeout=5)
        # The transport deadline can beat the host's expiry response. Either
        # unknown or not_started is conservative; the mutation must never run.
        self.assertIn(json.loads(result.stdout)["data"]["completion"], {"unknown", "not_started"})
        self.fixture.compiler.release.set()
        recovered = self.command("exec", "--code", "after-expiry")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(self.fixture.executed, ["after-expiry"])

    def test_authentication_required_before_cli_execution(self):
        payload = self.request(token="wrong")
        with socket.create_connection(self.fixture.service.cli_server.server_address, timeout=2) as connection:
            write_frame(connection, json.dumps(payload).encode(), time.monotonic() + 2)
            result = json.loads(read_frame(connection, time.monotonic() + 2))
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("authentication", result["stderr"])
        self.assertEqual(self.fixture.executed, [])

    def test_malformed_or_oversized_frames_never_execute(self):
        for frame in (b"\x00\x00\x00\x00", b"\x02\x00\x00\x01", b"\x00\x00\x00\x03{", b"\x00\x00\x00\x02[]"):
            with self.subTest(frame=frame), socket.create_connection(self.fixture.service.cli_server.server_address, timeout=2) as connection:
                connection.sendall(frame)
                connection.shutdown(socket.SHUT_WR)
                self.assertEqual(connection.recv(1), b"")
        self.assertEqual(self.fixture.executed, [])
        self.assertEqual(self.fixture.compiler.calls, [])

    def test_older_host_keeps_existing_http_route(self):
        path = endpoint_path(self.fixture.root, self.fixture.descriptor["runtimeId"])
        endpoint = read_json(path)
        endpoint.pop("cliProtocol")
        endpoint.pop("cliPort")
        atomic_json(path, endpoint)
        with patch.object(cli_server, "execute_cli", wraps=execute_cli) as calls:
            result = self.command("exec", "--code", "compatible-fallback")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.call_count, 0)
        self.assertEqual(self.fixture.executed, ["compatible-fallback"])

    def test_non_json_output_and_warning_match_existing_cli(self):
        self.fixture.snapshot["connectorVersion"] = "0.0.1"
        self.fixture.publish_snapshot()
        # Use the actual caller arguments here; command() normally selects JSON.
        prefix = [self.executable] if self.executable else [sys.executable, "-B", "-m", "unity_bridge"]
        argv = prefix + ["--no-update-check", "--instances-dir", str(self.fixture.instances), "exec", "--code", "same-text"]
        environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"), UNITY_BRIDGE_HOST_HOME=str(self.fixture.root))
        fast = subprocess.run(argv, env=environment, text=True, capture_output=True, timeout=5)
        slow = subprocess.run(argv, env=dict(environment, UNITY_BRIDGE_DISABLE_FAST_EXEC="1"), text=True, capture_output=True, timeout=5)
        self.assertEqual((fast.returncode, fast.stdout, fast.stderr), (slow.returncode, slow.stdout, slow.stderr))
        self.assertIn("WARNING:", fast.stderr)

    def test_parser_errors_stay_local_to_request(self):
        bad = execute_cli(self.fixture.service, self.request(argv=["--json", "exec", "--invalid"]))
        self.assertEqual(bad["exit_code"], 2)
        self.assertIn("usage:", bad["stderr"])
        good = self.command("exec", "--code=after-error", check_imports=True)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(self.fixture.executed, ["after-error"])

    def test_legacy_and_compiler_overrides_keep_existing_route(self):
        with patch.object(cli_server, "execute_cli", wraps=execute_cli) as calls:
            legacy = self.command("--backend", "legacy", "exec", "--code", "legacy")
            override = self.command("exec", "--code", "override", "--csc", "custom-compiler")
            legacy_baseline = self.command("--backend", "legacy", "exec", "--code", "legacy",
                                           env={"UNITY_BRIDGE_DISABLE_FAST_EXEC": "1"})
        # The host test Connector requires authentication even for the legacy
        # endpoint. Preserve that pre-existing rejection instead of rerouting it.
        self.assertEqual(legacy.returncode, legacy_baseline.returncode)
        self.assertEqual(legacy.stderr, legacy_baseline.stderr)
        self.assertEqual(override.returncode, legacy_baseline.returncode)
        self.assertEqual(calls.call_count, 0)
        self.assertEqual(self.fixture.compiler.calls, [])

    def test_update_check_gate_matches_existing_daily_schedule(self):
        from unity_bridge._fast_exec import _update_due
        from unity_bridge._cli.updates import _auto_update_check_due
        path = self.fixture.directory / "update-check.json"
        options = {"json": False, "no_update": False}
        with patch.dict(os.environ, {"UNITY_BRIDGE_SKIP_UPDATE_CHECK": "0"}):
            for age in (100, 86410):
                payload = {"checked_at": time.time() - age}
                path.write_text(json.dumps(payload))
                with patch("unity_bridge._fast_exec._read_json", return_value=payload):
                    self.assertEqual(_update_due(options), _auto_update_check_due(path, now=time.time()))
            with patch("unity_bridge._fast_exec._read_json", return_value=None):
                self.assertTrue(_update_due(options))
                self.assertFalse(_update_due(dict(options, json=True)))
                self.assertFalse(_update_due(dict(options, no_update=True)))


if __name__ == "__main__":
    unittest.main()
