from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an install-once standalone UnityBridge CLI bundle.")
    parser.add_argument("--output-name", required=True, help="Release archive name (.zip on Windows, .tar.gz elsewhere).")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    extension = ".zip" if sys.platform == "win32" else ".tar.gz"
    if Path(args.output_name).name != args.output_name or not args.output_name.endswith(extension):
        parser.error(f"--output-name must be a filename ending in {extension}")
    # Each executable points at its own immutable runtime. An update can publish
    # the new runtime before replacing the executable without mixing DLL versions.
    runtime_name = "_unity_bridge_runtime_" + uuid.uuid4().hex
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

    target = root / "dist" / args.output_name
    archive_format = "zip" if sys.platform == "win32" else "gztar"
    shutil.make_archive(str(target)[:-len(extension)], archive_format,
                        root_dir=root / "dist", base_dir="unity-bridge")

    print(f"Built {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
