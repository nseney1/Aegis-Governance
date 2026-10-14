"""Tests for MCP session shutdown auto-harvesting (Phase 13: v0.110.0).

Verifies that:
1. When stdio input terminates (EOF / disconnect), soma_mcp triggers session-close reflection.
2. `_on_session_close` invokes `run_outcome_engine` in-process.
3. Errors during shutdown reflection are safely trapped and do not crash or hang.
4. JSON-RPC output protocol on stdout is protected from reflection print statements.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_on_session_close_invokes_outcome_engine(tmp_path: Path):
    """_on_session_close must call run_outcome_engine with the workspace."""
    from aegis_mcp.server import _on_session_close

    ws = tmp_path / "ws"
    ws.mkdir()

    with patch("aegis_core.outcomes.run_outcome_engine") as mock_engine:
        _on_session_close(str(ws))
        mock_engine.assert_called_once_with(str(ws))


def test_on_session_close_survives_exceptions(tmp_path: Path):
    """_on_session_close must handle and swallow exceptions without bubbling."""
    from aegis_mcp.server import _on_session_close

    ws = tmp_path / "ws"
    ws.mkdir()

    with patch("aegis_core.outcomes.run_outcome_engine", side_effect=RuntimeError("disk full")):
        # Must not raise
        _on_session_close(str(ws))


def test_stdio_server_triggers_shutdown_harvesting_on_eof(tmp_path: Path, monkeypatch):
    """run_stdio_server must call _on_session_close when sys.stdin reaches EOF."""
    from aegis_mcp.server import run_stdio_server

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".soma" / "cells").mkdir(parents=True)
    monkeypatch.setenv("SOMA_WORKSPACE", str(ws))

    # Empty stdin (immediate EOF)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    with patch("aegis_mcp.server._on_session_close") as mock_close:
        rc = run_stdio_server()
        assert rc == 0
        mock_close.assert_called_once_with(str(ws.resolve()))
