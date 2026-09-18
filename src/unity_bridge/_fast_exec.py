"""Python-only fast path through an authenticated, already running local host.

The check below admits only known exec syntax. The host still uses the public
argument parser, client discovery, adapter and ordered execution queue. Every
unsupported case returns to the full CLI before transmitting a command.
"""
import json
import os
import sys
import time

from . import __version__


def _enabled(name):
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _options(argv):
    values = {"--project", "--port", "--timeout-ms", "--instances-dir", "--backend",
              "--code", "--code-file", "--file", "--using"}
    command, sources = False, 0
    options = {"json": False, "no_update": False, "timeout": 120_000, "usings": []}
    index = 0
    while index < len(argv):
        arg = argv[index]
        index += 1
        if arg == "exec" and not command:
            command = True
            continue
        if arg in {"--json", "--no-update-check"}:
            options["json" if arg == "--json" else "no_update"] = True
            continue
        if arg == "--stdin" and command:
            options["kind"] = "stdin"
            sources += 1
            continue
        name, assigned, value = arg.partition("=")
        if name not in values:
            return None
        if not assigned:
            if index == len(argv) or argv[index].startswith("--"):
                return None
            value = argv[index]
            index += 1
        if name in {"--code", "--code-file", "--file"}:
            if not command:
                return None
            options.update(kind=name, source=value)
            sources += 1
        elif name == "--using":
            if not command:
                return None
            options["usings"].append(value)
        elif name == "--backend":
            options["backend"] = value
            if value not in {"auto", "host"}:
                return None
        elif name in {"--port", "--timeout-ms"}:
            try:
                number = int(value)
            except ValueError:
                return None
            if not 0 < number <= (65535 if name == "--port" else 86_400_000):
                return None
            if name == "--timeout-ms":
                options["timeout"] = number
    return options if command and sources == 1 else None


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) <= 1024 * 1024:
            value = json.loads(data)
            return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        pass
    return None


def _pid_alive(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            status = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(status))) and status.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False


def _endpoint():
    root = os.path.expanduser(os.environ.get("UNITY_BRIDGE_HOST_HOME") or "~/.unity-bridge/host")
    descriptor = _read_json(os.path.join(root, "launcher.json"))
    if not descriptor or descriptor.get("protocol") != 1 or descriptor.get("version") != __version__:
        return None
    runtime, token, argv = descriptor.get("runtimeId"), descriptor.get("token"), descriptor.get("argv")
    if any(not isinstance(value, str) or len(value) != length or any(c not in "0123456789abcdef" for c in value)
           for value, length in ((runtime, 32), (token, 64))):
        return None
    if not isinstance(argv, list) or not argv or not isinstance(argv[0], str):
        return None
    try:
        if not os.path.samefile(argv[0], sys.executable):
            return None
    except OSError:
        return None
    if not getattr(sys, "frozen", False) and argv[1:3] != ["-m", "unity_bridge"]:
        return None
    endpoint = _read_json(os.path.join(root, "instances", runtime + ".json"))
    if not endpoint:
        return None
    port = endpoint.get("cliPort")
    if (endpoint.get("protocol") != 1 or endpoint.get("cliProtocol") != 1
            or endpoint.get("runtimeId") != runtime or endpoint.get("version") != __version__
            or endpoint.get("token") != token or not isinstance(port, int) or isinstance(port, bool)
            or not 0 < port < 65536 or not _pid_alive(endpoint.get("pid"))):
        return None
    return endpoint


def _update_due(options):
    if options["json"] or options["no_update"] or _enabled("UNITY_BRIDGE_SKIP_UPDATE_CHECK"):
        return False
    cache = _read_json(os.path.expanduser("~/.unity-bridge/update-check.json"))
    checked = cache.get("checked_at") if cache else None
    return not isinstance(checked, (int, float)) or time.time() - checked >= 86400


def _unknown(options, code):
    message = "exec sent to host; completion could not be confirmed"
    data = {"accepted": True, "completion": "unknown", "command": "exec"}
    if options["json"]:
        params = {"code": code}
        if options["usings"]:
            params["usings"] = options["usings"]
        print(json.dumps({"tool": "exec", "command": "exec", "params": params, "success": True,
                          "message": message, "data": data}, ensure_ascii=False, indent=2))
    else:
        print(message)
        print(json.dumps(data, ensure_ascii=False, indent=2))


def try_exec(argv):
    options = _options(argv)
    if options is None or _enabled("UNITY_BRIDGE_DISABLE_FAST_EXEC") or _update_due(options):
        return None, None
    backend = options.get("backend") or os.environ.get("UNITY_BRIDGE_BACKEND", "auto")
    if backend not in {"auto", "host"}:
        return None, None
    endpoint = _endpoint()
    if endpoint is None:
        return None, None
    stdin_text = None
    try:
        if options["kind"] == "stdin":
            code = stdin_text = sys.stdin.read()
        elif options["kind"] == "--code":
            code = options["source"]
        else:
            with open(options["source"], encoding="utf-8") as stream:
                code = stream.read()
        timeout = options["timeout"] / 1000
        deadline = time.monotonic() + timeout
        payload = json.dumps({"cli_protocol": 1, "version": __version__, "argv": argv, "cwd": os.getcwd(),
                              "code": code, "token": endpoint["token"], "backend": backend,
                              "instances_dir": os.path.expanduser("~/.unity-bridge/instances"),
                              "deadline_unix_ms": int(time.time() * 1000) + options["timeout"]},
                             ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        from ._wire import MAX_MESSAGE_BYTES, read_frame, write_frame
        if len(payload) > MAX_MESSAGE_BYTES:
            return None, stdin_text
        import socket
        # The endpoint is a numeric IPv4 loopback address. Avoid hostname/IDNA
        # initialization on every short-lived CLI process.
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            connection.settimeout(min(timeout, 1))
            connection.connect(("127.0.0.1", endpoint["cliPort"]))
        except BaseException:
            connection.close()
            raise
    except (OSError, ValueError):
        return None, stdin_text
    # A connected socket with any attempted frame write may have submitted work.
    # No retry or fallback is permitted beyond this point, including partial writes.
    try:
        with connection:
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            write_frame(connection, payload, deadline)
            response = json.loads(read_frame(connection, deadline))
        if (not isinstance(response, dict) or response.get("cli_protocol") != 1
                or type(response.get("exit_code")) is not int or not 0 <= response["exit_code"] <= 255
                or not isinstance(response.get("stdout"), str) or not isinstance(response.get("stderr"), str)):
            raise ValueError("Invalid CLI response")
    except (OSError, ValueError):
        _unknown(options, code)
        return 0, None
    print(response["stdout"], end="")
    print(response["stderr"], end="", file=sys.stderr)
    return response["exit_code"], None
