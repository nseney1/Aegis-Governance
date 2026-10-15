"""Unit tests for aegis check command (aegis_cli/check.py)."""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aegis_cli.check import CheckCommand, run_check
from aegis_cli.cli import main

CLEAN = "def compute(a: int, b: int) -> int:\n    return a + b\n\n\ndef main():\n    return compute(1, 2)\n"
UNGUARDED_IMPORT = "import unapproved_third_party_pkg_xyz\n\n\ndef main():\n    return 1\n"

FAKE_LLM = textwrap.dedent(
    """\
    import json, sys
    mode = sys.argv[1]
    prompt = sys.stdin.read()
    spec = "Spec Agent" in prompt
    if mode == "fail":
        sys.stderr.write("quota exceeded\\n")
        sys.exit(7)
    if mode == "block" and spec:
        print(json.dumps([{
            "category": "code_injection", "severity": "critical",
            "risk": "eval of untrusted input", "mechanism": "code execution",
            "affected_function": "compute",
        }]))
    else:
        print("[]")
    """
)


def _exit_code(argv: list[str]) -> int:
    try:
        return main(argv)
    except SystemExit as exc:
        return exc.code


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    return root


@pytest.fixture
def llm(tmp_path: Path):
    script = tmp_path / "fake_llm.py"
    script.write_text(FAKE_LLM, encoding="utf-8")
    return lambda mode: shlex.join([sys.executable, str(script), mode])


@pytest.fixture(autouse=True)
def _no_ambient_backend(monkeypatch):
    monkeypatch.delenv("AEGIS_LLM_CMD", raising=False)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _git_repo(root: Path) -> Path:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "README.md").write_text("# p\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "init")
    return root




def test_check_command_contract():
    cmd = CheckCommand()
    assert cmd.name == "check"
    assert "verify" in cmd.aliases
    assert "checkpoint" in cmd.aliases

    parser = argparse.ArgumentParser()
    cmd.configure_parser(parser)

    # Test argument parsing
    args = parser.parse_args(["foo.py", "--hook"])
    assert args.target_files == ["foo.py"]
    assert args.hook is True


def test_check_default_runs_layer1():
    args = argparse.Namespace(
        target_files=["foo.py"],
        files=None,
        hook=False,
        full=False,
        release=False,
        release_gate=False,
        checkpoint_only=False,
        plan=None,
        plan_file=None,
    )
    with patch("aegis_cli.check.run_verify", return_value=0) as mock_verify:
        rc = run_check(args)
        assert rc == 0
        assert args.files == ["foo.py"]
        assert args.layer1_only is True
        mock_verify.assert_called_once_with(args)


def test_check_full_runs_full_verification():
    args = argparse.Namespace(
        target_files=None,
        files=["a.py"],
        hook=False,
        full=True,
        release=False,
        release_gate=False,
        checkpoint_only=False,
    )
    with patch("aegis_cli.check.run_verify", return_value=0) as mock_verify:
        rc = run_check(args)
        assert rc == 0
        assert args.layer1_only is False
        mock_verify.assert_called_once_with(args)


def test_check_hook_mode():
    args = argparse.Namespace(
        target_files=None,
        files=None,
        hook=True,
        full=False,
        release=False,
        release_gate=False,
        checkpoint_only=False,
    )
    with patch("aegis_cli.check.run_checkpoint", return_value=0) as mock_cp, \
         patch("aegis_cli.check.run_verify", return_value=0) as mock_verify:
        rc = run_check(args)
        assert rc == 0
        assert args.hook is False
        assert args.layer1_only is True
        assert args.pre_commit is True
        mock_cp.assert_called_once_with(args)
        mock_verify.assert_called_once_with(args)


def test_check_checkpoint_only_mode():
    args = argparse.Namespace(
        target_files=None,
        files=None,
        hook=False,
        full=False,
        release=False,
        release_gate=False,
        checkpoint_only=True,
    )
    with patch("aegis_cli.check.run_checkpoint", return_value=0) as mock_cp:
        rc = run_check(args)
        assert rc == 0
        mock_cp.assert_called_once_with(args)


def test_check_supports_deep_and_all_flags():
    """v3.0.0: check supports --deep (alias for --full) and --all flags."""
    cmd = CheckCommand()
    parser = argparse.ArgumentParser()
    cmd.configure_parser(parser)
    parsed = parser.parse_args(["--deep", "--all"])
    assert parsed.full is True
    assert parsed.all_files is True


def test_check_json_mode_emits_valid_json_without_ansi(tmp_path, capsys):
    """v3.0.0: aegis check --json emits valid machine-parseable JSON with zero ANSI codes."""
    import json

    (tmp_path / ".aegis" / "rules").mkdir(parents=True)
    target = tmp_path / "sample.py"
    target.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    args = argparse.Namespace(
        target_files=["sample.py"],
        files=None,
        hook=False,
        full=False,
        release=False,
        release_gate=False,
        checkpoint_only=False,
        plan=None,
        plan_file=None,
        workspace=str(tmp_path),
        json=True,
        format="json",
    )
    rc = run_check(args)
    assert rc == 0
    raw = capsys.readouterr().out
    assert "\x1b[" not in raw
    payload = json.loads(raw)
    assert payload["passed"] is True
    assert payload["files"] == ["sample.py"]
    assert isinstance(payload["layer1"], list)


# ── Layer 2 (--full / --plan) ───────────────────────────────────────────────

class TestLayer2:
    @pytest.mark.parametrize(
        "extra", [["--full", "--plan", "p"], ["--plan", "p"], ["--plan-file", "plan.md"], ["--full"]],
        ids=["full+plan", "plan", "plan-file", "full"],
    )
    def test_without_a_backend_exits_2_before_running_anything(self, ws, capsys, extra):
        (ws / "plan.md").write_text("Add compute\n", encoding="utf-8")
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        assert _exit_code(["check", "--workspace", str(ws), *extra, "clean.py"]) == 2
        captured = capsys.readouterr()
        assert "Layer 2 needs --llm-cmd or AEGIS_LLM_CMD" in captured.err
        assert "skipped" not in (captured.out + captured.err).lower()
        assert "Layer 1:" not in captured.out

    def test_env_backend_ship_passes(self, ws, monkeypatch, capsys, llm):
        monkeypatch.setenv("AEGIS_LLM_CMD", llm("ship"))
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        assert _exit_code(["check", "--workspace", str(ws), "--full", "--plan", "Add compute", "clean.py"]) == 0
        out = capsys.readouterr().out
        assert "Layer 2: ✅ SHIP" in out

    def test_plan_alone_implies_full(self, ws, capsys, llm):
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        assert _exit_code(["check", "--workspace", str(ws), "--llm-cmd", llm("ship"), "--plan", "Add compute", "clean.py"]) == 0
        assert "Layer 2: ✅ SHIP" in capsys.readouterr().out

    def test_flag_beats_env(self, ws, monkeypatch, llm):
        monkeypatch.setenv("AEGIS_LLM_CMD", llm("fail"))
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        argv = ["check", "--workspace", str(ws), "--llm-cmd", llm("ship"), "--plan", "Add compute", "clean.py"]
        assert _exit_code(argv) == 0

    def test_block_verdict_fails(self, ws, capsys, llm):
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        argv = ["check", "--workspace", str(ws), "--llm-cmd", llm("block"), "--plan", "Add compute", "clean.py"]
        assert _exit_code(argv) == 1
        assert "Layer 2: 🔴 BLOCK" in capsys.readouterr().out

    def test_failing_backend_is_an_explicit_error(self, ws, capsys, llm):
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        argv = ["check", "--workspace", str(ws), "--llm-cmd", llm("fail"), "--plan", "Add compute", "clean.py"]
        assert _exit_code(argv) == 1
        assert "Layer 2 failed: LLM command exited 7: quota exceeded" in capsys.readouterr().err

    def test_full_without_a_plan_exits_2(self, ws, capsys, llm):
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        assert _exit_code(["check", "--workspace", str(ws), "--full", "--llm-cmd", llm("ship"), "clean.py"]) == 2
        assert "Layer 2 needs a task plan" in capsys.readouterr().err

    def test_missing_plan_file_is_an_error(self, ws, capsys, llm):
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        argv = ["check", "--workspace", str(ws), "--llm-cmd", llm("ship"), "--plan-file", "missing.md", "clean.py"]
        assert _exit_code(argv) == 1
        assert "plan file not found: missing.md" in capsys.readouterr().err

    def test_no_arbitration_evidence_is_written(self, ws, llm):
        _git_repo(ws)
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        _git(ws, "add", "clean.py")
        assert _exit_code(["check", "--workspace", str(ws), "--llm-cmd", llm("ship"), "--plan", "Add compute"]) == 0
        assert not list(ws.rglob("arbitration_cycle_*.json"))

    def test_json_includes_the_layer2_verdict(self, ws, capsys, llm):
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        argv = ["check", "--workspace", str(ws), "--format", "json", "--llm-cmd", llm("block"), "--plan", "p", "clean.py"]
        assert _exit_code(argv) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["passed"] is False
        assert payload["layer2"]["verdict"] == "block"
