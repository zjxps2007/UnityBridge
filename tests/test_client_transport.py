"""Legacy loopback wire behavior independent of the optional host service."""
from __future__ import annotations

import json
import os
import ssl
import sys
import threading
import unittest
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity_bridge import Instance, UnityConnectionError, UnityHttpError, send_command
from tests.helpers import FakeUnityServer


def instance(port: int) -> Instance:
    return Instance(state="ready", project_path="/project", port=port, pid=0)


@contextmanager
def interrupting_server(*, redirect: bool):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            received.append((self.command, self.path,
                             self.rfile.read(int(self.headers.get("Content-Length", "0")))))
            if redirect:
                self.send_response(302)
                self.send_header("Location", "/redirected")
                self.end_headers()
                self.wfile.write(b"redirect refused")
            # Otherwise close after accepting the command, without any response.
            self.close_connection = True

        def do_GET(self):  # noqa: N802
            received.append((self.command, self.path, b""))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"success":true,"message":"redirected"}')

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        yield int(server.server_port), received
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


class LegacyTransportTests(unittest.TestCase):
    def test_loopback_command_does_not_initialize_tls_or_use_proxy(self):
        proxy_env = {"http_proxy": "http://127.0.0.1:1", "HTTP_PROXY": "http://127.0.0.1:1",
                     "https_proxy": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1",
                     "no_proxy": "", "NO_PROXY": ""}
        with FakeUnityServer(b'{"success":true,"message":"ok"}') as server, \
                patch.dict(os.environ, proxy_env), \
                patch.object(urllib.request, "_opener", None), \
                patch.object(ssl, "_create_default_https_context", side_effect=AssertionError("TLS initialized")):
            result = send_command(instance(server.port), "exec", {"code": "return 1;"})
        self.assertTrue(result.success)
        self.assertEqual(len(server.received), 1)
        self.assertEqual(server.received[0]["body"], {"command": "exec", "params": {"code": "return 1;"}})

    def test_all_success_statuses_retain_response_parsing(self):
        for status in (200, 201, 202, 206, 299):
            with self.subTest(status=status), FakeUnityServer(b'{"success":true,"message":"ok"}', status=status) as server:
                self.assertTrue(send_command(instance(server.port), "list").success)

    def test_empty_204_response_retains_unknown_completion(self):
        with FakeUnityServer(b"", status=204) as server:
            result = send_command(instance(server.port), "editor")
        self.assertTrue(result.success)
        self.assertTrue(result.completion_unknown)
        self.assertEqual(result.data, {"accepted": True, "completion": "unknown",
                                      "connection_closed": True, "command": "editor"})

    def test_non_object_json_retains_plain_text_semantics(self):
        for raw in (b"null", b"true", b'["item", 1]', b'"message"', b"invalid\xff"):
            with self.subTest(raw=raw), FakeUnityServer(raw) as server:
                result = send_command(instance(server.port), "custom")
                self.assertTrue(result.success)
                self.assertEqual(result.message, raw.decode("utf-8", errors="replace"))
                self.assertIsNone(result.data)

    def test_falsey_params_are_not_replaced(self):
        for params in (False, 0, [], ""):
            with self.subTest(params=params), FakeUnityServer(b'{"success":true}') as server:
                send_command(instance(server.port), "custom", params)
                self.assertEqual(server.received[0]["body"]["params"], params)

    def test_http_errors_preserve_status_body_and_command(self):
        for status, body in ((400, b"invalid request"), (503, b"unavailable\xff"), (500, b"")):
            with self.subTest(status=status), FakeUnityServer(body, status=status) as server:
                with self.assertRaises(UnityHttpError) as error:
                    send_command(instance(server.port), "console")
                self.assertEqual(error.exception.status_code, status)
                self.assertEqual(error.exception.body, body.decode("utf-8", errors="replace"))
                self.assertEqual(error.exception.command, "console")
                self.assertEqual(str(error.exception), error.exception.body or f"HTTP {status} from Unity (command: console)")
                self.assertEqual(len(server.received), 1)

    def test_redirect_is_rejected_without_another_request(self):
        with interrupting_server(redirect=True) as (port, received):
            with self.assertRaises(UnityHttpError) as error:
                send_command(instance(port), "exec", {"code": "return 1;"})
            self.assertEqual(error.exception.status_code, 302)
            self.assertEqual(error.exception.body, "redirect refused")
            self.assertEqual([(method, path) for method, path, _ in received], [("POST", "/command")])

    def test_response_disconnect_is_not_replayed(self):
        with interrupting_server(redirect=False) as (port, received):
            with self.assertRaises(UnityConnectionError) as error:
                send_command(instance(port), "exec", {"code": "return 1;"})
            self.assertIn(f"cannot connect to Unity at port {port}", str(error.exception))
            self.assertEqual(len(received), 1)
            self.assertEqual(json.loads(received[0][2]), {"command": "exec", "params": {"code": "return 1;"}})


if __name__ == "__main__":
    unittest.main()
