"""Private loopback JSON transport. Never follow redirects or inherit proxies."""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from typing import Any

MAX_MESSAGE_BYTES = 32 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TransportError(Exception):
    pass


def post(port: int, token: str, path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
        raise TransportError("Invalid local endpoint")
    if path not in {"/command", "/health", "/stop"}:
        raise TransportError("Invalid local operation")
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                     data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json"})
    request.add_unredirected_header("X-UnityBridge-Token", token)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=max(.001, timeout)) as response:
            raw = response.read(MAX_MESSAGE_BYTES + 1)
        if not raw or len(raw) > MAX_MESSAGE_BYTES:
            raise TransportError("Local endpoint returned an empty or oversized response")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise TransportError("Local endpoint returned an invalid response")
        return value
    except (OSError, ValueError, http.client.HTTPException, urllib.error.URLError) as exc:
        raise TransportError("Local endpoint did not return a complete valid response") from exc
