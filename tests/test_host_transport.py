from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import ssl
import threading
import unittest
from unittest.mock import patch

from unity_bridge.host.transport import TransportError, post


class HostTransportTests(unittest.TestCase):
    def setUp(self):
        fixture = self
        self.requests = []
        self.reply_status = 200
        self.reply_body = b'{"success":true,"message":"fixture"}'

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fixture.requests.append((self.path, self.headers.get('X-UnityBridge-Token'), body))
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
