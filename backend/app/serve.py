"""
Module: serve

Runs the API as ONE uvicorn process (`BACKEND_WORKERS=1`) on a dual-stack socket.

Responsibilities:
- Bind `::` with `IPV6_V6ONLY` off, so one listener accepts IPv4 and IPv6 clients, and hand it to uvicorn.

Design decisions:
- `uvicorn --host :: --workers 1` serves in-process through asyncio's `create_server`, which sets `IPV6_V6ONLY`
  on the socket it creates: the listener then refuses IPv4, including the container health probe on `127.0.0.1`.
  With two or more workers uvicorn binds the socket itself, dual-stack, which is why only the single-process case
  needs this. Binding the socket here is the supported way to choose the options (`Server.run(sockets=...)`).
- A host without IPv6 falls back to an IPv4 wildcard listener, so the single-process mode still starts there.

External dependencies: uvicorn.
"""

from __future__ import annotations

import socket

import uvicorn

HOST = "::"
PORT = 8000


def bind_dual_stack(host: str = HOST, port: int = PORT) -> socket.socket:
    """Creates the listening socket, accepting IPv4 and IPv6 when the host has IPv6.

    Args:
        host: The address to bind (`::` for every interface).
        port: The TCP port.

    Returns:
        A bound, not yet listening socket (uvicorn starts listening on it).

    Raises:
        OSError: If the port cannot be bound.
    """
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except (OSError, AttributeError):  # no IPv6 support in this kernel
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        host = "0.0.0.0" if host == HOST else host
    else:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    return sock


def main() -> None:
    """Serves `app.main:app` in this process until stopped."""
    sock = bind_dual_stack()
    uvicorn.Server(uvicorn.Config("app.main:app", workers=1)).run(sockets=[sock])


if __name__ == "__main__":
    main()
