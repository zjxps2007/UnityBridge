"""Public CLI entry point for scripts, installed commands, and standalone builds."""
from __future__ import annotations

import argparse
import sys

from .adapter import UnityActionResult
from .client import CommandResponse, UnityBridgeError, UnityClient
from ._cli.arguments import (
    add_common_options,
    build_parser,
    direct_json_requested,
    is_direct_tool_invocation,
    parse_direct_tool_args,
)
from ._cli.commands import execute_command
from ._cli.output import (
    print_connector_version_warning,
    print_error,
    print_result,
    warn_for_selected_connector_version,
)

__all__ = ["main", "build_parser", "add_common_options"]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_host"]:
        from .host import main as host_main

        return host_main(argv[1:])
    direct = is_direct_tool_invocation(argv)
    json_output = direct_json_requested(argv)
    try:
        args = parse_direct_tool_args(argv) if direct else build_parser().parse_args(argv)
        if not direct:
            json_output = args.json

        if not direct:
            # Help exits during argument parsing, before update modules are loaded.
            from ._cli.updates import maybe_print_update_notice, run_update

            maybe_print_update_notice(args)
            if args.command == "update":
                return run_update(args)

        client = _create_client(args)
        if direct:
            instance = client.discover_instance()
            print_connector_version_warning(instance, json_output=args.json)
            result = client.call(args.command, args.params, instance=instance)
        else:
            if args.command not in {"instances", "status", "wait-ready"}:
                warn_for_selected_connector_version(client, json_output=args.json)
            result = execute_command(args, client)

        print_result(result, json_output=args.json)
        if isinstance(result, (CommandResponse, UnityActionResult)):
            return 0 if result.success else 1
        return 0
    except UnityBridgeError as exc:
        print_error(exc, json_output=json_output)
        return 1


def _create_client(args: argparse.Namespace) -> UnityClient:
    return UnityClient(
        project=args.project,
        port=args.port,
        timeout_ms=args.timeout_ms,
        instances_dir=args.instances_dir,
        backend=getattr(args, "backend", None),
    )


if __name__ == "__main__":
    raise SystemExit(main())
