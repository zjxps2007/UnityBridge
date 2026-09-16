"""Exercise the real installers offline, inside disposable installation paths."""
from __future__ import annotations

import json
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
                        FIXTURE_DIR=self.fixtures.as_posix(), INSTALL_TEST_ROOT=str(self.root),
                        UNITY_BRIDGE_HOST_HOME=(self.root / 'host registry').as_posix(),
                        HOST_TEST_LOG=(self.root / 'host-calls.tsv').as_posix())

    def bundle(self, *, windows=False, valid=True, host=False, worker=True):
        source = self.root / uuid.uuid4().hex
        bundle = source / "unity-bridge"
        runtime = "_unity_bridge_runtime_" + uuid.uuid4().hex
        (bundle / runtime).mkdir(parents=True)
        (bundle / runtime / "payload").write_text(runtime)
        if host:
            (bundle / runtime / 'host-manifest.json').write_text(json.dumps({
                'protocol': 1, 'version': 'fixture', 'compiler': 'compiler/UnityBridge.Compiler'}))
            if worker:
                compiler_dir = bundle / runtime / 'compiler'
                compiler_dir.mkdir()
                compiler_file = compiler_dir / ('UnityBridge.Compiler.exe' if windows else 'UnityBridge.Compiler')
                compiler_file.write_text('fixture worker; the fixture CLI exercises installer sequencing'
                                         if windows else '#!/bin/sh\nexit 0\n', newline='\n')
                compiler_file.chmod(0o755)
        if windows:
            shutil.copy2(self.host_exe if host else self.good_exe if valid else self.bad_exe,
                         bundle / "unity-bridge.exe")
        else:
            command = bundle / "unity-bridge"
            source_text = f'#!/bin/sh\ntest -f "$(dirname "$0")/{runtime}/payload" || exit 8\n'
            if host:
                source_text += '''if [ "$1" = "_host" ]; then
    operation="$2"
    executable=""
    if [ "$operation" = "register" ]; then executable="$4"; worker="$6"; else worker="$4"; fi
    self="$0"
    if command -v cygpath >/dev/null; then
        self=$(cygpath -m "$self")
        worker=$(cygpath -m "$worker")
        if [ -n "$executable" ]; then executable=$(cygpath -m "$executable"); fi
    fi
    intact=no
    if cmp -s "$INSTALL_TEST_ROOT/expected-previous" "$INSTALL_TEST_ROOT/custom install/unity-bridge"; then intact=yes; fi
    printf '%s\\t%s\\t%s\\t%s\\t%s\\n' "$operation" "$self" "$executable" "$worker" "$intact" >> "$HOST_TEST_LOG"
    if [ "$HOST_TEST_FAIL" = "$operation" ]; then exit 17; fi
    if [ "$operation" = "register" ]; then
        mkdir -p "$UNITY_BRIDGE_HOST_HOME"
        printf '%s\\n' "$executable" > "$UNITY_BRIDGE_HOST_HOME/registered"
    fi
fi
'''
            source_text += f'exit {0 if valid else 9}\n'
            command.write_text(source_text, newline='\n')
            command.chmod(0o755)
        archive = self.fixtures / ("unity-bridge-windows-amd64.zip" if windows else "unity-bridge-linux-amd64.tar.gz")
        extension = ".zip" if windows else ".tar.gz"
        shutil.make_archive(str(archive)[:-len(extension)], "zip" if windows else "gztar", source, "unity-bridge")
        return archive, runtime


class HostInstallerCases:
    """Same observable install/rollback contract for the real POSIX/Windows scripts."""

    windows = False

    def prior_install(self):
        _, previous_runtime = self.bundle(windows=self.windows)
        self.run_installer()
        target = self.install / ('unity-bridge.exe' if self.windows else 'unity-bridge')
        before = target.read_bytes()
        (self.root / 'expected-previous').write_bytes(before)
        return target, before, previous_runtime

    def host_calls(self):
        path = self.root / 'host-calls.tsv'
        return [line.split('\t') for line in path.read_text(encoding='utf-8-sig').splitlines()] if path.exists() else []

    def test_host_worker_checked_before_replacement_and_registration_uses_final_paths(self):
        target, before, _ = self.prior_install()
        _, runtime = self.bundle(windows=self.windows, host=True)
        self.run_installer()
        calls = self.host_calls()
        self.assertEqual([row[0] for row in calls], ['check-worker', 'register'])
        self.assertIn('.unity-bridge-stage', calls[0][1])
        self.assertIn('.unity-bridge-stage', calls[0][3])
        self.assertEqual(calls[0][4], 'yes', 'Existing CLI changed before worker validation.')
        self.assertEqual(Path(calls[1][1]).resolve(), target.resolve())
        self.assertEqual(Path(calls[1][2]).resolve(), target.resolve())
        expected_worker = self.install / runtime / 'compiler' / ('UnityBridge.Compiler.exe' if self.windows else 'UnityBridge.Compiler')
        self.assertEqual(Path(calls[1][3]).resolve(), expected_worker.resolve())
        self.assertEqual(calls[1][4], 'no', 'Registration did not use the newly installed CLI.')
        self.assertNotEqual(target.read_bytes(), before)
        self.assertTrue((self.root / 'host registry/registered').exists())

    def test_broken_worker_preserves_existing_cli_before_replacement(self):
        target, before, previous_runtime = self.prior_install()
        self.bundle(windows=self.windows, host=True)
        self.env['HOST_TEST_FAIL'] = 'check-worker'
        self.run_installer(success=False)
        self.assertEqual(target.read_bytes(), before)
        self.assertTrue((self.install / previous_runtime / 'payload').exists())
        self.assertEqual([row[0] for row in self.host_calls()], ['check-worker'])
        self.assertFalse((self.root / 'host registry/registered').exists())

    def test_registration_failure_rolls_back_existing_cli(self):
        target, before, previous_runtime = self.prior_install()
        self.bundle(windows=self.windows, host=True)
        self.env['HOST_TEST_FAIL'] = 'register'
        self.run_installer(success=False)
        self.assertEqual(target.read_bytes(), before)
        self.assertTrue((self.install / previous_runtime / 'payload').exists())
        self.assertEqual([row[0] for row in self.host_calls()], ['check-worker', 'register'])
        self.assertFalse((self.root / 'host registry/registered').exists())
        self.assertEqual(list(self.install.glob('.unity-bridge-stage*')), [])

    def test_marker_with_missing_worker_preserves_existing_install(self):
        target, before, _ = self.prior_install()
        self.bundle(windows=self.windows, host=True, worker=False)
        self.run_installer(success=False)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(self.host_calls(), [])


@unittest.skipUnless(SHELL, "POSIX shell is not installed")
class PosixInstallerTests(HostInstallerCases, InstallerFixture):
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
class WindowsInstallerTests(HostInstallerCases, InstallerFixture):
    windows = True
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
        source = Path(cls.binaries.name) / 'host.cs'
        source.write_text('''using System;
using System.IO;
using System.Reflection;
using System.Text;
public class Fixture {
    public static int Main(string[] args) {
        if (args.Length == 0 || args[0] != "_host") return 0;
        string operation = args[1];
        string executable = operation == "register" ? args[3] : "";
        string worker = operation == "register" ? args[5] : args[3];
        string root = Environment.GetEnvironmentVariable("INSTALL_TEST_ROOT");
        string expected = Path.Combine(root, "expected-previous");
        string target = Path.Combine(root, "custom install", "unity-bridge.exe");
        string intact = File.Exists(expected) && File.Exists(target) &&
            Convert.ToBase64String(File.ReadAllBytes(expected)) == Convert.ToBase64String(File.ReadAllBytes(target)) ? "yes" : "no";
        File.AppendAllText(Environment.GetEnvironmentVariable("HOST_TEST_LOG"),
            String.Join("\\t", new[] { operation, Assembly.GetExecutingAssembly().Location, executable, worker, intact }) + "\\n", new UTF8Encoding(false));
        if (Environment.GetEnvironmentVariable("HOST_TEST_FAIL") == operation) return 17;
        if (operation == "register") {
            string registry = Environment.GetEnvironmentVariable("UNITY_BRIDGE_HOST_HOME");
            Directory.CreateDirectory(registry);
            File.WriteAllText(Path.Combine(registry, "registered"), executable);
        }
        return 0;
    }
}
''')
        cls.host_exe = source.with_suffix('.exe')
        subprocess.run([str(compiler), '/nologo', f'/out:{cls.host_exe}', str(source)],
                       check=True, capture_output=True)

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
