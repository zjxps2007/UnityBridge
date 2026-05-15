from __future__ import annotations

import argparse
import base64
import importlib.metadata as importlib_metadata
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from . import __version__
from .adapter import UnityActionResult
from .adapter import UnityBridgeAdapter
from .client import CommandResponse
from .client import DiscoveryError
from .client import Instance
from .client import UnityBridgeError
from .client import UnityClient


DEFAULT_REPOSITORY_URL = "https://github.com/zjxps2007/UnityBridge.git"
DEFAULT_WINDOWS_ASSET_NAME = "unity-bridge-windows-amd64.exe"
DEFAULT_INSTALL_POWERSHELL_SCRIPT_URL = "https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.ps1"
DEFAULT_INSTALL_SHELL_SCRIPT_URL = "https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.sh"
AUTO_UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
AUTO_UPDATE_CHECK_TIMEOUT_SECONDS = 2
KNOWN_COMMANDS = {
    "instances",
    "status",
    "tools",
    "refresh",
    "console",
    "test",
    "editor",
    "menu",
    "reserialize",
    "profiler",
    "screenshot",
    "exec",
    "call",
    "wait-ready",
    "update",
}

GLOBAL_VALUE_OPTIONS = {
    "--project": "project",
    "--port": "port",
    "--timeout-ms": "timeout_ms",
    "--instances-dir": "instances_dir",
}
GLOBAL_BOOL_OPTIONS = {"--json": "json", "--no-update-check": "no_update_check"}


def add_common_options(
    parser: argparse.ArgumentParser,
    *,
    json_option: bool,
    suppress_defaults: bool,
) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    timeout_default = argparse.SUPPRESS if suppress_defaults else 120_000
    parser.add_argument("--project", default=default, help="Select Unity instance by exact project path, path suffix, or folder name.")
    parser.add_argument("--port", type=int, default=default, help="Select Unity instance by port.")
    parser.add_argument("--timeout-ms", type=int, default=timeout_default, help="HTTP timeout in milliseconds.")
    parser.add_argument("--instances-dir", default=default, help="Override ~/.unity-bridge/instances.")
    no_update_default = argparse.SUPPRESS if suppress_defaults else False
    parser.add_argument("--no-update-check", action="store_true", default=no_update_default, help="Skip the automatic daily update notice.")
    if json_option:
        json_default = argparse.SUPPRESS if suppress_defaults else False
        parser.add_argument("--json", action="store_true", default=json_default, help="Print JSON output.")


def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    add_common_options(parent, json_option=True, suppress_defaults=True)

    parser = argparse.ArgumentParser(
        prog="unity-bridge",
        epilog=(
            "Unknown command names are sent directly to Unity Connector, so project "
            "custom tools can be called as: unity-bridge my_tool --x 1 --params '{...}'"
        ),
    )
    add_common_options(parser, json_option=True, suppress_defaults=False)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("instances", parents=[parent], help="List discovered Unity Connector instances.")
    sub.add_parser("status", parents=[parent], help="Show selected Unity Connector instance status.")
    sub.add_parser("tools", parents=[parent], help="List Unity Connector tools.")

    refresh = sub.add_parser("refresh", parents=[parent], help="Refresh Unity assets.")
    refresh.add_argument("--mode", default="if_dirty", choices=["if_dirty", "force"], help="Refresh mode.")
    refresh.add_argument("--force", action="store_true", help="Allow refresh while entering or in play mode.")
    refresh.add_argument("--path", dest="paths", action="append", help="Asset path to import. Repeatable. Accepts Assets/..., Packages/..., or an absolute project path.")
    refresh.add_argument("--compile", default="none", choices=["none", "request"], help="Request script compilation.")
    refresh.add_argument("--wait", action="store_true", help="Wait until Unity reaches stable ready after refresh.")
    refresh.add_argument("--timeout-sec", type=int, default=300, help="Ready wait timeout in seconds.")
    refresh.add_argument("--stable-sec", type=float, default=0.5, help="Required stable ready duration when --wait is used.")

    console = sub.add_parser("console", parents=[parent], help="Read or clear Unity console logs.")
    console.add_argument("--count", "--lines", dest="count", type=int, default=50, help="Maximum number of entries to return.")
    console.add_argument("--type", dest="types", action="append", help="Log type: error, warning, or log. Repeatable.")
    console.add_argument("--stacktrace", default="user", choices=["none", "user", "full"], help="Stack trace output mode.")
    console.add_argument("--clear", action="store_true", help="Clear the Unity console.")

    test = sub.add_parser("test", parents=[parent], help="Run Unity tests.")
    test.add_argument("--mode", default="EditMode", choices=["EditMode", "PlayMode"], help="Unity test mode.")
    test.add_argument("--filter", help="Namespace, class, or full test name filter.")
    test.add_argument("--allow-dirty-scenes", action="store_true", help="Run tests with unsaved scene changes.")
    test.add_argument("--auto-save-scenes", action="store_true", help="Save dirty scenes before running tests.")
    test_wait = test.add_mutually_exclusive_group()
    test_wait.add_argument("--wait", dest="wait", action="store_true", help="Wait for PlayMode test results.")
    test_wait.add_argument("--no-wait", dest="wait", action="store_false", help="Return immediately after starting PlayMode tests.")
    test.set_defaults(wait=None)
    test.add_argument("--timeout-sec", type=int, default=600, help="PlayMode test result wait timeout in seconds.")
    test.add_argument("--poll-interval-sec", type=float, default=0.5, help="PlayMode test result poll interval in seconds.")

    editor = sub.add_parser("editor", parents=[parent], help="Control Unity Editor play state.")
    editor.add_argument("action", choices=["play", "stop", "pause"], help="Editor action.")
    editor.add_argument("--wait", action="store_true", help="Wait until play or stop completes.")
    editor.add_argument("--timeout-sec", type=int, default=300, help="Play/stop wait timeout in seconds.")
    editor.add_argument("--stable-sec", type=float, default=0.5, help="Required stable ready duration for stop waits.")
    editor.add_argument("--poll-interval-sec", type=float, default=0.5, help="Play/stop wait poll interval in seconds.")

    menu = sub.add_parser("menu", parents=[parent], help="Execute a Unity menu item.")
    menu.add_argument("menu_path", help="Unity menu item path, for example File/Save Project.")

    reserialize = sub.add_parser("reserialize", parents=[parent], help="Force reserialize assets.")
    reserialize.add_argument("paths", nargs="*", help="Optional asset paths. Omit for the entire project.")
    reserialize.add_argument("--wait", action="store_true", help="Wait until Unity reaches stable ready after reserialize.")
    reserialize.add_argument("--timeout-sec", type=int, default=300, help="Ready wait timeout in seconds.")
    reserialize.add_argument("--stable-sec", type=float, default=0.5, help="Required stable ready duration when --wait is used.")
    reserialize.add_argument("--poll-interval-sec", type=float, default=0.5, help="Ready wait poll interval in seconds.")

    profiler = sub.add_parser("profiler", parents=[parent], help="Control Unity Profiler.")
    profiler.add_argument("action", nargs="?", default="status", help="Profiler action: status, enable, disable, clear, hierarchy.")

    screenshot = sub.add_parser("screenshot", parents=[parent], help="Capture a Unity editor screenshot.")
    screenshot.add_argument("--view", default="scene", choices=["scene", "game"], help="View to capture.")
    screenshot.add_argument("--output-path", help="Output file path.")
    screenshot.add_argument("--width", type=int, help="Screenshot width.")
    screenshot.add_argument("--height", type=int, help="Screenshot height.")

    exec_command = sub.add_parser("exec", parents=[parent], help="Execute arbitrary C# code through Unity.")
    code_group = exec_command.add_mutually_exclusive_group(required=True)
    code_group.add_argument("--code", help="C# code to execute. Use 'return' for output.")
    code_group.add_argument("--code-file", "--file", dest="code_file", help="Read C# code from a file.")
    code_group.add_argument("--stdin", action="store_true", help="Read C# code from standard input.")
    exec_command.add_argument("--using", dest="usings", action="append", help="Additional using namespace. Repeatable.")
    exec_command.add_argument("--csc", help="Override csc compiler path.")
    exec_command.add_argument("--dotnet", help="Override dotnet runtime path.")

    call = sub.add_parser("call", parents=[parent], help="Send a command to Unity Connector.")
    call.add_argument("unity_command", help="Unity Connector command name, for example list or console.")
    call.add_argument("--params", default="{}", help="JSON object passed as command params.")

    wait_ready = sub.add_parser("wait-ready", parents=[parent], help="Wait until selected Unity instance is ready.")
    wait_ready.add_argument("--timeout-sec", type=int, default=300, help="Ready wait timeout in seconds.")

    update = sub.add_parser("update", parents=[parent], help="Update the UnityBridge CLI.")
    update.add_argument("--ref", default="main", help="Git ref to install, for example main, v0.1.5, or a branch name.")
    update.add_argument("--repo", default=DEFAULT_REPOSITORY_URL, help="Git repository URL.")
    update.add_argument("--package-spec", help="Full pip package spec. Overrides --repo and --ref.")
    update.add_argument("--dry-run", action="store_true", help="Print the pip command without running it.")
    update.add_argument("--check", action="store_true", help="Check available versions without installing.")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if _is_direct_tool_invocation(argv):
        return _main_direct_tool(argv)

    args = build_parser().parse_args(argv)
    _maybe_print_update_notice(args)
    client = UnityClient(
        project=getattr(args, "project", None),
        port=getattr(args, "port", None),
        timeout_ms=getattr(args, "timeout_ms", 120_000),
        instances_dir=getattr(args, "instances_dir", None),
    )

    try:
        if args.command == "instances":
            instances = client.scan_instances()
            _print(instances, json_output=args.json)
            return 0

        if args.command == "status":
            instance = client.status()
            _print(instance, json_output=args.json)
            return 0

        adapter = UnityBridgeAdapter(client=client)

        if args.command == "tools":
            response = adapter.list_tools()
            _print(response, json_output=args.json)
            return 0 if response.success else 1

        if args.command == "refresh":
            response = adapter.refresh_assets(
                mode=args.mode,
                force=args.force,
                paths=args.paths,
                compile=args.compile,
                wait=args.wait,
                timeout_sec=args.timeout_sec,
                stable_sec=args.stable_sec,
            )
            _print(response, json_output=args.json)
            return 0 if response.success else 1

        if args.command == "console":
            response = adapter.clear_console() if args.clear else adapter.read_console(
                count=args.count,
                types=args.types,
                stacktrace=args.stacktrace,
            )
            _print(response, json_output=args.json)
            return 0 if response.success else 1

        if args.command == "test":
            response = adapter.run_tests(
                mode=args.mode,
                filter=args.filter,
                allow_dirty_scenes=args.allow_dirty_scenes,
                auto_save_scenes=args.auto_save_scenes,
                wait=args.wait,
                timeout_sec=args.timeout_sec,
                poll_interval_sec=args.poll_interval_sec,
            )
            _print(response, json_output=args.json)
            return 0 if response.success else 1

        if args.command == "editor":
            if args.action == "play":
                response = adapter.editor_play(
                    wait=args.wait,
                    timeout_sec=args.timeout_sec,
                    poll_interval_sec=args.poll_interval_sec,
                )
            elif args.action == "stop":
                response = adapter.editor_stop(
                    wait=args.wait,
                    timeout_sec=args.timeout_sec,
                    stable_sec=args.stable_sec,
                    poll_interval_sec=args.poll_interval_sec,
                )
            else:
                response = adapter.editor_pause()
            _print(response, json_output=args.json)
            return 0 if response.success else 1

        if args.command == "menu":
            response = adapter.execute_menu_item(args.menu_path)
            _print(response, json_output=args.json)
            return 0 if response.success else 1

        if args.command == "reserialize":
            response = adapter.reserialize_assets(
                args.paths or None,
                wait=args.wait,
                timeout_sec=args.timeout_sec,
                stable_sec=args.stable_sec,
                poll_interval_sec=args.poll_interval_sec,
            )
            _print(response, json_output=args.json)
            return 0 if response.success else 1

        if args.command == "profiler":
            response = adapter.profiler(action=args.action)
            _print(response, json_output=args.json)
            return 0 if response.success else 1

        if args.command == "screenshot":
            response = adapter.screenshot(
                view=args.view,
                output_path=args.output_path,
                width=args.width,
                height=args.height,
            )
            _print(response, json_output=args.json)
            return 0 if response.success else 1

        if args.command == "exec":
            response = adapter.exec_csharp(
                _read_code_arg(args),
                usings=args.usings,
                csc=args.csc,
                dotnet=args.dotnet,
            )
            _print(response, json_output=args.json)
            return 0 if response.success else 1

        if args.command == "call":
            params = _parse_params(args.params)
            response = client.call(args.unity_command, params)
            _print(response, json_output=args.json)
            return 0 if response.success else 1

        if args.command == "wait-ready":
            instance = client.wait_for_ready(timeout_sec=args.timeout_sec)
            _print(instance, json_output=args.json)
            return 0

        if args.command == "update":
            return _run_update(args)

    except UnityBridgeError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 2


def _is_direct_tool_invocation(argv: list[str]) -> bool:
    command_index = _find_command_index(argv)
    if command_index is None:
        return False
    return argv[command_index] not in KNOWN_COMMANDS


def _main_direct_tool(argv: list[str]) -> int:
    try:
        parsed = _parse_direct_tool_args(argv)
        client = UnityClient(
            project=parsed["project"],
            port=parsed["port"],
            timeout_ms=parsed["timeout_ms"],
            instances_dir=parsed["instances_dir"],
        )
        response = client.call(parsed["command"], parsed["params"])
        _print(response, json_output=parsed["json"])
        return 0 if response.success else 1
    except UnityBridgeError as exc:
        if _direct_json_requested(argv):
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _parse_direct_tool_args(argv: list[str]) -> dict[str, Any]:
    command_index = _find_command_index(argv)
    if command_index is None:
        raise DiscoveryError("missing connector command")

    command = argv[command_index]
    tokens = argv[:command_index] + argv[command_index + 1 :]
    parsed: dict[str, Any] = {
        "command": command,
        "project": None,
        "port": None,
        "timeout_ms": 120_000,
        "instances_dir": None,
        "json": False,
        "no_update_check": False,
        "params": {},
    }
    positional: list[Any] = []

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--":
            positional.extend(_coerce_param_value(item) for item in tokens[i + 1 :])
            break

        global_match = _split_global_value_option(token)
        if global_match is not None:
            name, value, consumed_next = global_match
            if consumed_next:
                if i + 1 >= len(tokens):
                    raise DiscoveryError(f"{token} requires a value")
                value = tokens[i + 1]
            parsed[name] = _coerce_global_value(name, value)
            i += 2 if consumed_next else 1
            continue

        if token in GLOBAL_BOOL_OPTIONS:
            parsed[GLOBAL_BOOL_OPTIONS[token]] = True
            i += 1
            continue

        if token == "--params":
            if i + 1 >= len(tokens):
                raise DiscoveryError("--params requires a JSON object")
            parsed["params"].update(_parse_params(tokens[i + 1]))
            i += 2
            continue

        if token.startswith("--params="):
            parsed["params"].update(_parse_params(token.split("=", 1)[1]))
            i += 1
            continue

        if token.startswith("--no-") and len(token) > len("--no-"):
            _assign_param(parsed["params"], _flag_to_param_name(token[5:]), False)
            i += 1
            continue

        if token.startswith("--") and len(token) > 2:
            name, value, consumed_next = _split_param_option(token, tokens, i)
            _assign_param(parsed["params"], name, value)
            i += 2 if consumed_next else 1
            continue

        positional.append(_coerce_param_value(token))
        i += 1

    if positional:
        existing_args = parsed["params"].get("args")
        if existing_args is None:
            parsed["params"]["args"] = positional
        elif isinstance(existing_args, list):
            existing_args.extend(positional)
        else:
            parsed["params"]["args"] = [existing_args, *positional]

    return parsed


def _find_command_index(argv: list[str]) -> int | None:
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--":
            return i + 1 if i + 1 < len(argv) else None
        if token in GLOBAL_BOOL_OPTIONS:
            i += 1
            continue
        if token in GLOBAL_VALUE_OPTIONS:
            i += 2
            continue
        if _split_global_value_option(token) is not None:
            i += 1
            continue
        if token.startswith("-"):
            return None
        return i
    return None


def _split_global_value_option(token: str) -> tuple[str, str | None, bool] | None:
    if token in GLOBAL_VALUE_OPTIONS:
        return GLOBAL_VALUE_OPTIONS[token], None, True
    for option, name in GLOBAL_VALUE_OPTIONS.items():
        prefix = option + "="
        if token.startswith(prefix):
            return name, token[len(prefix) :], False
    return None


def _coerce_global_value(name: str, value: str | None) -> Any:
    if value is None:
        return None
    if name in {"port", "timeout_ms"}:
        try:
            return int(value)
        except ValueError as exc:
            raise DiscoveryError(f"--{name.replace('_', '-')} must be an integer") from exc
    return value


def _split_param_option(tokens_value: str, tokens: list[str], index: int) -> tuple[str, Any, bool]:
    if "=" in tokens_value:
        raw_name, raw_value = tokens_value[2:].split("=", 1)
        return _flag_to_param_name(raw_name), _coerce_param_value(raw_value), False

    raw_name = tokens_value[2:]
    next_index = index + 1
    if next_index >= len(tokens) or tokens[next_index].startswith("--"):
        return _flag_to_param_name(raw_name), True, False
    return _flag_to_param_name(raw_name), _coerce_param_value(tokens[next_index]), True


def _flag_to_param_name(value: str) -> str:
    return value.replace("-", "_")


def _coerce_param_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _assign_param(params: dict[str, Any], name: str, value: Any) -> None:
    if name in params:
        existing = params[name]
        if isinstance(existing, list):
            existing.append(value)
        else:
            params[name] = [existing, value]
        return
    params[name] = value


def _direct_json_requested(argv: list[str]) -> bool:
    return any(token == "--json" for token in argv)


def _read_code_arg(args: argparse.Namespace) -> str:
    if args.code is not None:
        return args.code
    if getattr(args, "stdin", False):
        return sys.stdin.read()
    try:
        return Path(args.code_file).read_text(encoding="utf-8")
    except OSError as exc:
        raise DiscoveryError(f"cannot read --code-file/--file: {exc}") from exc


def _run_update(args: argparse.Namespace) -> int:
    if args.check:
        return _run_update_check(args)
    if _is_standalone_build():
        return _run_standalone_update(args)

    package_spec = args.package_spec or _git_package_spec(args.repo, args.ref)
    command = [sys.executable, "-m", "pip", "install", "--upgrade", "--force-reinstall", package_spec]
    connector_url = _connector_package_url(args.repo, args.ref)
    payload = {
        "ok": True,
        "dry_run": bool(args.dry_run),
        "command": command,
        "package_spec": package_spec,
        "connector_url": connector_url,
        "note": "This updates the Python CLI package. Update the Unity Connector package separately in Unity Package Manager if needed.",
    }

    if args.dry_run:
        _print_update_payload(payload, json_output=args.json)
        return 0

    if not args.json:
        print("Updating UnityBridge Python package...")
        print(_format_shell_command(command))

    completed = subprocess.run(command)
    payload["ok"] = completed.returncode == 0
    payload["returncode"] = completed.returncode

    if args.json:
        _print_update_payload(payload, json_output=True)
    elif completed.returncode == 0:
        print("UnityBridge Python package updated.")
        print(f"Unity Connector package URL: {connector_url}")
    else:
        print(f"UnityBridge update failed with exit code {completed.returncode}.", file=sys.stderr)
    return int(completed.returncode)


def _run_standalone_update(args: argparse.Namespace) -> int:
    if args.package_spec:
        raise DiscoveryError("--package-spec is only supported by Python package installs")

    version = _standalone_update_version(args.ref)
    command = _standalone_update_command(version, wait_pid=os.getpid())
    connector_ref = "main" if version == "latest" else version
    connector_url = _connector_package_url(args.repo, connector_ref)
    asset_name = _standalone_asset_name()
    payload = {
        "ok": True,
        "mode": "standalone",
        "dry_run": bool(args.dry_run),
        "command": command,
        "version": version,
        "asset_name": asset_name,
        "connector_url": connector_url,
        "note": "This updates the standalone executable from GitHub Releases. Update the Unity Connector package separately in Unity Package Manager if needed.",
    }

    if args.dry_run:
        _print_update_payload(payload, json_output=args.json)
        return 0

    if not args.json:
        print("Updating UnityBridge standalone executable...")
        print(_format_shell_command(command))

    try:
        popen_kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(command, **popen_kwargs)
    except OSError as exc:
        payload["ok"] = False
        payload["error"] = str(exc)
        if args.json:
            _print_update_payload(payload, json_output=True)
        else:
            print(f"UnityBridge standalone update failed to start: {exc}", file=sys.stderr)
        return 1

    payload["scheduled"] = True

    if args.json:
        _print_update_payload(payload, json_output=True)
    else:
        print("UnityBridge standalone executable update requested.")
        print("Open a new terminal if PATH changes were applied.")
        print(f"Unity Connector package URL: {connector_url}")
    return 0


def _run_update_check(args: argparse.Namespace) -> int:
    package_spec = args.package_spec or _git_package_spec(args.repo, args.ref)
    connector_url = _connector_package_url(args.repo, args.ref)
    current_version = _current_package_version()
    latest_version = _remote_python_version(args.repo, args.ref)
    connector_version = _remote_connector_version(args.repo, args.ref)
    status = _version_status(current_version, latest_version)
    payload = {
        "ok": True,
        "check": True,
        "mode": _install_mode(),
        "repo": args.repo,
        "ref": args.ref,
        "package_spec": package_spec,
        "connector_url": connector_url,
        "current_version": current_version,
        "latest_version": latest_version,
        "target_connector_version": connector_version,
        "status": status,
        "update_available": status == "outdated",
        "note": "This checks the installed UnityBridge CLI version. Update the Unity Connector package separately in Unity Package Manager if needed.",
    }
    if _is_standalone_build():
        payload["asset_name"] = _standalone_asset_name()
    _print_update_check_payload(payload, json_output=args.json)
    return 0


def _maybe_print_update_notice(args: argparse.Namespace) -> None:
    if not _should_auto_update_check(args):
        return

    cache_path = _update_check_cache_path()
    now = time.time()
    if not _auto_update_check_due(cache_path, now=now):
        return

    payload: dict[str, Any] = {"checked_at": now}
    try:
        current_version = _current_package_version()
        latest_version = _remote_python_version(
            DEFAULT_REPOSITORY_URL,
            "main",
            timeout_sec=AUTO_UPDATE_CHECK_TIMEOUT_SECONDS,
        )
        status = _version_status(current_version, latest_version)
        payload.update(
            {
                "current_version": current_version,
                "latest_version": latest_version,
                "status": status,
            }
        )
        if status == "outdated":
            print(
                f"UnityBridge update available: {current_version} -> {latest_version}. Run: unity-bridge update",
                file=sys.stderr,
            )
    except Exception as exc:  # noqa: BLE001 - update notices must never break the requested command.
        payload["error"] = str(exc)
    finally:
        _write_update_check_cache(cache_path, payload)


def _should_auto_update_check(args: argparse.Namespace) -> bool:
    if getattr(args, "command", "") == "update":
        return False
    if getattr(args, "json", False):
        return False
    if getattr(args, "no_update_check", False):
        return False
    return not _env_flag_enabled("UNITY_BRIDGE_SKIP_UPDATE_CHECK")


def _env_flag_enabled(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _update_check_cache_path() -> Path:
    return Path.home() / ".unity-bridge" / "update-check.json"


def _auto_update_check_due(path: Path, *, now: float) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if not isinstance(payload, dict):
        return True
    checked_at = payload.get("checked_at")
    if not isinstance(checked_at, (int, float)):
        return True
    return now - float(checked_at) >= AUTO_UPDATE_CHECK_INTERVAL_SECONDS


def _write_update_check_cache(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _git_package_spec(repo: str, ref: str) -> str:
    repo = repo.strip()
    ref = ref.strip()
    if not ref:
        return f"git+{repo}"
    return f"git+{repo}@{ref}"


def _connector_package_url(repo: str, ref: str) -> str:
    repo = repo.strip()
    ref = ref.strip()
    suffix = f"#{ref}" if ref else ""
    return f"{repo}?path=/unity-bridge-connector{suffix}"


def _print_update_payload(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(_format_shell_command(payload["command"]))
    if payload.get("asset_name"):
        print(f"Standalone asset: {payload['asset_name']}")
    print(f"Unity Connector package URL: {payload['connector_url']}")
    print(payload["note"])


def _print_update_check_payload(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    label = "UnityBridge standalone CLI" if payload.get("mode") == "standalone" else "UnityBridge Python package"
    current = payload["current_version"]
    latest = payload["latest_version"]
    status = payload["status"]
    if status == "outdated":
        print(f"{label}: {current} -> {latest} available")
        print("Run: unity-bridge update")
    elif status == "current":
        print(f"{label}: {current} (up to date)")
    elif status == "newer":
        print(f"{label}: {current} (newer than {latest})")
    else:
        print(f"{label}: {current} (latest: {latest})")
    if payload.get("asset_name"):
        print(f"Standalone asset: {payload['asset_name']}")
    print(f"Target Unity Connector version: {payload['target_connector_version']}")
    print(f"Unity Connector package URL: {payload['connector_url']}")
    print(payload["note"])


def _current_package_version() -> str:
    if _is_standalone_build():
        return __version__
    try:
        return importlib_metadata.version("unity-bridge")
    except importlib_metadata.PackageNotFoundError:
        return _local_python_version()


def _local_python_version() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        return _parse_pyproject_version(pyproject.read_text(encoding="utf-8"))
    except OSError:
        return __version__ or "unknown"


def _is_standalone_build() -> bool:
    return bool(getattr(sys, "frozen", False))


def _install_mode() -> str:
    return "standalone" if _is_standalone_build() else "python"


def _standalone_update_version(ref: str) -> str:
    ref = (ref or "").strip()
    if not ref or ref == "main":
        return "latest"
    if ref.startswith("refs/tags/"):
        return ref[len("refs/tags/") :]
    return ref


def _standalone_update_command(version: str, *, wait_pid: int | None = None) -> list[str]:
    if sys.platform == "win32":
        return _standalone_windows_update_command(version, wait_pid=wait_pid)
    return _standalone_posix_update_command(version, wait_pid=wait_pid)


def _standalone_windows_update_command(version: str, *, wait_pid: int | None = None) -> list[str]:
    wait_script = ""
    if wait_pid is not None and wait_pid > 0:
        wait_script = f"try {{ Wait-Process -Id {int(wait_pid)} -Timeout 30 -ErrorAction SilentlyContinue }} catch {{ }}; "
    script = (
        "$ErrorActionPreference = 'Stop'; "
        + wait_script
        + "$script = Join-Path $env:TEMP 'unity-bridge-install.ps1'; "
        + f"Invoke-WebRequest -Uri '{DEFAULT_INSTALL_POWERSHELL_SCRIPT_URL}' -OutFile $script; "
        + f"& $script -Version '{_escape_powershell_single_quoted(version)}'"
    )
    return [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "& { " + script + " }",
    ]


def _standalone_posix_update_command(version: str, *, wait_pid: int | None = None) -> list[str]:
    wait_script = ""
    if wait_pid is not None and wait_pid > 0:
        wait_script = (
            f"i=0; while kill -0 {int(wait_pid)} 2>/dev/null && [ $i -lt 30 ]; "
            "do i=$((i + 1)); sleep 1; done; "
        )
    script = (
        "set -e; "
        + wait_script
        + "script=\"${TMPDIR:-/tmp}/unity-bridge-install-$$.sh\"; "
        + "if command -v curl >/dev/null 2>&1; then "
        + f"curl -fsSL {_sh_quote(DEFAULT_INSTALL_SHELL_SCRIPT_URL)} -o \"$script\"; "
        + "elif command -v wget >/dev/null 2>&1; then "
        + f"wget -qO \"$script\" {_sh_quote(DEFAULT_INSTALL_SHELL_SCRIPT_URL)}; "
        + "else echo 'curl or wget is required to update UnityBridge.' >&2; exit 1; fi; "
        + f"sh \"$script\" --version {_sh_quote(version)}; "
        + "rm -f \"$script\""
    )
    return ["sh", "-c", script]


def _standalone_asset_name() -> str:
    os_name = _standalone_os_name()
    arch_name = _standalone_arch_name()
    if os_name == "windows" and arch_name == "amd64":
        return DEFAULT_WINDOWS_ASSET_NAME
    extension = ".exe" if os_name == "windows" else ""
    return f"unity-bridge-{os_name}-{arch_name}{extension}"


def _standalone_os_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    raise DiscoveryError(f"unsupported standalone platform: {sys.platform}")


def _standalone_arch_name() -> str:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "amd64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    raise DiscoveryError(f"unsupported standalone architecture: {machine}")


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _escape_powershell_single_quoted(value: str) -> str:
    return value.replace("'", "''")


def _remote_python_version(repo: str, ref: str, *, timeout_sec: float = 10) -> str:
    return _parse_pyproject_version(
        _read_remote_repository_file(repo, ref, "pyproject.toml", timeout_sec=timeout_sec)
    )


def _remote_connector_version(repo: str, ref: str, *, timeout_sec: float = 10) -> str:
    text = _read_remote_repository_file(
        repo,
        ref,
        "unity-bridge-connector/package.json",
        timeout_sec=timeout_sec,
    )
    try:
        value = json.loads(text).get("version")
    except json.JSONDecodeError as exc:
        raise DiscoveryError(f"failed to parse remote connector package.json: {exc}") from exc
    if not isinstance(value, str) or not value:
        raise DiscoveryError("remote connector package.json does not contain a version")
    return value


def _read_remote_repository_file(repo: str, ref: str, path: str, *, timeout_sec: float = 10) -> str:
    owner, name = _parse_github_repo(repo)
    encoded_path = urllib.parse.quote(path, safe="/")
    encoded_ref = urllib.parse.quote(ref or "main", safe="")
    url = f"https://api.github.com/repos/{owner}/{name}/contents/{encoded_path}?ref={encoded_ref}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.raw",
            "User-Agent": "unity-bridge-cli",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raise DiscoveryError(f"failed to check remote version: GitHub returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise DiscoveryError(f"failed to check remote version: {exc.reason}") from exc

    text = body.decode("utf-8")
    if "json" not in content_type.lower():
        return text

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    content = payload.get("content")
    encoding = payload.get("encoding")
    if isinstance(content, str) and encoding == "base64":
        return base64.b64decode(content).decode("utf-8")
    return text


def _parse_github_repo(repo: str) -> tuple[str, str]:
    repo = repo.strip()
    ssh_match = re.fullmatch(r"git@github\.com:([^/]+)/(.+?)(?:\.git)?", repo)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    parsed = urllib.parse.urlparse(repo)
    if parsed.hostname not in {"github.com", "www.github.com"}:
        raise DiscoveryError("--check currently supports github.com repository URLs")
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2:
        raise DiscoveryError("--check requires a GitHub repository URL")
    name = parts[1]
    if name.endswith(".git"):
        name = name[:-4]
    return parts[0], name


def _parse_pyproject_version(text: str) -> str:
    match = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']', text)
    if not match:
        raise DiscoveryError("pyproject.toml does not contain a project version")
    return match.group(1)


def _version_status(current: str, latest: str) -> str:
    current_key = _version_key(current)
    latest_key = _version_key(latest)
    if current_key is None or latest_key is None:
        return "unknown"
    if current_key < latest_key:
        return "outdated"
    if current_key > latest_key:
        return "newer"
    return "current"


def _version_key(value: str) -> tuple[int, ...] | None:
    if value == "unknown":
        return None
    parts = re.findall(r"\d+", value)
    if not parts:
        return None
    numbers = [int(part) for part in parts[:4]]
    while len(numbers) < 4:
        numbers.append(0)
    return tuple(numbers)


def _format_shell_command(command: list[str]) -> str:
    return " ".join(_quote_command_part(part) for part in command)


def _quote_command_part(value: str) -> str:
    if not value or any(ch.isspace() for ch in value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def _parse_params(value: str) -> Any:
    try:
        params = json.loads(value)
    except json.JSONDecodeError as exc:
        raise DiscoveryError(f"--params must be valid JSON: {exc}") from exc
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise DiscoveryError("--params must be a JSON object")
    return params


def _print(value: Any, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(_to_jsonable(value), ensure_ascii=False, indent=2))
        return

    if isinstance(value, list):
        if not value:
            print("No Unity instances found.")
            return
        for instance in value:
            _print_instance(instance)
        return
    if isinstance(value, Instance):
        _print_instance(value)
        return
    if isinstance(value, CommandResponse):
        print(value.message)
        if value.data is not None:
            print(json.dumps(value.data, ensure_ascii=False, indent=2))
        return
    if isinstance(value, UnityActionResult):
        print(value.message)
        if value.data is not None:
            print(json.dumps(value.data, ensure_ascii=False, indent=2))
        return
    print(value)


def _print_instance(instance: Instance) -> None:
    age = instance.heartbeat_age_seconds
    age_label = "unknown" if age is None else f"{age:.1f}s"
    print(f"Unity (port {instance.port}): {instance.state}")
    print(f" Project: {instance.project_path}")
    print(f" Version: {instance.unity_version or 'unknown'}")
    print(f" Connector: {instance.connector_version or 'unknown'}")
    print(f" PID: {instance.pid}")
    print(f" Heartbeat age: {age_label}")


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Instance):
        return value.to_dict()
    if isinstance(value, CommandResponse):
        return value.to_dict()
    if isinstance(value, UnityActionResult):
        return value.to_dict()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
