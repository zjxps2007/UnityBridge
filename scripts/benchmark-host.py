"""Compare standalone builds in disposable native Unity projects.

Records process-to-response latency, Editor update gaps, Windows working sets and
installation size. Batch-mode update gaps are not interactive GUI frame timings.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from unity_bridge.client import _read_instance_text


def read(path):
    try:
        return json.loads(_read_instance_text(path))
    except (OSError, ValueError):
        return {}


def save(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def stats(samples):
    ordered = sorted(samples)
    return {"n": len(ordered), "p50_ms": ordered[math.ceil(len(ordered) * .5) - 1],
            "p95_ms": ordered[math.ceil(len(ordered) * .95) - 1], "max_ms": ordered[-1]} if ordered else {}


def working_set(pid):
    if os.name != "nt":
        return None
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        return None
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        return counters.WorkingSetSize if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb) else None
    finally:
        kernel.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unity-editor", required=True, type=Path)
    parser.add_argument("--unity-version", required=True)
    parser.add_argument("--baseline-bin", required=True, type=Path)
    parser.add_argument("--candidate-bin", required=True, type=Path)
    parser.add_argument("--baseline-ref", default="v0.2.3")
    parser.add_argument("--baseline-host", action="store_true",
                        help="Use the external host in both builds (baseline defaults to legacy)")
    parser.add_argument("--variants", nargs="+", choices=["baseline", "candidate"],
                        default=["baseline", "candidate", "candidate", "baseline"])
    parser.add_argument("--samples", default=40, type=int)
    parser.add_argument("--exec-samples", default=20, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error("Use an empty output directory to preserve previous evidence")
    unity = args.unity_editor.resolve()
    results = {"unity_version": args.unity_version, "baseline_ref": args.baseline_ref,
               "baseline_host": args.baseline_host, "sessions": [],
               "scope": "Windows, empty projects, batchmode/nographics, standalone subprocess latency, no reboot/disk cache purge; Editor gap samples include only intervals above 1 ms"}
    files = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", args.baseline_ref,
                                     "unity-bridge-connector/Editor"], cwd=REPO, text=True).splitlines()
    candidate_files = [p.relative_to(REPO).as_posix() for p in (REPO / "unity-bridge-connector/Editor").rglob("*") if p.is_file()]
    for number, variant in enumerate(args.variants, 1):
        use_host = variant == "candidate" or args.baseline_host
        folder = output / f"{number}-{variant}"
        project = folder / "UnityProject"
        editor = project / "Assets/Editor"
        editor.mkdir(parents=True)
        package_name = "unity-bridge-connector/package.json"
        package = json.loads((REPO / package_name).read_text() if variant == "candidate" else
                             subprocess.check_output(["git", "show", f"{args.baseline_ref}:{package_name}"], cwd=REPO))
        package.pop("dependencies", None)
        package_root = project / "Packages" / package["name"]
        package_root.mkdir(parents=True)
        save(package_root / "package.json", package)
        hashes = {}
        for name in candidate_files if variant == "candidate" else files:
            relative = Path(name).relative_to("unity-bridge-connector/Editor")
            if "TestRunner" in relative.parts or relative.name == "TestRunner.meta":
                continue
            destination = package_root / "Editor" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            data = (REPO / name).read_bytes() if variant == "candidate" else subprocess.check_output(
                ["git", "show", f"{args.baseline_ref}:{name}"], cwd=REPO)
            destination.write_bytes(data)
            if destination.suffix == ".cs":
                hashes[relative.as_posix()] = hashlib.sha256(data).hexdigest()
        shutil.copy2(REPO / "tests/unity/HostPerformanceAudit.cs", editor)
        plugins = project / "Assets/Plugins/Editor"
        plugins.mkdir(parents=True)
        shutil.copy2(unity.parent / "Data/Managed/Newtonsoft.Json.dll", plugins)
        (project / "ProjectSettings").mkdir()
        (project / "ProjectSettings/ProjectVersion.txt").write_text(f"m_EditorVersion: {args.unity_version}\n")
        save(project / "Packages/manifest.json", {"dependencies": {f"com.unity.modules.{n}": "1.0.0"
             for n in ("imgui", "imageconversion", "screencapture", "jsonserialize")}})
        executable = (args.candidate_bin if variant == "candidate" else args.baseline_bin).resolve()
        env = dict(os.environ, UNITY_BRIDGE_HOST_HOME=str(folder / "host"), UNITY_BRIDGE_SKIP_UPDATE_CHECK="1")
        row = {"number": number, "variant": variant, "source_sha256": hashes, "version": package["version"],
               "calls": [], "passed": False, "executable": str(executable),
               "installed_bytes": sum(p.stat().st_size for p in executable.parent.rglob("*") if p.is_file())}
        results["sessions"].append(row)
        unity_process = subprocess.Popen([str(unity), "-batchmode", "-nographics", "-projectPath", str(project),
                                          "-logFile", str(folder / "unity.log"), "-executeMethod", "HostPerformanceAudit.Start"],
                                         env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        descriptor = None

        def call(name, *command, backend=None):
            argv = [str(executable), "--json", "--no-update-check", "--project", str(project)]
            if backend:
                argv += ["--backend", backend]
            started = time.perf_counter()
            response = subprocess.run(argv + list(command), env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
            sample = {"name": name, "ms": (time.perf_counter() - started) * 1000}
            row["calls"].append(sample)
            assert response.returncode == 0, (sample, response.stdout, response.stderr)
            value = json.loads(response.stdout)
            assert value.get("success", True), value
            assert not isinstance(value.get("data"), dict) or value["data"].get("completion") != "unknown", value
            return value

        def registry():
            return read(folder / "host/instances" / (descriptor["runtimeId"] + ".json")) if descriptor else {}

        def host_request(path):
            info = registry()
            connection = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=5)
            try:
                connection.request("POST", path, "{}", {"Content-Type": "application/json", "X-UnityBridge-Token": descriptor["token"]})
                return json.loads(connection.getresponse().read())
            finally:
                connection.close()

        def wait(predicate, seconds=120):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                assert unity_process.poll() is None, "Unity exited; inspect log"
                if value := predicate():
                    return value
                time.sleep(.02)
            raise TimeoutError("Benchmark readiness timed out")

        try:
            def heartbeat():
                for path in (Path.home() / ".unity-bridge/instances").glob("*.json"):
                    value = read(path)
                    if value.get("pid") == unity_process.pid and value.get("state") == "ready":
                        return value
                return None
            row["initial_heartbeat"] = wait(heartbeat)
            backend = "host" if use_host else None
            if use_host:
                runtime = next(executable.parent.glob("_unity_bridge_runtime_*"))
                worker = runtime / "compiler/UnityBridge.Compiler.exe"
                response = subprocess.run([str(executable), "_host", "register", "--executable", str(executable),
                                           "--worker", str(worker)], env=env, capture_output=True, text=True, timeout=30)
                assert response.returncode == 0, response.stderr
                descriptor = read(folder / "host/launcher.json")
            cold_start = time.perf_counter()
            if use_host:
                response = subprocess.run([str(executable), "_host", "start"], env=env, capture_output=True, text=True, timeout=30)
                assert response.returncode == 0, response.stderr
                wait(lambda: any(p.get("pid") == unity_process.pid for p in registry().get("projects", [])), 40)
            assert call("first_exec", "exec", "--code", "return 40 + 2;", backend=backend)["data"] == 42
            row["cold_service_to_first_result_ms"] = (time.perf_counter() - cold_start) * 1000
            if use_host:
                wait(lambda: all(p.get("prewarmState") == "ready" for p in registry().get("projects", [])), 40)
                row["host_before"] = host_request("/health")
            assert call("warmed_new_snippet", "exec", "--code", "return 42 + 1;", backend=backend)["data"] == 43
            if use_host:
                # A fresh worker that has only performed automatic harmless
                # reference preparation, and has never compiled a user request.
                previous_pid = registry()["pid"]
                assert host_request("/stop").get("stopped")
                wait(lambda: registry().get("pid") != previous_pid, 10)
                response = subprocess.run([str(executable), "_host", "start"], env=env, capture_output=True, text=True, timeout=30)
                assert response.returncode == 0, response.stderr
                wait(lambda: any(p.get("pid") == unity_process.pid and p.get("prewarmState") == "ready"
                                 for p in registry().get("projects", [])), 40)
            assert call("prewarm_only_first_exec", "exec", "--code", "return 45 + 6;", backend=backend)["data"] == 51
            call("frame_idle_start", "call", "host_performance_audit", "--params", '{"action":"start"}', backend=backend)
            time.sleep(2)
            row["idle_editor_gaps"] = call("frame_idle_stop", "call", "host_performance_audit", "--params", '{"action":"stop"}', backend=backend)["data"]["gaps_ms"]
            for _ in range(args.samples):
                call("status", "status")
                call("console", "console", "--count", "1", "--type", "error", backend=backend)
                call("tools", "tools", backend=backend)
            call("frame_exec_start", "call", "host_performance_audit", "--params", '{"action":"start"}', backend=backend)
            for i in range(args.exec_samples):
                assert call("unique_exec", "exec", "--code", f"return {i} + 100;", backend=backend)["data"] == i + 100
                assert call("repeat_exec", "exec", "--code", "return 123;", backend=backend)["data"] == 123
            row["exec_editor_gaps"] = call("frame_exec_stop", "call", "host_performance_audit", "--params", '{"action":"stop"}', backend=backend)["data"]["gaps_ms"]
            row["unity_working_set_bytes"] = working_set(unity_process.pid)
            if use_host:
                info = host_request("/health")
                row["host_after"] = info
                row["host_working_set_bytes"] = working_set(registry()["pid"])
                # Worker process ID is discovered from the owned host's child list on Windows.
                command = f"Get-CimInstance Win32_Process -Filter 'ParentProcessId = {registry()['pid']}' | Select-Object ProcessId,Name | ConvertTo-Json -Compress"
                child_output = subprocess.check_output(["powershell", "-NoProfile", "-Command", command], text=True)
                children = json.loads(child_output) if child_output.strip() else []
                if isinstance(children, dict): children = [children]
                workers = [p for p in children if p["Name"] == "UnityBridge.Compiler.exe"]
                assert len(workers) == 1, ("Expected exactly one live compiler child", children)
                row["worker_working_set_bytes"] = working_set(int(workers[0]["ProcessId"]))
                assert row["worker_working_set_bytes"] is not None, "Compiler working set unavailable"
            row["passed"] = True
        finally:
            if unity_process.poll() is None:
                (project / "audit-stop").touch()
                try:
                    unity_process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    unity_process.kill()
                    unity_process.wait(timeout=10)
            if descriptor and registry():
                try:
                    host_request("/stop")
                except (OSError, http.client.HTTPException):
                    pass
            save(output / "results.json", results)
        print(json.dumps({"session": number, "variant": variant, "passed": row["passed"]}), flush=True)
    summary = {}
    for variant in ("baseline", "candidate"):
        sessions = [row for row in results["sessions"] if row["variant"] == variant]
        summary[variant] = {name: stats([c["ms"] for row in sessions for c in row["calls"] if c["name"] == name])
                            for name in ("status", "console", "tools", "unique_exec", "repeat_exec", "first_exec", "warmed_new_snippet", "prewarm_only_first_exec")}
        summary[variant]["cold_service_to_first_result"] = stats([r["cold_service_to_first_result_ms"] for r in sessions])
        summary[variant]["idle_editor_gaps"] = stats([g for r in sessions for g in r["idle_editor_gaps"]])
        summary[variant]["exec_editor_gaps"] = stats([g for r in sessions for g in r["exec_editor_gaps"]])
    gates = {}
    for name in ("status", "console", "tools"):
        baseline, candidate = summary["baseline"][name]["p95_ms"], summary["candidate"][name]["p95_ms"]
        gates[name] = {"passed": candidate - baseline <= max(baseline * .05, 10), "delta_ms": candidate - baseline,
                       "allowed_ms": max(baseline * .05, 10)}
    functional_passed = all(r["passed"] for r in results["sessions"])
    results.update(summary=summary, ordinary_command_gates=gates, functional_passed=functional_passed,
                   passed=functional_passed and all(g["passed"] for g in gates.values()))
    save(output / "results.json", results)
    print(json.dumps({"summary": summary, "gates": gates}, indent=2))


if __name__ == "__main__":
    main()
