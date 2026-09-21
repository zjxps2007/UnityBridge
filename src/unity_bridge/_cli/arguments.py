"""Built-in arguments and direct Connector tool syntax."""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
from typing import Any

from ..client import DiscoveryError
from . import DEFAULT_REPOSITORY_URL


KNOWN_COMMANDS = {
    "instances",
    "session",
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
    "--backend": "backend",
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
    parser.add_argument("--backend", choices=["auto", "host", "legacy"], default=default,
                        help="Select the automatic, external host, or direct Connector route.")
    no_update_default = argparse.SUPPRESS if suppress_defaults else False
    parser.add_argument("--no-update-check", action="store_true", default=no_update_default, help="Skip the automatic daily update notice.")
    if json_option:
        json_default = argparse.SUPPRESS if suppress_defaults else False
        parser.add_argument("--json", action="store_true", default=json_default, help="Print JSON output.")


def build_parser(command: str | None = None, *, parser_class=argparse.ArgumentParser) -> argparse.ArgumentParser:
    parent = parser_class(add_help=False)
    add_common_options(parent, json_option=True, suppress_defaults=True)

    parser = parser_class(
        prog="unity-bridge",
        epilog=(
            "Unknown command names are sent directly to Unity Connector, so project "
            "custom tools can be called as: unity-bridge my_tool --x 1 --params '{...}'"
        ),
    )
    add_common_options(parser, json_option=True, suppress_defaults=False)
    sub = parser.add_subparsers(dest="command", required=True)

    if command is None or command == "instances":
        sub.add_parser("instances", parents=[parent], help="List discovered Unity Connector instances.")

    if command is None or command == "status":
        sub.add_parser("status", parents=[parent], help="Show selected Unity Connector instance status.")

    if command is None or command == "tools":
        sub.add_parser("tools", parents=[parent], help="List Unity Connector tools.")

    if command is None or command == "refresh":
        refresh = sub.add_parser("refresh", parents=[parent], help="Refresh Unity assets.")
        refresh.add_argument("--mode", default="if_dirty", choices=["if_dirty", "force"], help="Refresh mode.")
        refresh.add_argument("--force", action="store_true", help="Allow refresh while entering or in play mode.")
        refresh.add_argument("--path", dest="paths", action="append", help="Asset path to import. Repeatable. Accepts Assets/..., Packages/..., or an absolute project path.")
        refresh.add_argument("--compile", default="none", choices=["none", "request"], help="Request script compilation.")
        refresh.add_argument("--wait", action="store_true", help="Wait until Unity reaches stable ready after refresh.")
        refresh.add_argument("--timeout-sec", type=int, default=300, help="Ready wait timeout in seconds.")
        refresh.add_argument("--stable-sec", type=float, default=None, help="Extra ready stability duration; default: 0 for confirmed operations, 0.5 for legacy waits.")

    if command is None or command == "console":
        console = sub.add_parser("console", parents=[parent], help="Read or clear Unity console logs.")
        console.add_argument("--count", "--lines", dest="count", type=int, default=50, help="Maximum number of entries to return.")
        console.add_argument("--type", dest="types", action="append", help="Log type: error, warning, or log. Repeatable.")
        console.add_argument("--stacktrace", default="user", choices=["none", "user", "full"], help="Stack trace output mode.")
        console.add_argument("--clear", action="store_true", help="Clear the Unity console.")

    if command is None or command == "test":
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

    if command is None or command == "editor":
        editor = sub.add_parser("editor", parents=[parent], help="Control Unity Editor play state.")
        editor.add_argument("action", choices=["play", "stop", "pause"], help="Editor action.")
        editor.add_argument("--wait", action="store_true", help="Wait until play or stop completes.")
        editor.add_argument("--timeout-sec", type=int, default=300, help="Play/stop wait timeout in seconds.")
        editor.add_argument("--stable-sec", type=float, default=None, help="Extra stability duration; default: 0 for confirmed operations, 0.5 for legacy stop waits.")
        editor.add_argument("--poll-interval-sec", type=float, default=None, help="Wait poll interval; default: 0.05 for operation receipts, 0.5 for legacy waits.")

    if command is None or command == "menu":
        menu = sub.add_parser("menu", parents=[parent], help="Execute a Unity menu item.")
        menu.add_argument("menu_path", help="Unity menu item path, for example File/Save Project.")

    if command is None or command == "reserialize":
        reserialize = sub.add_parser("reserialize", parents=[parent], help="Force reserialize assets.")
        reserialize.add_argument("paths", nargs="*", help="Optional asset paths. Omit for the entire project.")
        reserialize.add_argument("--wait", action="store_true", help="Wait until Unity reaches stable ready after reserialize.")
        reserialize.add_argument("--timeout-sec", type=int, default=300, help="Ready wait timeout in seconds.")
        reserialize.add_argument("--stable-sec", type=float, default=None, help="Extra ready stability duration; default: 0 for confirmed operations, 0.5 for legacy waits.")
        reserialize.add_argument("--poll-interval-sec", type=float, default=None, help="Wait poll interval; default: 0.05 for operation receipts, 0.5 for legacy waits.")

    if command is None or command == "profiler":
        profiler = sub.add_parser("profiler", parents=[parent], help="Control Unity Profiler.")
        profiler.add_argument("action", nargs="?", default="status", help="Profiler action: status, enable, disable, clear, hierarchy.")

    if command is None or command == "screenshot":
        screenshot = sub.add_parser("screenshot", parents=[parent], help="Capture a Unity editor screenshot.")
        screenshot.add_argument("--view", default="scene", choices=["scene", "game"], help="View to capture.")
        screenshot.add_argument("--output-path", help="Output file path.")
        screenshot.add_argument("--width", type=int, help="Screenshot width.")
        screenshot.add_argument("--height", type=int, help="Screenshot height.")

    if command is None or command == "exec":
        exec_command = sub.add_parser("exec", parents=[parent], help="Execute arbitrary C# code through Unity.")
        code_group = exec_command.add_mutually_exclusive_group(required=True)
        code_group.add_argument("--code", help="C# code to execute. Use 'return' for output.")
        code_group.add_argument("--code-file", "--file", dest="code_file", help="Read C# code from a file.")
        code_group.add_argument("--stdin", action="store_true", help="Read C# code from standard input.")
        exec_command.add_argument("--using", dest="usings", action="append", help="Additional using namespace. Repeatable.")
        exec_command.add_argument("--csc", help="Override csc compiler path.")
        exec_command.add_argument("--dotnet", help="Override dotnet runtime path.")

    if command is None or command == "call":
        call = sub.add_parser("call", parents=[parent], help="Send a command to Unity Connector.")
        call.add_argument("unity_command", help="Unity Connector command name, for example list or console.")
        call.add_argument("--params", default="{}", help="JSON object passed as command params.")

    if command is None or command == "wait-ready":
        wait_ready = sub.add_parser("wait-ready", parents=[parent], help="Confirm readiness with the Unity Editor; no fixed settling delay.")
        wait_ready.add_argument("--timeout-sec", type=int, default=300, help="Ready wait timeout in seconds.")

    if command is None or command == "update":
        update = sub.add_parser("update", parents=[parent], help="Update the UnityBridge CLI.")
        update.add_argument("--ref", default="main", help="Git ref to install, for example main, v0.2.1, or a branch name.")
        update.add_argument("--repo", default=DEFAULT_REPOSITORY_URL, help="Git repository URL.")
        update.add_argument("--package-spec", help="Full pip package spec. Overrides --repo and --ref.")
        update.add_argument("--dry-run", action="store_true", help="Print the pip command without running it.")
        update.add_argument("--check", action="store_true", help="Check available versions without installing.")

    if command is None or command == "session":
        session = sub.add_parser("session", parents=[parent], help="Process one JSON request per stdin line without restarting the CLI.")
        session.add_argument("--pipeline", type=int, choices=(1, 2, 4), default=1,
                             help="Maximum outstanding inline exec requests (default: sequential).")
    return parser


def parser_for(argv: list[str]) -> argparse.ArgumentParser:
    index = _find_command_index(argv)
    selected = argv[index] if index is not None and argv[index] in KNOWN_COMMANDS else None
    return _cached_parser(selected)


@lru_cache(maxsize=32)
def _cached_parser(command: str | None) -> argparse.ArgumentParser:
    # Public build_parser() still returns an independent, complete parser.
    return build_parser(command)


def is_direct_tool_invocation(argv: list[str]) -> bool:
    command_index = _find_command_index(argv)
    if command_index is None:
        return False
    return argv[command_index] not in KNOWN_COMMANDS


def parse_direct_tool_args(argv: list[str]) -> argparse.Namespace:
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
        "backend": None,
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
            parsed["params"].update(parse_params(tokens[i + 1]))
            i += 2
            continue

        if token.startswith("--params="):
            parsed["params"].update(parse_params(token.split("=", 1)[1]))
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

    return argparse.Namespace(**parsed)


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


def direct_json_requested(argv: list[str]) -> bool:
    return any(token == "--json" for token in argv)


def parse_params(value: str) -> Any:
    try:
        params = json.loads(value)
    except json.JSONDecodeError as exc:
        raise DiscoveryError(f"--params must be valid JSON: {exc}") from exc
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise DiscoveryError("--params must be a JSON object")
    return params
