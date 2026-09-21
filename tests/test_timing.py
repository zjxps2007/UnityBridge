import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class TimingTests(unittest.TestCase):
    def test_concurrent_diagnostics_preserve_complete_jsonl_records(self):
        with tempfile.TemporaryDirectory() as directory:
            script = '''
from concurrent.futures import ThreadPoolExecutor
from unity_bridge._timing import mark
def emit(worker):
    for index in range(80):
        mark('concurrent', f'{worker}-{index}', parent_request_id='parent')
with ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(emit, range(8)))
'''
            result = subprocess.run([sys.executable, '-B', '-c', script],
                                    env=dict(os.environ, UNITY_BRIDGE_TIMING_DIR=directory),
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(result.stderr, '')
            files = list(Path(directory).glob('*.jsonl'))
            self.assertEqual(len(files), 1)
            events = [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(events), 640)
            self.assertEqual(len({item['request_id'] for item in events}), 640)
            self.assertTrue(all(item['stage'] == 'concurrent' and item['parent_request_id'] == 'parent'
                                for item in events))

    def test_disabled_diagnostics_do_not_import_threading(self):
        env = dict(os.environ)
        env.pop('UNITY_BRIDGE_TIMING_DIR', None)
        result = subprocess.run([sys.executable, '-B', '-c', '''
import sys
before = 'threading' in sys.modules
from unity_bridge._timing import mark
mark('disabled')
assert ('threading' in sys.modules) == before
'''], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
