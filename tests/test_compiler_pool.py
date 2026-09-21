import threading
import time
import unittest

from unity_bridge.host.compiler_pool import CompilerPool
from tests.test_host_service import eventually


class Worker:
    def __init__(self, executable, environment=None):
        self.last_info = {}
        self.calls = []
        self.closed = False
        self.ready = threading.Event()
        self.ready.set()

    def start(self):
        pass

    def warmup(self):
        self.ready.wait(3)

    def request(self, payload, *, deadline, background=False):
        if self.closed:
            raise AssertionError('A retired worker must never receive work')
        self.calls.append(dict(payload))
        return {'success': True}

    def close(self):
        self.closed = True


class CompilerPoolTests(unittest.TestCase):
    def test_cold_secondary_never_receives_foreground_and_idle_retirement_is_safe(self):
        workers = []
        def factory(*args, **kwargs):
            worker = Worker(*args, **kwargs)
            if workers:
                worker.ready.clear()
            workers.append(worker)
            return worker
        pool = CompilerPool('fixture', worker_factory=factory, idle_seconds=.05)
        payload = dict(operation='compile', code='real', references=[], reference_generation='generation',
                       project_id='project', language_version='9.0')
        try:
            pool.request(payload, deadline=time.perf_counter() + 3)
            eventually(lambda: len(workers) == 2)
            pool.request(dict(payload, code='foreground'), deadline=time.perf_counter() + 3)
            pool.request(dict(payload, code='cold-lookahead'), deadline=time.perf_counter() + 3, background=True)
            self.assertEqual(workers[1].calls, [])
            workers[1].ready.set()
            eventually(lambda: pool.ready_key is not None)
            pool.request(dict(payload, code='ready-lookahead'), deadline=time.perf_counter() + 3, background=True)
            self.assertEqual([p['code'] for p in workers[1].calls], ['return null;', 'ready-lookahead'])
            self.assertEqual([p['code'] for p in workers[0].calls], ['real', 'foreground', 'cold-lookahead'])
            eventually(lambda: workers[1].closed)
            self.assertIsNone(pool.secondary)
            pool.request(payload, deadline=time.perf_counter() + 3)
            eventually(lambda: len(workers) == 3)
            self.assertFalse(workers[0].closed)
        finally:
            for worker in workers:
                worker.ready.set()
            pool.close()
        self.assertTrue(all(worker.closed for worker in workers))

    def test_close_waits_for_preparation_then_reaps_only_owned_workers(self):
        workers = []
        def factory(*args, **kwargs):
            worker = Worker(*args, **kwargs)
            if workers:
                worker.ready.clear()
            workers.append(worker)
            return worker
        pool = CompilerPool('fixture', worker_factory=factory)
        pool.request(dict(operation='compile', code='real'), deadline=time.perf_counter() + 3)
        closed = threading.Event()
        thread = threading.Thread(target=lambda: (pool.close(), closed.set()), daemon=True)
        thread.start()
        self.assertFalse(closed.wait(.03))
        workers[1].ready.set()
        thread.join(3)
        self.assertTrue(closed.is_set())
        self.assertTrue(all(worker.closed for worker in workers))


if __name__ == '__main__':
    unittest.main()
