"""Server state is per process; every test here starts from a fresh connection."""
from __future__ import annotations

import pytest

import aegis_mcp.server as server


@pytest.fixture(autouse=True)
def fresh_server(monkeypatch):
    for name, value in server.fresh_state().items():
        monkeypatch.setattr(server, name, value)
    # Host-attested environment must come only from what a test sets.
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    server._tool_call_times.clear()
    yield
    server._tool_call_times.clear()
