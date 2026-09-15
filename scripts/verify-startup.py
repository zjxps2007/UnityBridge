"""Run a matched, no-warm-up Unity/CLI comparison in disposable projects.

Requires Git, an installed Unity Editor, and baseline/candidate standalone builds.
No user installation or existing Unity project is modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

REPO = Path(__file__).resolve().parents[1]


def save(path, data):
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unity-editor', required=True, type=Path)
    parser.add_argument('--unity-version', required=True, help='For example 6000.3.13f1 or 2021.3.19f1.')
    parser.add_argument('--baseline-bin', required=True, type=Path)
    parser.add_argument('--candidate-bin', required=True, type=Path)
    parser.add_argument('--baseline-ref', default='main')
    parser.add_argument('--variants', nargs='+', choices=['baseline', 'candidate'],
                        default=['baseline', 'candidate', 'candidate', 'baseline'])
    parser.add_argument('--output', required=True, type=Path)
    options = parser.parse_args()
    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error('--output must be empty; previous evidence is never overwritten')
    unity = options.unity_editor.resolve()
    project = output / 'UnityProject'
    files = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', options.baseline_ref,
                                     'unity-bridge-connector/Editor'], cwd=REPO, text=True).splitlines()
    legacy = subprocess.check_output(['git', 'show', f'{options.baseline_ref}:unity-bridge-connector/Editor/ToolDiscovery.cs'], cwd=REPO).decode()
    baseline_commit = subprocess.check_output(['git', 'rev-parse', options.baseline_ref], cwd=REPO, text=True).strip()
    results = []
    for number, variant in enumerate(options.variants, 1):
        package_file = 'unity-bridge-connector/package.json'
        package = json.loads((REPO / package_file).read_text(encoding='utf-8') if variant == 'candidate' else
                             subprocess.check_output(['git', 'show', f'{options.baseline_ref}:{package_file}'], cwd=REPO))
        expected_version = package['version']
        package_root = project / 'Packages' / package['name']
        package_root.mkdir(parents=True, exist_ok=True)
        # Use a real embedded UPM package so runtime version resolution is exercised.
        # Newtonsoft is supplied from the Editor below for offline validation.
        package.pop('dependencies', None)
        save(package_root / 'package.json', package)
        manifest = {}
        for name in files:
            relative = Path(name).relative_to('unity-bridge-connector/Editor')
            if 'TestRunner' in relative.parts or relative.name == 'TestRunner.meta':
                continue
            path = package_root / 'Editor' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            data = ((REPO / name).read_bytes() if variant == 'candidate' else
                    subprocess.check_output(['git', 'show', f'{options.baseline_ref}:{name}'], cwd=REPO))
            path.write_bytes(data)
            if path.suffix == '.cs':
                manifest[str(relative)] = hashlib.sha256(data).hexdigest()
        editor = project / 'Assets/Editor'
        editor.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / 'tests/unity/StartupDiscoveryAudit.cs', editor)
        (editor / 'LegacyToolDiscovery.cs').write_text(legacy.replace('ToolDiscovery', 'LegacyToolDiscovery'), encoding='utf-8')
        (editor / 'StartupRevision.cs').write_text('public static class StartupRevision { public const int Value = 0; }\n')
        plugins = project / 'Assets/Plugins/Editor'
        plugins.mkdir(parents=True, exist_ok=True)
        shutil.copy2(unity.parent / 'Data/Managed/Newtonsoft.Json.dll', plugins)
        (project / 'Packages').mkdir(exist_ok=True)
        (project / 'ProjectSettings').mkdir(exist_ok=True)
        (project / 'ProjectSettings/ProjectVersion.txt').write_text(f'm_EditorVersion: {options.unity_version}\n')
        save(project / 'Packages/manifest.json', {'dependencies': {f'com.unity.modules.{name}': '1.0.0'
             for name in ['imgui', 'imageconversion', 'screencapture', 'jsonserialize']}})
        for name in ['audit-stop', 'audit-status.json']:
            (project / name).unlink(missing_ok=True)
        result = {'session': number, 'variant': variant, 'baseline_commit': baseline_commit,
                  'source_sha256': manifest, 'expected_connector_version': expected_version,
                  'calls': [], 'passed': False}
        process = subprocess.Popen([str(unity), '-batchmode', '-nographics', '-projectPath', str(project),
                                    '-logFile', str(output / f'session-{number}.log'),
                                    '-executeMethod', 'StartupDiscoveryAudit.Start'],
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('Unity exited during startup; inspect the session log')
                try:
                    state = json.loads((project / 'audit-status.json').read_text())
                except (OSError, ValueError):
                    state = {}
                if (state.get('pid') == process.pid and state.get('http_running') and
                        not state.get('is_compiling') and not state.get('is_updating') and not state.get('compile_errors')):
                    for file in (Path.home() / '.unity-bridge/instances').glob('*.json'):
                        try:
                            heartbeat = json.loads(file.read_text())
                        except (OSError, ValueError):
                            continue
                        if (heartbeat.get('pid') == process.pid and heartbeat.get('port') == state['port'] and
                                heartbeat.get('state') == 'ready' and
                                heartbeat.get('projectPath', '').casefold() == project.as_posix().casefold() and
                                abs(time.time() * 1000 - heartbeat.get('timestamp', 0)) < 1500):
                            result['heartbeat'] = heartbeat
                            break
                    if 'heartbeat' in result:
                        break
                time.sleep(.05)
            else:
                raise RuntimeError('Unity startup/heartbeat timeout')
            result['environment'] = state
            executable = (options.candidate_bin if variant == 'candidate' else options.baseline_bin).resolve()

            def call(name, *args):
                start = time.perf_counter()
                response = subprocess.run([str(executable), '--json', '--no-update-check', '--project', str(project), *args],
                                          capture_output=True, text=True, encoding='utf-8', timeout=90)
                row = {'name': name, 'ms': (time.perf_counter() - start) * 1000,
                       'exit_code': response.returncode}
                if response.returncode:
                    row['error'] = response.stderr
                else:
                    row['result'] = json.loads(response.stdout)
                result['calls'].append(row)
                if response.returncode:
                    raise AssertionError(row)
                return row['result']

            for name in ['first_console', 'warm_console_1', 'warm_console_2']:
                response = call(name, 'console', '--count', '1', '--type', 'error')
                assert response['success'] and response.get('data') == [], response

            def check_versions(suffix):
                for command in ['status', 'wait-ready']:
                    response = call(command + suffix, command)
                    assert response['connectorVersion'] == expected_version, response
                # Also check the human-readable line reported in the RC1 regression.
                text_status = subprocess.run([str(executable), '--no-update-check', '--project', str(project), 'status'],
                                             capture_output=True, text=True, encoding='utf-8', timeout=30)
                assert text_status.returncode == 0, text_status.stderr
                assert f' Connector: {expected_version}' in text_status.stdout, text_status.stdout
                result['status_text' + suffix] = text_status.stdout

            check_versions('_before_reload')
            if variant == 'candidate':
                response = call('discovery_checks', 'call', 'startup_discovery_audit')
                assert response['success'], response
                old_domain = response['data']['domain']
                (editor / 'StartupRevision.cs').write_text('public static class StartupRevision { public const int Value = 1; }\n')
                response = call('refresh_reload', 'refresh', '--compile', 'request', '--wait')
                assert response['success'], response
                response = call('after_reload_checks', 'call', 'startup_discovery_audit')
                assert response['success'] and response['data']['domain'] != old_domain, response
                assert response['data']['revision'] == 1, response
                check_versions('_after_reload')
                expected_schemas = response['data']['schemas']
                response = call('exec_after_reload', 'exec', '--code', 'return 1 + 2;')
                assert response['success'] and response['data'] == 3, response
                response = call('list_after_exec', 'tools')
                assert response['success'] and len(response['data']) == expected_schemas, response
                assert any(tool['name'] == 'startup_discovery_audit' for tool in response['data']), response
            result['passed'] = True
        finally:
            (project / 'audit-stop').write_text('complete')
            try:
                result['unity_exit_code'] = process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.terminate()
                result['forced_stop'] = True
                result['unity_exit_code'] = process.wait(timeout=10)
            save(output / f'session-{number}.json', result)
        results.append(result)
        print(json.dumps({'variant': variant, 'session': number, 'passed': result['passed'],
                          'calls': [{k: v for k, v in row.items() if k != 'result'} for row in result['calls']]}), flush=True)
    save(output / 'results.json', results)


if __name__ == '__main__':
    main()
