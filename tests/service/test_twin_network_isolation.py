"""The hosted twin lane must reject non-loopback sockets."""

from __future__ import annotations

import os
import socket

import pytest
from pytest_socket import SocketConnectBlockedError


def test_hosted_socket_guard_blocks_non_loopback():
    if os.environ.get("TWIN_SOCKET_GUARD") != "1":
        return
    with socket.socket() as sock:
        sock.settimeout(0.01)
        with pytest.raises(SocketConnectBlockedError):
            sock.connect(("192.0.2.1", 9))
