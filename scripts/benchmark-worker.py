"""Compare fresh JIT and ReadyToRun workers using a saved real Unity context.

This is a compiler component benchmark, not Unity command latency. DLL references
in --context must still exist. Workers never load or execute emitted user code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from unity_bridge.host.compiler import CompilerWorker


def stats(values):
    values = sorted(values)
    return {"n": len(values), "p50_ms": values[math.ceil(len(values) * .5) - 1],
            "p95_ms": values[math.ceil(len(values) * .95) - 1], "max_ms": values[-1]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, type=Path)
    parser.add_argument("--jit", required=True, type=Path)
    parser.add_argument("--r2r", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.samples < 2 or args.output.exists():
        parser.error("Use at least two samples and a new output file")
    context = json.loads(args.context.read_text(encoding="utf-8"))
    payload = {"operation": "compile", "code": "return 42;", "usings": [],
               "language_version": context["languageVersion"], "references": context["references"],
               "project_id": "worker-startup-benchmark", "reference_generation": "fixed-context",
               "fresh_identity": True}
    rows = []
    result = {"context_sha256": hashlib.sha256(args.context.read_bytes()).hexdigest(),
              "reference_count": len(context["references"]), "samples_per_variant": args.samples,
              "scope": "Fresh processes, alternating order, no OS file cache purge; compilation only, no Unity execution",
              "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for index in range(args.samples):
        for variant in (("jit", "r2r") if index % 2 == 0 else ("r2r", "jit")):
            worker = CompilerWorker(str(getattr(args, variant)))
            try:
                started = time.perf_counter()
                worker.prewarm()
                ping_ms = (time.perf_counter() - started) * 1000
                compile_start = time.perf_counter()
                cold = worker.request(payload, deadline=time.monotonic() + 30)
                first_ms = (time.perf_counter() - compile_start) * 1000
                total_ms = (time.perf_counter() - started) * 1000
                warm_start = time.perf_counter()
                warm = worker.request(payload, deadline=time.monotonic() + 30)
                warm_ms = (time.perf_counter() - warm_start) * 1000
                assert not cold["cache_hit"] and warm["cache_hit"] and not warm["emit_reused"]
                assert cold["assembly_name"] != warm["assembly_name"]
                rows.append({"variant": variant, "sample": index + 1, "ping_ms": ping_ms,
                             "first_compile_ms": first_ms, "start_to_first_compile_ms": total_ms,
                             "warm_compile_ms": warm_ms})
            finally:
                worker.close()
            args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    result["summary"] = {variant: {key: stats([row[key] for row in rows if row["variant"] == variant])
                                    for key in ("ping_ms", "first_compile_ms", "start_to_first_compile_ms", "warm_compile_ms")}
                         for variant in ("jit", "r2r")}
    result["installed_bytes"] = {variant: sum(path.stat().st_size for path in getattr(args, variant).parent.rglob("*") if path.is_file())
                                 for variant in ("jit", "r2r")}
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
