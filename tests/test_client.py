from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from contextlib import redirect_stderr
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import unity_bridge.cli as cli_module
from unity_bridge import CommandResponse
from unity_bridge import DiscoveryError
from unity_bridge import Instance
from unity_bridge import UnityActionResult
from unity_bridge import UnityBridgeAdapter
from unity_bridge import UnityClient
from unity_bridge import UnityConnectionError
from unity_bridge import discover_instance
from unity_bridge import find_active_by_port
from unity_bridge import find_by_port
from unity_bridge import scan_instances
from unity_bridge import send_command
from unity_bridge.adapter import test_results_path
from unity_bridge.adapter import wait_for_test_results
from unity_bridge.adapter import TEST_FRAMEWORK_MISSING_MESSAGE
from unity_bridge.cli import main as cli_main
from unity_bridge.client import default_instances_dir
from unity_bridge.client import wait_for_ready


def write_instance(directory: Path, name: str, **overrides: object) -> Path:
    payload = {
        "state": "ready",
        "projectPath": "D:/UnityProjects/Game",
        "port": 8090,
        "pid": 1234,
        "unityVersion": "6000.0.0f1",
        "connectorVersion": cli_module.__version__,
        "timestamp": 1_700_000_000_000,
        "compileErrors": False,
    }
    payload.update(overrides)
    path = directory / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class FakeUnityServer:
    def __init__(self, response: bytes, *, status: int = 200) -> None:
        self.received: list[dict[str, object]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                outer.received.append(
                    {
                        "path": urlparse(self.path).path,
                        "content_type": self.headers.get("Content-Type"),
                        "body": json.loads(body.decode("utf-8")),
                    }
                )
                self.send_response(status)
                self.end_headers()
                if response:
                    self.wfile.write(response)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )

    @property
    def port(self) -> int:
        return int(self.server.server_port)

    def __enter__(self) -> "FakeUnityServer":
        self.thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


class DiscoveryTests(unittest.TestCase):
    def test_default_instances_dir_uses_unity_bridge_home_directory(self) -> None:
        self.assertEqual(default_instances_dir(), Path.home() / ".unity-bridge" / "instances")

    def test_scan_instances_ignores_invalid_files_and_removes_confirmed_dead_pids(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            alive = write_instance(directory, "alive", pid=111, port=8090)
            dead = write_instance(directory, "dead", pid=222, port=8091)
            (directory / "broken.json").write_text("{", encoding="utf-8")
            (directory / "note.txt").write_text("ignored", encoding="utf-8")

            instances = scan_instances(
                instances_dir=directory,
                process_checker=lambda pid: pid == 222,
            )

            self.assertEqual([instance.port for instance in instances], [8090])
            self.assertTrue(alive.exists())
            self.assertFalse(dead.exists())

    def test_discovery_recovers_from_temporary_heartbeat_access_conflict(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            path = write_instance(directory, "game", pid=111)
            payload = path.read_text(encoding="utf-8")

            with patch.object(Path, "read_text", side_effect=[PermissionError(), payload]):
                instance = discover_instance(
                    project="D:/UnityProjects/Game",
                    instances_dir=directory,
                    process_checker=lambda pid: False,
                )

            self.assertEqual(instance.pid, 111)
            self.assertEqual(instance.port, 8090)
            self.assertTrue(path.exists())

    def test_scan_skips_permanently_inaccessible_file_after_bounded_retries(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            blocked = write_instance(directory, "blocked", pid=111)
            write_instance(directory, "readable", pid=222, port=8091)
            read_text = Path.read_text
            attempts = 0

            def read(path: Path, *args: object, **kwargs: object) -> str:
                nonlocal attempts
                if path == blocked:
                    attempts += 1
                    if attempts > 5:
                        raise AssertionError("Heartbeat access retries must be bounded")
                    raise PermissionError("Access is permanently denied")
                return read_text(path, *args, **kwargs)

            with patch.object(Path, "read_text", read), patch("unity_bridge.client.time.sleep") as sleep:
                instances = scan_instances(
                    instances_dir=directory,
                    process_checker=lambda pid: False,
                )

            self.assertEqual([instance.pid for instance in instances], [222])
            self.assertTrue(blocked.exists())
            self.assertLessEqual(sum(call.args[0] for call in sleep.call_args_list), 0.04)

    def test_scan_does_not_wait_for_readable_or_malformed_heartbeats(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "game", pid=111)
            (directory / "broken.json").write_text("{", encoding="utf-8")

            with patch("unity_bridge.client.time.sleep") as sleep:
                instances = scan_instances(
                    instances_dir=directory,
                    process_checker=lambda pid: False,
                )

            self.assertEqual([instance.pid for instance in instances], [111])
            sleep.assert_not_called()

    def test_discovery_recovers_when_heartbeat_is_temporarily_missing_from_listing(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            path = write_instance(directory, "game", pid=111)

            with patch.object(Path, "iterdir", side_effect=[iter(()), iter((path,))]):
                instance = discover_instance(
                    project="D:/UnityProjects/Game",
                    instances_dir=directory,
                    process_checker=lambda pid: False,
                )

            self.assertEqual(instance.pid, 111)

    def test_discovery_stops_retrying_when_no_editor_is_running(self) -> None:
        with TemporaryDirectory() as tmp, patch("unity_bridge.client.time.sleep") as sleep:
            with self.assertRaises(DiscoveryError):
                discover_instance(instances_dir=Path(tmp))

            sleep.assert_called_once_with(0.01)

    def test_find_by_port_selects_most_recent_even_if_stopped(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "old", port=8090, timestamp=10)
            write_instance(directory, "new", port=8090, state="stopped", timestamp=20)

            instance = find_by_port(8090, instances_dir=directory, process_checker=lambda pid: False)

            self.assertEqual(instance.timestamp, 20)
            self.assertEqual(instance.state, "stopped")

    def test_find_active_by_port_skips_stopped_instances(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "stopped", port=8090, state="stopped", timestamp=20)
            write_instance(directory, "ready", port=8090, state="ready", timestamp=10)

            instance = find_active_by_port(8090, instances_dir=directory, process_checker=lambda pid: False)

            self.assertEqual(instance.state, "ready")

    def test_discover_instance_prefers_project_filter_then_cwd_then_recent(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "game", projectPath="D:/UnityProjects/Game", port=8090, timestamp=10)
            write_instance(directory, "tool", projectPath="D:/UnityProjects/Tool", port=8091, timestamp=20)

            by_project = discover_instance(
                project="UnityProjects/Game",
                instances_dir=directory,
                process_checker=lambda pid: False,
            )
            by_cwd = discover_instance(
                instances_dir=directory,
                cwd="D:/UnityProjects/Game/Assets",
                process_checker=lambda pid: False,
            )
            by_recent = discover_instance(
                instances_dir=directory,
                cwd="D:/Other",
                process_checker=lambda pid: False,
            )

            self.assertEqual(by_project.port, 8090)
            self.assertEqual(by_cwd.port, 8090)
            self.assertEqual(by_recent.port, 8091)

    def test_discover_instance_matches_exact_project_folder_name(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "game", projectPath="D:/UnityProjects/Game", port=8090, timestamp=10)
            write_instance(directory, "prototype", projectPath="D:/UnityProjects/GamePrototype", port=8091, timestamp=20)

            instance = discover_instance(
                project="Game",
                instances_dir=directory,
                process_checker=lambda pid: False,
            )

            self.assertEqual(instance.port, 8090)

    def test_discover_instance_matches_project_path_suffix_by_segments(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "game", projectPath="D:/UnityProjects/Game", port=8090, timestamp=10)
            write_instance(directory, "tool", projectPath="D:/UnityProjects/Tool", port=8091, timestamp=20)

            instance = discover_instance(
                project="UnityProjects/Game",
                instances_dir=directory,
                process_checker=lambda pid: False,
            )

            self.assertEqual(instance.port, 8090)

    def test_discover_instance_rejects_substring_only_project_match(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "prototype", projectPath="D:/UnityProjects/GamePrototype", port=8091, timestamp=20)

            with self.assertRaises(DiscoveryError) as cm:
                discover_instance(
                    project="Game",
                    instances_dir=directory,
                    process_checker=lambda pid: False,
                )

            self.assertIn("no Unity instance found", str(cm.exception))

    def test_discover_instance_reports_ambiguous_project_folder_name(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "game-a", projectPath="D:/UnityProjects/Game", port=8090, timestamp=10)
            write_instance(directory, "game-b", projectPath="E:/UnityProjects/Game", port=8091, timestamp=20)

            with self.assertRaises(DiscoveryError):
                discover_instance(
                    project="Game",
                    instances_dir=directory,
                    process_checker=lambda pid: False,
                )

    def test_discover_instance_uses_case_insensitive_project_match_on_windows(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows-only path case behavior")
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "game", projectPath="D:/UnityProjects/Game", port=8090, timestamp=10)

            instance = discover_instance(
                project="d:/unityprojects/game",
                instances_dir=directory,
                process_checker=lambda pid: False,
            )

            self.assertEqual(instance.port, 8090)

    def test_discover_instance_picks_most_specific_cwd_match(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "root", projectPath="D:/UnityProjects/Game", port=8090, timestamp=20)
            write_instance(directory, "nested", projectPath="D:/UnityProjects/Game/Nested", port=8091, timestamp=10)

            instance = discover_instance(
                instances_dir=directory,
                cwd="D:/UnityProjects/Game/Nested/Assets/Scripts",
                process_checker=lambda pid: False,
            )

            self.assertEqual(instance.port, 8091)

    def test_discover_instance_reports_missing_connector_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "instances"

            with self.assertRaises(DiscoveryError) as cm:
                discover_instance(instances_dir=missing)
            self.assertEqual(
                str(cm.exception),
                "no Unity instances found. Is Unity running with the Connector package?",
            )
            self.assertNotIn(str(missing), str(cm.exception))

    def test_wait_for_ready_requires_newer_stable_ready(self) -> None:
        sequence = [
            Instance(state="ready", project_path="D:/Game", port=8090, pid=1, timestamp=10),
            Instance(state="compiling", project_path="D:/Game", port=8090, pid=1, timestamp=11),
            Instance(state="ready", project_path="D:/Game", port=8090, pid=1, timestamp=12),
            Instance(state="ready", project_path="D:/Game", port=8090, pid=1, timestamp=12),
            Instance(state="ready", project_path="D:/Game", port=8090, pid=1, timestamp=12),
        ]
        calls = {"count": 0}

        def resolve() -> Instance:
            index = min(calls["count"], len(sequence) - 1)
            calls["count"] += 1
            return sequence[index]

        instance = wait_for_ready(
            resolve,
            timeout_sec=1,
            poll_interval_sec=0.01,
            after_timestamp=10,
            stable_sec=0.015,
        )

        self.assertEqual(instance.timestamp, 12)
        self.assertGreaterEqual(calls["count"], 4)

    def test_wait_for_ready_checks_current_state_before_sleeping(self) -> None:
        ready = Instance(state="ready", project_path="D:/Game", port=8090, pid=1, timestamp=11)

        with patch("unity_bridge.client.time.sleep") as sleep:
            instance = wait_for_ready(
                lambda: ready,
                timeout_sec=1,
                poll_interval_sec=0.5,
                after_timestamp=10,
            )

        self.assertEqual(instance, ready)
        sleep.assert_not_called()

    def test_wait_for_ready_caps_sleep_to_remaining_timeout(self) -> None:
        clock = {"now": 0.0}
        compiling = Instance(state="compiling", project_path="D:/Game", port=8090, pid=1, timestamp=11)

        def advance(seconds: float) -> None:
            clock["now"] += seconds

        with (
            patch("unity_bridge.client.time.monotonic", side_effect=lambda: clock["now"]),
            patch("unity_bridge.client.time.sleep", side_effect=advance) as sleep,
            self.assertRaises(DiscoveryError),
        ):
            wait_for_ready(
                lambda: compiling,
                timeout_sec=0.1,
                poll_interval_sec=1,
                after_timestamp=10,
            )

        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], 0.1)


class HttpClientTests(unittest.TestCase):
    def test_send_command_posts_unity_command_json_and_parses_response(self) -> None:
        payload = json.dumps(
            {
                "success": True,
                "message": "Listed tools",
                "data": [{"name": "console"}],
            }
        ).encode("utf-8")
        with FakeUnityServer(payload) as server:
            instance = Instance(state="ready", project_path="D:/Game", port=server.port, pid=1, timestamp=1)

            response = send_command(instance, "list", {"verbose": True})

            self.assertEqual(
                response,
                CommandResponse(success=True, message="Listed tools", data=[{"name": "console"}]),
            )
            self.assertEqual(server.received[0]["path"], "/command")
            self.assertEqual(server.received[0]["content_type"], "application/json")
            self.assertEqual(
                server.received[0]["body"],
                {"command": "list", "params": {"verbose": True}},
            )

    def test_send_command_accepts_plain_text_response(self) -> None:
        with FakeUnityServer(b"plain ok") as server:
            instance = Instance(state="ready", project_path="D:/Game", port=server.port, pid=1, timestamp=1)

            response = send_command(instance, "editor")

            self.assertEqual(response, CommandResponse(success=True, message="plain ok"))

    def test_send_command_accepts_empty_response(self) -> None:
        with FakeUnityServer(b"") as server:
            instance = Instance(state="ready", project_path="D:/Game", port=server.port, pid=1, timestamp=1)

            response = send_command(instance, "editor")

            self.assertTrue(response.success)
            self.assertIn("connection closed before response", response.message)
            self.assertTrue(response.completion_unknown)
            self.assertEqual(response.data["completion"], "unknown")
            self.assertTrue(response.data["connection_closed"])

    def test_unity_client_discovers_instance_and_calls_command(self) -> None:
        response_body = json.dumps({"success": True, "message": "ok"}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port)
            client = UnityClient(instances_dir=directory, process_checker=lambda pid: False)

            response = client.call("status")

            self.assertEqual(response, CommandResponse(success=True, message="ok"))


class AdapterTests(unittest.TestCase):
    def test_live_ready_preserves_explicit_stability_and_resets_on_busy(self) -> None:
        clock = {"now": 0.0}
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "game", pid=0)
            adapter = UnityBridgeAdapter(instances_dir=directory)

            def query(instance: Instance, command: str, params: dict[str, object], *, timeout_ms: int) -> CommandResponse:
                state = instance.to_dict()
                state["state"] = "compiling" if 0.1 <= clock["now"] < 0.3 else "ready"
                return CommandResponse(True, "state", {"requestId": params["request_id"], "instance": state})

            def advance(seconds: float) -> None:
                clock["now"] += seconds

            with (
                patch("unity_bridge.client.send_command", side_effect=query),
                patch("unity_bridge.client.time.monotonic", side_effect=lambda: clock["now"]),
                patch("unity_bridge.client.time.sleep", side_effect=advance),
            ):
                result = adapter.wait_for_ready(timeout_sec=2, stable_sec=0.2, poll_interval_sec=0.1)
            self.assertEqual(result.state, "ready")
            self.assertGreaterEqual(clock["now"], 0.5)
            self.assertLess(clock["now"], 0.7)

    def test_live_ready_does_not_accept_response_after_deadline(self) -> None:
        clock = {"now": 0.0}
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_instance(directory, "game", pid=0)
            adapter = UnityBridgeAdapter(instances_dir=directory)

            def delayed(instance: Instance, command: str, params: dict[str, object], *, timeout_ms: int) -> CommandResponse:
                self.assertLessEqual(timeout_ms, 1000)
                clock["now"] = 1.1
                return CommandResponse(True, "state", {"requestId": params["request_id"], "instance": instance.to_dict()})

            with (
                patch("unity_bridge.client.send_command", side_effect=delayed),
                patch("unity_bridge.client.time.monotonic", side_effect=lambda: clock["now"]),
                self.assertRaises(DiscoveryError),
            ):
                adapter.wait_for_ready(timeout_sec=1)

    def test_adapter_refresh_assets_sends_paths_payload(self) -> None:
        response_body = json.dumps(
            {
                "success": True,
                "message": "Refresh requested.",
                "data": {
                    "refresh_triggered": True,
                    "scope": "paths",
                    "paths": ["Assets/Scripts/Player.cs"],
                },
            }
        ).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port)
            adapter = UnityBridgeAdapter(instances_dir=directory, process_checker=lambda pid: False)

            result = adapter.refresh_assets(paths=[r"D:\Game\Assets\Scripts\Player.cs"])

            self.assertTrue(result.success)
            self.assertEqual(result.data["scope"], "paths")
            self.assertEqual(
                server.received[0]["body"],
                {
                    "command": "refresh_unity",
                    "params": {
                        "mode": "if_dirty",
                        "force": False,
                        "paths": [r"D:\Game\Assets\Scripts\Player.cs"],
                        "compile": "none",
                    },
                },
            )

    def test_adapter_refresh_assets_can_wait_for_new_ready_heartbeat_on_new_port(self) -> None:
        response_body = json.dumps(
            {
                "success": True,
                "message": "Refresh requested.",
                "data": {"refresh_triggered": True, "scope": "paths"},
            }
        ).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port, timestamp=10)
            adapter = UnityBridgeAdapter(instances_dir=directory, process_checker=lambda pid: False)

            def write_ready() -> None:
                write_instance(directory, "game", port=server.port + 1, timestamp=20)

            timer = threading.Timer(0.05, write_ready)
            timer.start()
            try:
                result = adapter.refresh_assets(
                    paths=["Assets/Scripts/Player.cs"],
                    wait=True,
                    timeout_sec=2,
                    stable_sec=0.01,
                    poll_interval_sec=0.01,
                )
            finally:
                timer.cancel()

            self.assertTrue(result.success)
            self.assertEqual(result.data["ready"]["timestamp"], 20)
            self.assertEqual(result.data["initial_port"], server.port)
            self.assertEqual(result.data["current_port"], server.port + 1)
            self.assertEqual(
                server.received[0]["body"],
                {
                    "command": "refresh_unity",
                    "params": {
                        "mode": "if_dirty",
                        "force": False,
                        "paths": ["Assets/Scripts/Player.cs"],
                        "compile": "none",
                    },
                },
            )

    def test_adapter_console_uses_connector_console_params(self) -> None:
        response_body = json.dumps({"success": True, "message": "Retrieved 0 entries.", "data": []}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port)
            adapter = UnityBridgeAdapter(instances_dir=directory, process_checker=lambda pid: False)

            result = adapter.read_console(count=20, types=["error", "warning"], stacktrace="none")

            self.assertEqual(
                result,
                UnityActionResult(
                    tool="console",
                    command="console",
                    params={"count": 20, "type": "error,warning", "stacktrace": "none"},
                    success=True,
                    message="Retrieved 0 entries.",
                    data=[],
                ),
            )
            self.assertEqual(
                server.received[0]["body"],
                {
                    "command": "console",
                    "params": {"count": 20, "type": "error,warning", "stacktrace": "none"},
                },
            )

    def test_adapter_editor_play_waits_for_playing_state_after_port_change(self) -> None:
        response_body = json.dumps({"success": True, "message": "Entered play mode (confirmed)."}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port, timestamp=10)
            adapter = UnityBridgeAdapter(instances_dir=directory, process_checker=lambda pid: False)

            def write_playing() -> None:
                write_instance(directory, "game", state="playing", port=server.port + 2, timestamp=20)

            timer = threading.Timer(0.05, write_playing)
            timer.start()
            try:
                result = adapter.editor_play(
                    wait=True,
                    timeout_sec=2,
                    poll_interval_sec=0.01,
                )
            finally:
                timer.cancel()

            self.assertTrue(result.success)
            self.assertEqual(result.data["completion"], "confirmed")
            self.assertEqual(result.data["state"]["state"], "playing")
            self.assertEqual(result.data["initial_port"], server.port)
            self.assertEqual(result.data["current_port"], server.port + 2)
            self.assertEqual(
                server.received[0]["body"],
                {
                    "command": "manage_editor",
                    "params": {"action": "play", "wait_for_completion": False},
                },
            )

    def test_adapter_menu_sends_raw_menu_path(self) -> None:
        response_body = json.dumps({"success": True, "message": "Executed menu item."}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port)
            adapter = UnityBridgeAdapter(instances_dir=directory, process_checker=lambda pid: False)

            adapter.execute_menu_item("File/Save Project")

            self.assertEqual(
                server.received[0]["body"],
                {
                    "command": "menu",
                    "params": {"menu_path": "File/Save Project"},
                },
            )

    def test_adapter_reserialize_can_wait_for_ready_after_port_change(self) -> None:
        response_body = json.dumps({"success": True, "message": "Reserialize complete."}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port, timestamp=10)
            adapter = UnityBridgeAdapter(instances_dir=directory, process_checker=lambda pid: False)

            def write_ready() -> None:
                write_instance(directory, "game", port=server.port + 3, timestamp=20)

            timer = threading.Timer(0.05, write_ready)
            timer.start()
            try:
                result = adapter.reserialize_assets(
                    ["Assets/Prefabs/Player.prefab"],
                    wait=True,
                    timeout_sec=2,
                    stable_sec=0.01,
                    poll_interval_sec=0.01,
                )
            finally:
                timer.cancel()

            self.assertTrue(result.success)
            self.assertEqual(result.data["completion"], "confirmed")
            self.assertEqual(result.data["ready"]["timestamp"], 20)
            self.assertEqual(result.data["initial_port"], server.port)
            self.assertEqual(result.data["current_port"], server.port + 3)

    def test_adapter_exec_csharp_has_no_policy_gate(self) -> None:
        response_body = json.dumps({"success": True, "message": "ok", "data": 3}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port)
            adapter = UnityBridgeAdapter(instances_dir=directory, process_checker=lambda pid: False)

            result = adapter.exec_csharp("return 1 + 2;", usings=["UnityEditor"])

            self.assertEqual(result.data, 3)
            self.assertEqual(
                server.received[0]["body"],
                {
                    "command": "exec",
                    "params": {"code": "return 1 + 2;", "usings": ["UnityEditor"]},
                },
            )

    def test_adapter_playmode_tests_wait_for_result_file(self) -> None:
        response_body = json.dumps(
            {"success": True, "message": "running", "data": {"port": 0}}
        ).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp) / "instances"
            status_dir = Path(tmp) / "status"
            directory.mkdir()
            write_instance(directory, "game", port=server.port)
            adapter = UnityBridgeAdapter(
                instances_dir=directory,
                status_dir=status_dir,
                process_checker=lambda pid: False,
            )

            def write_results() -> None:
                result_path = test_results_path(server.port, status_dir=status_dir)
                result_path.parent.mkdir(parents=True, exist_ok=True)
                result_path.write_text(
                    json.dumps(
                        {
                            "success": False,
                            "message": "1 test(s) failed.",
                            "data": {"total": 1, "passed": 0, "failed": 1},
                        }
                    ),
                    encoding="utf-8",
                )

            timer = threading.Timer(0.05, write_results)
            timer.start()
            try:
                result = adapter.run_tests(
                    mode="PlayMode",
                    timeout_sec=2,
                    poll_interval_sec=0.01,
                )
            finally:
                timer.cancel()

            self.assertFalse(result.success)
            self.assertEqual(result.message, "1 test(s) failed.")
            self.assertEqual(result.data, {"total": 1, "passed": 0, "failed": 1})
            self.assertFalse(test_results_path(server.port, status_dir=status_dir).exists())
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

    def test_adapter_playmode_tests_can_return_without_waiting(self) -> None:
        response_body = json.dumps({"success": True, "message": "running"}).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port)
            adapter = UnityBridgeAdapter(instances_dir=directory, process_checker=lambda pid: False)

            result = adapter.run_tests(mode="PlayMode", wait=False)

            self.assertTrue(result.success)
            self.assertEqual(result.message, "running")

    def test_wait_for_test_results_retries_partial_json_until_valid(self) -> None:
        with TemporaryDirectory() as tmp:
            status_dir = Path(tmp)
            result_path = test_results_path(8090, status_dir=status_dir)
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text("{", encoding="utf-8")

            def finish_write() -> None:
                result_path.write_text(
                    json.dumps({"success": True, "message": "ok", "data": {"passed": 1}}),
                    encoding="utf-8",
                )

            timer = threading.Timer(0.05, finish_write)
            timer.start()
            try:
                response = wait_for_test_results(
                    8090,
                    status_dir=status_dir,
                    timeout_sec=2,
                    poll_interval_sec=0.01,
                )
            finally:
                timer.cancel()

            self.assertEqual(response, CommandResponse(success=True, message="ok", data={"passed": 1}))
            self.assertFalse(result_path.exists())

    def test_wait_for_test_results_keeps_partial_json_on_timeout(self) -> None:
        with TemporaryDirectory() as tmp:
            status_dir = Path(tmp)
            result_path = test_results_path(8090, status_dir=status_dir)
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text("{", encoding="utf-8")

            with self.assertRaises(DiscoveryError) as cm:
                wait_for_test_results(
                    8090,
                    status_dir=status_dir,
                    timeout_sec=0.05,
                    poll_interval_sec=0.01,
                )

            self.assertIn("last read error", str(cm.exception))
            self.assertTrue(result_path.exists())

    def test_adapter_tests_report_missing_test_framework_like_unity_cli(self) -> None:
        response_body = json.dumps(
            {"success": False, "message": "Unknown command: run_tests"}
        ).encode("utf-8")
        with TemporaryDirectory() as tmp, FakeUnityServer(response_body) as server:
            directory = Path(tmp)
            write_instance(directory, "game", port=server.port)
            adapter = UnityBridgeAdapter(instances_dir=directory, process_checker=lambda pid: False)

            result = adapter.run_tests()

            self.assertFalse(result.success)
            self.assertEqual(result.message, TEST_FRAMEWORK_MISSING_MESSAGE)

    def test_wait_for_test_results_fails_if_editor_stopped(self) -> None:
        stopped = Instance(state="stopped", project_path="D:/Game", port=8090, pid=1, timestamp=1)
        with TemporaryDirectory() as tmp:
            with self.assertRaises(DiscoveryError):
                wait_for_test_results(
                    8090,
                    status_dir=Path(tmp),
                    timeout_sec=2,
                    poll_interval_sec=0.01,
                    status_resolver=lambda: stopped,
                )


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._update_check_env = patch.dict(os.environ, {"UNITY_BRIDGE_SKIP_UPDATE_CHECK": "1"})
        self._update_check_env.start()

    def tearDown(self) -> None:
        self._update_check_env.stop()

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
                f"WARNING: Unity Connector version 0.1.2 differs from UnityBridge CLI version {cli_module.__version__}",
                stderr.getvalue(),
            )

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

        payload = cli_module._to_jsonable(result)

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
                f"WARNING: Unity Connector version 0.1.2 differs from UnityBridge CLI version {cli_module.__version__}",
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
            patch.object(cli_module, "_current_package_version", return_value="0.1.1"),
            patch.object(cli_module, "_read_remote_repository_file", side_effect=lambda repo, ref, path, **kwargs: remote_files[path]),
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

    def test_cli_update_check_prints_up_to_date(self) -> None:
        remote_files = {
            "pyproject.toml": '[project]\nversion = "0.1.5"\n',
            "unity-bridge-connector/package.json": '{"version":"0.1.5"}',
        }

        with (
            patch.object(cli_module, "_current_package_version", return_value="0.1.5"),
            patch.object(cli_module, "_read_remote_repository_file", side_effect=lambda repo, ref, path, **kwargs: remote_files[path]),
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
            patch.object(cli_module.sys, "frozen", True, create=True),
            patch.object(cli_module, "_read_remote_repository_file", side_effect=lambda repo, ref, path, **kwargs: remote_files[path]),
        ):
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = cli_main(["update", "--check"])

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn(f"UnityBridge standalone CLI: {cli_module.__version__}", output)
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
                patch.object(cli_module, "_current_package_version", return_value="0.1.4"),
                patch.object(cli_module, "_remote_python_version", return_value="0.1.5"),
                patch.object(cli_module, "_update_check_cache_path", return_value=cache_path),
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
                patch.object(cli_module, "_remote_python_version", side_effect=AssertionError("should not check")),
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
                patch.object(cli_module, "_remote_python_version", side_effect=AssertionError("should not check")),
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
                patch.object(cli_module.time, "time", return_value=1_001.0),
                patch.object(cli_module, "_remote_python_version", side_effect=AssertionError("should not check")),
                patch.object(cli_module, "_update_check_cache_path", return_value=cache_path),
                redirect_stdout(StringIO()),
            ):
                exit_code = cli_main(["--instances-dir", str(directory), "status"])

            self.assertEqual(exit_code, 0)

    def test_cli_standalone_update_dry_run_uses_windows_installer(self) -> None:
        with (
            patch.object(cli_module.sys, "frozen", True, create=True),
            patch.object(cli_module.sys, "platform", "win32"),
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
            patch.object(cli_module.sys, "frozen", True, create=True),
            patch.object(cli_module.sys, "platform", "darwin"),
            patch.object(cli_module.platform, "machine", return_value="arm64"),
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

    def test_standalone_update_keeps_custom_install_directory(self) -> None:
        custom = Path("custom install's directory") / "unity-bridge.exe"
        with patch.object(cli_module.sys, "executable", str(custom)):
            windows = cli_module._standalone_windows_update_command("v0.2.1")[-1]
            posix = cli_module._standalone_posix_update_command("v0.2.1")[-1]
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
                    patch.object(cli_module.sys, "platform", platform_name), \
                    patch.object(cli_module.platform, "machine", return_value=machine):
                self.assertEqual(cli_module._standalone_asset_name(), expected)


if __name__ == "__main__":
    unittest.main()
