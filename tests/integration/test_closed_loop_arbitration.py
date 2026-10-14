"""Closed-Circuit End-to-End Integration Tests for Two-Layer Arbitration & Gating.

Verifies the entire lifecycle loop:
1. Source files modified.
2. `soma verify` executed.
3. Layer 1 + Layer 2 executed.
4. `.soma/evidence/arbitration_cycle_{N}.json` atomically persisted to disk with target_files, commit_sha, and tree_hash.
5. `soma checkpoint` verifies the newly persisted receipt.
6. `verify_release_gate` (Gate 4.5) passes cleanly.
7. Any subsequent file mutation without re-arbitration fails closed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import pytest

from aegis_cli.checkpoint import run_checkpoint
from aegis_cli.verify import run_verify, verify_release_gate
from aegis_core.verification import Verdict


def _setup_git_workspace(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=str(tmp_path), check=True)

    # Initial commit on main
    init_file = tmp_path / "README.md"
    init_file.write_text("# Project\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), check=True)

    # Create develop branch
    subprocess.run(["git", "checkout", "-b", "develop"], cwd=str(tmp_path), check=True)

    # Create tests/ directory and source directory
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".soma" / "cells" / "walls").mkdir(parents=True)

    # Add a valid wall cell
    wall = tmp_path / ".soma" / "cells" / "walls" / "wall-test.md"
    wall.write_text(
        "---\nid: wall-test\ntype: wall\nenforcement: gate\ndomain: testing\n---\n# Wall\n",
        encoding="utf-8",
    )

    src = tmp_path / "src" / "calc.py"
    src.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    test = tmp_path / "tests" / "test_calc.py"
    test.write_text(
        "import os, sys\n"
        "sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))\n"
        "from src.calc import add\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n"
        "    assert add(0, 0) == 0\n"
        "    assert add(-1, 1) == 0\n",
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "feat: add calculator"], cwd=str(tmp_path), check=True)

    return tmp_path


class TestClosedLoopArbitrationCircuit:
    """Verifies end-to-end integration across CLI verify, evidence persistence, and checkpoint release gating."""

    def test_end_to_end_verification_persists_evidence_and_passes_gate(self, tmp_path, monkeypatch):
        repo_root = _setup_git_workspace(tmp_path)

        # Mock inference provider to return empty list (SHIP)
        class MockProvider:
            def generate(self, prompt: str) -> str:
                return json.dumps([])

        from aegis_cli import verify as cli_verify
        monkeypatch.setattr(cli_verify, "resolve_cli_provider", lambda args, root: MockProvider())

        # Run soma verify with plan
        args = argparse.Namespace(
            workspace=str(repo_root),
            files=["src/calc.py"],
            plan="Add calculator implementation",
            plan_file=None,
            provider=None,
            layer1_only=False,
            release_gate=False,
            in_band=False,
            dry_run=False,
        )

        exit_code = run_verify(args)
        assert exit_code == 0, "run_verify must succeed with SHIP verdict"

        # Assert evidence file was written to disk
        ev_dir = repo_root / ".soma" / "evidence"
        ev_file = ev_dir / "arbitration_cycle_1.json"
        assert ev_file.is_file(), "Arbitration evidence file must be created on disk"

        record = json.loads(ev_file.read_text(encoding="utf-8"))
        assert record["cycle"] == 1
        assert record["verdict"] == "ship"
        assert "target_files" in record
        assert "src/calc.py" in record["target_files"]
        assert "commit_sha" in record
        assert "tree_hash" in record

        # Assert soma checkpoint --strict passes with this evidence
        chk_args = argparse.Namespace(
            workspace=str(repo_root),
            pre_commit=False,
            strict=True,
            require_arbitration=True,
            json=False,
        )
        assert run_checkpoint(chk_args) == 0

        # Assert release gate passes
        passed, msg = verify_release_gate(str(repo_root))
        assert passed is True, f"Release Gate 4.5 must pass: {msg}"
        assert "Release Gate 4.5 PASS" in msg

    def test_unverified_file_fails_release_gate_closed(self, tmp_path, monkeypatch):
        repo_root = _setup_git_workspace(tmp_path)

        # Add a new unverified python file to develop branch
        unverified = repo_root / "src" / "unverified.py"
        unverified.write_text("def secret(): pass\n", encoding="utf-8")
        subprocess.run(["git", "add", "src/unverified.py"], cwd=str(repo_root), check=True)
        subprocess.run(["git", "commit", "-m", "unverified file"], cwd=str(repo_root), check=True)

        # Only verify calc.py, omitting unverified.py
        class MockProvider:
            def generate(self, prompt: str) -> str:
                return json.dumps([])

        from aegis_cli import verify as cli_verify
        monkeypatch.setattr(cli_verify, "resolve_cli_provider", lambda args, root: MockProvider())

        args = argparse.Namespace(
            workspace=str(repo_root),
            files=["src/calc.py"],
            plan="Verify calc only",
            plan_file=None,
            provider=None,
            layer1_only=False,
            release_gate=False,
            in_band=False,
            dry_run=False,
        )
        run_verify(args)

        # Release Gate comparing origin/main (or main) to HEAD must fail because src/unverified.py is not in receipt
        passed, msg = verify_release_gate(str(repo_root))
        assert passed is False
        assert "does not cover" in msg or "FAIL" in msg
