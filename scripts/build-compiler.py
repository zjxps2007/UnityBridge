"""Publish the independent compiler with its own .NET runtime; Unity supplies metadata only."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dotnet", default="dotnet", help="Path to the .NET 10 SDK executable.")
    parser.add_argument("--runtime", required=True, choices=("win-x64", "linux-x64", "linux-arm64", "osx-x64", "osx-arm64"))
    parser.add_argument("--output", required=True, type=Path, help="Destination for the complete self-contained worker directory.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sdk = shutil.which(args.dotnet) or args.dotnet
    output = args.output.resolve()
    environment = os.environ.copy()
    environment.setdefault("DOTNET_CLI_TELEMETRY_OPTOUT", "1")
    environment.setdefault("DOTNET_SKIP_FIRST_TIME_EXPERIENCE", "1")
    subprocess.run([
        sdk, "publish", str(root / "compiler-worker" / "UnityBridge.Compiler" / "UnityBridge.Compiler.csproj"),
        "--configuration", "Release", "--runtime", args.runtime, "--self-contained", "true",
        "--output", str(output), "-p:PublishSingleFile=false", "-p:PublishTrimmed=false",
    ], cwd=root, env=environment, check=True)
    executable = output / ("UnityBridge.Compiler.exe" if args.runtime.startswith("win-") else "UnityBridge.Compiler")
    if not executable.is_file():
        raise RuntimeError(f"Compiler publish did not produce {executable}")
    print(f"Built self-contained compiler: {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
