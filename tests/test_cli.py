from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity_bridge import __version__, CommandResponse, Instance, UnityActionResult, UnityConnectionError
from unity_bridge._cli import output as cli_output
from unity_bridge._cli import standalone as cli_standalone
from unity_bridge._cli import updates as cli_updates
from unity_bridge.cli import main as cli_main
from unity_bridge.client import scan_instances
from tests.helpers import FakeUnityServer, write_instance


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._update_check_env = patch.dict(os.environ, {"UNITY_BRIDGE_SKIP_UPDATE_CHECK": "1"})
        self._update_check_env.start()

    def tearDown(self) -> None:
        self._update_check_env.stop()

    def test_cli_requests_match_pre_refactor_wire_contract(self) -> None:
        fixture = json.loads((ROOT / "tests/fixtures/cli_requests.json").read_text(encoding="utf-8"))
        response = json.dumps({"success": True, "message": "ok", "data": {"marker": [1, 2]}}).encode()
        for case in fixture["cases"]:
            with self.subTest(argv=case["argv"]), TemporaryDirectory() as tmp, FakeUnityServer(response) as server:
                write_instance(Path(tmp), "game", port=server.port, pid=0)
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr), patch("sys.stdin", StringIO(case["stdin"])):
                    code = cli_main(["--json", "--instances-dir", tmp, *case["argv"]])
                self.assertEqual(code, 0, stderr.getvalue())
                self.assertEqual(stderr.getvalue(), "")
                self.assertTrue(json.loads(stdout.getvalue())["success"])
                self.assertEqual([row["body"] for row in server.received], [case["request"]])

    def test_cli_json_transport_errors_use_stderr_for_both_routes(self) -> None:
        for command in ["console", "custom_tool"]:
            with self.subTest(command=command), TemporaryDirectory() as tmp, FakeUnityServer(b"unavailable", status=503) as server:
                write_instance(Path(tmp), "game", port=server.port, pid=0)
                stdout, stderr = StringIO(), StringIO()
                with warnings.catch_warnings(), redirect_stdout(stdout), redirect_stderr(stderr):
                    # urllib's HTTPError cleanup warning is enabled by unittest
                    # on Python 3.14; this check covers CLI protocol output.
                    warnings.simplefilter("ignore", ResourceWarning)
                    code = cli_main(["--json", "--instances-dir", tmp, command])
                self.assertEqual(code, 1)
                self.assertEqual(stdout.getvalue(), "")
                error = json.loads(stderr.getvalue())
                self.assertEqual(set(error), {"ok", "error"})
                self.assertFalse(error["ok"])
                self.assertIn("unavailable", error["error"])

    def test_cli_failed_tool_response_uses_stdout_and_failure_exit_code(self) -> None:
        response = json.dumps({"success": False, "message": "rejected", "data": {"reason": "busy"}}).encode()
        for command in ["console", "custom_tool"]:
            with self.subTest(command=command), TemporaryDirectory() as tmp, FakeUnityServer(response) as server:
                write_instance(Path(tmp), "game", port=server.port, pid=0)
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = cli_main(["--json", "--instances-dir", tmp, command])
                self.assertEqual(code, 1)
                self.assertEqual(stderr.getvalue(), "")
                result = json.loads(stdout.getvalue())
                self.assertFalse(result["success"])
                self.assertEqual(result["message"], "rejected")
                self.assertEqual(result["data"], {"reason": "busy"})

    def test_cli_version_fallback_reads_repository_pyproject(self) -> None:
        import importlib.metadata

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[project]\nversion = "9.8.7"\n', encoding="utf-8")
            with (
                patch.object(cli_updates, "__file__", str(root / "src/unity_bridge/_cli/updates.py")),
                patch.object(cli_standalone.sys, "frozen", False, create=True),
                patch("importlib.metadata.version", side_effect=importlib.metadata.PackageNotFoundError),
            ):
                self.assertEqual(cli_updates._current_package_version(), "9.8.7")

    def test_cli_module_and_standalone_entry_points_keep_the_same_help(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            cli_main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        expected = stdout.getvalue()
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        for entry in [["-m", "unity_bridge"], ["-m", "unity_bridge.cli"], [str(ROOT / "scripts/pyinstaller_entry.py")]]:
            with self.subTest(entry=entry):
                result = subprocess.run([sys.executable, *entry, "--help"], capture_output=True, text=True,
                                        encoding="utf-8", env=env, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(result.stdout, expected)

    def _wait_ready_timeline(
        self,
        timeline: list[tuple[float, dict[str, object] | None]],
        live_timeline: list[tuple[float, dict[str, object] | CommandResponse | Exception]],
        *,
        timeout_sec: int = 3,
        port: int | None = None,
    ) -> tuple[int, str, str, float, list[dict[str, object]]]:
        """Exercise CLI/discovery with independent file and live editor states."""
        clock = {"now": 0.0}
        calls: list[dict[str, object]] = []
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)

            def publish() -> None:
                payload = next(value for at, value in reversed(timeline) if at <= clock["now"])
                if payload is None:
                    (directory / "game.json").unlink(missing_ok=True)
                else:
                    write_instance(directory, "game", pid=0, **payload)

            def advance(seconds: float) -> None:
                clock["now"] += seconds
                publish()

            def query(instance: Instance, command: str, params: dict[str, object], *, timeout_ms: int) -> CommandResponse:
                self.assertEqual(command, "get_editor_state")
                self.assertTrue(params["request_id"])
                calls.append({"at": clock["now"], "port": instance.port, "timeout_ms": timeout_ms})
                value = next(value for at, value in reversed(live_timeline) if at <= clock["now"])
                if isinstance(value, Exception):
                    raise value
                if isinstance(value, CommandResponse):
                    return value
                state = instance.to_dict()
                state.update(value)
                return CommandResponse(True, "Current editor state", {
                    "requestId": params["request_id"], "instance": state,
                })

            publish()
            args = ["--json", "--instances-dir", str(directory), "wait-ready", "--timeout-sec", str(timeout_sec)]
            if port is not None:
                args.extend(["--port", str(port)])
            stdout = StringIO()
            stderr = StringIO()
            with (
                patch("unity_bridge.client.time.monotonic", side_effect=lambda: clock["now"]),
                patch("unity_bridge.client.time.sleep", side_effect=advance),
                patch("unity_bridge.client.send_command", side_effect=query),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = cli_main(args)
        return exit_code, stdout.getvalue(), stderr.getvalue(), clock["now"], calls

    def test_cli_wait_ready_checks_live_state_instead_of_old_ready_file(self) -> None:
        exit_code, stdout, stderr, elapsed, calls = self._wait_ready_timeline([
            (0, {"state": "ready", "timestamp": 10}),
        ], [
            (0, {"state": "compiling", "timestamp": 11}),
            (0.8, {"state": "ready", "timestamp": 12}),
        ])
        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(json.loads(stdout)["timestamp"], 12)
        self.assertAlmostEqual(elapsed, 1.0)
        self.assertEqual(len(calls), 3)

    def test_cli_wait_ready_has_no_settling_delay_after_live_confirmation(self) -> None:
        exit_code, stdout, stderr, elapsed, calls = self._wait_ready_timeline([
            (0, {"state": "ready", "timestamp": 10}),
        ], [
            (0, {"state": "ready", "timestamp": 20}),
        ])
        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(json.loads(stdout)["timestamp"], 20)
        self.assertEqual(elapsed, 0)
        self.assertEqual(len(calls), 1)

    def test_cli_wait_ready_cannot_succeed_from_file_without_live_response(self) -> None:
        exit_code, stdout, stderr, elapsed, calls = self._wait_ready_timeline([
            (0, {"state": "ready", "timestamp": 10}),
        ], [
            (0, UnityConnectionError("editor unavailable")),
        ], timeout_sec=1)
        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("timed out", json.loads(stderr)["error"])
        self.assertAlmostEqual(elapsed, 1.0)
        self.assertTrue(calls)

    def test_cli_wait_ready_does_not_accept_unknown_completion(self) -> None:
        exit_code, stdout, stderr, elapsed, calls = self._wait_ready_timeline([
            (0, {"state": "ready", "timestamp": 10}),
        ], [
            (0, CommandResponse(True, "connection closed", {"completion": "unknown"})),
            (0.5, {"state": "ready", "timestamp": 20}),
        ])
        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(json.loads(stdout)["timestamp"], 20)
        self.assertAlmostEqual(elapsed, 0.5)
        self.assertEqual(len(calls), 2)

    def test_cli_wait_ready_requires_matching_live_response(self) -> None:
        invalid = [
            CommandResponse(True, "cached", {"requestId": "old", "instance": {"state": "ready"}}),
            {"state": "ready", "projectPath": "D:/DifferentProject"},
            {"state": "ready", "timestamp": 0},
        ]
        for live in invalid:
            with self.subTest(live=live):
                exit_code, stdout, stderr, elapsed, _ = self._wait_ready_timeline([
                    (0, {"state": "ready", "timestamp": 10}),
                ], [(0, live)])
                self.assertEqual(exit_code, 1)
                self.assertEqual(stdout, "")
                self.assertFalse(json.loads(stderr)["ok"])
                self.assertEqual(elapsed, 0)

    def test_cli_wait_ready_reports_unsupported_connector_without_file_fallback(self) -> None:
        exit_code, stdout, stderr, elapsed, _ = self._wait_ready_timeline([
            (0, {"state": "ready", "timestamp": 10}),
        ], [(0, CommandResponse(False, "Unknown command: get_editor_state"))])
        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Update the Unity Connector", json.loads(stderr)["error"])
        self.assertEqual(elapsed, 0)

    def test_cli_wait_ready_can_wait_for_editor_startup(self) -> None:
        exit_code, stdout, stderr, elapsed, _ = self._wait_ready_timeline([
            (0, None),
            (0.2, {"state": "ready", "timestamp": 10}),
        ], [(0, {"state": "ready", "timestamp": 20})])
        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(json.loads(stdout)["timestamp"], 20)
        self.assertGreaterEqual(elapsed, 0.2)
        self.assertLess(elapsed, 1.0)

    def test_cli_wait_ready_timeout_includes_editor_startup(self) -> None:
        exit_code, stdout, stderr, elapsed, calls = self._wait_ready_timeline([
            (0, None),
            (0.2, {"state": "ready", "timestamp": 10}),
        ], [(0, {"state": "compiling", "timestamp": 20})], timeout_sec=1)
        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("timed out", json.loads(stderr)["error"])
        self.assertAlmostEqual(elapsed, 1.0)
        for call in calls:
            self.assertLessEqual(call["timeout_ms"], (1.0 - call["at"]) * 1000)

    def test_cli_wait_ready_follows_same_project_after_port_change(self) -> None:
        exit_code, stdout, stderr, elapsed, calls = self._wait_ready_timeline([
            (0, {"state": "ready", "timestamp": 10, "port": 8090}),
            (0.5, {"state": "ready", "timestamp": 11, "port": 8091}),
        ], [
            (0, UnityConnectionError("domain reload")),
            (0.5, {"state": "ready", "timestamp": 20, "port": 8091}),
        ], port=8090)
        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(json.loads(stdout)["port"], 8091)
        self.assertEqual(json.loads(stdout)["projectPath"], "D:/UnityProjects/Game")
        self.assertAlmostEqual(elapsed, 0.5)
        self.assertEqual([call["port"] for call in calls], [8090, 8091])

    def test_cli_status_warns_when_connector_version_differs(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "game", port=8090, pid=0, connectorVersion="0.1.2")

            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cli_main(["--instances-dir", str(directory), "status"])

            self.assertEqual(exit_code, 0)
            self.assertIn("Connector: 0.1.2", stdout.getvalue())
            self.assertIn(
                f"WARNING: Unity Connector version 0.1.2 differs from UnityBridge CLI version {__version__}",
                stderr.getvalue(),
            )

    def test_cli_status_accepts_equivalent_prerelease_spellings(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "game", port=8090, pid=0, connectorVersion="0.2.2-rc.1")
            stderr = StringIO()
            with patch.object(cli_output, "__version__", "0.2.2rc1"), redirect_stdout(StringIO()), redirect_stderr(stderr):
                code = cli_main(["--instances-dir", str(directory), "status"])
            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), "")

    def test_cli_status_json_suppresses_connector_version_warning(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "game", port=8090, pid=0, connectorVersion="0.1.2")

            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cli_main(["--json", "--instances-dir", str(directory), "status"])

            self.assertEqual(exit_code, 0)
            self.assertEqual("", stderr.getvalue())
            self.assertEqual(json.loads(stdout.getvalue())["connectorVersion"], "0.1.2")

    def test_cli_json_command_discovers_instance_once(self) -> None:
        response_body = json.dumps({"success": True, "message": "ok", "data": []}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port, pid=0)

            with patch("unity_bridge.client.scan_instances", wraps=scan_instances) as scan, redirect_stdout(StringIO()):
                exit_code = cli_main(["--json", "--instances-dir", str(directory), "console"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(scan.call_count, 1)

    def test_cli_json_conversion_does_not_copy_large_nested_payloads(self) -> None:
        data = [{"frame": 1, "children": [{"name": "Update"}]}]
        result = UnityActionResult(
            tool="profiler",
            command="profiler",
            params={"action": "hierarchy"},
            success=True,
            message="ok",
            data=data,
        )

        payload = cli_output.to_jsonable(result)

        self.assertIs(payload["data"], data)
        self.assertEqual(payload["params"], {"action": "hierarchy"})

    def test_cli_command_warns_when_connector_version_differs(self) -> None:
        response_body = json.dumps({"success": True, "message": "Retrieved 0 entries.", "data": []}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port, pid=0, connectorVersion="0.1.2")

            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cli_main(["--instances-dir", str(directory), "console"])

            self.assertEqual(exit_code, 0)
            self.assertIn("Retrieved 0 entries.", stdout.getvalue())
            self.assertIn(
                f"WARNING: Unity Connector version 0.1.2 differs from UnityBridge CLI version {__version__}",
                stderr.getvalue(),
            )

    def test_cli_console_command_sends_adapter_request(self) -> None:
        response_body = json.dumps({"success": True, "message": "Retrieved 0 entries.", "data": []}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port, pid=0)

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = cli_main(
                    [
                        "--instances-dir",
                        str(directory),
                        "console",
                        "--count",
                        "5",
                        "--type",
                        "error",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertIn("Retrieved 0 entries.", stdout.getvalue())
            self.assertEqual(
                server.received[0]["body"],
                {
                    "command": "console",
                    "params": {"count": 5, "type": "error", "stacktrace": "user"},
                },
            )

    def test_cli_console_accepts_lines_alias(self) -> None:
        response_body = json.dumps({"success": True, "message": "Retrieved 0 entries.", "data": []}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port, pid=0)

            with redirect_stdout(StringIO()):
                exit_code = cli_main(
                    [
                        "--instances-dir",
                        str(directory),
                        "console",
                        "--lines",
                        "5",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                server.received[0]["body"],
                {
                    "command": "console",
                    "params": {"count": 5, "type": "error,warning,log", "stacktrace": "user"},
                },
            )

    def test_cli_refresh_accepts_repeated_path_flags(self) -> None:
        response_body = json.dumps({"success": True, "message": "Refresh requested."}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port, pid=0)

            with redirect_stdout(StringIO()):
                exit_code = cli_main(
                    [
                        "--instances-dir",
                        str(directory),
                        "refresh",
                        "--path",
                        "Assets/Scripts/Player.cs",
                        "--path",
                        r"D:\Game\Assets\Prefabs\Enemy.prefab",
                        "--compile",
                        "request",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                server.received[0]["body"],
                {
                    "command": "refresh_unity",
                    "params": {
                        "mode": "if_dirty",
                        "force": False,
                        "paths": ["Assets/Scripts/Player.cs", r"D:\Game\Assets\Prefabs\Enemy.prefab"],
                        "compile": "request",
                    },
                },
            )

    def test_cli_playmode_test_can_skip_waiting(self) -> None:
        response_body = json.dumps({"success": True, "message": "running"}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port, pid=0)

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = cli_main(
                    [
                        "--instances-dir",
                        str(directory),
                        "test",
                        "--mode",
                        "PlayMode",
                        "--no-wait",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertIn("running", stdout.getvalue())
            self.assertEqual(
                server.received[0]["body"],
                {
                    "command": "run_tests",
                    "params": {
                        "mode": "PlayMode",
                        "allow_dirty_scenes": False,
                        "auto_save_scenes": False,
                    },
                },
            )

    def test_cli_exec_accepts_file_alias(self) -> None:
        response_body = json.dumps({"success": True, "message": "ok"}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp) / "instances"
            directory.mkdir()
            code_file = Path(tmp) / "query.cs"
            code_file.write_text("return UnityEngine.Application.dataPath;", encoding="utf-8")
            write_instance(directory, "game", port=server.port, pid=0)

            with redirect_stdout(StringIO()):
                exit_code = cli_main(
                    [
                        "--instances-dir",
                        str(directory),
                        "exec",
                        "--file",
                        str(code_file),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                server.received[0]["body"],
                {
                    "command": "exec",
                    "params": {"code": "return UnityEngine.Application.dataPath;"},
                },
            )

    def test_cli_exec_accepts_stdin(self) -> None:
        response_body = json.dumps({"success": True, "message": "ok"}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port, pid=0)
            old_stdin = sys.stdin
            sys.stdin = StringIO("return 1 + 2;")
            try:
                with redirect_stdout(StringIO()):
                    exit_code = cli_main(
                        [
                            "--instances-dir",
                            str(directory),
                            "exec",
                            "--stdin",
                        ]
                    )
            finally:
                sys.stdin = old_stdin

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                server.received[0]["body"],
                {
                    "command": "exec",
                    "params": {"code": "return 1 + 2;"},
                },
            )

    def test_cli_direct_custom_tool_accepts_dynamic_flags(self) -> None:
        response_body = json.dumps({"success": True, "message": "Enemy spawned"}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port, pid=0)

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = cli_main(
                    [
                        "--instances-dir",
                        str(directory),
                        "spawn",
                        "--x",
                        "1",
                        "--y",
                        "0",
                        "--z",
                        "5",
                        "--prefab",
                        "Enemy",
                        "--active",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertIn("Enemy spawned", stdout.getvalue())
            self.assertEqual(
                server.received[0]["body"],
                {
                    "command": "spawn",
                    "params": {"x": 1, "y": 0, "z": 5, "prefab": "Enemy", "active": True},
                },
            )

    def test_cli_direct_custom_tool_accepts_params_json_and_positionals(self) -> None:
        response_body = json.dumps({"success": True, "message": "ok"}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port, pid=0)

            with redirect_stdout(StringIO()):
                exit_code = cli_main(
                    [
                        "my_custom_tool",
                        "--instances-dir",
                        str(directory),
                        "--params",
                        '{"prefab":"Enemy","count":2}',
                        "--count",
                        "3",
                        "first",
                        "second",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                server.received[0]["body"],
                {
                    "command": "my_custom_tool",
                    "params": {"prefab": "Enemy", "count": [2, 3], "args": ["first", "second"]},
                },
            )

    def test_cli_direct_connector_command_supports_list_alias(self) -> None:
        response_body = json.dumps({"success": True, "message": "Listed tools", "data": []}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port, pid=0)

            with redirect_stdout(StringIO()):
                exit_code = cli_main(["--instances-dir", str(directory), "list"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(server.received[0]["body"], {"command": "list", "params": {}})

    def test_cli_update_dry_run_prints_pip_command(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = cli_main(["update", "--dry-run", "--ref", "feature/test"])

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("-m pip install --upgrade --force-reinstall", output)
        self.assertIn("git+https://github.com/zjxps2007/UnityBridge.git@feature/test", output)
        self.assertIn("?path=/unity-bridge-connector#feature/test", output)

    def test_cli_update_dry_run_json_reports_command(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = cli_main(["--json", "update", "--dry-run", "--package-spec", "unity-bridge==0.1.5"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["package_spec"], "unity-bridge==0.1.5")
        self.assertIn("pip", payload["command"])

    def test_cli_update_check_json_reports_available_version(self) -> None:
        remote_files = {
            "pyproject.toml": '[project]\nversion = "0.1.5"\n',
            "unity-bridge-connector/package.json": '{"version":"0.1.5"}',
        }

        with (
            patch.object(cli_updates, "_current_package_version", return_value="0.1.1"),
            patch.object(cli_updates, "_read_remote_repository_file", side_effect=lambda repo, ref, path, **kwargs: remote_files[path]),
        ):
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = cli_main(["--json", "update", "--check", "--ref", "v0.1.5"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["check"])
        self.assertTrue(payload["update_available"])
        self.assertEqual(payload["status"], "outdated")
        self.assertEqual(payload["current_version"], "0.1.1")
        self.assertEqual(payload["latest_version"], "0.1.5")
        self.assertEqual(payload["target_connector_version"], "0.1.5")

    def test_cli_update_check_offers_final_release_to_rc_installs(self) -> None:
        for current in ["0.2.2-rc.1", "0.2.2rc1"]:
            with self.subTest(current=current), \
                    patch.object(cli_updates, "_current_package_version", return_value=current), \
                    patch.object(cli_updates, "_remote_python_version", return_value="0.2.2"), \
                    patch.object(cli_updates, "_remote_connector_version", return_value="0.2.2"):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    code = cli_main(["--json", "update", "--check"])
                payload = json.loads(stdout.getvalue())
                self.assertEqual(code, 0)
                self.assertEqual(payload["status"], "outdated")
                self.assertTrue(payload["update_available"])

    def test_cli_update_check_prints_up_to_date(self) -> None:
        remote_files = {
            "pyproject.toml": '[project]\nversion = "0.1.5"\n',
            "unity-bridge-connector/package.json": '{"version":"0.1.5"}',
        }

        with (
            patch.object(cli_updates, "_current_package_version", return_value="0.1.5"),
            patch.object(cli_updates, "_read_remote_repository_file", side_effect=lambda repo, ref, path, **kwargs: remote_files[path]),
        ):
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = cli_main(["update", "--check"])

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("up to date", output)
        self.assertIn("Target Unity Connector version: 0.1.5", output)

    def test_cli_update_check_labels_standalone_build(self) -> None:
        remote_files = {
            "pyproject.toml": '[project]\nversion = "0.2.0"\n',
            "unity-bridge-connector/package.json": '{"version":"0.2.0"}',
        }

        with (
            patch.object(cli_standalone.sys, "frozen", True, create=True),
            patch.object(cli_standalone.sys, "platform", "win32"),
            patch.object(cli_standalone.platform, "machine", return_value="AMD64"),
            patch.object(cli_updates, "_read_remote_repository_file", side_effect=lambda repo, ref, path, **kwargs: remote_files[path]),
        ):
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = cli_main(["update", "--check"])

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn(f"UnityBridge standalone CLI: {__version__}", output)
        self.assertIn("Standalone asset: unity-bridge-windows-amd64.zip", output)

    def test_cli_auto_update_notice_prints_when_update_is_available(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp) / "instances"
            cache_path = Path(tmp) / "update-check.json"
            directory.mkdir()
            write_instance(directory, "game", port=8090, pid=0)

            stdout = StringIO()
            stderr = StringIO()
            with (
                patch.dict(os.environ, {"UNITY_BRIDGE_SKIP_UPDATE_CHECK": ""}),
                patch.object(cli_updates, "_current_package_version", return_value="0.1.4"),
                patch.object(cli_updates, "_remote_python_version", return_value="0.1.5"),
                patch.object(cli_updates, "_update_check_cache_path", return_value=cache_path),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = cli_main(["--instances-dir", str(directory), "status"])

            self.assertEqual(exit_code, 0)
            self.assertIn("UnityBridge update available: 0.1.4 -> 0.1.5", stderr.getvalue())
            self.assertTrue(cache_path.exists())

    def test_cli_auto_update_notice_skips_json_output(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "game", port=8090, pid=0)

            with (
                patch.dict(os.environ, {"UNITY_BRIDGE_SKIP_UPDATE_CHECK": ""}),
                patch.object(cli_updates, "_remote_python_version", side_effect=AssertionError("should not check")),
                redirect_stdout(StringIO()),
            ):
                exit_code = cli_main(["--json", "--instances-dir", str(directory), "status"])

            self.assertEqual(exit_code, 0)

    def test_cli_auto_update_notice_can_be_skipped_by_option(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "game", port=8090, pid=0)

            with (
                patch.dict(os.environ, {"UNITY_BRIDGE_SKIP_UPDATE_CHECK": ""}),
                patch.object(cli_updates, "_remote_python_version", side_effect=AssertionError("should not check")),
                redirect_stdout(StringIO()),
            ):
                exit_code = cli_main(["--no-update-check", "--instances-dir", str(directory), "status"])

            self.assertEqual(exit_code, 0)

    def test_cli_auto_update_notice_respects_cache(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp) / "instances"
            cache_path = Path(tmp) / "update-check.json"
            directory.mkdir()
            write_instance(directory, "game", port=8090, pid=0)
            cache_path.write_text(json.dumps({"checked_at": 1_000.0}), encoding="utf-8")

            with (
                patch.dict(os.environ, {"UNITY_BRIDGE_SKIP_UPDATE_CHECK": ""}),
                patch.object(cli_updates.time, "time", return_value=1_001.0),
                patch.object(cli_updates, "_remote_python_version", side_effect=AssertionError("should not check")),
                patch.object(cli_updates, "_update_check_cache_path", return_value=cache_path),
                redirect_stdout(StringIO()),
            ):
                exit_code = cli_main(["--instances-dir", str(directory), "status"])

            self.assertEqual(exit_code, 0)

    def test_cli_standalone_update_dry_run_uses_windows_installer(self) -> None:
        with (
            patch.object(cli_standalone.sys, "frozen", True, create=True),
            patch.object(cli_standalone.sys, "platform", "win32"),
        ):
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = cli_main(["update", "--dry-run", "--ref", "v0.1.5"])

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("powershell", output)
        self.assertIn("install.ps1", output)
        self.assertIn("-Version 'v0.1.5'", output)
        self.assertIn("Unity Connector package URL: https://github.com/zjxps2007/UnityBridge.git?path=/unity-bridge-connector#v0.1.5", output)

    def test_cli_standalone_update_dry_run_uses_posix_installer(self) -> None:
        with (
            patch.object(cli_standalone.sys, "frozen", True, create=True),
            patch.object(cli_standalone.sys, "platform", "darwin"),
            patch.object(cli_standalone.platform, "machine", return_value="arm64"),
        ):
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = cli_main(["update", "--dry-run", "--ref", "v0.1.5"])

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("sh -c", output)
        self.assertIn("install.sh", output)
        self.assertIn("--version", output)
        self.assertIn("v0.1.5", output)
        self.assertIn("darwin-arm64", output)

    def test_standalone_prerelease_update_uses_the_tagged_installer(self) -> None:
        for platform_name, script_name in [("win32", "install.ps1"), ("linux", "install.sh")]:
            with self.subTest(platform=platform_name), \
                    patch.object(cli_standalone.sys, "frozen", True, create=True), \
                    patch.object(cli_standalone.sys, "platform", platform_name), \
                    patch.object(cli_standalone.platform, "machine", return_value="AMD64"):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    code = cli_main(["--json", "update", "--dry-run", "--ref", "refs/tags/v0.2.2-rc.1"])
                payload = json.loads(stdout.getvalue())
                self.assertEqual(code, 0)
                self.assertEqual(payload["version"], "v0.2.2-rc.1")
                self.assertIn(f"https://raw.githubusercontent.com/zjxps2007/UnityBridge/v0.2.2-rc.1/{script_name}", payload["command"][-1])

    def test_standalone_stable_updates_keep_the_default_installer(self) -> None:
        for version in ["latest", "v0.2.1"]:
            with self.subTest(version=version):
                windows = cli_standalone._standalone_windows_update_command(version)[-1]
                posix = cli_standalone._standalone_posix_update_command(version)[-1]
                self.assertIn(cli_standalone.DEFAULT_INSTALL_POWERSHELL_SCRIPT_URL, windows)
                self.assertIn(cli_standalone.DEFAULT_INSTALL_SHELL_SCRIPT_URL, posix)

    def test_standalone_update_keeps_custom_install_directory(self) -> None:
        custom = Path("custom install's directory") / "unity-bridge.exe"
        with patch.object(cli_standalone.sys, "executable", str(custom)):
            windows = cli_standalone._standalone_windows_update_command("v0.2.1")[-1]
            posix = cli_standalone._standalone_posix_update_command("v0.2.1")[-1]
        self.assertIn("-InstallDir 'custom install''s directory' -NoPathUpdate", windows)
        self.assertIn("--install-dir 'custom install'\"'\"'s directory' --no-path-update", posix)

    def test_standalone_asset_names_use_installable_archives(self) -> None:
        for platform_name, machine, expected in [
            ("win32", "AMD64", "unity-bridge-windows-amd64.zip"),
            ("linux", "x86_64", "unity-bridge-linux-amd64.tar.gz"),
            ("linux", "aarch64", "unity-bridge-linux-arm64.tar.gz"),
            ("darwin", "arm64", "unity-bridge-darwin-arm64.tar.gz"),
            ("darwin", "x86_64", "unity-bridge-darwin-amd64.tar.gz"),
        ]:
            with self.subTest(platform=platform_name, machine=machine), \
                    patch.object(cli_standalone.sys, "platform", platform_name), \
                    patch.object(cli_standalone.platform, "machine", return_value=machine):
                self.assertEqual(cli_standalone.standalone_asset_name(), expected)


if __name__ == "__main__":
    unittest.main()
