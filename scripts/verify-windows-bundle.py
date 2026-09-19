"""Verify real Windows bundles offline in isolated install and host directories."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--baseline-dir', type=Path, required=True)
    parser.add_argument('--nuitka-dir', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This script exercises the Windows installer')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error('Use an empty output directory')
    driver = output / 'invoke.ps1'
    driver.write_text("""$ErrorActionPreference = 'Stop'
function Invoke-RestMethod {
    return [pscustomobject]@{tag_name='fixture'; assets=@([pscustomobject]@{
        name='unity-bridge-windows-amd64.zip'; browser_download_url=$env:BUNDLE_ARCHIVE})}
}
function Invoke-WebRequest {
    param($Uri, $OutFile, $Headers)
    Copy-Item -LiteralPath $Uri -Destination $OutFile
}
& $env:BUNDLE_INSTALLER -InstallDir $env:BUNDLE_DESTINATION -NoPathUpdate
""", encoding='utf-8')
    results = {'archive_sha256': digest(args.archive), 'checks': [], 'passed': False,
               'scope': 'Real installer and binaries; only remote discovery/download are replaced with local files; user PATH unchanged.'}

    def install(name, archive, destination, *, success=True):
        env = dict(os.environ, BUNDLE_ARCHIVE=str(archive.resolve()), BUNDLE_INSTALLER=str(ROOT / 'install.ps1'),
                   BUNDLE_DESTINATION=str(destination), UNITY_BRIDGE_HOST_HOME=str(output / 'host'),
                   UNITY_BRIDGE_SKIP_UPDATE_CHECK='1')
        run = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(driver)],
                             env=env, capture_output=True, text=True, timeout=120)
        (output / (name + '.log')).write_text(run.stdout + run.stderr, encoding='utf-8')
        assert (run.returncode == 0) == success, (name, run.stdout, run.stderr)
        results['checks'].append({'name': name, 'passed': True, 'installer_exit_code': run.returncode})
        return env

    def check_launcher(destination):
        launcher = json.loads((output / 'host/launcher.json').read_text())
        assert Path(launcher['argv'][0]).samefile(destination / 'unity-bridge.exe')
        worker = Path(launcher['workerPath'])
        assert worker.is_file() and worker.is_relative_to(destination)

    try:
        fresh = output / 'fresh install'
        env = install('fresh', args.archive, fresh)
        check_launcher(fresh)
        expected = digest(fresh / 'unity-bridge.exe')
        install('reinstall', args.archive, fresh)
        assert digest(fresh / 'unity-bridge.exe') == expected
        upgraded = output / 'upgrade install'
        shutil.copytree(args.baseline_dir, upgraded)
        old_runtimes = {p.name for p in upgraded.glob('_unity_bridge_runtime_*')}
        env = install('upgrade_public_rc2', args.archive, upgraded)
        check_launcher(upgraded)
        assert digest(upgraded / 'unity-bridge.exe') == expected
        assert old_runtimes < {p.name for p in upgraded.glob('_unity_bridge_runtime_*')}
        try:
            run = subprocess.run([str(upgraded / 'unity-bridge.exe'), '_host', 'start'], env=env,
                                 capture_output=True, text=True, timeout=30)
            assert run.returncode == 0, run.stderr
            deadline = time.perf_counter() + 10
            while True:
                run = subprocess.run([str(upgraded / 'unity-bridge.exe'), '_host', 'status'], env=env,
                                     capture_output=True, text=True, timeout=15)
                assert run.returncode == 0, run.stderr
                value = json.loads(run.stdout)
                if value.get('state') == 'running':
                    break
                assert time.perf_counter() < deadline, value
                time.sleep(.02)  # _host start launches asynchronously.
        finally:
            stopped = subprocess.run([str(upgraded / 'unity-bridge.exe'), '_host', 'stop'], env=env,
                                     capture_output=True, text=True, timeout=30)
            assert stopped.returncode == 0, stopped.stderr
        results['checks'].append({'name': 'installed_host_relaunch', 'passed': True})
        if args.nuitka_dir:
            archive = output / 'flat-nuitka.zip'
            with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as bundle:
                for path in args.nuitka_dir.rglob('*'):
                    if path.is_file():
                        bundle.write(path, 'unity-bridge/' + path.relative_to(args.nuitka_dir).as_posix())
            install('reject_flat_nuitka', archive, upgraded, success=False)
            assert digest(upgraded / 'unity-bridge.exe') == expected
            assert not list(upgraded.glob('.unity-bridge-stage-*'))
        results['passed'] = True
    finally:
        (output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
