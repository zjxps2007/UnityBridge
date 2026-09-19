"""Sequential JSONL commands in one CLI process; discovery stays fresh per request."""
from __future__ import annotations

import argparse
from io import StringIO
import json
import sys

from .arguments import (GLOBAL_VALUE_OPTIONS, KNOWN_COMMANDS, _find_command_index,
                        build_parser, is_direct_tool_invocation, parse_direct_tool_args)
from .commands import execute_command, result_exit_code
from .output import to_jsonable
from ..client import UnityBridgeError

MAX_REQUEST_CHARS = 1024 * 1024


def _decode_output(value: str):
    if not value:
        return None
    try:
        return json.loads(value)
    except ValueError:
        return value.rstrip()


class SessionExecutor:
    """One sequential session owns its parsers and diagnostics, never sys.stdout."""

    def __init__(self):
        self.stdout, self.stderr = StringIO(), StringIO()
        self.parsers = {}
        self.pool = None
        owner = self

        class Parser(argparse.ArgumentParser):
            def _print_message(self, message, file=None):
                if message:
                    (owner.stdout if file is sys.stdout else owner.stderr).write(message)

        self.parser_class = Parser

    def invoke(self, argv):
        from ..cli import _create_client
        self.stdout, self.stderr = StringIO(), StringIO()
        try:
            direct = is_direct_tool_invocation(argv)
            if direct:
                parsed = parse_direct_tool_args(argv)
            else:
                index = _find_command_index(argv)
                selected = argv[index] if index is not None and argv[index] in KNOWN_COMMANDS else None
                if selected not in self.parsers:
                    self.parsers[selected] = build_parser(selected, parser_class=self.parser_class)
                parsed = self.parsers[selected].parse_args(argv)
            client = _create_client(parsed)
            if parsed.command not in {"instances", "status"}:
                if self.pool is None:
                    from ..host.transport import ConnectionPool
                    self.pool = ConnectionPool()
                client._connection_pool = self.pool
            if direct:
                result = client.call(parsed.command, parsed.params, instance=client.discover_instance())
            else:
                result = execute_command(parsed, client)
            return result_exit_code(result), to_jsonable(result), None
        except SystemExit as exc:
            return int(exc.code or 0), _decode_output(self.stdout.getvalue()), _decode_output(self.stderr.getvalue())
        except UnityBridgeError as exc:
            return 1, None, {"ok": False, "error": str(exc)}

    def close(self):
        if self.pool is not None:
            self.pool.close()


def run_session(args: argparse.Namespace) -> int:
    executor = SessionExecutor()
    try:
        return _run_session(args, executor)
    finally:
        executor.close()


def _run_session(args: argparse.Namespace, executor: SessionExecutor) -> int:

    inherited = ["--json"]
    for option, name in GLOBAL_VALUE_OPTIONS.items():
        value = getattr(args, name, None)
        if value is not None:
            inherited.extend([option, str(value)])
    stream, output = sys.stdin, sys.stdout
    while True:
        line = stream.readline(MAX_REQUEST_CHARS + 1)
        if not line:
            return 0
        request_id = None
        try:
            if len(line) > MAX_REQUEST_CHARS:
                while line and not line.endswith("\n"):
                    line = stream.readline(MAX_REQUEST_CHARS + 1)
                raise ValueError("Session request exceeds 1 MiB of characters")
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("Session request must be an object with id and args")
            request_id = request.get("id")
            if request_id is not None and (isinstance(request_id, bool) or not isinstance(request_id, (str, int))):
                request_id = None
                raise ValueError("Session id must be a string, integer, or null")
            argv = request.get("args")
            if not isinstance(argv, list) or not argv or any(not isinstance(value, str) for value in argv):
                raise ValueError("Session args must be a nonempty array of argument strings")
            index = _find_command_index(argv)
            if index is not None and argv[index] in {"session", "update", "_host"}:
                raise ValueError("Session requests cannot invoke session, update, or _host")
            if "--stdin" in argv:
                raise ValueError("Use --code or --code-file in a session; stdin carries JSONL requests")
            code, result, error = executor.invoke(inherited + argv)
            response = {"id": request_id, "exit_code": code, "result": result, "error": error}
        except (ValueError, TypeError) as exc:
            response = {"id": request_id, "exit_code": 2, "result": None, "error": str(exc)}
        output.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        output.flush()
