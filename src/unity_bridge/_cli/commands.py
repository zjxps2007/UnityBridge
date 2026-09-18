"""Map parsed CLI options to client and adapter operations."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..adapter import UnityActionResult
from ..client import CommandResponse, DiscoveryError, Instance, UnityClient
from .arguments import parse_params


def _read_code_arg(args: argparse.Namespace) -> str:
    if args.code is not None:
        return args.code
    if getattr(args, "stdin", False):
        return sys.stdin.read()
    try:
        return Path(args.code_file).read_text(encoding="utf-8")
    except OSError as exc:
        raise DiscoveryError(f"cannot read --code-file/--file: {exc}") from exc


def execute_command(args: argparse.Namespace, client: UnityClient) -> UnityActionResult | CommandResponse | Instance | list[Instance]:
    if args.command == "instances":
        return client.scan_instances()
    if args.command == "status":
        return client.status()

    from ..adapter import UnityBridgeAdapter
    adapter = UnityBridgeAdapter(client=client)
    if args.command == "wait-ready":
        return adapter.wait_for_ready(timeout_sec=args.timeout_sec)

    if args.command == "tools":
        return adapter.list_tools()

    if args.command == "refresh":
        return adapter.refresh_assets(
            mode=args.mode,
            force=args.force,
            paths=args.paths,
            compile=args.compile,
            wait=args.wait,
            timeout_sec=args.timeout_sec,
            stable_sec=args.stable_sec,
        )

    if args.command == "console":
        return adapter.clear_console() if args.clear else adapter.read_console(
            count=args.count,
            types=args.types,
            stacktrace=args.stacktrace,
        )

    if args.command == "test":
        return adapter.run_tests(
            mode=args.mode,
            filter=args.filter,
            allow_dirty_scenes=args.allow_dirty_scenes,
            auto_save_scenes=args.auto_save_scenes,
            wait=args.wait,
            timeout_sec=args.timeout_sec,
            poll_interval_sec=args.poll_interval_sec,
        )

    if args.command == "editor":
        if args.action == "play":
            return adapter.editor_play(
                wait=args.wait,
                timeout_sec=args.timeout_sec,
                poll_interval_sec=args.poll_interval_sec,
            )
        elif args.action == "stop":
            return adapter.editor_stop(
                wait=args.wait,
                timeout_sec=args.timeout_sec,
                stable_sec=args.stable_sec,
                poll_interval_sec=args.poll_interval_sec,
            )
        else:
            return adapter.editor_pause()

    if args.command == "menu":
        return adapter.execute_menu_item(args.menu_path)

    if args.command == "reserialize":
        return adapter.reserialize_assets(
            args.paths or None,
            wait=args.wait,
            timeout_sec=args.timeout_sec,
            stable_sec=args.stable_sec,
            poll_interval_sec=args.poll_interval_sec,
        )

    if args.command == "profiler":
        return adapter.profiler(action=args.action)

    if args.command == "screenshot":
        return adapter.screenshot(
            view=args.view,
            output_path=args.output_path,
            width=args.width,
            height=args.height,
        )

    if args.command == "exec":
        return adapter.exec_csharp(
            _read_code_arg(args),
            usings=args.usings,
            csc=args.csc,
            dotnet=args.dotnet,
        )

    if args.command == "call":
        params = parse_params(args.params)
        return client.call(args.unity_command, params)
    raise DiscoveryError(f"unsupported built-in command: {args.command}")
