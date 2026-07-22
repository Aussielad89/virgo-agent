"""
virgo_fingerprinter — banner grabber for local services.

Connects to 127.0.0.1:11434 (Ollama default), sends a basic HTTP GET,
and prints the first 3 lines of the response headers/banner.
"""

from __future__ import annotations

import os
import socket
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _console import icon

TARGET_HOST = "127.0.0.1"
TARGET_PORT = 11434
TIMEOUT = 3


def grab_banner(
    host: str = TARGET_HOST,
    port: int = TARGET_PORT,
    timeout: int = TIMEOUT,
) -> list[str]:
    """Connect to *host*:*port*, send an HTTP GET, and return response lines.

    Returns up to 3 lines of the server's response.  If the connection
    fails or times out an empty list is returned.
    """
    print(f"{icon('antenna')} Connecting to {host}:{port} ...")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)

    try:
        sock.connect((host, port))
    except (TimeoutError, ConnectionRefusedError, OSError) as exc:
        sock.close()
        print(f"{icon('error')} Connection failed: {exc}")
        return []

    # Send a minimal HTTP/1.1 GET so Ollama responds with headers
    request = b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
    try:
        sock.sendall(request)
    except OSError as exc:
        sock.close()
        print(f"{icon('error')} Send failed: {exc}")
        return []

    # Read response until we have at least 3 lines or connection closes
    buffer = b""
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
            if buffer.count(b"\n") >= 3:
                break
    except (TimeoutError, OSError) as exc:
        print(f"{icon('warn')} Read interrupted: {exc}")
    finally:
        sock.close()

    if not buffer:
        print(f"{icon('warn')} No data received from {host}:{port}")
        return []

    # Decode and split into lines
    text = buffer.decode("utf-8", errors="replace")
    lines = [line.rstrip("\r\n") for line in text.splitlines() if line.strip()]

    return lines[:3]


def run_fingerprinter() -> None:
    """Main entry point — grab and print the Ollama banner."""
    print(f"\n{icon('tool')} Virgo Service Fingerprinter")
    print("-" * 40)

    lines = grab_banner()

    if lines:
        print(f"\n{icon('ok')} Banner received (first {len(lines)} line(s)):\n")
        for i, line in enumerate(lines, 1):
            print(f"  {i}. {line}")
    else:
        print(
            f"\n{icon('info')} No banner captured. Is Ollama running on {TARGET_HOST}:{TARGET_PORT}?"
        )

    print()


if __name__ == "__main__":
    run_fingerprinter()
    input("\n[PRESS ENTER TO RETURN]")
