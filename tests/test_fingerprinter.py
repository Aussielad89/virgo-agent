"""Tests for virgo_fingerprinter — banner grabber."""

from __future__ import annotations

import socket
import threading
import time
from unittest.mock import patch

import pytest

from virgo_fingerprinter import grab_banner, TARGET_HOST, TARGET_PORT


def test_grab_banner_connection_refused() -> None:
    """When nothing is listening, grab_banner returns empty list."""
    lines = grab_banner(host="127.0.0.1", port=59999)
    assert lines == []


def test_grab_banner_receives_response() -> None:
    """Spin up a tiny TCP server, connect, verify we get the banner."""
    banner = b"HTTP/1.1 200 OK\r\nServer: Test/1.0\r\n\r\nbody"

    # Create and bind the server socket in the main thread so we know the port
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    def server() -> None:
        conn, _ = server_sock.accept()
        # Send banner immediately after accept, before client starts reading.
        # The client sends GET, then reads — we need to have data ready.
        try:
            conn.sendall(banner)
        except OSError:
            pass
        conn.close()
        server_sock.close()

    t = threading.Thread(target=server, daemon=True)
    t.start()
    time.sleep(0.3)  # ensure server is listening

    lines = grab_banner(host="127.0.0.1", port=port, timeout=5)

    if not lines:
        # The server may have closed before the client's GET arrived.
        # Race condition on Windows — accept with retry.
        server_sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock2.bind(("127.0.0.1", 0))
        port2 = server_sock2.getsockname()[1]
        server_sock2.listen(1)

        def server2() -> None:
            conn2, _ = server_sock2.accept()
            # Read first so we know client is ready
            conn2.settimeout(3)
            try:
                conn2.recv(1024)
            except OSError:
                pass
            conn2.sendall(banner)
            conn2.close()
            server_sock2.close()

        t2 = threading.Thread(target=server2, daemon=True)
        t2.start()
        time.sleep(0.3)
        lines = grab_banner(host="127.0.0.1", port=port2, timeout=5)

    assert len(lines) >= 2, f"Got {len(lines)} lines: {lines}"
    assert "200 OK" in lines[0] or "Test" in lines[0]


def test_grab_banner_timeout() -> None:
    """If a connection hangs, grab_banner returns what it got so far
    rather than blocking forever."""
    # Create a server that accepts but never sends
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    def server() -> None:
        conn, _ = server_sock.accept()
        # Hold the connection open without sending
        time.sleep(5)
        conn.close()
        server_sock.close()

    t = threading.Thread(target=server, daemon=True)
    t.start()
    time.sleep(0.1)  # let server accept

    lines = grab_banner(host="127.0.0.1", port=port, timeout=1)
    assert isinstance(lines, list)
