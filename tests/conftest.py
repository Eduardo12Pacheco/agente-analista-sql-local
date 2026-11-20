"""Shared pytest configuration: deterministic hypothesis and network isolation."""

from __future__ import annotations

import socket
from typing import Any

import pytest
from hypothesis import settings

settings.register_profile("ci", max_examples=200, derandomize=True)
settings.load_profile("ci")


@pytest.fixture(autouse=True)
def block_non_loopback_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail fast when a test opens a non-loopback socket (D29).

    Loopback stays available for e2e servers started on ephemeral ports.
    Unix-domain and in-process connections are unaffected.
    """

    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        if self.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple):
            host = address[0]
            loopback = {"127.0.0.1", "::1", "localhost"}
            if host not in loopback:
                raise RuntimeError(f"network access blocked in tests: {host!r}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
