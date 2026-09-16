"""Private loopback JSON transport. Never follow redirects or inherit proxies."""
from __future__ import annotations

import http.client
import json
from typing import Any

MAX_MESSAGE_BYTES = 32 * 1024 * 1024


class TransportError(Exception):
    pass


def post(port: int, token: str, path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
        raise TransportError("Invalid local endpoint")
    if path not in {"/command", "/health", "/stop"}:
        raise TransportError("Invalid local operation")
    # The destination is always a fixed loopback HTTP endpoint. Generic urllib
    # openers also initialize HTTPS and the Windows certificate store, even for
    # these HTTP-only calls; doing that per forward adds avoidable startup work.
    # HTTPConnection neither consults proxy settings nor follows redirects.
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=max(.001, timeout))
    try:
        connection.request("POST", path, body=json.dumps(payload).encode("utf-8"),
                           headers={"Content-Type": "application/json", "X-UnityBridge-Token": token})
        response = connection.getresponse()
        if response.status != 200:
            raise TransportError("Local endpoint did not accept the request")
        raw = response.read(MAX_MESSAGE_BYTES + 1)
        if not raw or len(raw) > MAX_MESSAGE_BYTES:
            raise TransportError("Local endpoint returned an empty or oversized response")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise TransportError("Local endpoint returned an invalid response")
        return value
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise TransportError("Local endpoint did not return a complete valid response") from exc
    finally:
        connection.close()
