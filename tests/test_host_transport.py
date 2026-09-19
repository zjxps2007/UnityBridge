from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import ssl
import threading
import unittest
from unittest.mock import patch

from unity_bridge.host.transport import ConnectionPool, TransportError, post


class HostTransportTests(unittest.TestCase):
    def setUp(self):
        fixture = self
        self.requests = []
        self.connections = []
        self.drop_response = False
        self.blocked = threading.Event()
        self.release = threading.Event()
        self.reply_status = 200
        self.reply_body = b'{"success":true,"message":"fixture"}'

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            disable_nagle_algorithm = True
            def log_message(self, *args):
                pass

            def handle(self):
                try:
                    super().handle()
                except ConnectionError:
                    pass  # A non-200 fixture response is deliberately discarded.

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fixture.requests.append((self.path, self.headers.get('X-UnityBridge-Token'), body))
                fixture.connections.append(self.client_address)
                if body.get('block'):
                    fixture.blocked.set()
                    fixture.release.wait(3)
                if fixture.drop_response:
                    self.close_connection = True
                    return
                self.send_response(fixture.reply_status)
                if fixture.reply_status == 302:
                    self.send_header('Location', f'http://127.0.0.1:{self.server.server_port}/redirected')
                self.send_header('Content-Length', str(len(fixture.reply_body)))
                self.end_headers()
                self.wfile.write(fixture.reply_body)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.release.set)

    def pool(self):
        pool = ConnectionPool()
        self.addCleanup(pool.close)
        return pool

    def pooled(self, pool, *, key='execution', identity='domain-one', timeout=2, body=None):
        return post(self.server.server_port, 'private-token', '/command', body or {}, timeout,
                    pool=pool, key=key, identity=identity)

    def test_connection_reuse_and_generation_change(self):
        pool = self.pool()
        for _ in range(3):
            self.assertTrue(self.pooled(pool)['success'])
        self.assertEqual(len(set(self.connections)), 1)
        self.assertTrue(self.pooled(pool, identity='domain-two')['success'])
        self.assertEqual(len(set(self.connections)), 2)

    def test_lost_pooled_response_is_never_replayed(self):
        pool = self.pool()
        self.pooled(pool)
        self.drop_response = True
        with self.assertRaises(TransportError):
            self.pooled(pool, body={'mutation': True})
        self.assertEqual(len(self.requests), 2)
        self.drop_response = False
        self.assertTrue(self.pooled(pool)['success'])
        self.assertEqual(len(self.requests), 3)

    def test_control_connection_bypasses_busy_execution_and_expired_waiter(self):
        from concurrent.futures import ThreadPoolExecutor
        pool = self.pool()
        with ThreadPoolExecutor(max_workers=1) as executor:
            execution = executor.submit(self.pooled, pool, body={'block': True})
            try:
                self.assertTrue(self.blocked.wait(2))
                self.assertTrue(self.pooled(pool, key='control', timeout=.5)['success'])
                with self.assertRaises(TransportError):
                    self.pooled(pool, timeout=.02)
                self.assertEqual(len(self.requests), 2)
                pool.close()  # Retiring a live connection must not abort its result.
            finally:
                self.release.set()
            self.assertTrue(execution.result(timeout=2)['success'])

    def test_loopback_request_never_initializes_https_or_certificate_store(self):
        with patch.object(ssl, '_create_default_https_context', side_effect=AssertionError('HTTPS must not initialize')) as tls:
            result = post(self.server.server_port, 'private-token', '/health', {}, 1)
        self.assertTrue(result['success'])
        tls.assert_not_called()
        self.assertEqual(self.requests, [('/health', 'private-token', {})])

    def test_environment_proxies_cannot_intercept_loopback_credentials(self):
        proxy = 'http://127.0.0.1:1'
        with patch.dict(os.environ, {'HTTP_PROXY': proxy, 'HTTPS_PROXY': proxy, 'ALL_PROXY': proxy,
                                     'http_proxy': proxy, 'https_proxy': proxy, 'all_proxy': proxy,
                                     'NO_PROXY': '', 'no_proxy': ''}):
            self.assertTrue(post(self.server.server_port, 'private-token', '/health', {}, 1)['success'])
        self.assertEqual(len(self.requests), 1)

    def test_redirect_response_is_rejected_without_forwarding_credentials(self):
        self.reply_status = 302
        with self.assertRaises(TransportError):
            post(self.server.server_port, 'private-token', '/command', {}, 1)
        self.assertEqual([request[0] for request in self.requests], ['/command'])

    def test_oversized_and_invalid_json_responses_are_rejected(self):
        with patch('unity_bridge.host.transport.MAX_MESSAGE_BYTES', 8):
            with self.assertRaises(TransportError):
                post(self.server.server_port, 'private-token', '/health', {}, 1)
        self.reply_body = b'not json'
        with self.assertRaises(TransportError):
            post(self.server.server_port, 'private-token', '/health', {}, 1)


if __name__ == '__main__':
    unittest.main()
