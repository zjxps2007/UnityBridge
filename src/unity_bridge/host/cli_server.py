"""Private framed CLI transport; shares the service's authenticated execution queue."""
import hmac
import json
import socket
from socketserver import BaseRequestHandler, ThreadingTCPServer
import time

from .._wire import read_frame, write_frame
from .cli_request import execute_cli


def create_cli_server(service):
    class Handler(BaseRequestHandler):
        def handle(self):
            self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                payload = json.loads(read_frame(self.request, time.monotonic() + 5))
                if not isinstance(payload, dict):
                    return
                token = payload.pop("token", None)
                if (not isinstance(token, str) or not token.isascii()
                        or not hmac.compare_digest(token, service.descriptor["token"])):
                    response = {"cli_protocol": 1, "exit_code": 1, "stdout": "", "stderr": "ERROR: Host authentication required.\n"}
                elif service.stopping.is_set():
                    response = {"cli_protocol": 1, "exit_code": 1, "stdout": "", "stderr": "ERROR: Host is stopping.\n"}
                else:
                    response = execute_cli(service, payload)
                write_frame(self.request, json.dumps(response, ensure_ascii=False).encode("utf-8"), time.monotonic() + 5)
            except (OSError, ValueError):
                # A disconnected caller may have lost an execution result. Never
                # resubmit its command or leak request contents to diagnostic logs.
                return

    class Server(ThreadingTCPServer):
        daemon_threads = True
        block_on_close = False

    return Server(("127.0.0.1", 0), Handler)
