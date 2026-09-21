"""Standard HTTP parsing with a numeric IPv4-only connection setup."""
from http.client import HTTPConnection
import socket


class LoopbackHTTPConnection(HTTPConnection):
    def __init__(self, port, *, timeout=None):
        super().__init__('127.0.0.1', port, timeout=timeout)

    def connect(self):
        # No DNS, IDNA, proxy, tunnel or TLS is involved in this private endpoint.
        # Keep the standard library's HTTP framing and response validation.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.connect(('127.0.0.1', self.port))
        except BaseException:
            sock.close()
            raise
        self.sock = sock
