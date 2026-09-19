"""Build a standalone benchmark candidate; this is NOT a release archive.

Nuitka's flat native-library layout is intentionally kept intact. The production
installer requires immutable versioned runtime directories and rejects this
layout. Do not publish this candidate before both layout and performance gates
have been met on all supported platforms.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compiler-dir', type=Path, required=True)
    parser.add_argument('--c-compiler', choices=('auto', 'mingw64', 'zig'), default='auto')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    env = dict(os.environ, PYTHONPATH=str(root / 'src'))
    env.setdefault('NUITKA_CACHE_DIR', str(output / 'cache'))
    command = [sys.executable, '-m', 'nuitka', '--mode=standalone',
               '--output-filename=unity-bridge.exe' if os.name == 'nt' else '--output-filename=unity-bridge',
               '--output-dir=' + str(output), '--include-package=unity_bridge',
               '--assume-yes-for-downloads', '--jobs=4',
               '--report=' + str(output / 'compilation.xml')]
    if args.c_compiler != 'auto':
        command.append('--' + args.c_compiler)
    subprocess.run(command + [str(root / 'scripts/pyinstaller_entry.py')], env=env, cwd=root, check=True)
    bundle = output / 'pyinstaller_entry.dist'
    shutil.copytree(args.compiler_dir, bundle / 'compiler', dirs_exist_ok=True)
    (output / 'build-info.json').write_text(json.dumps({
        'python': sys.version, 'packager': 'Nuitka', 'packager_version': importlib.metadata.version('Nuitka'),
        'seconds': time.perf_counter() - started,
        'installed_bytes': sum(p.stat().st_size for p in bundle.rglob('*') if p.is_file()),
        'release_eligible': False, 'layout': 'flat-standalone-experiment',
        'source_sha256': {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (root / 'src').rglob('*.py')},
        'compiler_sha256': hashlib.sha256((bundle / 'compiler/UnityBridge.Compiler.dll').read_bytes()).hexdigest(),
    }, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
