"""Run one lightweight CLI exec request in the resident Python interpreter.

Only presentation and argument parsing live here. Discovery, execution ordering,
deadlines and unknown-completion handling use the same client/service contracts.
No process-global cwd, environment or stdout is changed by a request.
"""
from __future__ import annotations

import argparse
from io import StringIO
import json
from pathlib import Path
import sys
import time
from typing import TYPE_CHECKING
import uuid

from .._cli.arguments import build_parser
from .._cli.commands import execute_command, result_exit_code
from .._cli.output import _connector_version_warning, print_result
from .._fast_exec import _options, SUPPORTED_COMMANDS
from ..client import CommandResponse, DiscoveryError, UnityBridgeError, UnityClient, UnityConnectionError, send_command
from .registry import normalized_project

if TYPE_CHECKING:
    from .service import HostService

CLI_PROTOCOL = 1


class _ParseExit(Exception):
    def __init__(self, status: int):
        self.status = status


class _LocalClient(UnityClient):
    def __init__(self, service: HostService, deadline: int, **kwargs):
        super().__init__(**kwargs)
        self.service, self.deadline = service, deadline

    def call(self, command, params=None, *, timeout_ms=None, instance=None):
        target = instance or self.discover_instance()
        now = int(time.time() * 1000)
        call_deadline = min(self.deadline, now + (timeout_ms or self.timeout_ms))
        remaining = call_deadline - now
        if remaining <= 0:
            from .service import not_started
            return CommandResponse.from_dict(not_started("expired", "Request expired before Unity execution"))
        service = self.service
        if (self.backend != "legacy" and target.bridge_protocol == 1
                and normalized_project(self.instances_dir) == normalized_project(service.instances_dir)):
            # submit refreshes authoritative discovery when the CLI observes a
            # new instance before the watchdog. Initial negotiation must not
            # force a direct compiler fallback or reject the first request.
            return CommandResponse.from_dict(service.submit({
                "command": command, "params": params or {}, "request_id": uuid.uuid4().hex,
                "deadline_unix_ms": call_deadline,
                "target": {"projectPath": target.project_path, "pid": target.pid, "port": target.port},
            }))
        if self.backend == "host":
            raise UnityConnectionError("no compatible UnityBridge host is ready for this Unity instance")
        # Route selection happens before sending anything to Unity. An older
        # Connector retains its existing direct route; a sent command is never replayed.
        return send_command(target, command, params, timeout_ms=remaining)


def execute_cli(service: HostService, payload: dict) -> dict:
    stdout, stderr = StringIO(), StringIO()
    json_output = False

    def reply(code):
        return {"cli_protocol": CLI_PROTOCOL, "exit_code": code,
                "stdout": stdout.getvalue(), "stderr": stderr.getvalue()}

    class Parser(argparse.ArgumentParser):
        def _print_message(self, message, file=None):
            if message:
                (stdout if file is sys.stdout else stderr).write(message)

        def exit(self, status=0, message=None):
            if message:
                stderr.write(message)
            raise _ParseExit(status)

    try:
        argv, cwd, code = payload.get("argv"), payload.get("cwd"), payload.get("code")
        deadline = payload.get("deadline_unix_ms")
        if (payload.get("cli_protocol") != CLI_PROTOCOL or payload.get("version") != service.descriptor["version"]
                or not isinstance(argv, list) or not 0 < len(argv) <= 4096
                or any(not isinstance(arg, str) for arg in argv)
                or not isinstance(cwd, str) or not Path(cwd).is_absolute()
                or not isinstance(deadline, int) or isinstance(deadline, bool)):
            raise DiscoveryError("Invalid fast CLI request")
        options = _options(argv)
        selected = options["command"] if options else "exec"
        args = build_parser(selected, parser_class=Parser).parse_args(argv)
        json_output = args.json
        if (args.command not in SUPPORTED_COMMANDS or getattr(args, "csc", None) or getattr(args, "dotnet", None)
                or (args.command == "exec" and not isinstance(code, str))):
            raise DiscoveryError("Unsupported fast CLI request")
        if not 0 < args.timeout_ms <= 86_400_000:
            raise DiscoveryError("--timeout-ms must be between 1 and 86400000")
        # The caller sends its original absolute deadline. Receiving the request
        # and parsing arguments must not restart the timeout.
        budget = args.timeout_sec * 1000 if args.command == "wait-ready" else args.timeout_ms
        deadline = min(deadline, int(time.time() * 1000) + budget)
        directory = args.instances_dir or payload.get("instances_dir")
        if directory is not None:
            if not isinstance(directory, str):
                raise DiscoveryError("Invalid instance directory")
            directory = str(Path(cwd) / directory)
        backend = args.backend or payload.get("backend") or "auto"
        client = _LocalClient(service, deadline, project=args.project, port=args.port,
                              timeout_ms=args.timeout_ms, instances_dir=directory, cwd=cwd, backend=backend)
        if not json_output and args.command not in {"instances", "status", "wait-ready"}:
            warning = _connector_version_warning(client.discover_instance())
            if warning:
                stderr.write(warning + "\n")
        if args.command == "exec":
            args.code = code
        result = execute_command(args, client)
        print_result(result, json_output=json_output, stdout=stdout, stderr=stderr)
        return reply(result_exit_code(result))
    except _ParseExit as exc:
        return reply(exc.status)
    except UnityBridgeError as exc:
        stderr.write((json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2)
                      if json_output else f"ERROR: {exc}") + "\n")
        return reply(1)
