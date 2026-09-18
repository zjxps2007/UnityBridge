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
from .._cli.output import _connector_version_warning, render_action_result
from ..adapter import UnityBridgeAdapter
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
        remaining = self.deadline - int(time.time() * 1000)
        if remaining <= 0:
            from .service import not_started
            return CommandResponse.from_dict(not_started("expired", "Request expired before Unity execution"))
        service = self.service
        with service.projects_lock:
            registered = (normalized_project(target.project_path), target.pid) in service.projects
        if (self.backend != "legacy" and target.bridge_protocol == 1 and registered
                and normalized_project(self.instances_dir) == normalized_project(service.instances_dir)):
            return CommandResponse.from_dict(service.submit({
                "command": command, "params": params or {}, "request_id": uuid.uuid4().hex,
                "deadline_unix_ms": self.deadline,
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
                or not isinstance(code, str)
                or not isinstance(deadline, int) or isinstance(deadline, bool)):
            raise DiscoveryError("Invalid fast CLI request")
        args = build_parser("exec", parser_class=Parser).parse_args(argv)
        json_output = args.json
        if args.command != "exec" or args.csc or args.dotnet:
            raise DiscoveryError("Fast CLI request only supports exec without compiler overrides")
        if not 0 < args.timeout_ms <= 86_400_000:
            raise DiscoveryError("--timeout-ms must be between 1 and 86400000")
        # The caller sends its original absolute deadline. Receiving the request
        # and parsing arguments must not restart the timeout.
        deadline = min(deadline, int(time.time() * 1000) + args.timeout_ms)
        directory = args.instances_dir or payload.get("instances_dir")
        if directory is not None:
            if not isinstance(directory, str):
                raise DiscoveryError("Invalid instance directory")
            directory = str(Path(cwd) / directory)
        backend = args.backend or payload.get("backend") or "auto"
        client = _LocalClient(service, deadline, project=args.project, port=args.port,
                              timeout_ms=args.timeout_ms, instances_dir=directory, cwd=cwd, backend=backend)
        if not json_output:
            warning = _connector_version_warning(client.discover_instance())
            if warning:
                stderr.write(warning + "\n")
        result = UnityBridgeAdapter(client=client).exec_csharp(code, usings=args.usings)
        stdout.write(render_action_result(result, json_output=json_output))
        return reply(0 if result.success else 1)
    except _ParseExit as exc:
        return reply(exc.status)
    except UnityBridgeError as exc:
        stderr.write((json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2)
                      if json_output else f"ERROR: {exc}") + "\n")
        return reply(1)
