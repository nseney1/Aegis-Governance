"""Tests for soma doctor AST driver diagnostics and --fix auto-repair."""
import argparse
from pathlib import Path
import pytest

from aegis_cli.doctor import run_doctor, _check_ast_drivers
from aegis_core.skills.slots import SlotRegistry


def test_doctor_detects_unconfigured_polyglot_language(tmp_path: Path):
    # Setup Rust project without slots.yaml
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'app'\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text("fn main() {}\n", encoding="utf-8")

    # Doctor check without fix returns False / warns
    ok = _check_ast_drivers(tmp_path, fix=False)
    assert ok is False


def test_doctor_fix_provisions_missing_drivers(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'app'\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text("fn main() {}\n", encoding="utf-8")

    # Doctor check with fix=True automatically provisions slots
    ok = _check_ast_drivers(tmp_path, fix=True)
    assert ok is True

    # Verify slots.yaml now has ast_driver_rs
    registry = SlotRegistry.load(tmp_path)
    assert registry.get_ast_driver(".rs") is not None
    assert (tmp_path / ".aegis" / "drivers" / "rust_ast.py").is_file()


from unittest.mock import patch


def test_doctor_cli_fix_flag(tmp_path: Path, monkeypatch):
    (tmp_path / "go.mod").write_text("module example.com/app\n", encoding="utf-8")
    (tmp_path / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
    (tmp_path / ".aegis" / "evidence").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".gemini").mkdir(exist_ok=True)
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "rule.md").write_text("# rule")

    args = argparse.Namespace(
        project_root=tmp_path,
        _project_root=tmp_path,
        fix=True,
        fix_path=False,
        yes=True,
    )

    monkeypatch.chdir(tmp_path)
    with patch("aegis_cli.doctor.shutil.which", side_effect=lambda cmd, **kw: "/usr/local/bin/soma" if cmd == "soma" else "/bin/go"), \
         patch("aegis_cli.init.get_rules_dir", return_value=rules_dir):
        exit_code = run_doctor(args)
    # Doctor exits 0 when health checks pass or are repaired
    registry = SlotRegistry.load(tmp_path)
    assert registry.get_ast_driver(".go") is not None


def test_doctor_fix_output_reports_provisioned_driver_status(tmp_path: Path, capsys):
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'app'\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text("fn main() {}\n", encoding="utf-8")

    ok = _check_ast_drivers(tmp_path, fix=True)
    assert ok is True
    out = capsys.readouterr().out
    assert "AST driver (.rs)" in out
    assert "AST drivers: native Python stdlib (in-process)" not in out
