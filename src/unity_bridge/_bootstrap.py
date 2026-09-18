"""Small entry point: most exec calls need neither argparse nor the full client."""
import sys


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    stdin_text = None
    if "exec" in args:
        from ._fast_exec import try_exec
        result, stdin_text = try_exec(args)
        if result is not None:
            return result
    from .cli import main as full_main
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
