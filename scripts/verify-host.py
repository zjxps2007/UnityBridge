"""Exercise the external host and real Unity Connector in a disposable project.

Results are functional evidence, not a matched performance benchmark. The driver
owns its Unity process and isolated host registry; existing projects are untouched.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from unity_bridge.host.compiler import CompilerWorker
from unity_bridge.client import _read_instance_text
from unity_bridge.host.registry import atomic_json


def save(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def wait_for(function, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = function()
        if result:
            return result
        time.sleep(.05)
    raise TimeoutError("Timed out waiting for " + getattr(function, "__name__", "condition"))


def post(port, payload, *, token=None, path="/command", timeout=45):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-UnityBridge-Token"] = token
    try:
        connection.request("POST", path, json.dumps(payload), headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def require_success(value):
    assert value.get("success") is True, value
    assert not isinstance(value.get("data"), dict) or value["data"].get("completion") != "unknown", value
    return value.get("data")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unity-editor", required=True, type=Path)
    parser.add_argument("--unity-version", required=True)
    parser.add_argument("--worker", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cli-exe", type=Path, help="Optional packaged CLI; source Python is the default.")
    parser.add_argument("--stale-host-registry", action="store_true",
                        help="Seed a stale endpoint whose PID belongs to this live driver; verify automatic recovery.")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error("--output must be empty; evidence is never overwritten")
    unity, worker = args.unity_editor.resolve(), args.worker.resolve()
    assert unity.is_file() and worker.is_file()
    project = output / "UnityProject"
    editor = project / "Assets/Editor"
    editor.mkdir(parents=True)
    package = json.loads((REPO / "unity-bridge-connector/package.json").read_text(encoding="utf-8"))
    expected_version = package["version"]
    package.pop("dependencies", None)
    package_root = project / "Packages" / package["name"]
    package_root.mkdir(parents=True)
    save(package_root / "package.json", package)
    hashes = {}
    # Working-tree enumeration includes newly added, not-yet-committed Connector files.
    for source in (REPO / "unity-bridge-connector/Editor").rglob("*"):
        relative = source.relative_to(REPO / "unity-bridge-connector/Editor")
        if not source.is_file() or "TestRunner" in relative.parts or relative.name == "TestRunner.meta":
            continue
        destination = package_root / "Editor" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if source.suffix == ".cs":
            hashes[relative.as_posix()] = hashlib.sha256(source.read_bytes()).hexdigest()
    for name in ("StartupDiscoveryAudit.cs", "HostConnectorAudit.cs", "HeartbeatPublishingAudit.cs"):
        shutil.copy2(REPO / "tests/unity" / name, editor)
    legacy = (REPO / "unity-bridge-connector/Editor/ToolDiscovery.cs").read_text(encoding="utf-8")
    (editor / "LegacyToolDiscovery.cs").write_text(legacy.replace("ToolDiscovery", "LegacyToolDiscovery"), encoding="utf-8")
    revision = editor / "StartupRevision.cs"
    revision.write_text("public static class StartupRevision { public const int Value = 0; }\n", encoding="utf-8")
    plugins = project / "Assets/Plugins/Editor"
    plugins.mkdir(parents=True)
    # Windows/Linux keep Data beside Unity; macOS uses Unity.app/Contents.
    editor_data = unity.parent / "Data"
    if not editor_data.is_dir():
        editor_data = unity.parents[1]
    shutil.copy2(editor_data / "Managed/Newtonsoft.Json.dll", plugins)
    (project / "ProjectSettings").mkdir()
    (project / "ProjectSettings/ProjectVersion.txt").write_text(f"m_EditorVersion: {args.unity_version}\n", encoding="utf-8")
    save(project / "Packages/manifest.json", {"dependencies": {
        f"com.unity.modules.{name}": "1.0.0" for name in ("imgui", "imageconversion", "screencapture", "jsonserialize")}})

    env = dict(os.environ, PYTHONPATH=str(REPO / "src"), UNITY_BRIDGE_HOST_HOME=str(output / "host"),
               UNITY_BRIDGE_SKIP_UPDATE_CHECK="1")
    cli = [str(args.cli_exe.resolve())] if args.cli_exe else [sys.executable, "-m", "unity_bridge"]
    register = (cli + ["_host", "register", "--executable", cli[0], "--worker", str(worker)]
                if args.cli_exe else
                [sys.executable, "-m", "unity_bridge", "_host", "register", "--executable", sys.executable,
                 "--python-module", "--worker", str(worker)])
    registered = subprocess.run(register, cwd=REPO, env=env, capture_output=True, text=True, timeout=30)
    (output / "registration.log").write_text(registered.stdout + registered.stderr, encoding="utf-8")
    assert registered.returncode == 0, registered.stderr
    descriptor = read(output / "host/launcher.json")
    token = descriptor["token"]
    registry_path = output / "host/instances" / (descriptor["runtimeId"] + ".json")
    if args.stale_host_registry:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            unused_port = probe.getsockname()[1]
        atomic_json(registry_path, {"protocol": 1, "runtimeId": descriptor["runtimeId"],
                                   "version": descriptor["version"], "pid": os.getpid(), "port": unused_port,
                                   "token": token, "projects": []})
    results = {"unity_version": args.unity_version, "expected_connector_version": expected_version,
               "source_sha256": hashes, "checks": [], "passed": False,
               "scope": "Empty-project batch-mode functional checks, not GUI or performance measurements."}
    process = subprocess.Popen([str(unity), "-batchmode", "-nographics", "-projectPath", str(project),
                                "-logFile", str(output / "unity.log"), "-executeMethod", "StartupDiscoveryAudit.Start"],
                               env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    compiler = None
    pool = ThreadPoolExecutor(max_workers=3)
    heartbeat_file = None

    def heartbeat():
        nonlocal heartbeat_file
        if process.poll() is not None:
            raise RuntimeError("Unity exited; inspect unity.log")
        if heartbeat_file is not None:
            # Use the client reader's bounded Windows atomic-replacement retries.
            return json.loads(_read_instance_text(heartbeat_file))
        for path in (Path.home() / ".unity-bridge/instances").glob("*.json"):
            value = read(path)
            if value and value.get("pid") == process.pid and value.get("projectPath", "").casefold() == project.as_posix().casefold():
                heartbeat_file = path
                return value
        return {}

    def ready(state="ready", timeout=45):
        return wait_for(lambda: (value if (value := heartbeat()).get("state") == state and not value.get("compileErrors") else None), timeout)

    def endpoint():
        return read(registry_path) or {}

    def host(command, params=None, *, seconds=40, request_id=None):
        value = heartbeat()
        payload = {"command": command, "params": params or {}, "request_id": request_id or uuid.uuid4().hex,
                   "deadline_unix_ms": int(time.time() * 1000 + seconds * 1000),
                   "target": {"projectPath": project.as_posix(), "pid": process.pid, "port": value["port"]}}
        status, result = post(endpoint()["port"], payload, token=token, timeout=seconds + 3)
        assert status == 200, (status, result)
        return result

    def direct(command, params=None, *, seconds=40, auth=True, **extra):
        payload = {"command": command, "params": params or {}, "request_id": uuid.uuid4().hex,
                   "deadline_unix_ms": int(time.time() * 1000 + seconds * 1000), **extra}
        return post(heartbeat()["port"], payload, token=token if auth else None, timeout=max(3, seconds + 2))

    def health():
        status, value = post(endpoint()["port"], {}, token=token, path="/health")
        assert status == 200, value
        return value

    def check(name, function):
        started = time.perf_counter()
        row = {"name": name, "passed": False}
        results["checks"].append(row)
        try:
            row["result"] = function()
            row["passed"] = True
            print(name + ": passed", flush=True)
            return row["result"]
        except Exception as error:
            row["error"] = repr(error)
            raise
        finally:
            row["elapsed_ms"] = (time.perf_counter() - started) * 1000
            save(output / "results.json", results)

    try:
        first = ready(timeout=150)
        assert first["connectorVersion"] == expected_version and first["bridgeProtocol"] == 1, first
        results["initial_heartbeat"] = first
        wait_for(lambda: endpoint() if any(item.get("pid") == process.pid for item in endpoint().get("projects", [])) else None, 45)
        results["host_pid"] = endpoint()["pid"]
        if args.stale_host_registry:
            assert results["host_pid"] != os.getpid(), "An unrelated live PID prevented host startup"
            results["stale_registry_recovery"] = {"unrelated_pid": os.getpid(), "host_pid": results["host_pid"], "passed": True}
        context = require_success(direct("bridge_context")[1])
        results["context_summary"] = {key: context[key] for key in ("domainId", "referenceGeneration", "languageVersion", "pid")}
        results["context_summary"]["reference_count"] = len(context["references"])
        check("connector_protocol_audit", lambda: require_success(host("host_connector_audit")))

        def authentication():
            status, denied = direct("bridge_context", auth=False)
            assert status == 403 and denied["data"]["reason"] == "unauthorized", (status, denied)
            host_status, _ = post(endpoint()["port"], {}, token="invalid", path="/health")
            assert host_status == 403, host_status
            return {"connector_http": status, "host_http": host_status}
        check("authentication", authentication)

        def cli_routing():
            response = subprocess.run(cli + ["--json", "--no-update-check", "--project", str(project),
                                             "exec", "--code", "return 20 + 22;"],
                                      cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
            assert response.returncode == 0, response.stderr
            value = json.loads(response.stdout)
            assert require_success(value) == 42, value
            worker_state = health()["compiler"]
            assert worker_state.get("assembly_name"), "CLI bypassed external compiler host"
            return {"response": value, "compiler": worker_state}
        check("cli_uses_external_compiler", cli_routing)

        def repeated_exec():
            values = [require_success(host("exec", {"code": "return 77;"})) for _ in range(2)]
            state = health()["compiler"]
            assert values == [77, 77] and state.get("cache_hit") is True, (values, state)
            static_code = "return ++Counter; } public static int Counter; public static object Tail() { return null;"
            counters = [require_success(host("exec", {"code": static_code})) for _ in range(2)]
            assert counters == [1, 1], counters
            return {"results": values, "compiler": state, "fresh_static_results": counters}
        check("repeated_exec_and_static_isolation", repeated_exec)

        compiler = CompilerWorker(str(worker))
        def compile_bytes(code, fresh=False):
            current = require_success(direct("bridge_context")[1])
            return compiler.request({"operation": "compile", "code": code, "usings": [],
                                     "language_version": current["languageVersion"], "references": current["references"],
                                     "project_id": project.as_posix(), "reference_generation": "native-audit",
                                     "fresh_identity": fresh}, deadline=time.monotonic() + 30)
        static_pe = compile_bytes("return ++Counter; } public static int Counter; public static object Tail() { return null;")
        check("same_pe_reload_observation", lambda: require_success(host("host_connector_audit", {"assembly": static_pe["assembly_base64"]})))

        def invalid_metadata():
            current = require_success(direct("bridge_context")[1])
            cases = {"stale_domain": {"domain_id": "old-domain", "reference_generation": current["referenceGeneration"]},
                     "stale_references": {"domain_id": current["domainId"], "reference_generation": current["referenceGeneration"] - 1},
                     "expired": {"deadline_unix_ms": int(time.time() * 1000) - 1}}
            for expected, metadata in cases.items():
                response = direct("bridge_exec_assembly", {"assembly": static_pe["assembly_base64"]}, **metadata)[1]
                assert response.get("success") is False and response["data"]["reason"] == expected and response["data"]["completion"] == "not_started", response
            return list(cases)
        check("stale_and_expired_preexecution", invalid_metadata)

        def queued_deadline():
            before = require_success(direct("host_audit_counter")[1])
            delayed = pool.submit(direct, "host_audit_delay", {"milliseconds": 1800})
            time.sleep(.15)
            control = require_success(host("get_editor_state", {"request_id": "control-audit"}))
            assert not delayed.done(), "State control waited for the execution lock"
            expired = direct("host_audit_counter", {"increment": True}, seconds=.15)[1]
            assert expired["data"]["reason"] == "expired" and expired["data"]["completion"] == "not_started", expired
            require_success(delayed.result(timeout=5)[1])
            after = require_success(direct("host_audit_counter")[1])
            assert after == before + 1, (before, after)
            return {"before": before, "after": after, "control_state": control["instance"]["state"], "expired": expired}
        check("control_bypass_and_no_late_side_effect", queued_deadline)

        def while_compiling():
            code = "return 42; } " + " ".join(f"public static int M{i}() => {i};" for i in range(6000)) + " public static object Tail() { return null;"
            compiled = pool.submit(host, "exec", {"code": code})
            time.sleep(.1)
            live = require_success(host("get_editor_state", {"request_id": "compiling-control"}))
            still_compiling = not compiled.done()
            value = require_success(compiled.result(timeout=45))
            assert value == 42 and still_compiling, (value, still_compiling)
            return {"live_state": live["instance"]["state"], "control_finished_before_exec": still_compiling, "result": value}
        check("live_control_during_external_compile", while_compiling)

        def compilation_error():
            response = host("exec", {"code": "return MissingAuditSymbol;"})
            assert not response["success"] and response["data"]["completion"] == "not_started", response
            assert response["data"]["reason"] == "compile_error", response
            assert require_success(host("exec", {"code": "return 5;"})) == 5
            return response
        check("compile_error_and_recovery", compilation_error)

        def reference_invalidation():
            emitted = compile_bytes("return 191;", fresh=True)
            reference_path = output / "AuditReference.dll"
            reference_path.write_bytes(base64.b64decode(emitted["assembly_base64"]))
            value = require_success(host("host_connector_audit", {"referencePath": str(reference_path)}))
            assert value["after"] > value["before"], value
            assert require_success(host("exec", {"code": "return 6;"})) == 6
            return value
        check("reference_manifest_invalidation", reference_invalidation)

        def reload():
            old = heartbeat()["domainId"]
            revision.write_text("public static class StartupRevision { public const int Value = 1; }\n", encoding="utf-8")
            requested = host("refresh_unity", {"paths": ["Assets/Editor/StartupRevision.cs"], "compile": "request"})
            assert requested.get("success"), requested
            wait_for(lambda: (value if (value := heartbeat()).get("domainId") != old and value.get("state") == "ready" else None), 60)
            value = require_success(host("exec", {"code": "return StartupRevision.Value;"}))
            assert value == 1 and endpoint()["pid"] == results["host_pid"], (value, endpoint().get("pid"))
            return {"previous_domain": old, "new_domain": heartbeat()["domainId"], "host_pid": endpoint()["pid"], "revision": value}
        check("domain_reload_preserves_host", reload)

        def play_pause():
            response = host("manage_editor", {"action": "play", "wait_for_completion": False})
            assert response.get("success"), response
            ready("playing", 60)
            assert require_success(host("exec", {"code": "return UnityEditor.EditorApplication.isPlaying;"})) is True
            observations = []
            for expected in ("paused", "playing"):
                (project / "audit-pause.json").unlink(missing_ok=True)
                (project / "audit-pause-request").write_text("toggle", encoding="utf-8")
                event = wait_for(lambda: read(project / "audit-pause.json"), 10)
                assert event.get("matches") and event.get("observed") == expected, event
                (project / "host-audit-readiness.json").unlink(missing_ok=True)
                (project / "host-audit-readiness-request").write_text("check", encoding="utf-8")
                guard = wait_for(lambda: read(project / "host-audit-readiness.json"), 10)
                assert guard.get("accepted") and guard["instance"]["state"] == expected, guard
                observations.append({"event": event, "guard": guard})
            response = host("manage_editor", {"action": "stop", "wait_for_completion": False})
            assert response.get("success"), response
            ready(timeout=60)
            require_success(host("get_editor_state"))
            assert endpoint()["pid"] == results["host_pid"]
            return observations
        check("play_pause_state_and_execution_guard", play_pause)
        results["final_heartbeat"] = heartbeat()
        results["health"] = health()
        results["passed"] = True
    except Exception as error:
        results["error"] = repr(error)
        raise
    finally:
        if compiler is not None:
            compiler.close()
        pool.shutdown(wait=True, cancel_futures=True)
        # The process handle was created by this driver, so cleanup cannot target
        # an unrelated Editor selected from discovery files.
        if process.poll() is None:
            (project / "audit-stop").touch()
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        results["unity_exit_code"] = process.returncode
        saved = endpoint()
        if saved:
            try:
                status, stopped = post(saved["port"], {}, token=token, path="/stop", timeout=5)
                results["host_cleanup"] = {"http_status": status, "result": stopped}
            except (OSError, ValueError, http.client.HTTPException) as error:
                results["host_cleanup"] = {"error": repr(error)}
        save(output / "results.json", results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
