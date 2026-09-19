"""General fast commands preserve CLI contracts and live readiness semantics."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from tests import test_fast_exec
from unity_bridge.host import cli_server
from unity_bridge.host.cli_request import execute_cli
from unity_bridge.host.registry import atomic_json, endpoint_path, read_json
from unity_bridge._cli.session import SessionExecutor


class GeneralFastCliTests(unittest.TestCase):
    def setUp(self):
        self.harness = test_fast_exec.FastExecTests()
        self.addCleanup(self.harness.doCleanups)
        self.harness.setUp()
        self.fixture = self.harness.fixture

    def test_general_commands_skip_cli_imports_and_match_original_output(self):
        for argv in [('instances',), ('status',), ('tools',),
                     ('console', '--lines', '12', '--type', 'warning', '--stacktrace', 'full'),
                     ('wait-ready', '--timeout-sec', '2')]:
            with self.subTest(argv=argv):
                fast = self.harness.command(*argv, check_imports=True, env={'UNITY_BRIDGE_FAST_SNAPSHOTS': '1'})
                original = self.harness.command(*argv, env={'UNITY_BRIDGE_DISABLE_FAST_CLI': '1'})
                self.assertEqual(fast.returncode, 0, fast.stderr)
                self.assertEqual((fast.returncode, json.loads(fast.stdout), fast.stderr),
                                 (original.returncode, json.loads(original.stdout), original.stderr))

    def test_snapshots_stay_local_by_default_after_tail_latency_gate(self):
        with patch.object(cli_server, 'execute_cli', wraps=execute_cli) as calls:
            for name in ('instances', 'status'):
                result = self.harness.command(name)
                self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.call_count, 0)

    def test_old_capability_list_falls_back_before_new_command_submission(self):
        path = endpoint_path(self.fixture.root, self.fixture.descriptor['runtimeId'])
        endpoint = read_json(path)
        endpoint.pop('cliCommands')
        atomic_json(path, endpoint)
        with patch.object(cli_server, 'execute_cli', wraps=execute_cli) as calls:
            result = self.harness.command('console')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.call_count, 0)
        self.assertEqual(self.fixture.executed, ['console'])

    def test_parser_errors_match_local_cli_and_do_not_execute(self):
        for argv in [('console', '--count', 'invalid'), ('console', '--stacktrace', 'invalid')]:
            fast = self.harness.command(*argv)
            original = self.harness.command(*argv, env={'UNITY_BRIDGE_DISABLE_FAST_CLI': '1'})
            self.assertEqual((fast.returncode, fast.stdout, fast.stderr),
                             (original.returncode, original.stdout, original.stderr))
        self.assertEqual(self.fixture.executed, [])

    def test_console_clear_is_not_replayed_after_lost_response(self):
        with patch.object(cli_server, 'write_frame', side_effect=OSError('lost result')):
            result = self.harness.command('console', '--clear')
        self.assertEqual(json.loads(result.stdout)['data']['completion'], 'unknown')
        self.assertEqual(self.fixture.executed, ['console'])

    def test_session_passes_result_objects_without_rendering_and_reparsing(self):
        executor = SessionExecutor()
        self.addCleanup(executor.close)
        with patch('unity_bridge._cli.session._decode_output', side_effect=AssertionError('result was reparsed')):
            code, value, error = executor.invoke(['--json', '--instances-dir', str(self.fixture.instances), 'console'])
        reference = self.harness.command('console', env={'UNITY_BRIDGE_DISABLE_FAST_CLI': '1'})
        self.assertEqual((code, value, error), (reference.returncode, json.loads(reference.stdout), None))

    def test_host_entry_does_not_load_regular_cli(self):
        root = Path(__file__).resolve().parents[1]
        code = """import sys
from unity_bridge._bootstrap import main
try:
    main(['_host', '--help'])
except SystemExit as error:
    assert error.code == 0
assert 'unity_bridge.cli' not in sys.modules
assert 'unity_bridge._cli.output' not in sys.modules
"""
        result = subprocess.run([sys.executable, '-c', code], env=dict(os.environ, PYTHONPATH=str(root / 'src')),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
