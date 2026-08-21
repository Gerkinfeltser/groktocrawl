"""The hosted twin lane must reject non-loopback sockets."""

from __future__ import annotations

import os
import socket

import pytest


def test_hosted_socket_guard_blocks_non_loopback():
    if os.environ.get("TWIN_SOCKET_GUARD") != "1":
        return
    with socket.socket() as sock:
        sock.settimeout(0.01)
        with pytest.raises(RuntimeError) as raised:
            sock.connect(("192.0.2.1", 9))
    assert type(raised.value).__module__ == "pytest_socket"
    assert type(raised.value).__name__ == "SocketConnectBlockedError"
