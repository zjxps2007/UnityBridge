"""Temporary heartbeat and loopback HTTP fixtures shared by client and CLI tests."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from unity_bridge import __version__


def write_instance(directory: Path, name: str, **overrides: object) -> Path:
    payload = {
        "state": "ready",
        "projectPath": "D:/UnityProjects/Game",
        "port": 8090,
        "pid": 1234,
        "unityVersion": "6000.0.0f1",
        "connectorVersion": __version__,
        "timestamp": 1_700_000_000_000,
        "compileErrors": False,
    }
    payload.update(overrides)
    path = directory / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class FakeUnityServer:
    def __init__(self, response: bytes, *, status: int = 200) -> None:
        self.received: list[dict[str, object]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                outer.received.append(
                    {
                        "path": urlparse(self.path).path,
                        "content_type": self.headers.get("Content-Type"),
                        "body": json.loads(body.decode("utf-8")),
                    }
                )
                self.send_response(status)
                self.end_headers()
                if response:
                    self.wfile.write(response)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )

    @property
    def port(self) -> int:
        return int(self.server.server_port)

    def __enter__(self) -> "FakeUnityServer":
        self.thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
