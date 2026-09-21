import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from tests import test_host_service as fixtures
from unity_bridge.client import CommandResponse
from unity_bridge.host.pipeline import PipelineConnection
from unity_bridge.host.transport import TransportError

ROOT = Path(__file__).resolve().parents[1]


class PipelineSessionTests(unittest.TestCase):
    setUp = fixtures.HostServiceTests.setUp
    publish_snapshot = fixtures.HostServiceTests.publish_snapshot
    instance = fixtures.HostServiceTests.instance
    stop_host = fixtures.HostServiceTests.stop_host

    def start(self, pipeline=4):
        process = subprocess.Popen([sys.executable, '-B', '-m', 'unity_bridge', '--json',
                                    '--instances-dir', str(self.instances), '--project', self.project_path,
                                    'session', '--pipeline', str(pipeline)], cwd=ROOT,
                                   env=dict(os.environ, PYTHONPATH=str(ROOT / 'src'), UNITY_BRIDGE_SKIP_UPDATE_CHECK='1'),
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8')
        def cleanup():
            if process.poll() is None:
                process.kill()
                process.wait(5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        self.addCleanup(cleanup)
        return process

    def run_requests(self, argv, pipeline=4):
        process = self.start(pipeline)
        raw = '\n'.join(json.dumps({'id': i, 'args': args}) for i, args in enumerate(argv)) + '\n'
        out, err = process.communicate(raw, timeout=15)
        self.assertEqual(err, '')
        return process.returncode, [json.loads(line) for line in out.splitlines()]

    def test_pipeline_matches_sequential_jsonl_and_preserves_all_order(self):
        commands = [['exec', '--code', 'return 7;', '--using', 'System', '--using', 'System.Text'],
                    ['exec', '--code', 'return 8;'], ['console'], ['exec', '--code', 'return 9;']]
        sequential = self.run_requests(commands, 1)
        self.executed.clear()
        pipelined = self.run_requests(commands, 4)
        self.assertEqual(pipelined, sequential)
        self.assertTrue(all(item['exit_code'] == 0 for item in pipelined[1]))
        self.assertEqual(self.executed, ['return 7;', 'return 8;', 'console', 'return 9;'])

    def test_pipeline_flushes_single_request_before_eof_and_bad_input_recovers(self):
        process = self.start()
        lines = queue.Queue()
        def read():
            for line in process.stdout:
                lines.put(json.loads(line))
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        for raw, code in [('{bad}', 2), (json.dumps({'id': 1, 'args': ['exec', '--code', 'first']}), 0),
                          (json.dumps({'id': 2, 'args': ['exec', '--stdin']}), 2)]:
            process.stdin.write(raw + '\n')
            process.stdin.flush()
            self.assertEqual(lines.get(timeout=8)['exit_code'], code)
            self.assertIsNone(process.poll())
        process.stdin.close()
        self.assertEqual(process.wait(8), 0)
        reader.join(2)
        self.assertEqual(process.stderr.read(), '')

    def test_normal_barrier_reuses_enqueue_socket_and_receipts_stay_separate(self):
        handler = self.service.server.RequestHandlerClass
        original = handler.do_POST
        observed = []

        def record(request):
            observed.append((request.path, request.client_address))
            return original(request)

        with patch.object(handler, 'do_POST', record):
            code, responses = self.run_requests([['exec', '--code', 'first'], ['console'],
                                                 ['exec', '--code', 'last']])
        self.assertEqual(code, 0)
        self.assertTrue(all(item['exit_code'] == 0 for item in responses))
        submissions = [address for path, address in observed if path == '/enqueue']
        barriers = [address for path, address in observed if path == '/command']
        receipts = [address for path, address in observed if path == '/result']
        self.assertEqual(len(submissions), 2)
        self.assertEqual(barriers, [submissions[0]])
        self.assertEqual(submissions[0], submissions[1])
        self.assertTrue(receipts)
        self.assertTrue(all(address != submissions[0] for address in receipts))

    def test_file_read_is_a_barrier_after_preceding_execution(self):
        source = self.directory / 'created.cs'
        original = self.service._post
        def create(snapshot, payload, timeout, lane='execute'):
            if payload['command'] == 'bridge_exec_assembly' and not source.exists():
                source.write_text('second', encoding='utf-8')
            return original(snapshot, payload, timeout, lane)
        with patch.object(self.service, '_post', side_effect=create):
            code, responses = self.run_requests([['exec', '--code', 'create-file'],
                                                 ['exec', '--code-file', str(source)], ['exec', '--code', 'third']])
        self.assertEqual(code, 0)
        self.assertTrue(all(item['exit_code'] == 0 for item in responses))
        self.assertEqual(self.executed, ['create-file', 'second', 'third'])

    def test_pipeline_window_bounds_admission_and_expires_queued_commands(self):
        self.compiler.release.clear()
        process = self.start(2)
        requests = [{'id': i, 'args': ['--timeout-ms', '10000' if i == 0 else '1000', 'exec', '--code', str(i)]}
                    for i in range(6)]
        process.stdin.write(json.dumps(requests[0]) + '\n')
        process.stdin.flush()
        project = self.service._project_list()[0]
        try:
            self.assertTrue(self.compiler.started.wait(4))
            process.stdin.write(''.join(json.dumps(item) + '\n' for item in requests[1:]))
            process.stdin.flush()
            fixtures.eventually(lambda: len(project.jobs) == 2)
            self.assertEqual(len(project.jobs), 2)
            # Wait for the actual admitted deadline, independent of startup speed.
            import time
            second = next(job for job in project.jobs.values() if job.payload['params']['code'] == '1')
            threading.Event().wait(max(0., second.deadline - time.perf_counter()) + .03)
        finally:
            self.compiler.release.set()
        process.stdin.close()
        responses = [json.loads(process.stdout.readline()) for _ in requests]
        self.assertEqual(process.wait(8), 0)
        self.assertEqual(process.stderr.read(), '')
        self.assertEqual(responses[1]['result']['data']['completion'], 'not_started')
        self.assertNotIn('1', self.executed)
        self.assertEqual([item['id'] for item in responses], list(range(6)))

    def test_old_host_capability_falls_back_before_submission(self):
        from unity_bridge.host.registry import atomic_json, endpoint_path
        registry = dict(self.service.last_registry)
        registry.pop('pipelineProtocol')
        atomic_json(endpoint_path(self.root, self.descriptor['runtimeId']), registry)
        code, responses = self.run_requests([['exec', '--code', 'old-host']])
        self.assertEqual(code, 0)
        self.assertEqual(responses[0]['exit_code'], 0)
        self.assertEqual(self.executed, ['old-host'])
        self.assertTrue(all('pipeline_id' not in job.payload for job in self.service._project_list()[0].jobs.values()))

    def test_lost_response_stops_pipeline_without_replay(self):
        self.drop_response = True
        code, responses = self.run_requests([['exec', '--code', str(i)] for i in range(12)])
        self.assertEqual(code, 1)
        self.assertEqual(responses[0]['result']['data']['completion'], 'unknown')
        self.assertEqual(self.executed, ['0'])
        self.assertLessEqual(len(responses), 4)

    def test_unknown_completion_exits_even_when_interactive_stdin_remains_open(self):
        self.drop_response = True
        process = self.start()
        process.stdin.write(json.dumps({'id': 1, 'args': ['exec', '--code', 'once']}) + '\n')
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        self.assertEqual(response['result']['data']['completion'], 'unknown')
        self.assertEqual(process.wait(8), 1)
        self.assertEqual(process.stderr.read(), '')
        self.assertEqual(self.executed, ['once'])


class PipelineTransportTests(unittest.TestCase):
    def test_lost_enqueue_ack_is_unknown_and_never_retries(self):
        target = type('Target', (), dict(project_path='fixture', pid=123, port=456,
                                         domain_id='domain', reference_generation=1))()
        connection = PipelineConnection({'runtimeId': 'fixture'}, {'pid': 789}, target, None)
        with patch.object(connection, 'exchange', side_effect=TransportError('lost')) as exchange:
            ticket = connection.enqueue({'code': 'once'}, 'group', 2000)
            self.assertTrue(ticket.wait().completion_unknown)
            self.assertEqual(exchange.call_count, 1)


if __name__ == '__main__':
    unittest.main()
