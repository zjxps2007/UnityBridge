"""Bounded, length-prefixed loopback frames; no HTTP/parser imports at CLI startup."""
import time

MAX_MESSAGE_BYTES = 32 * 1024 * 1024


def read_frame(connection, deadline):
    def read_exact(count):
        chunks = bytearray()
        while len(chunks) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Local request deadline expired")
            connection.settimeout(remaining)
            chunk = connection.recv(min(count - len(chunks), 65536))
            if not chunk:
                raise OSError("Local connection ended before a complete response")
            chunks.extend(chunk)
        return bytes(chunks)
    length = int.from_bytes(read_exact(4), "big")
    if not 0 < length <= MAX_MESSAGE_BYTES:
        raise ValueError("Invalid local frame size")
    return read_exact(length)


def write_frame(connection, data, deadline):
    if not 0 < len(data) <= MAX_MESSAGE_BYTES:
        raise ValueError("Invalid local frame size")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Local request deadline expired")
    connection.settimeout(remaining)
    connection.sendall(len(data).to_bytes(4, "big") + data)
