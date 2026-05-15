from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a standalone UnityBridge CLI executable.")
    parser.add_argument("--output-name", required=True, help="Filename to copy into dist after PyInstaller finishes.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--name",
        "unity-bridge",
        "--paths",
        str(root / "src"),
        str(root / "scripts" / "pyinstaller_entry.py"),
    ]
    subprocess.run(command, cwd=root, check=True)

    source_name = "unity-bridge.exe" if sys.platform == "win32" else "unity-bridge"
    source = root / "dist" / source_name
    target = root / "dist" / args.output_name
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    if sys.platform != "win32":
        target.chmod(target.stat().st_mode | 0o755)

    print(f"Built {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
