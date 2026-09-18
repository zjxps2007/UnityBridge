import sys

from unity_bridge._bootstrap import main


# Frozen Python ignores PYTHONIOENCODING. Keep pipe input/output in UTF-8 on
# every platform so JSON and C# snippets survive non-ASCII Windows locales.
for stream in (sys.stdin, sys.stdout, sys.stderr):
    if stream is not None:
        stream.reconfigure(encoding="utf-8")

raise SystemExit(main())
