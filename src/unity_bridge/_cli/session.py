"""Sequential JSONL commands in one CLI process; discovery stays fresh per request."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import sys

from .arguments import GLOBAL_VALUE_OPTIONS, _find_command_index

MAX_REQUEST_CHARS = 1024 * 1024


def _decode_output(value: str):
    if not value:
        return None
    try:
        return json.loads(value)
    except ValueError:
        return value.rstrip()


def run_session(args: argparse.Namespace) -> int:
    from ..cli import main

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
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                try:
                    code = main(inherited + argv)
                except SystemExit as exc:
                    code = int(exc.code or 0)
            response = {"id": request_id, "exit_code": code,
                        "result": _decode_output(stdout.getvalue()), "error": _decode_output(stderr.getvalue())}
        except (ValueError, TypeError) as exc:
            response = {"id": request_id, "exit_code": 2, "result": None, "error": str(exc)}
        output.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        output.flush()
