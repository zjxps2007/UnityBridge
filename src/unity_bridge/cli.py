from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .adapter import UnityActionResult
from .adapter import UnityBridgeAdapter
from .client import CommandResponse
from .client import DiscoveryError
from .client import Instance
from .client import UnityBridgeError
from .client import UnityClient


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
}

GLOBAL_VALUE_OPTIONS = {
    "--project": "project",
    "--port": "port",
    "--timeout-ms": "timeout_ms",
    "--instances-dir": "instances_dir",
}
GLOBAL_BOOL_OPTIONS = {"--json": "json"}


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
    console.add_argument("--count", type=int, default=50, help="Maximum number of entries to return.")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if _is_direct_tool_invocation(argv):
        return _main_direct_tool(argv)

    args = build_parser().parse_args(argv)
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
