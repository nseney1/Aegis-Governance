"""`aegis check`: the v4 verification gate, driven through the real CLI entry point.

Interface: aegis check [FILES...] [--hook] [--strict] [--full]
           [--plan TEXT | --plan-file PATH] [--llm-cmd CMD] [--dry-run] [--format text|json]

Layer 1 (default) = the workspace checkpoint checks plus call_graph, import_guard
and forbid_ast on the target files. Layer 2 (--full, or a plan) adds the adversarial
review, run by one external command (--llm-cmd / AEGIS_LLM_CMD).
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

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


# ── Flag diet ───────────────────────────────────────────────────────────────

class TestInterface:
    @pytest.mark.parametrize(
        "flag",
        [
            ["--no-layer2"], ["--all"], ["--files", "a.py"], ["--pre-commit"], ["--checkpoint-only"],
            ["--layer1-only"], ["--deep"], ["--release"], ["--release-gate"], ["--require-arbitration"],
            ["--in-band"], ["--provider", "gemini"], ["--format", "sarif"],
        ],
        ids=lambda f: f[0] if len(f) == 1 else " ".join(f),
    )
    def test_removed_flags_are_usage_errors(self, ws, capsys, flag):
        assert _exit_code(["check", "--workspace", str(ws), *flag]) == 2
        err = capsys.readouterr().err
        assert "unrecognized arguments" in err or "invalid choice" in err

    @pytest.mark.parametrize("name", ["verify", "checkpoint"])
    def test_verify_and_checkpoint_are_no_longer_check_aliases(self, ws, name):
        assert _exit_code([name, "--workspace", str(ws)]) == 2

    def test_plan_and_plan_file_are_mutually_exclusive(self, ws, capsys):
        assert _exit_code(["check", "--workspace", str(ws), "--plan", "x", "--plan-file", "p.md"]) == 2
        assert "not allowed with argument" in capsys.readouterr().err

    def test_help_lists_exactly_the_v4_interface(self, capsys):
        assert _exit_code(["check", "--help"]) == 0
        out = capsys.readouterr().out
        for flag in ("--hook", "--strict", "--full", "--plan", "--plan-file", "--llm-cmd", "--dry-run", "--format"):
            assert flag in out
        assert "sarif" not in out
        assert "--provider" not in out


# ── Layer 1 (default) ───────────────────────────────────────────────────────

class TestLayer1:
    def test_clean_file_passes(self, ws, capsys):
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        assert _exit_code(["check", "--workspace", str(ws), "clean.py"]) == 0
        out = capsys.readouterr().out
        assert "Layer 1:" in out and "PASSED" in out
        assert "Layer 2" not in out

    def test_unguarded_third_party_import_fails(self, ws, capsys):
        (ws / "bad.py").write_text(UNGUARDED_IMPORT, encoding="utf-8")
        assert _exit_code(["check", "--workspace", str(ws), "bad.py"]) == 1
        assert "import_guard" in capsys.readouterr().out

    def test_only_the_named_files_are_checked(self, ws):
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        (ws / "bad.py").write_text(UNGUARDED_IMPORT, encoding="utf-8")
        assert _exit_code(["check", "--workspace", str(ws), "clean.py"]) == 0
        assert _exit_code(["check", "--workspace", str(ws), "clean.py", "bad.py"]) == 1

    def test_missing_file_is_an_error(self, ws, capsys):
        assert _exit_code(["check", "--workspace", str(ws), "nope.py"]) == 1
        assert "file not found: nope.py" in capsys.readouterr().err

    def test_out_of_tree_files_are_refused(self, ws, capsys):
        assert _exit_code(["check", "--workspace", str(ws), "../../etc/passwd"]) == 1
        assert "outside the repository" in capsys.readouterr().err

    def test_no_changed_files_is_a_clean_pass(self, ws, capsys):
        assert _exit_code(["check", "--workspace", str(ws)]) == 0
        assert "0 files changed" in capsys.readouterr().out

    def test_changed_files_come_from_git_when_none_are_named(self, ws, capsys):
        _git_repo(ws)
        (ws / "bad.py").write_text(UNGUARDED_IMPORT, encoding="utf-8")
        _git(ws, "add", "bad.py")
        assert _exit_code(["check", "--workspace", str(ws)]) == 1
        assert "bad.py" in capsys.readouterr().out

    def test_dry_run_lists_files_and_runs_nothing(self, ws, capsys):
        (ws / "bad.py").write_text(UNGUARDED_IMPORT, encoding="utf-8")
        assert _exit_code(["check", "--workspace", str(ws), "--dry-run", "bad.py"]) == 0
        out = capsys.readouterr().out
        assert "Dry run" in out and "bad.py" in out and "Layer 1" in out
        assert "import_guard" not in out

    def test_json_is_one_document_with_layer1_and_checkpoint(self, ws, capsys):
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        assert _exit_code(["check", "--workspace", str(ws), "--format", "json", "clean.py"]) == 0
        raw = capsys.readouterr().out
        assert "\x1b[" not in raw
        payload = json.loads(raw)
        assert payload["passed"] is True
        assert payload["files"] == ["clean.py"]
        assert {r["tool"] for r in payload["layer1"]} >= {"call_graph", "import_guard"}
        assert isinstance(payload["checkpoint_issues"], list)
        assert "layer2" not in payload

    def test_global_json_flag_matches_format_json(self, ws, capsys):
        (ws / "bad.py").write_text(UNGUARDED_IMPORT, encoding="utf-8")
        assert _exit_code(["check", "--workspace", str(ws), "--json", "bad.py"]) == 1
        assert json.loads(capsys.readouterr().out)["passed"] is False


# ── --strict and the workspace checkpoint ───────────────────────────────────

class TestStrict:
    def _missing_test_and_hardcoded_path(self, ws: Path) -> None:
        (ws / "src").mkdir()
        (ws / "src" / "svc.py").write_text('CACHE = "/home/alice/cache"\n', encoding="utf-8")

    def test_checkpoint_issues_warn_by_default(self, ws, capsys):
        self._missing_test_and_hardcoded_path(ws)
        assert _exit_code(["check", "--workspace", str(ws)]) == 0
        out = capsys.readouterr().out
        assert "[WARN] Missing test file for svc.py" in out
        assert "[WARN] Hardcoded absolute path found in svc.py:1" in out

    def test_strict_fails_on_checkpoint_issues(self, ws, capsys):
        # #12: `check --strict` must not be a passing no-op on a failing workspace.
        self._missing_test_and_hardcoded_path(ws)
        assert _exit_code(["check", "--workspace", str(ws), "--strict"]) == 1
        out = capsys.readouterr().out
        assert "[FAIL] Missing test file for svc.py" in out
        assert "[FAIL] Hardcoded absolute path found in svc.py:1" in out

    def test_strict_passes_a_clean_workspace(self, ws):
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        (ws / "tests").mkdir()
        (ws / "tests" / "test_clean.py").write_text(
            "from clean import compute\n\n\ndef test_compute():\n    assert compute(1, 2) == 3\n", encoding="utf-8"
        )
        assert _exit_code(["check", "--workspace", str(ws), "--strict", "clean.py"]) == 0

    def test_json_reports_checkpoint_issues(self, ws, capsys):
        self._missing_test_and_hardcoded_path(ws)
        assert _exit_code(["check", "--workspace", str(ws), "--strict", "--format", "json"]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["passed"] is False
        assert {i["check"] for i in payload["checkpoint_issues"]} == {"test_coverage", "hardcoded_paths"}


# ── --hook (git pre-commit) ─────────────────────────────────────────────────

class TestHook:
    def test_staged_clean_file_passes(self, ws):
        _git_repo(ws)
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        _git(ws, "add", "clean.py")
        assert _exit_code(["check", "--workspace", str(ws), "--hook"]) == 0

    def test_staged_unguarded_import_blocks(self, ws, capsys):
        _git_repo(ws)
        (ws / "bad.py").write_text(UNGUARDED_IMPORT, encoding="utf-8")
        _git(ws, "add", "bad.py")
        assert _exit_code(["check", "--workspace", str(ws), "--hook"]) == 1
        assert "import_guard: bad.py" in capsys.readouterr().out

    @pytest.mark.parametrize("extra", [["--full"], ["--plan", "x"], ["--plan-file", "plan.md"]])
    def test_hook_never_runs_layer2(self, ws, capsys, llm, extra):
        assert _exit_code(["check", "--workspace", str(ws), "--hook", "--llm-cmd", llm("ship"), *extra]) == 2
        assert "--hook runs Layer 1 only" in capsys.readouterr().err

    @pytest.mark.parametrize("strict", [[], ["--strict"]])
    def test_hook_fails_when_layer1_cannot_run(self, ws, monkeypatch, capsys, strict):
        from aegis_core.verification import runner

        def boom(**_kwargs):
            raise RuntimeError("driver registry exploded")

        monkeypatch.setattr(runner, "run_layer1", boom)
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        assert _exit_code(["check", "--workspace", str(ws), "--hook", *strict, "clean.py"]) == 1
        assert "Layer 1 could not run: driver registry exploded" in capsys.readouterr().err

    @pytest.mark.parametrize("strict", [[], ["--strict"]])
    def test_hook_fails_when_a_layer1_tool_raises(self, ws, monkeypatch, capsys, strict):
        from aegis_core.verification import call_graph

        def boom(*_args, **_kwargs):
            raise RecursionError("maximum recursion depth exceeded")

        monkeypatch.setattr(call_graph, "check", boom)
        (ws / "clean.py").write_text(CLEAN, encoding="utf-8")
        assert _exit_code(["check", "--workspace", str(ws), "--hook", *strict, "clean.py"]) == 1
        out = capsys.readouterr().out
        assert "call_graph: clean.py" in out
        assert "RecursionError: maximum recursion depth exceeded" in out


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
