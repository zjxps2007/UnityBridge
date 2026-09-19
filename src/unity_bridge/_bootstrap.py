"""Small entry point: most exec calls need neither argparse nor the full client."""
import sys
from ._timing import mark


def main(argv=None):
    mark('python_entry')
    try:
        return _main(argv)
    finally:
        mark('python_result')


def _main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["_host"]:
        from .host.cli import main as host_main
        mark('host_cli_imported')
        return host_main(args[1:])
    stdin_text = None
    from ._fast_exec import try_exec
    mark('fast_cli_imported')
    result, stdin_text = try_exec(args)
    if result is not None:
        return result
    from .cli import main as full_main
    mark('full_cli_imported')
    if stdin_text is None:
        return full_main(args)
    # A connection can fail before dispatch after stdin was read. Replay only
    # the local input to the normal parser, never a submitted Unity command.
    from io import StringIO
    previous = sys.stdin
    try:
        sys.stdin = StringIO(stdin_text)
        return full_main(args)
    finally:
        sys.stdin = previous
