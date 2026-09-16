from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an install-once standalone UnityBridge CLI bundle.")
    parser.add_argument("--output-name", required=True, help="Release archive name (.zip on Windows, .tar.gz elsewhere).")
    parser.add_argument("--dotnet", default="dotnet", help="SDK executable used to build the bundled compiler.")
    parser.add_argument("--compiler-dir", type=Path, help="Use an already published self-contained compiler directory.")
    parser.add_argument("--without-compiler", action="store_true", help="Build a direct-Connector-only development bundle.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    extension = ".zip" if sys.platform == "win32" else ".tar.gz"
    if Path(args.output_name).name != args.output_name or not args.output_name.endswith(extension):
        parser.error(f"--output-name must be a filename ending in {extension}")
    # Each executable points at its own immutable runtime. An update can publish
    # the new runtime before replacing the executable without mixing DLL versions.
    runtime_name = "_unity_bridge_runtime_" + uuid.uuid4().hex
    compiler = None
    if not args.without_compiler:
        architecture = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
        operating_system = {"win32": "win", "darwin": "osx", "linux": "linux"}.get(sys.platform)
        if not architecture or not operating_system:
            parser.error("unsupported compiler platform")
        rid = f"{operating_system}-{architecture}"
        compiler = args.compiler_dir.resolve() if args.compiler_dir else root / "build" / "compiler" / rid
        if args.compiler_dir is None:
            subprocess.run([sys.executable, str(root / "scripts/build-compiler.py"),
                            "--dotnet", args.dotnet, "--runtime", rid, "--output", str(compiler)],
                           cwd=root, check=True)
        compiler_name = "UnityBridge.Compiler.exe" if sys.platform == "win32" else "UnityBridge.Compiler"
        if not (compiler / compiler_name).is_file():
            parser.error("compiler directory does not contain the platform executable")
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onedir",
        "--contents-directory",
        runtime_name,
        "--name",
        "unity-bridge",
        "--paths",
        str(root / "src"),
        str(root / "scripts" / "pyinstaller_entry.py"),
    ]
    subprocess.run(command, cwd=root, check=True)

    if compiler is not None:
        runtime = root / "dist" / "unity-bridge" / runtime_name
        shutil.copytree(compiler, runtime / "compiler")
        # Installers recognize this marker without needing Python, jq, or an SDK.
        (runtime / "host-manifest.json").write_text(json.dumps({
            "protocol": 1, "compiler": "compiler/" + compiler_name,
        }), encoding="utf-8")

    target = root / "dist" / args.output_name
    archive_format = "zip" if sys.platform == "win32" else "gztar"
    shutil.make_archive(str(target)[:-len(extension)], archive_format,
                        root_dir=root / "dist", base_dir="unity-bridge")

    print(f"Built {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
