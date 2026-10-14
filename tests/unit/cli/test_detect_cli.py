"""Unit tests for soma detect CLI command and options."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import pytest

from aegis_cli.cli import main
from aegis_cli.detect import run_detect


def test_detect_pure_python_repo(tmp_path, capsys):
    (tmp_path / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")

    code = main(["system", "drivers", "--workspace", str(tmp_path)])
    assert code == 0

    out = capsys.readouterr().out
    assert "Discovered Languages:" in out
    assert "Python" in out
    assert "native Python stdlib" in out
    assert "Dynamically Configured Source Extensions:" in out
    assert ".py" in out


def test_detect_json_output(tmp_path, capsys):
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'test'\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text("fn main() {}\n", encoding="utf-8")

    code = main(["system", "drivers", "--workspace", str(tmp_path), "--json"])
    assert code == 0

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["workspace"] == str(tmp_path)
    assert "rust" in data["languages"]
    assert ".py" in data["searchable_extensions"]


def test_detect_fix_provisions_slots(tmp_path, capsys):
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'test'\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text("fn main() {}\n", encoding="utf-8")

    code = main(["system", "drivers", "--workspace", str(tmp_path), "--fix"])
    assert code == 0

    slots_path = tmp_path / ".aegis" / "slots.yaml"
    assert slots_path.is_file()
    content = slots_path.read_text(encoding="utf-8")
    assert "ast_driver_rs" in content

    # Running detect again shows it configured
    code_again = main(["system", "drivers", "--workspace", str(tmp_path)])
    assert code_again == 0
    out = capsys.readouterr().out
    assert "configured: {python} .aegis/drivers/rust_ast.py" in out
    assert ".rs" in out


def test_doctor_drivers_flag_only_runs_ast_checks(tmp_path, capsys):
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    code = main(["system", "doctor", "--drivers", "--workspace", str(tmp_path)])
    assert code == 0

    out = capsys.readouterr().out
    assert "AST driver health check" in out
    assert "native Python stdlib" in out
    # Full doctor checks (e.g. MCP launcher, rules, zero-dependencies) should not run
    assert "MCP launcher" not in out
    assert "zero-dependency runtime operational" not in out
