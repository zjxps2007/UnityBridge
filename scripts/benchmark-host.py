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
from unity_bridge.host.registry import process_alive


def read(path):
    try:
        return json.loads(_read_instance_text(path))
    except (OSError, ValueError):
        return {}


def save(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def record_launch(directory, pid, stage, operation, ns, unix_ns):
    if not directory:
        return
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    # On Windows both driver and packaged CPython use the shared QPC clock.
    # Record only timing and the fixture operation name, never argv or user data.
    with (path / f'launch-{pid}.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'pid': pid, 'parent_pid': os.getpid(), 'stage': stage,
                                 'operation': operation, 'ns': ns, 'unix_ns': unix_ns}) + '\n')


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


def compiler_working_set(host_pid):
    """Inspect the owned host's child without spawning a GUI-affecting shell."""
    if os.name != 'nt':
        return None
    class ProcessEntry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                    ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
                    ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    for operation in (kernel.Process32FirstW, kernel.Process32NextW):
        operation.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        operation.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    workers = []
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        available = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while available:
            if entry.th32ParentProcessID == host_pid and entry.szExeFile == 'UnityBridge.Compiler.exe':
                workers.append(entry.th32ProcessID)
            available = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    assert len(workers) == 1, ('Expected exactly one live compiler child', workers)
    return working_set(workers[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unity-editor", required=True, type=Path)
    parser.add_argument("--unity-version", required=True)
    parser.add_argument("--baseline-bin", required=True, type=Path)
    parser.add_argument("--candidate-bin", required=True, type=Path)
    parser.add_argument("--baseline-ref", default="v0.2.3")
    parser.add_argument("--baseline-host", action="store_true",
                        help="Use the external host in both builds (baseline defaults to legacy)")
    parser.add_argument("--baseline-working-tree-connector", action="store_true",
                        help="Use the current Connector for both executables to isolate CLI/host changes.")
    parser.add_argument("--variants", nargs="+", choices=["baseline", "candidate"],
                        default=["baseline", "candidate", "candidate", "baseline"])
    parser.add_argument("--samples", default=40, type=int)
    parser.add_argument("--exec-samples", default=20, type=int)
    parser.add_argument("--cold-samples", default=1, type=int)
    parser.add_argument("--session-samples", default=20, type=int)
    parser.add_argument("--large-samples", default=0, type=int, help="Additional 1.5 MiB Unicode CLI/session results per variant.")
    parser.add_argument("--candidate-env", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--startup-host", action="store_true", help="Register before Unity starts, measuring automatic startup overlap.")
    parser.add_argument("--startup-only", action="store_true", help="Measure only Unity startup and its first command; requires --startup-host.")
    parser.add_argument("--reuse-projects", action="store_true", help="Reuse each variant's imported project across startup-only repetitions.")
    parser.add_argument("--gui", choices=("foreground", "background"), help="Interactive Editor instead of batchmode; record actual foreground PID.")
    parser.add_argument("--extended", action="store_true", help="Also measure operation waits, rotating snippets, and candidate JSONL sessions.")
    parser.add_argument('--snippet-offset', type=int, default=100,
                        help='Change the generated new-code expressions when diagnosing cross-run caching.')
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.startup_only and not args.startup_host:
        parser.error("--startup-only requires --startup-host")
    if args.reuse_projects and not args.startup_only:
        parser.error("--reuse-projects requires --startup-only")
    original_window = None
    if args.gui:
        desktop = ctypes.WinDLL('user32')
        desktop.GetForegroundWindow.restype = wintypes.HWND
        desktop.GetShellWindow.restype = wintypes.HWND
        original_window = desktop.GetForegroundWindow() or desktop.GetShellWindow()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error("Use an empty output directory to preserve previous evidence")
    unity = args.unity_editor.resolve()
    results = {"unity_version": args.unity_version, "baseline_ref": args.baseline_ref,
               "baseline_host": args.baseline_host, "baseline_working_tree_connector": args.baseline_working_tree_connector,
               "sessions": [],
               "scope": f"Windows, empty projects, {args.gui or 'batchmode/nographics'}, standalone subprocess latency, no reboot/disk cache purge; Editor gap samples include only intervals above 1 ms",
               "configuration": vars(args) | {k: str(v) for k, v in vars(args).items() if isinstance(v, Path)}}
    files = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", args.baseline_ref,
                                     "unity-bridge-connector/Editor"], cwd=REPO, text=True).splitlines()
    candidate_files = [p.relative_to(REPO).as_posix() for p in (REPO / "unity-bridge-connector/Editor").rglob("*") if p.is_file()]
    for number, variant in enumerate(args.variants, 1):
        current_connector = variant == "candidate" or args.baseline_working_tree_connector
        use_host = variant == "candidate" or args.baseline_host
        folder = output / f"{number}-{variant}"
        folder.mkdir(parents=True)
        project = (output / "projects" / variant / "UnityProject") if args.reuse_projects else (folder / "UnityProject")
        reused_project = project.exists()
        editor = project / "Assets/Editor"
        editor.mkdir(parents=True, exist_ok=True)
        package_name = "unity-bridge-connector/package.json"
        package = json.loads((REPO / package_name).read_text() if current_connector else
                             subprocess.check_output(["git", "show", f"{args.baseline_ref}:{package_name}"], cwd=REPO))
        package.pop("dependencies", None)
        package_root = project / "Packages" / package["name"]
        package_root.mkdir(parents=True, exist_ok=True)
        if not reused_project:
            save(package_root / "package.json", package)
        hashes = {}
        for name in candidate_files if current_connector else files:
            relative = Path(name).relative_to("unity-bridge-connector/Editor")
            if "TestRunner" in relative.parts or relative.name == "TestRunner.meta":
                continue
            destination = package_root / "Editor" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            data = (REPO / name).read_bytes() if current_connector else subprocess.check_output(
                ["git", "show", f"{args.baseline_ref}:{name}"], cwd=REPO)
            if relative.name == "BridgeHostLauncher.cs" and not args.startup_host:
                # Both variants use an owned manual host lifecycle for repeated
                # cold-service samples. Automatic startup is measured separately.
                data = data.replace(b"static BridgeHostLauncher()\r\n        {", b'static BridgeHostLauncher()\r\n        {\r\n            if (Environment.GetEnvironmentVariable("UNITY_BRIDGE_BENCH_MANUAL_HOST") == "1") return;')
                data = data.replace(b"static BridgeHostLauncher()\n        {", b'static BridgeHostLauncher()\n        {\n            if (Environment.GetEnvironmentVariable("UNITY_BRIDGE_BENCH_MANUAL_HOST") == "1") return;')
            if not destination.is_file() or destination.read_bytes() != data:
                destination.write_bytes(data)
            if destination.suffix == ".cs":
                hashes[relative.as_posix()] = hashlib.sha256(data).hexdigest()
        if not reused_project:
            shutil.copy2(REPO / "tests/unity/HostPerformanceAudit.cs", editor)
        plugins = project / "Assets/Plugins/Editor"
        plugins.mkdir(parents=True, exist_ok=True)
        if not reused_project:
            shutil.copy2(unity.parent / "Data/Managed/Newtonsoft.Json.dll", plugins)
        (project / "ProjectSettings").mkdir(exist_ok=True)
        if not reused_project:
            (project / "ProjectSettings/ProjectVersion.txt").write_text(f"m_EditorVersion: {args.unity_version}\n")
            save(project / "Packages/manifest.json", {"dependencies": {f"com.unity.modules.{n}": "1.0.0"
                 for n in ("imgui", "imageconversion", "screencapture", "jsonserialize")}})
        executable = (args.candidate_bin if variant == "candidate" else args.baseline_bin).resolve()
        env = dict(os.environ, UNITY_BRIDGE_HOST_HOME=str(folder / "host"), UNITY_BRIDGE_SKIP_UPDATE_CHECK="1")
        if not args.startup_host:
            env['UNITY_BRIDGE_BENCH_MANUAL_HOST'] = '1'
        if variant == 'candidate':
            env.update(item.split('=', 1) for item in args.candidate_env)
        row = {"number": number, "variant": variant, "source_sha256": hashes, "version": package["version"],
               "calls": [], "passed": False, "executable": str(executable),
               "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
               "installed_bytes": sum(p.stat().st_size for p in executable.parent.rglob("*") if p.is_file())}
        row['reused_project'] = reused_project
        (project / 'audit-stop').unlink(missing_ok=True)
        results["sessions"].append(row)
        descriptor = None
        def register():
            runtimes = list(executable.parent.glob("_unity_bridge_runtime_*"))
            worker = (runtimes[0] if runtimes else executable.parent) / "compiler/UnityBridge.Compiler.exe"
            response = subprocess.run([str(executable), "_host", "register", "--executable", str(executable),
                                       "--worker", str(worker)], env=env, capture_output=True, text=True, timeout=30)
            assert response.returncode == 0, response.stderr
            return read(folder / "host/launcher.json")
        if use_host and args.startup_host:
            descriptor = register()
        unity_started = time.perf_counter()
        unity_process = subprocess.Popen([str(unity)] + ([] if args.gui else ["-batchmode", "-nographics"]) + ["-projectPath", str(project),
                                          "-logFile", str(folder / "unity.log"), "-executeMethod", "HostPerformanceAudit.Start"],
                                         env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        focus_api = None
        focus_window = None

        def is_foreground():
            if focus_api is None:
                return None
            pid = wintypes.DWORD()
            focus_api.GetWindowThreadProcessId(focus_api.GetForegroundWindow(), ctypes.byref(pid))
            return pid.value == unity_process.pid

        def set_focus_once():
            nonlocal focus_window
            if focus_api is None:
                return
            requested = args.gui == 'foreground'
            if is_foreground() == requested:
                return
            # Editor startup can replace its splash/progress window after the
            # first heartbeat. Resolve the current owned windows, not a stale HWND.
            current_windows = []
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def collect(hwnd, _):
                owner = wintypes.DWORD()
                focus_api.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                if owner.value == unity_process.pid and focus_api.IsWindowVisible(hwnd):
                    rectangle = wintypes.RECT()
                    focus_api.GetWindowRect(hwnd, ctypes.byref(rectangle))
                    title = ctypes.create_unicode_buffer(1024)
                    focus_api.GetWindowTextW(hwnd, title, len(title))
                    current_windows.append(('UnityProject' in title.value,
                        (rectangle.right - rectangle.left) * (rectangle.bottom - rectangle.top), hwnd))
                return True
            focus_api.EnumWindows(callback_type(collect), 0)
            if current_windows:
                focus_window = max(current_windows)[2]
            if requested:
                focus_api.ShowWindow(focus_window, 9)
                target_window = focus_window
            else:
                for _, _, owned_window in current_windows:
                    focus_api.ShowWindow(owned_window, 6)
                target_window = original_window if focus_api.IsWindow(original_window) else focus_api.GetShellWindow()
            focus_api.SetForegroundWindow(target_window)
            if is_foreground() != requested:
                kernel = ctypes.WinDLL('kernel32')
                kernel.GetCurrentThreadId.restype = wintypes.DWORD
                thread_id = kernel.GetCurrentThreadId()
                foreground_thread = focus_api.GetWindowThreadProcessId(focus_api.GetForegroundWindow(), None)
                target_thread = focus_api.GetWindowThreadProcessId(target_window, None)
                attached = []
                try:
                    for other in {foreground_thread, target_thread} - {0, thread_id}:
                        if focus_api.AttachThreadInput(thread_id, other, True):
                            attached.append(other)
                    focus_api.BringWindowToTop(target_window)
                    focus_api.SetForegroundWindow(target_window)
                finally:
                    for other in reversed(attached):
                        focus_api.AttachThreadInput(thread_id, other, False)
            time.sleep(.1)  # Outside the measured request, only when focus changed.

        def ensure_focus():
            if focus_api is None:
                return
            # The first ready heartbeat may precede replacement of Unity's
            # startup window. Allow that UI transition outside timed samples,
            # but never label a sample foreground without observing it.
            for _ in range(30):
                set_focus_once()
                if is_foreground() == (args.gui == 'foreground'):
                    return
            foreground_pid = wintypes.DWORD()
            focus_api.GetWindowThreadProcessId(focus_api.GetForegroundWindow(), ctypes.byref(foreground_pid))
            row['focus_failure'] = {'requested': args.gui, 'unity_pid': unity_process.pid,
                                    'observed_foreground_pid': foreground_pid.value}
            raise RuntimeError('Windows did not allow the requested Unity focus state')

        def call(name, *command, backend=None):
            argv = [str(executable), "--json", "--no-update-check", "--project", str(project)]
            if backend:
                argv += ["--backend", backend]
            ensure_focus()
            started = time.perf_counter()
            timing_directory = env.get('UNITY_BRIDGE_TIMING_DIR')
            if timing_directory:
                spawn_ns, spawn_unix_ns = time.perf_counter_ns(), time.time_ns()
                with subprocess.Popen(argv + list(command), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as child:
                    record_launch(timing_directory, child.pid, 'process_start', name, spawn_ns, spawn_unix_ns)
                    try:
                        stdout, stderr = child.communicate(timeout=60)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.communicate()
                        raise
                    record_launch(timing_directory, child.pid, 'process_end', name, time.perf_counter_ns(), time.time_ns())
                    response = subprocess.CompletedProcess(argv + list(command), child.returncode, stdout, stderr)
            else:
                # Keep process creation separate from command execution: OS
                # launch delays must not be attributed to Roslyn or Unity.
                with subprocess.Popen(argv + list(command), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding='utf-8',
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if args.gui else 0) as child:
                    launched = time.perf_counter()
                    try:
                        stdout, stderr = child.communicate(timeout=60)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.communicate()
                        raise
                    response = subprocess.CompletedProcess(argv + list(command), child.returncode, stdout, stderr)
            sample = {"name": name, "ms": (time.perf_counter() - started) * 1000}
            if not timing_directory:
                sample['process_launch_ms'] = (launched - started) * 1000
            if args.gui:
                sample['unity_foreground'] = is_foreground()
            row["calls"].append(sample)
            assert response.returncode == 0, (sample, response.stdout, response.stderr)
            value = json.loads(response.stdout)
            assert not isinstance(value, dict) or value.get("success", True), value
            assert not isinstance(value, dict) or not isinstance(value.get("data"), dict) or value["data"].get("completion") != "unknown", value
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
            row['unity_ready_ms'] = (time.perf_counter() - unity_started) * 1000
            if args.gui:
                user32 = ctypes.WinDLL('user32', use_last_error=True)
                user32.GetForegroundWindow.restype = wintypes.HWND
                user32.GetShellWindow.restype = wintypes.HWND
                user32.IsWindow.argtypes = [wintypes.HWND]
                user32.IsWindowVisible.argtypes = [wintypes.HWND]
                user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
                user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
                user32.SetForegroundWindow.argtypes = [wintypes.HWND]
                user32.BringWindowToTop.argtypes = [wintypes.HWND]
                user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
                user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
                user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
                focus_api = user32
                windows = []
                callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                def find_window(hwnd, _):
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value == unity_process.pid and user32.IsWindowVisible(hwnd):
                        rectangle = wintypes.RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(rectangle))
                        windows.append(((rectangle.right - rectangle.left) * (rectangle.bottom - rectangle.top), hwnd))
                    return True
                callback = callback_type(find_window)
                user32.EnumWindows(callback, 0)
                assert windows, 'No visible owned Unity window'
                window = max(windows)[1]  # Ignore small floating tooltips/splash windows.
                focus_window = window
                user32.ShowWindow(window, 6 if args.gui == 'background' else 9)
                ensure_focus()
                time.sleep(1)
                foreground = wintypes.DWORD()
                user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(foreground))
                row['unity_is_foreground'] = foreground.value == unity_process.pid
            backend = "host" if use_host else None
            if use_host and descriptor is None:
                descriptor = register()
            row['cold_service_samples_ms'] = []
            for cold_index in range(args.cold_samples):
                if use_host and cold_index:
                    old_pid = registry()['pid']
                    assert host_request('/stop').get('stopped')
                    wait(lambda: not process_alive(old_pid), 10)
                cold_start = time.perf_counter()
                if use_host and not (args.startup_host and cold_index == 0):
                    response = subprocess.run([str(executable), '_host', 'start'], env=env, capture_output=True, text=True, timeout=30)
                    assert response.returncode == 0, response.stderr
                    wait(lambda: any(p.get('pid') == unity_process.pid for p in registry().get('projects', [])), 40)
                first_backend = 'auto' if args.startup_host and cold_index == 0 else backend
                assert call('first_exec', 'exec', '--code', 'return 40 + 2;', backend=first_backend)['data'] == 42
                row['cold_service_samples_ms'].append((time.perf_counter() - cold_start) * 1000)
                if args.startup_host and cold_index == 0:
                    row['unity_start_to_first_result_ms'] = (time.perf_counter() - unity_started) * 1000
                    row['after_ready_to_first_result_ms'] = row['unity_start_to_first_result_ms'] - row['unity_ready_ms']
                if (cold_index + 1) % 10 == 0:
                    print(f'{variant}: cold {cold_index + 1}/{args.cold_samples}', flush=True)
                save(output / 'results.json', results)
            row['cold_service_to_first_result_ms'] = row['cold_service_samples_ms'][0]
            if use_host:
                wait(lambda: any(p.get('pid') == unity_process.pid and p.get("prewarmState") == "ready"
                                 for p in registry().get("projects", [])), 40)
                row["host_before"] = host_request("/health")
            if args.startup_only:
                row['passed'] = True
                row['unity_working_set_bytes'] = working_set(unity_process.pid)
                if use_host:
                    row['host_working_set_bytes'] = working_set(registry()['pid'])
                    row['worker_working_set_bytes'] = compiler_working_set(registry()['pid'])
                print(json.dumps({'startup': number, 'variant': variant, 'reused_project': reused_project,
                                  'unity_ready_ms': row['unity_ready_ms'],
                                  'first_result_ms': row['unity_start_to_first_result_ms']}), flush=True)
                continue
            assert call("warmed_new_snippet", "exec", "--code", "return 42 + 1;", backend=backend)["data"] == 43
            if use_host:
                # A fresh worker that has only performed automatic harmless
                # reference preparation, and has never compiled a user request.
                previous_pid = registry()["pid"]
                assert host_request("/stop").get("stopped")
                wait(lambda: not process_alive(previous_pid), 10)
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
                call("instances", "instances")
                call("wait_ready", "wait-ready", "--timeout-sec", "5", backend=backend)
            call("frame_exec_start", "call", "host_performance_audit", "--params", '{"action":"start"}', backend=backend)
            for i in range(args.exec_samples):
                assert call("unique_exec", "exec", "--code", f"return {i} + {args.snippet_offset};", backend=backend)["data"] == i + args.snippet_offset
                assert call("repeat_exec", "exec", "--code", "return 123;", backend=backend)["data"] == 123
            row["exec_editor_gaps"] = call("frame_exec_stop", "call", "host_performance_audit", "--params", '{"action":"stop"}', backend=backend)["data"]["gaps_ms"]
            if args.large_samples:
                large_code = "return new string('\uac00', 512 * 1024) + \"\U0001f600\";"
                expected_large = '\uac00' * (512 * 1024) + '\U0001f600'
                for _ in range(args.large_samples):
                    assert call('large_exec', 'exec', '--code', large_code, backend=backend)['data'] == expected_large
                if use_host:
                    with subprocess.Popen([str(executable), '--json', '--project', str(project), '--backend', 'host', 'session'],
                                          env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as session:
                        try:
                            for index in range(args.large_samples + 1):
                                ensure_focus()
                                started = time.perf_counter()
                                session.stdin.write(json.dumps({'id': index, 'args': ['exec', '--code', large_code]}) + '\n')
                                session.stdin.flush()
                                response = json.loads(session.stdout.readline())
                                elapsed = (time.perf_counter() - started) * 1000
                                assert response['id'] == index and response['exit_code'] == 0, response.get('error')
                                assert response['result'].get('data') == expected_large
                                if index:
                                    sample = {'name': 'session_large_exec', 'ms': elapsed}
                                    if args.gui:
                                        sample['unity_foreground'] = is_foreground()
                                    row['calls'].append(sample)
                            session.stdin.close()
                            assert session.wait(timeout=10) == 0, session.stderr.read()
                        finally:
                            if session.poll() is None:
                                session.kill()
                                session.wait(timeout=10)
            if args.extended:
                for _ in range(8):
                    call("refresh_wait", "refresh", "--wait", backend=backend)
                row["rotating_cache_hits"] = []
                for cycle in range(2):
                    for index in range(8):
                        assert call("rotating_exec", "exec", "--code", f"return {9000 + index};", backend=backend)["data"] == 9000 + index
                        if use_host:
                            row["rotating_cache_hits"].append(bool(host_request("/health")["compiler"].get("cache_hit")))
                if use_host:
                    started = time.perf_counter()
                    session = subprocess.Popen([str(executable), "--json", "--project", str(project), "--backend", "host", "session"],
                                               env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                               text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    try:
                        for index in range(args.session_samples + 1):
                            ensure_focus()
                            if index:
                                started = time.perf_counter()
                            session.stdin.write(json.dumps({"id": index, "args": ["console", "--count", "1", "--type", "error"]}) + "\n")
                            session.stdin.flush()
                            response = json.loads(session.stdout.readline())
                            elapsed = (time.perf_counter() - started) * 1000
                            assert response["id"] == index and response["exit_code"] == 0, response
                            assert response['result'].get('success', True), response
                            data = response['result'].get('data')
                            assert not isinstance(data, dict) or data.get('completion') != 'unknown', response
                            row["calls"].append({"name": "session_first" if index == 0 else "session_console", "ms": elapsed})
                            if args.gui:
                                row['calls'][-1]['unity_foreground'] = is_foreground()
                        session.stdin.close()
                        assert session.wait(timeout=10) == 0, session.stderr.read()
                    finally:
                        if session.poll() is None:
                            session.kill()
                            session.wait(timeout=10)
                        for stream in (session.stdin, session.stdout, session.stderr):
                            stream.close()
            row["unity_working_set_bytes"] = working_set(unity_process.pid)
            if use_host:
                info = host_request("/health")
                row["host_after"] = info
                row["host_working_set_bytes"] = working_set(registry()["pid"])
                row["worker_working_set_bytes"] = compiler_working_set(registry()['pid'])
                assert row["worker_working_set_bytes"] is not None, "Compiler working set unavailable"
                # Capture only after timings/memory samples, for an independent
                # worker ablation with this exact, still-on-disk reference set.
                current = heartbeat()
                connection = http.client.HTTPConnection('127.0.0.1', current['port'], timeout=10)
                try:
                    connection.request('POST', '/command', json.dumps({
                        'command': 'bridge_context', 'params': {}, 'request_id': 'benchmark-context',
                        'deadline_unix_ms': int(time.time() * 1000) + 10000,
                    }), {'Content-Type': 'application/json', 'X-UnityBridge-Token': descriptor['token']})
                    context_result = json.loads(connection.getresponse().read())
                    assert context_result['success'], context_result.get('message')
                    save(folder / 'compiler-context.json', context_result['data'])
                finally:
                    connection.close()
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
                            for name in ("instances", "wait_ready", "status", "console", "tools", "unique_exec", "repeat_exec", "first_exec", "warmed_new_snippet", "prewarm_only_first_exec")}
        if args.extended:
            for name in ("refresh_wait", "rotating_exec", "session_first", "session_console"):
                values = [c["ms"] for row in sessions for c in row["calls"] if c["name"] == name]
                if values:
                    summary[variant][name] = stats(values)
        if args.large_samples:
            for name in ('large_exec', 'session_large_exec'):
                summary[variant][name] = stats([c['ms'] for row in sessions for c in row['calls'] if c['name'] == name])
        summary[variant]["cold_service_to_first_result"] = stats([v for r in sessions for v in r['cold_service_samples_ms']])
        summary[variant]["idle_editor_gaps"] = stats([g for r in sessions for g in r.get("idle_editor_gaps", [])])
        summary[variant]["exec_editor_gaps"] = stats([g for r in sessions for g in r.get("exec_editor_gaps", [])])
        if args.startup_host:
            for metric in ('unity_ready_ms', 'unity_start_to_first_result_ms', 'after_ready_to_first_result_ms'):
                # The first asset import is reported separately from repeated
                # Editor launches over an already imported project.
                for reused in (False, True):
                    summary[variant][metric + ('_reused' if reused else '_new_project')] = stats([
                        r[metric] for r in sessions if r['reused_project'] == reused])
    gates = {}
    for name in ("instances", "wait_ready", "status", "console", "tools"):
        if not summary['baseline'][name] or not summary['candidate'][name]:
            continue
        baseline, candidate = summary["baseline"][name]["p95_ms"], summary["candidate"][name]["p95_ms"]
        gates[name] = {"passed": candidate - baseline <= max(baseline * .05, 10), "delta_ms": candidate - baseline,
                       "allowed_ms": max(baseline * .05, 10)}
    workload_gates = {}
    for name in ('unique_exec', 'repeat_exec', 'session_console', 'large_exec', 'session_large_exec'):
        baseline = summary['baseline'].get(name, {})
        candidate = summary['candidate'].get(name, {})
        if not baseline or not candidate:
            continue
        delta = candidate['p95_ms'] - baseline['p95_ms']
        allowed = max(baseline['p95_ms'] * .05, 10)
        workload_gates[name] = {'passed': delta <= allowed, 'delta_ms': delta, 'allowed_ms': allowed}
    all_gates = {**gates, **workload_gates}
    functional_passed = all(r["passed"] for r in results["sessions"])
    if args.gui:
        focus_samples = [c.get('unity_foreground') == (args.gui == 'foreground')
                         for row in results['sessions'] for c in row['calls']]
        results['focus_validation'] = {'matched_samples': sum(focus_samples), 'total_samples': len(focus_samples),
                                       'passed': bool(focus_samples) and all(focus_samples)}
    results.update(summary=summary, ordinary_command_gates=gates, workload_gates=workload_gates,
                   functional_passed=functional_passed, performance_gates_evaluated=bool(all_gates),
                   passed=(functional_passed and all(g["passed"] for g in all_gates.values())
                           and results.get('focus_validation', {}).get('passed', True)) if all_gates else None)
    save(output / "results.json", results)
    print(json.dumps({"summary": summary, "gates": gates}, indent=2))


if __name__ == "__main__":
    main()
