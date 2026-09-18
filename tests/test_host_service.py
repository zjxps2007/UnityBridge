from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from unity_bridge.client import Instance
from unity_bridge.host import host_status, try_host_command
from unity_bridge.host.compiler import CompilerError
from unity_bridge.host.context import PreparedContext
from unity_bridge.host.registry import atomic_json, endpoint_path, register_launcher
from unity_bridge.host.service import HostService
from unity_bridge.host.transport import TransportError, post


def eventually(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("Expected asynchronous state was not reached")


class FakeCompiler:
    def __init__(self):
        self.last_info = {}
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.calls = []

    def prewarm(self):
        return {"protocol": 1, "success": True}

    def request(self, payload, *, deadline):
        self.calls.append(payload)
        self.started.set()
        if not self.release.wait(max(0, deadline - time.monotonic())):
            # A timed-out worker cannot produce a successful assembly. Windows
            # waits may return just before monotonic() crosses the deadline.
            raise CompilerError("compiler_timeout", "Fixture compilation timed out")
        return {"reference_generation": payload["reference_generation"],
                "assembly_base64": base64.b64encode(payload["code"].encode()).decode()}

    def close(self):
        self.release.set()


class HostServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="unity-host-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.root = self.directory / "host"
        self.instances = self.directory / "instances"
        self.instances.mkdir()
        self.project_path = str(self.directory / "Unity Project")
        worker = self.directory / "compiler"
        worker.write_text("test fixture")
        self.descriptor = register_launcher(sys.executable, str(worker), python_module=True,
                                            version="test", root=self.root, instances_dir=str(self.instances))
        self.token = self.descriptor["token"]
        self.compiler = FakeCompiler()
        self.context_calls = 0
        self.executed = []
        self.drop_response = False
        self.reject_stale_once = False
        self.snapshot = {"bridgeProtocol": 1, "domainId": "domain-one", "referenceGeneration": 1,
                         "projectPath": self.project_path, "pid": os.getpid(), "state": "ready",
                         "unityVersion": "6000.3", "connectorVersion": "test", "timestamp": 1,
                         "compileErrors": False}
        default_fixture = self

        class Connector(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                fixture = getattr(self.server, "audit_fixture", default_fixture)
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.headers.get("X-UnityBridge-Token") != fixture.token:
                    self.send_error(403)
                    return
                command = body["command"]
                if command == "bridge_context":
                    fixture.context_calls += 1
                    response = {"success": True, "message": "context", "data": {
                        "protocol": 1, "domainId": fixture.snapshot["domainId"],
                        "referenceGeneration": fixture.snapshot["referenceGeneration"],
                        "projectPath": fixture.project_path, "pid": os.getpid(), "languageVersion": "9.0",
                        "references": [{"path": "fixture.dll", "mvid": "fixture-mvid", "name": "fixture"}],
                        "instance": fixture.snapshot}}
                elif command == "get_editor_state":
                    response = {"success": True, "message": "state", "data": {
                        "requestId": body["params"].get("request_id"), "instance": fixture.snapshot}}
                elif fixture.reject_stale_once:
                    fixture.reject_stale_once = False
                    fixture.snapshot["domainId"] = "domain-two"
                    fixture.publish_snapshot()
                    response = {"success": False, "message": "changed", "data": {
                        "completion": "not_started", "reason": "stale_domain", "domainId": "domain-two"}}
                else:
                    if command == "bridge_exec_assembly":
                        command = base64.b64decode(body["params"]["assembly"]).decode()
                    fixture.executed.append(command)
                    if fixture.drop_response:
                        self.connection.close()
                        return
                    response = {"success": True, "message": "OK", "data": command}
                raw = json.dumps(response).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    pass

        self.connector = ThreadingHTTPServer(("127.0.0.1", 0), Connector)
        self.connector.daemon_threads = True
        threading.Thread(target=self.connector.serve_forever, daemon=True).start()
        self.addCleanup(self.connector.server_close)
        self.addCleanup(self.connector.shutdown)
        self.snapshot["port"] = self.connector.server_address[1]
        self.publish_snapshot()
        self.service = HostService(self.root, self.descriptor, instances_dir=self.instances,
                                   compiler=self.compiler, idle_seconds=300, scan_interval=.02)
        self.thread = threading.Thread(target=self.service.serve, daemon=True)
        self.thread.start()
        self.env_patch = patch.dict(os.environ, {"UNITY_BRIDGE_HOST_HOME": str(self.root)})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.addCleanup(self.stop_host)
        eventually(lambda: host_status(self.instance(), self.instances).get("project_registered"))
        eventually(lambda: host_status(self.instance(), self.instances).get("prewarm_state") == "ready")
        self.compiler.calls.clear()
        self.compiler.started.clear()

    def publish_snapshot(self):
        atomic_json(self.instances / "project.json", dict(self.snapshot))

    def instance(self):
        return Instance.from_dict(self.snapshot)

    def stop_host(self):
        self.compiler.release.set()
        self.service.request_stop()
        self.thread.join(4)
        self.assertFalse(self.thread.is_alive())

    def payload(self, command="mutate", timeout=3, params=None, request_id=None):
        return {"command": command, "params": params or {}, "request_id": request_id or uuid.uuid4().hex,
                "deadline_unix_ms": int((time.time() + timeout) * 1000),
                "target": {"projectPath": self.project_path, "pid": os.getpid(), "port": self.snapshot["port"]}}

    def call(self, command="mutate", timeout=3, params=None):
        return post(self.service.port, self.token, "/command", self.payload(command, timeout, params), timeout + 1)

    def test_ordinary_calls_do_not_repeat_context_negotiation_or_start_compiler(self):
        before = self.context_calls
        for _ in range(3):
            self.assertTrue(self.call()["success"])
        self.assertEqual(self.context_calls, before)
        self.assertEqual(self.compiler.calls, [])
        self.assertEqual(self.executed, ["mutate"] * 3)
        self.assertEqual(host_status(self.instance(), self.instances)["state"], "running")

    def test_change_notification_wakes_long_periodic_scan(self):
        self.service.scan_interval = 30
        self.service.discovery_wakeup.set()
        time.sleep(.06)
        before = self.context_calls
        self.snapshot["domainId"] = "notified-domain"
        self.publish_snapshot()
        with self.assertRaises(TransportError):
            post(self.service.port, "invalid", "/changed", {}, 1)
        self.assertTrue(post(self.service.port, self.token, "/changed", {}, 1)["accepted"])
        eventually(lambda: self.context_calls > before, timeout=2)
        self.assertTrue(self.call("after-notification")["success"])

    def test_control_refreshes_stale_port_before_dispatch_without_periodic_scan(self):
        self.service.scan_interval = 30
        self.service.discovery_wakeup.set()
        time.sleep(.06)
        replacement = ThreadingHTTPServer(("127.0.0.1", 0), self.connector.RequestHandlerClass)
        replacement.daemon_threads = True
        threading.Thread(target=lambda: replacement.serve_forever(poll_interval=.01), daemon=True).start()
        self.addCleanup(replacement.server_close)
        self.addCleanup(replacement.shutdown)
        self.snapshot["port"] = replacement.server_port
        self.publish_snapshot()
        # Keep the old listener alive: a request must select the new authoritative
        # port, not rely on an old socket error to recover or replay.
        with patch("unity_bridge.host.service.post", wraps=post) as sent:
            result = self.call("get_editor_state", params={"request_id": "new-listener"})
        self.assertEqual(result["data"]["requestId"], "new-listener")
        controls = [call for call in sent.call_args_list if call.args[3].get("command") == "get_editor_state"]
        self.assertEqual(len(controls), 1)
        self.assertEqual(controls[0].args[0], replacement.server_port)

    def test_compile_preserves_fifo_while_live_control_query_bypasses_it(self):
        self.compiler.release.clear()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.call, "exec", 3, {"code": "exec-one"})
            self.assertTrue(self.compiler.started.wait(1))
            second = pool.submit(self.call, "mutate-two")
            state = self.call("get_editor_state", params={"request_id": "live"})
            self.assertEqual(state["data"]["requestId"], "live")
            self.assertEqual(self.executed, [])
            self.compiler.release.set()
            self.assertTrue(first.result()["success"])
            self.assertTrue(second.result()["success"])
        self.assertEqual(self.executed, ["exec-one", "mutate-two"])
        self.assertTrue(self.compiler.calls[0]["fresh_identity"])

    def test_expired_queued_command_never_executes_after_compilation_finishes(self):
        self.compiler.release.clear()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.call, "exec", 3, {"code": "exec-one"})
            self.assertTrue(self.compiler.started.wait(1))
            expired = self.call("must-not-run", timeout=.1)
            self.assertEqual(expired["data"]["completion"], "not_started")
            self.assertEqual(expired["data"]["reason"], "expired")
            self.compiler.release.set()
            self.assertTrue(first.result()["success"])
        time.sleep(.05)
        self.assertEqual(self.executed, ["exec-one"])

    def test_compilation_deadline_cannot_later_invoke_assembly(self):
        self.compiler.release.clear()
        response = self.call("exec", timeout=.1, params={"code": "must-not-run"})
        self.assertEqual(response["data"]["completion"], "not_started")
        self.compiler.release.set()
        time.sleep(.05)
        self.assertEqual(self.executed, [])

    def test_domain_reload_waits_and_renegotiates_before_first_execution(self):
        self.snapshot["state"] = "reloading"
        self.publish_snapshot()
        self.service.scan_once()
        before = self.context_calls
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(self.call, "after-reload")
            time.sleep(.08)
            self.assertEqual(self.executed, [])
            self.snapshot.update(state="ready", domainId="domain-two", referenceGeneration=2)
            self.publish_snapshot()
            self.assertTrue(waiting.result()["success"])
        self.assertEqual(self.executed, ["after-reload"])
        self.assertEqual(self.context_calls, before + 1)

    def test_manifest_prewarm_compiles_once_without_loading_into_unity(self):
        self.snapshot["referenceGeneration"] = 2
        self.publish_snapshot()
        eventually(lambda: len(self.compiler.calls) == 1)
        eventually(lambda: host_status(self.instance(), self.instances).get("prewarm_state") == "ready")
        self.assertEqual(self.compiler.calls[0]["code"], "return null;")
        for _ in range(5):
            self.service.scan_once()
        self.assertEqual(len(self.compiler.calls), 1)
        self.assertEqual(self.executed, [])

    def test_exec_reuses_prepared_context_until_reference_generation_changes(self):
        project = self.service._project_list()[0]
        initial = project.context
        with patch.object(PreparedContext, "from_connector", wraps=PreparedContext.from_connector) as prepare:
            for code in ("first-exec", "second-exec"):
                self.assertTrue(self.call("exec", params={"code": code})["success"])
            prepare.assert_not_called()
            self.assertIs(project.context, initial)
            self.assertTrue(all(call["fresh_identity"] for call in self.compiler.calls))
            self.assertTrue(all(call["reference_generation"] == initial.compiler_reference_generation
                                for call in self.compiler.calls))
            self.snapshot["referenceGeneration"] += 1
            self.publish_snapshot()
            eventually(lambda: project.context is not initial)
            eventually(lambda: project.prewarm_state == "ready")
            self.assertEqual(prepare.call_count, 1)
            self.assertTrue(self.call("exec", params={"code": "after-ref-change"})["success"])
            self.assertEqual(prepare.call_count, 1)
        self.assertEqual(self.executed, ["first-exec", "second-exec", "after-ref-change"])

    def test_proven_not_started_stale_domain_can_retry_but_executes_once(self):
        self.reject_stale_once = True
        response = self.call("mutation")
        self.assertTrue(response["success"])
        self.assertEqual(self.executed, ["mutation"])
        self.assertEqual(self.context_calls, 2)

    def test_post_dispatch_disconnect_is_unknown_and_never_replayed(self):
        self.drop_response = True
        response = try_host_command(self.instance(), "mutation", {}, 1000, self.instances)
        self.assertTrue(response.completion_unknown)
        self.assertEqual(self.executed, ["mutation"])

    def test_request_id_is_deduplicated_and_cannot_be_reused_for_different_work(self):
        payload = self.payload(request_id="same")
        first = post(self.service.port, self.token, "/command", payload, 3)
        second = post(self.service.port, self.token, "/command", payload, 3)
        self.assertEqual(first, second)
        self.assertEqual(self.executed, ["mutate"])
        payload["command"] = "different"
        rejected = post(self.service.port, self.token, "/command", payload, 3)
        self.assertEqual(rejected["data"]["reason"], "request_id_conflict")

    def test_authentication_and_browser_origin_rejected(self):
        with self.assertRaises(TransportError):
            post(self.service.port, "incorrect", "/command", self.payload(), 1)
        import urllib.error
        import urllib.request
        request = urllib.request.Request(f"http://127.0.0.1:{self.service.port}/command",
                                         data=json.dumps(self.payload()).encode(),
                                         headers={"X-UnityBridge-Token": self.token, "Origin": "https://example.com"})
        with self.assertRaises(urllib.error.HTTPError) as result:
            urllib.request.urlopen(request, timeout=1)
        self.assertEqual(result.exception.code, 403)
        self.assertEqual(self.executed, [])

    def test_accepted_response_socket_disables_nagle_without_a_timing_threshold(self):
        handler = self.service.server.RequestHandlerClass
        original = handler.reply
        observed = []

        def inspect_socket(request, status, value):
            observed.append(request.connection.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY))
            return original(request, status, value)

        with patch.object(handler, "reply", inspect_socket):
            self.assertTrue(self.call("small-response")["success"])
        self.assertEqual(len(observed), 1)
        self.assertTrue(observed[0])  # Darwin can return a nonzero bit flag rather than 1.

    def test_playing_and_paused_projects_can_execute(self):
        for state in ("playing", "paused"):
            self.snapshot["state"] = state
            self.publish_snapshot()
            self.service.scan_once()
            self.assertTrue(self.call(state)["success"])
        self.assertEqual(self.executed, ["playing", "paused"])

    def test_unavailable_host_returns_none_before_post_and_status_never_probes_unity(self):
        before = self.context_calls
        self.assertTrue(host_status(self.instance(), self.instances)["project_registered"])
        self.assertEqual(self.context_calls, before)
        endpoint_path(self.root, self.descriptor["runtimeId"]).unlink()
        self.assertIsNone(try_host_command(self.instance(), "mutation", {}, 1000, self.instances))
        self.assertEqual(self.executed, [])

    def test_compiler_override_keeps_legacy_route(self):
        self.assertIsNone(try_host_command(self.instance(), "exec", {"csc": "custom"}, 1000, self.instances))
        self.assertEqual(self.executed, [])

    def test_control_only_clients_keep_bounded_request_history(self):
        for index in range(270):
            payload = self.payload("get_editor_state", request_id=f"read-{index}")
            response = self.service.submit(payload)
            self.assertTrue(response["success"])
        project = self.service._project_list()[0]
        self.assertLessEqual(len(project.jobs), 256)
        payload = self.payload("get_editor_state", request_id="read-269")
        self.assertEqual(self.service.submit(payload), project.jobs["read-269"].response)

    def test_new_launcher_retires_idle_older_runtime_even_with_live_unity(self):
        register_launcher(sys.executable, self.descriptor["workerPath"], python_module=True,
                          version="new-runtime", root=self.root, instances_dir=str(self.instances))
        self.thread.join(3)
        self.assertFalse(self.thread.is_alive())

    def test_transient_heartbeat_read_failure_does_not_retire_a_live_editor(self):
        with patch("unity_bridge.host.service.read_json", return_value=None):
            self.service.scan_once()
        self.assertTrue(self.call("still-live")["success"])
        self.assertEqual(self.executed, ["still-live"])

    def test_explicit_stopped_heartbeat_retires_project(self):
        self.snapshot["state"] = "stopped"
        self.publish_snapshot()
        self.service.scan_once()
        response = self.call("must-not-run")
        self.assertEqual(response["data"]["completion"], "not_started")
        self.assertEqual(self.executed, [])

    def test_another_project_executes_while_first_project_compiles(self):
        second_snapshot = dict(self.snapshot, projectPath=str(self.directory / "Second Unity Project"),
                               domainId="second-project-domain")
        second_fixture = SimpleNamespace(
            token=self.token, snapshot=second_snapshot, project_path=second_snapshot["projectPath"],
            context_calls=0, executed=[], drop_response=False, reject_stale_once=False)
        second_connector = ThreadingHTTPServer(("127.0.0.1", 0), self.connector.RequestHandlerClass)
        second_connector.daemon_threads = True
        second_connector.audit_fixture = second_fixture
        second_snapshot["port"] = second_connector.server_address[1]
        threading.Thread(target=second_connector.serve_forever, daemon=True).start()
        self.addCleanup(second_connector.server_close)
        self.addCleanup(second_connector.shutdown)
        atomic_json(self.instances / "second-project.json", second_snapshot)
        second_instance = Instance.from_dict(second_snapshot)
        eventually(lambda: host_status(second_instance, self.instances).get("prewarm_state") == "ready")
        self.compiler.started.clear()
        self.compiler.release.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.call, "exec", 3, {"code": "first-project-exec"})
            self.assertTrue(self.compiler.started.wait(1))
            second = try_host_command(second_instance, "second-project-mutation", {}, 1000, self.instances)
            self.assertTrue(second.success)
            self.assertEqual(second_fixture.executed, ["second-project-mutation"])
            self.assertEqual(self.executed, [])
            self.compiler.release.set()
            self.assertTrue(first.result()["success"])
        self.assertEqual(self.executed, ["first-project-exec"])

    def test_project_target_requires_matching_unity_process_identity(self):
        payload = self.payload("must-not-run")
        payload["target"]["pid"] += 100000
        response = self.service.submit(payload)
        self.assertEqual(response["data"]["reason"], "unsupported_connector")
        self.assertEqual(self.executed, [])

    def test_temporary_registry_publication_failure_keeps_service_live_and_retries(self):
        project = self.service._project_list()[0]
        previous = self.service.last_registry
        with project.condition:
            project.prewarm_state = 'fixture-updated'
        with patch('unity_bridge.host.service.atomic_json', side_effect=PermissionError('reader lock')):
            self.service._write_registry()
            self.assertEqual(self.service.last_registry, previous)
            self.service.last_registry = None
            health = post(self.service.port, self.token, '/health', {}, 1)
            self.assertEqual(health['protocol'], 1)
            self.assertEqual(health['projects'], [])
        self.service._write_registry()
        self.assertEqual(self.service.last_registry['projects'][0]['prewarmState'], 'fixture-updated')
        self.assertTrue(self.call('still-live')['success'])

    def test_instance_directory_symlink_alias_matches_registered_physical_path(self):
        alias = self.directory / 'instances alias'
        try:
            alias.symlink_to(self.instances, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'Directory symlink creation is unavailable: {exc}')
        self.assertTrue(host_status(self.instance(), alias)['project_registered'])
        result = try_host_command(self.instance(), 'through-alias', {}, 1000, alias)
        self.assertTrue(result.success)
        self.assertEqual(self.executed, ['through-alias'])


if __name__ == "__main__":
    unittest.main()
