"""Unit tests for aegis agent command (aegis_cli/agent.py)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aegis_cli.agent import AgentCommand, run_agent


def test_agent_command_contract():
    cmd = AgentCommand()
    assert cmd.name == "agent"

    parser = argparse.ArgumentParser()
    cmd.configure_parser(parser)

    # Test scan
    args_scan = parser.parse_args(["scan", "a.py", "b.py"])
    assert args_scan.agent_action == "scan"
    assert args_scan.target_files == ["a.py", "b.py"]

    # Test grade
    args_grade = parser.parse_args(["grade"])
    assert args_grade.agent_action == "grade"

    # Test receipt
    args_rcpt = parser.parse_args(["receipt", "--operation", "verify"])
    assert args_rcpt.agent_action == "receipt"
    assert args_rcpt.operation == "verify"

    # Test record
    args_rec = parser.parse_args(["record", "--outcome", "tp", "--rules", "inv-1,inv-2"])
    assert args_rec.agent_action == "record"
    assert args_rec.outcome == "tp"
    assert args_rec.rules == ["inv-1,inv-2"]


def test_agent_scan(tmp_path, capsys):
    with patch("aegis_mcp.jit_engine.express", return_value={"status": "PASS", "cells": []}):
        args = argparse.Namespace(
            agent_action="scan",
            workspace=str(tmp_path),
            files=["test.py"],
            target_files=None,
        )
        rc = run_agent(args)
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "PASS"


def test_agent_grade(tmp_path, capsys):
    with patch("aegis_core.telemetry.calculate_immune_grade", return_value={"grade": "A", "score": 95}):
        args = argparse.Namespace(
            agent_action="grade",
            workspace=str(tmp_path),
        )
        rc = run_agent(args)
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["grade"] == "A"


def test_agent_receipt(tmp_path, capsys):
    with patch("aegis_core.receipts.issue_receipt", return_value="rcpt_12345"):
        args = argparse.Namespace(
            agent_action="receipt",
            workspace=str(tmp_path),
            operation="verify",
            session_id="sess-1",
        )
        rc = run_agent(args)
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "ISSUED"
        assert data["receipt"] == "rcpt_12345"


def test_agent_record(tmp_path):
    with patch("aegis_core.telemetry.append_signals", return_value=1) as mock_append:
        args = argparse.Namespace(
            agent_action="record",
            workspace=str(tmp_path),
            outcome="tp",
            key="test-key",
            rules=["inv-1"],
        )
        rc = run_agent(args)
        assert rc == 0
        mock_append.assert_called_once()
