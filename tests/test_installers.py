"""Exercise the real installers offline, inside disposable installation paths."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid

REPO = Path(__file__).resolve().parents[1]
SHELL = shutil.which("sh")
if not SHELL and os.name == "nt":
    candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
    if candidate.exists():
        SHELL = str(candidate)


class InstallerFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="unity-bridge-install-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root / "custom install"
        self.fixtures = self.root / "fixtures"
        self.fixtures.mkdir()
        self.env = dict(os.environ, UNITY_BRIDGE_SKIP_UPDATE_CHECK="1",
                        FIXTURE_DIR=self.fixtures.as_posix(), INSTALL_TEST_ROOT=str(self.root))

    def bundle(self, *, windows=False, valid=True):
        source = self.root / uuid.uuid4().hex
        bundle = source / "unity-bridge"
        runtime = "_unity_bridge_runtime_" + uuid.uuid4().hex
        (bundle / runtime).mkdir(parents=True)
        (bundle / runtime / "payload").write_text(runtime)
        if windows:
            shutil.copy2(self.good_exe if valid else self.bad_exe, bundle / "unity-bridge.exe")
        else:
            command = bundle / "unity-bridge"
            command.write_text(f'#!/bin/sh\ntest -f "$(dirname "$0")/{runtime}/payload" || exit 8\nexit {0 if valid else 9}\n', newline='\n')
            command.chmod(0o755)
        archive = self.fixtures / ("unity-bridge-windows-amd64.zip" if windows else "unity-bridge-linux-amd64.tar.gz")
        extension = ".zip" if windows else ".tar.gz"
        shutil.make_archive(str(archive)[:-len(extension)], "zip" if windows else "gztar", source, "unity-bridge")
        return archive, runtime


@unittest.skipUnless(SHELL, "POSIX shell is not installed")
class PosixInstallerTests(InstallerFixture):
    def setUp(self):
        super().setUp()
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        (fake_bin / "curl").write_text('''#!/bin/sh
while [ "$#" -gt 0 ]; do
    case "$1" in
        -o) output="$2"; shift 2 ;;
        https:*) asset="${1##*/}"; shift ;;
        *) shift ;;
    esac
done
test -f "$FIXTURE_DIR/$asset" || exit 22
cp "$FIXTURE_DIR/$asset" "$output"
''', newline='\n')
        (fake_bin / "uname").write_text('#!/bin/sh\ncase "$1" in -s) echo Linux ;; -m) echo x86_64 ;; esac\n', newline='\n')
        for path in fake_bin.iterdir():
            path.chmod(0o755)
        # Windows' PATH delimiter differs from the one the child POSIX shell uses.
        self.env['TEST_BIN'] = fake_bin.as_posix()

    def run_installer(self, *args, success=True):
        result = subprocess.run([SHELL, "-c", 'if command -v cygpath >/dev/null; then TEST_BIN=$(cygpath -u "$TEST_BIN"); fi; export PATH="$TEST_BIN:$PATH"; exec sh "$@"', "installer",
                                 (REPO / "install.sh").as_posix(), "--install-dir", self.install.as_posix(),
                                 "--no-path-update", *args], env=self.env, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_bundle_upgrade_reinstall_and_rejected_download(self):
        _, old_runtime = self.bundle()
        self.run_installer()
        original = (self.install / "unity-bridge").read_bytes()
        self.run_installer()  # Same build remains installable.
        _, new_runtime = self.bundle()
        self.run_installer()
        self.assertTrue((self.install / old_runtime / "payload").exists())
        self.assertTrue((self.install / new_runtime / "payload").exists())
        updated = (self.install / "unity-bridge").read_bytes()
        self.assertNotEqual(original, updated)
        self.bundle(valid=False)
        self.run_installer(success=False)
        self.assertEqual((self.install / "unity-bridge").read_bytes(), updated)
        self.assertEqual(list(self.install.glob('.unity-bridge-stage*')), [])

    def test_legacy_release_fallback_and_migration(self):
        legacy = self.fixtures / "unity-bridge-linux-amd64"
        legacy.write_text('#!/bin/sh\nexit 0\n', newline='\n')
        self.run_installer()
        self.assertEqual((self.install / "unity-bridge").read_bytes(), legacy.read_bytes())
        self.bundle()
        self.run_installer()
        self.assertTrue(list(self.install.glob('_unity_bridge_runtime_*')))

    def test_invalid_archive_preserves_existing_install(self):
        archive, _ = self.bundle()
        self.run_installer()
        before = (self.install / 'unity-bridge').read_bytes()
        archive.write_bytes(b'not an archive')
        self.run_installer(success=False)
        self.assertEqual((self.install / 'unity-bridge').read_bytes(), before)


@unittest.skipUnless(os.name == 'nt', "Windows installer requires Windows")
class WindowsInstallerTests(InstallerFixture):
    @classmethod
    def setUpClass(cls):
        cls.binaries = tempfile.TemporaryDirectory(prefix="unity-bridge-fixture-")
        cls.addClassCleanup(cls.binaries.cleanup)
        for name, code in [('good', 0), ('bad', 9)]:
            source = Path(cls.binaries.name) / f'{name}.cs'
            output = source.with_suffix('.exe')
            source.write_text(f'public class Fixture {{ public static int Main(string[] args) {{ return {code}; }} }}')
            compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            subprocess.run([str(compiler), '/nologo', f'/out:{output}', str(source)], check=True, capture_output=True)
            setattr(cls, f'{name}_exe', output)

    def run_installer(self, *, success=True):
        driver = self.root / 'invoke.ps1'
        driver.write_text('''$ErrorActionPreference = 'Stop'
function Invoke-RestMethod {
    $assets = @(Get-ChildItem -LiteralPath $env:FIXTURE_DIR -File | ForEach-Object {
        [pscustomobject]@{name=$_.Name; browser_download_url=$_.FullName}
    })
    return [pscustomobject]@{tag_name='test'; assets=$assets}
}
function Invoke-WebRequest {
    param($Uri, $OutFile, $Headers)
    Copy-Item -LiteralPath $Uri -Destination $OutFile
}
& $env:INSTALL_TEST_SCRIPT -InstallDir (Join-Path $env:INSTALL_TEST_ROOT 'custom install') -NoPathUpdate
''')
        self.env['INSTALL_TEST_SCRIPT'] = str(REPO / 'install.ps1')
        result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(driver)], env=self.env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_bundle_upgrade_reinstall_and_rejected_download(self):
        _, old_runtime = self.bundle(windows=True)
        self.run_installer()
        self.run_installer()
        _, new_runtime = self.bundle(windows=True)
        self.run_installer()
        self.assertTrue((self.install / old_runtime / 'payload').exists())
        self.assertTrue((self.install / new_runtime / 'payload').exists())
        before = (self.install / 'unity-bridge.exe').read_bytes()
        self.bundle(windows=True, valid=False)
        self.run_installer(success=False)
        self.assertEqual((self.install / 'unity-bridge.exe').read_bytes(), before)
        self.assertEqual(list(self.install.glob('.unity-bridge-stage*')), [])

    def test_legacy_fallback_and_migration(self):
        shutil.copy2(self.good_exe, self.fixtures / 'unity-bridge-windows-x64.exe')
        self.run_installer()
        self.bundle(windows=True)
        self.run_installer()
        self.assertTrue(list(self.install.glob('_unity_bridge_runtime_*')))

    def test_invalid_archive_preserves_existing_install(self):
        archive, _ = self.bundle(windows=True)
        self.run_installer()
        before = (self.install / 'unity-bridge.exe').read_bytes()
        archive.write_bytes(b'not an archive')
        self.run_installer(success=False)
        self.assertEqual((self.install / 'unity-bridge.exe').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
