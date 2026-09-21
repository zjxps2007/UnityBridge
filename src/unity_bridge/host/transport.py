"""Private loopback JSON transport. Never follow redirects or inherit proxies."""
from __future__ import annotations

import http.client
import json
import os
import select
import threading
import time
from collections import OrderedDict
from typing import Any

from .._loopback_http import LoopbackHTTPConnection

MAX_MESSAGE_BYTES = 32 * 1024 * 1024


class TransportError(Exception):
    pass


def _exchange(connection, token, path, payload, timeout):
    connection.timeout = max(.001, timeout)
    if connection.sock is not None:
        connection.sock.settimeout(connection.timeout)
    connection.request("POST", path, body=json.dumps(payload).encode("utf-8"),
                       headers={"Content-Type": "application/json", "X-UnityBridge-Token": token})
    response = connection.getresponse()
    try:
        if response.status != 200:
            raise TransportError("Local endpoint did not accept the request")
        raw = response.read(MAX_MESSAGE_BYTES + 1)
        if not raw or len(raw) > MAX_MESSAGE_BYTES:
            raise TransportError("Local endpoint returned an empty or oversized response")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise TransportError("Local endpoint returned an invalid response")
        return value
    finally:
        response.close()


class _Entry:
    def __init__(self, port, identity):
        self.identity = identity
        self.connection = LoopbackHTTPConnection(port)
        self.lock = threading.Lock()
        self.retired = False
        self.used_at = 0.

    def retire(self):
        self.retired = True
        if self.lock.acquire(blocking=False):
            try:
                self.connection.close()
            finally:
                self.lock.release()


class ConnectionPool:
    """Bounded, serialized connections per logical lane and endpoint generation.

    A failed exchange is never retried. Retiring a busy connection closes it
    after its response, so discovery cannot interrupt an in-flight operation.
    """
    def __init__(self, capacity=32):
        self.capacity = capacity
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def close(self):
        with self.lock:
            entries, self.entries = self.entries, OrderedDict()
        for entry in entries.values():
            entry.retire()

    def post(self, port, token, path, payload, timeout, key, identity):
        deadline = time.perf_counter() + timeout
        identity = (port, token, identity)
        with self.lock:
            entry = self.entries.pop(key, None)
            if entry is not None and entry.identity != identity:
                entry.retire()
                entry = None
            if entry is None:
                entry = _Entry(port, identity)
            self.entries[key] = entry
            while len(self.entries) > self.capacity:
                _, oldest = self.entries.popitem(last=False)
                oldest.retire()
        remaining = deadline - time.perf_counter()
        if remaining <= 0 or not entry.lock.acquire(timeout=max(0., remaining)):
            raise TransportError("Local request expired while waiting for its connection")
        try:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise TransportError("Local request expired before transmission")
            sock = entry.connection.sock
            # A closed idle socket is safe to replace BEFORE writing this request.
            # Never replay a request after request()/sendall() has been attempted.
            if sock is not None and (time.perf_counter() - entry.used_at > 2.
                                     or select.select([sock], [], [], 0)[0]):
                entry.connection.close()
            return _exchange(entry.connection, token, path, payload, remaining)
        except (OSError, ValueError, http.client.HTTPException, TransportError):
            entry.connection.close()
            raise
        finally:
            entry.used_at = time.perf_counter()
            if entry.retired:
                entry.connection.close()
            entry.lock.release()


def post(port: int, token: str, path: str, payload: dict[str, Any], timeout: float,
         *, pool: ConnectionPool | None = None, key=None, identity=None) -> dict[str, Any]:
    if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
        raise TransportError("Invalid local endpoint")
    if path not in {"/command", "/health", "/stop", "/changed", "/enqueue", "/result", "/cancel"}:
        raise TransportError("Invalid local operation")
    # The destination is always a fixed loopback HTTP endpoint. Generic urllib
    # openers also initialize HTTPS and the Windows certificate store, even for
    # these HTTP-only calls; doing that per forward adds avoidable startup work.
    # HTTPConnection neither consults proxy settings nor follows redirects.
    connection = None
    try:
        if pool is not None and os.environ.get("UNITY_BRIDGE_DISABLE_CONNECTION_REUSE") != "1":
            return pool.post(port, token, path, payload, timeout, key, identity)
        connection = LoopbackHTTPConnection(port)
        return _exchange(connection, token, path, payload, timeout)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise TransportError("Local endpoint did not return a complete valid response") from exc
    finally:
        if connection is not None:
            connection.close()
