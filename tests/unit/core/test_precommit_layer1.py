"""Behavioral tests verifying non-bypassable Layer 1 verification in pre-commit hooks.

Validates:
1. Clean staged Python files pass pre-commit Layer 1 verification.
2. Staged Python files with deterministic Layer 1 violations (e.g. import guard violations)
   fail closed and block the commit (exit code 1).
3. Non-Python staged files bypass Python AST checks cleanly.
4. JSON mode reports structured rejection diagnostics.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
import pytest

from aegis_cli.hooks import run_pre_commit


class TestPrecommitLayer1Verification:
    """Verifies that soma hook run pre-commit executes Layer 1 deterministic checks on staged files."""

    def test_clean_staged_python_files_pass_layer1(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo), check=True)

        clean_file = repo / "calculator.py"
        clean_file.write_text("def add(a: int, b: int) -> int:\n    return a + b\n\ndef main():\n    return add(1, 2)\n", encoding="utf-8")
        subprocess.run(["git", "add", "calculator.py"], cwd=str(repo), check=True)

        exit_code = run_pre_commit(workspace=repo, strict=False)
        assert exit_code == 0

    def test_staged_file_with_import_guard_violation_blocks_commit(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo), check=True)

        # Create a Python file in aegis_core/ that attempts an unguarded forbidden import (e.g. pytest or google.genai)
        core_dir = repo / "aegis_core"
        core_dir.mkdir()
        bad_file = core_dir / "bad_mod.py"
        bad_file.write_text("import google.genai\n\ndef run():\n    return 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "aegis_core/bad_mod.py"], cwd=str(repo), check=True)

        exit_code = run_pre_commit(workspace=repo, strict=False)
        assert exit_code == 1

    def test_json_mode_reports_layer1_blocked(self, tmp_path, capsys):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo), check=True)

        core_dir = repo / "aegis_core"
        core_dir.mkdir()
        bad_file = core_dir / "bad_mod.py"
        bad_file.write_text("import google.genai\n\ndef run():\n    return 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "aegis_core/bad_mod.py"], cwd=str(repo), check=True)

        exit_code = run_pre_commit(workspace=repo, strict=False, use_json=True)
        assert exit_code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out.strip())
        assert data["status"] == "blocked"
        assert data["reason"] == "layer1_failed"
        assert "layer1_evidence" in data
