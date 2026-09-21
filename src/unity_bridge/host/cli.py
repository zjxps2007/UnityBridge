"""Hidden host administration entry point used by installers and the Connector."""
from __future__ import annotations

import argparse
import json
import sys

from .registry import (ProcessLock, endpoint_path, host_home, launch, load_launcher,
                       process_alive, read_json, register_launcher)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="unity-bridge _host")
    sub = parser.add_subparsers(dest="operation", required=True)
    register = sub.add_parser("register")
    register.add_argument("--executable", required=True)
    register.add_argument("--worker", required=True)
    register.add_argument("--python-module", action="store_true")
    register.add_argument("--instances-dir")
    serve = sub.add_parser("serve")
    serve.add_argument("--runtime-id", required=True)
    serve.add_argument("--instances-dir")
    check = sub.add_parser("check-worker")
    check.add_argument("--worker", required=True)
    sub.add_parser("start")
    sub.add_parser("status")
    sub.add_parser("stop")
    args = parser.parse_args(argv)
    root = host_home()
    try:
        if args.operation == "register":
            from .. import __version__
            value = register_launcher(args.executable, args.worker, python_module=args.python_module,
                                      version=__version__, root=root, instances_dir=args.instances_dir)
            print(json.dumps({"registered": True, "runtimeId": value["runtimeId"], "version": value["version"]}))
            return 0
        if args.operation == "check-worker":
            from .compiler import CompilerWorker
            worker = CompilerWorker(args.worker)
            try:
                result = worker.prewarm()
                print(json.dumps({"passed": True, "protocol": result["protocol"],
                                  "compiler_version": result.get("compiler_version", "")}))
                return 0
            finally:
                worker.close()
        if args.operation == "start":
            print(json.dumps(launch(root)))
            return 0
        if args.operation == "status":
            from . import host_status
            print(json.dumps(host_status()))
            return 0
        descriptor = load_launcher(root, args.runtime_id if args.operation == "serve" else None)
        if descriptor is None:
            raise ValueError("No compatible UnityBridge host launcher is registered")
        if args.operation == "stop":
            from .transport import post
            endpoint = read_json(endpoint_path(root, descriptor["runtimeId"]))
            if not endpoint or not process_alive(endpoint.get("pid")):
                print(json.dumps({"stopped": True, "was_running": False}))
                return 0
            print(json.dumps(post(endpoint["port"], descriptor["token"], "/stop", {}, 5)))
            return 0
        from pathlib import Path
        lock = ProcessLock(root / "locks" / f"{descriptor['runtimeId']}.lock")
        if not lock.acquire():
            return 0
        try:
            from .compiler import CompilerError
            from .compiler_pool import create_compiler
            compiler = create_compiler(descriptor["workerPath"])
            try:
                # Runtime startup overlaps HTTP/parser imports. No project code
                # or Unity API executes in this child process.
                compiler_error = ""
                try:
                    compiler.start()
                except CompilerError as exc:
                    compiler_error = str(exc)
                from .service import HostService
                service = HostService(root, descriptor, compiler=compiler,
                                      instances_dir=Path(args.instances_dir) if args.instances_dir else None)
                service.compiler_error = compiler_error
                service.serve()
            finally:
                compiler.close()
        finally:
            lock.close()
        return 0
    except Exception as exc:
        # Exception messages are intentionally free of launcher contents/tokens.
        print(f"UnityBridge host: {exc}", file=sys.stderr)
        return 1
