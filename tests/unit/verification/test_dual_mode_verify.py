"""Behavioral tests for Dual-Mode In-Band Verification across MCP and CLI (Phase 20).

Verifies:
- soma_verify_changes in-band charge sheet generation (zero external API keys)
- soma_verify_changes defense rebuttal arbitration
- Information Partitioning Guard (SOMA-V01) enforcement over MCP
- soma verify --in-band CLI behavior
"""
from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aegis_mcp.tools import _handle_verify_changes
from aegis_cli.verify import run_verify
from aegis_core.workspace import Workspace


class TestMCPDualModeVerify:
    """Tests soma_verify_changes MCP tool dual-mode execution."""

    def test_mcp_layer1_only_default(self, tmp_path):
        ws = Workspace(root=tmp_path)
        ws.scaffold()
        f = tmp_path / "mod.py"
        f.write_text("def fn():\n    return 1\ndef main():\n    fn()\n", encoding="utf-8")

        args = {
            "workspace": str(tmp_path),
            "files": ["mod.py"],
            "layer1_only": True,
            "receipt": "rcpt_test",
        }
        resp = _handle_verify_changes(args, gov=None)
        assert resp["status"] == "PASS"
        assert resp["layer1_only"] is True
        assert len(resp["evidence"]) > 0

    def test_mcp_in_band_charge_sheet_generation(self, tmp_path):
        ws = Workspace(root=tmp_path)
        ws.scaffold()
        f = tmp_path / "banking.py"
        f.write_text(
            "def transfer(sender, receiver, amount):\n    return True\ndef main():\n    transfer('a', 'b', 10)\n",
            encoding="utf-8",
        )

        args = {
            "workspace": str(tmp_path),
            "files": ["banking.py"],
            "layer1_only": False,
            "task_plan": "Implement fund transfer",
            "receipt": "rcpt_test",
        }
        resp = _handle_verify_changes(args, gov=None)

        assert resp["status"] == "CHARGE_SHEET"
        assert resp["target_files"] == ["banking.py"]
        assert len(resp["charges"]) > 0
        assert any(c["affected_function"] == "transfer" for c in resp["charges"])
        assert "instructions" in resp

        # SOMA-V01: Never leak task plan or internal eval criteria to defense
        assert "task_plan" not in resp
        assert "system_prompt" not in resp

    def test_mcp_in_band_rebuttal_arbitrates_to_ship(self, tmp_path):
        ws = Workspace(root=tmp_path)
        ws.scaffold()
        f = tmp_path / "banking.py"
        f.write_text(
            "def transfer(sender, receiver, amount):\n    return True\ndef main():\n    transfer('a', 'b', 10)\n",
            encoding="utf-8",
        )

        rebuttal = [
            {
                "category": "missing_coverage",
                "claim": "Tested in test_banking.py",
                "evidence_file": "tests/test_banking.py",
                "evidence_line": 5,
                "tests_covering": ["test_transfer_success"],
            },
            {
                "category": "unguarded_transition",
                "claim": "Preconditions guarded at line 1",
                "evidence_file": "banking.py",
                "evidence_line": 1,
                "tests_covering": ["test_transfer_precondition"],
            },
        ]

        args = {
            "workspace": str(tmp_path),
            "files": ["banking.py"],
            "layer1_only": False,
            "task_plan": "Implement fund transfer",
            "rebuttal": rebuttal,
            "receipt": "rcpt_test",
        }
        resp = _handle_verify_changes(args, gov=None)

        assert resp["status"] == "SHIP"
        assert resp["passed"] is True
        assert "divergences" in resp
        assert "convergences" in resp

    def test_mcp_single_canonical_persistence_point(self, tmp_path):
        """Verify soma_verify_changes does not duplicate evidence saving or double-increment cycle."""
        ws = Workspace(root=tmp_path)
        ws.scaffold()
        f = tmp_path / "banking.py"
        f.write_text(
            "def transfer(sender, receiver, amount):\n    return True\ndef main():\n    transfer('a', 'b', 10)\n",
            encoding="utf-8",
        )
        rebuttal = [
            {
                "category": "missing_coverage",
                "claim": "Tested",
                "evidence_file": "banking.py",
                "evidence_line": 1,
                "tests_covering": ["test_fn"],
            },
        ]
        args = {
            "workspace": str(tmp_path),
            "files": ["banking.py"],
            "layer1_only": False,
            "task_plan": "Implement fund transfer",
            "rebuttal": rebuttal,
            "receipt": "rcpt_test",
        }
        resp = _handle_verify_changes(args, gov=None)
        assert resp["status"] == "SHIP"

        evidence_files = list((tmp_path / ".aegis" / "evidence").glob("arbitration_cycle_*.json"))
        # Must write exactly 1 file (cycle 1), NOT duplicate with cycle 2
        assert len(evidence_files) == 1
        assert evidence_files[0].name == "arbitration_cycle_1.json"
        assert resp.get("cycle") == 1


class TestCLIDualModeVerify:
    """Tests soma verify --in-band CLI command."""

    def test_cli_in_band_emits_charge_sheet_and_exits_1(self, tmp_path, capsys):
        ws = Workspace(root=tmp_path)
        ws.scaffold()
        f = tmp_path / "feature.py"
        f.write_text(
            "def run_feature():\n    pass\ndef main():\n    run_feature()\n",
            encoding="utf-8",
        )

        args = argparse.Namespace(
            workspace=str(tmp_path),
            files=["feature.py"],
            in_band=True,
            layer1_only=False,
            dry_run=False,
            plan="Implement run_feature",
            plan_file=None,
            provider=None,
        )

        exit_code = run_verify(args)
        assert exit_code == 1

        out, _err = capsys.readouterr()
        assert "AEGIS VERIFICATION REPORT" in out
        assert "SOMA IN-BAND CHARGE SHEET" not in out
        assert "run_feature" in out
        assert "Rebuttal instructions" in out

