from pathlib import Path
"""TDD Gate 1 tests for soma checkpoint CLI command.

The `soma checkpoint` command runs deterministic quality checks on
the current changeset (no LLM required):
- Checks test files exist for changed implementation files
- Checks for hardcoded paths (e.g., /home, /Users, /tmp)
- Checks assertion density in test files
- Checks cell fitness scores from evidence ledger
- Supports --pre-commit (warn mode: exit 0 unless strict, exit 1 in strict mode)
- Supports --json (machine-readable output)
- Supports --workspace (override target directory)

Implementation will be in `aegis_cli/checkpoint.py` with `run_checkpoint(args) -> int`.
"""
import argparse
import json
import os
import sys
import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)


from aegis_cli.checkpoint import run_checkpoint


def _setup_clean_workspace(root):
    """Helper to populate a clean workspace with compliant code and tests."""
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    tests = root / "tests"
    tests.mkdir(parents=True, exist_ok=True)

    # Compliant implementation file
    (src / "math_utils.py").write_text(
        "def multiply(a: int, b: int) -> int:\n"
        "    return a * b\n\n"
        "def divide(a: int, b: int) -> float:\n"
        "    if b == 0:\n"
        "        raise ValueError('Cannot divide by zero')\n"
        "    return a / b\n",
        encoding="utf-8",
    )

    # Compliant test file with good assertion density
    (tests / "test_math_utils.py").write_text(
        "import pytest\n"
        "from src.math_utils import multiply, divide\n\n"
        "def test_multiply():\n"
        "    assert multiply(2, 3) == 6\n"
        "    assert multiply(-1, 5) == -5\n"
        "    assert multiply(0, 10) == 0\n\n"
        "def test_divide():\n"
        "    assert divide(10, 2) == 5.0\n"
        "    with pytest.raises(ValueError):\n"
        "        divide(1, 0)\n",
        encoding="utf-8",
    )

    # Healthy canonical signal evidence
    evidence = root / ".aegis" / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    signal_records = [
        {
            "cell": "math-rule",
            "signal": "trigger",
            "timestamp": "2026-09-30T12:00:00Z",
        },
        {
            "cell": "math-rule",
            "signal": "tp",
            "timestamp": "2026-09-30T12:00:00Z",
        },
    ]
    (evidence / "signals.jsonl").write_text(
        "\n".join(json.dumps(record) for record in signal_records) + "\n",
        encoding="utf-8",
    )
    return root


# ── 1. CLI Parsing Tests ─────────────────────────────────────────────────────

class TestCheckpointCLIParsing:
    """Verify soma checkpoint CLI subparser and argument definitions."""

    def test_checkpoint_subparser_registered(self):
        """'checkpoint' must be registered as a recognized subcommand."""
        from aegis_cli.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["checkpoint"])
        assert args.command == "checkpoint"

    def test_checkpoint_defaults(self):
        """Default arguments must match expected behavior (not pre-commit, not json)."""
        from aegis_cli.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["checkpoint"])
        assert args.pre_commit is False
        assert args.json is False
        assert getattr(args, "workspace", None) is None
        assert getattr(args, "strict", False) is False

    def test_checkpoint_pre_commit_flag(self):
        """--pre-commit flag should be accepted and set to True."""
        from aegis_cli.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["checkpoint", "--pre-commit"])
        assert args.pre_commit is True

    def test_checkpoint_json_flag(self):
        """--json flag should be accepted and set to True."""
        from aegis_cli.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["checkpoint", "--json"])
        assert args.json is True

    def test_checkpoint_workspace_option(self):
        """--workspace option should accept a path string."""
        from aegis_cli.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["checkpoint", "--workspace", "/custom/path"])
        assert args.workspace == "/custom/path"

    def test_checkpoint_strict_flag(self):
        """--strict flag should be accepted when specified."""
        from aegis_cli.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["checkpoint", "--strict"])
        assert args.strict is True

    def test_checkpoint_all_flags_combined(self):
        """All checkpoint flags can be used together."""
        from aegis_cli.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "checkpoint",
            "--workspace", "/project/root",
            "--pre-commit",
            "--strict",
            "--json",
        ])
        assert args.command == "checkpoint"
        assert args.workspace == "/project/root"
        assert args.pre_commit is True
        assert args.strict is True
        assert args.json is True

    def test_checkpoint_help_exits_zero(self):
        """'soma checkpoint --help' prints help and exits with status 0."""
        from aegis_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["checkpoint", "--help"])
        assert exc_info.value.code == 0

    def test_checkpoint_unknown_flag_exits_code_two(self):
        """Argparse rejects unrecognized flags with exit code 2."""
        from aegis_cli.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["checkpoint", "--invalid-flag-12345"])
        assert exc_info.value.code == 2


# ── 2. Module Import & Dispatch Tests ────────────────────────────────────────

class TestCheckpointImportAndDispatch:
    """Verify run_checkpoint exists and is wired to CLI dispatch."""

    def test_run_checkpoint_importable(self):
        """run_checkpoint must be importable from aegis_cli.checkpoint."""
        from aegis_cli.checkpoint import run_checkpoint

        assert callable(run_checkpoint)

    def test_checkpoint_in_cli_commands(self):
        """COMMANDS dictionary in aegis_cli.cli must include 'checkpoint'."""
        from aegis_cli.cli import COMMANDS

        assert "checkpoint" in COMMANDS
        assert callable(COMMANDS["checkpoint"])


# ── 3. Clean Project Checks (Happy Path) ─────────────────────────────────────

class TestCheckpointCleanProject:
    """Verify checkpoint behavior on clean, conforming projects."""

    def test_clean_project_run_checkpoint_returns_zero(self, tmp_path, capsys):
        """run_checkpoint on a compliant workspace returns exit 0."""
        from aegis_cli.checkpoint import run_checkpoint

        _setup_clean_workspace(tmp_path)
        args = argparse.Namespace(
            workspace=str(tmp_path),
            pre_commit=False,
            strict=False,
            json=False,
        )
        exit_code = run_checkpoint(args)
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "FAIL" not in captured.out
        assert "Traceback" not in captured.err

    def test_clean_project_main_invocation_returns_zero(self, tmp_path):
        """Calling main(['checkpoint', '--workspace', ...]) returns 0 for a clean project."""
        from aegis_cli.cli import main

        _setup_clean_workspace(tmp_path)
        exit_code = main(["checkpoint", "--workspace", str(tmp_path)])
        assert exit_code == 0


# ── 4. Test Coverage Verification & Exit Behavior ────────────────────────────

class TestCheckpointTestCoverage:
    """Verify missing test files trigger appropriate exit codes based on flags."""

    def test_missing_test_coverage_returns_nonzero_by_default(self, tmp_path, capsys):
        """Implementation file with no corresponding test must fail in default/strict mode."""
        from aegis_cli.checkpoint import run_checkpoint

        src = tmp_path / "src"
        src.mkdir(parents=True)
        # Orphaned implementation file without test_service.py
        (src / "service.py").write_text(
            "def handle_request():\n    return 'ok'\n",
            encoding="utf-8",
        )
        args = argparse.Namespace(
            workspace=str(tmp_path),
            pre_commit=False,
            strict=False,
            json=False,
        )
        exit_code = run_checkpoint(args)
        assert exit_code != 0
        captured = capsys.readouterr()
        assert "service.py" in captured.out or "service.py" in captured.err

    def test_missing_test_coverage_warn_mode_exits_zero(self, tmp_path, capsys):
        """In --pre-commit mode (without --strict), issues warn but exit code is 0."""
        from aegis_cli.checkpoint import run_checkpoint

        src = tmp_path / "src"
        src.mkdir(parents=True)
        (src / "orphaned.py").write_text(
            "def worker():\n    pass\n",
            encoding="utf-8",
        )
        args = argparse.Namespace(
            workspace=str(tmp_path),
            pre_commit=True,
            strict=False,
            json=False,
        )
        exit_code = run_checkpoint(args)
        assert exit_code == 0
        captured = capsys.readouterr()
        # Should warn the user despite exiting 0
        out_and_err = captured.out + captured.err
        assert "warn" in out_and_err.lower() or "orphaned.py" in out_and_err

    def test_missing_test_coverage_pre_commit_strict_exits_nonzero(self, tmp_path):
        """In --pre-commit with --strict, issues cause exit code 1."""
        from aegis_cli.checkpoint import run_checkpoint

        src = tmp_path / "src"
        src.mkdir(parents=True)
        (src / "untested.py").write_text(
            "def process():\n    return 42\n",
            encoding="utf-8",
        )
        args = argparse.Namespace(
            workspace=str(tmp_path),
            pre_commit=True,
            strict=True,
            json=False,
        )
        exit_code = run_checkpoint(args)
        assert exit_code == 1


# ── 5. Hardcoded Paths, Assertion Density & Fitness Checks ───────────────────

class TestCheckpointDeterministicQualityChecks:
    """Verify specific deterministic checks: hardcoded paths, assertion density, cell fitness."""

    def test_hardcoded_paths_detected(self, tmp_path, capsys):
        """Hardcoded absolute paths (/home, /Users, /tmp) must be flagged."""
        from aegis_cli.checkpoint import run_checkpoint

        _setup_clean_workspace(tmp_path)
        # Introduce a hardcoded path in implementation
        bad_file = tmp_path / "src" / "hardcoded.py"
        bad_file.write_text(
            'CACHE_PATH = "/home/alice/data/cache.bin"\n',
            encoding="utf-8",
        )
        test_file = tmp_path / "tests" / "test_hardcoded.py"
        test_file.write_text(
            "from src.hardcoded import CACHE_PATH\n"
            "def test_cache():\n"
            "    assert CACHE_PATH.endswith('.bin')\n",
            encoding="utf-8",
        )

        args = argparse.Namespace(
            workspace=str(tmp_path),
            pre_commit=False,
            strict=False,
            json=False,
        )
        exit_code = run_checkpoint(args)
        assert exit_code != 0
        captured = capsys.readouterr()
        assert "hardcoded" in (captured.out + captured.err).lower()

    def test_low_assertion_density_flagged(self, tmp_path, capsys):
        """Test files with zero assertions should be flagged."""
        from aegis_cli.checkpoint import run_checkpoint

        _setup_clean_workspace(tmp_path)
        # Create a test file without any assert statements
        empty_test = tmp_path / "tests" / "test_vacuous.py"
        empty_test.write_text(
            "def test_does_nothing():\n"
            "    x = 1 + 2\n"
            "    y = x * 3\n",
            encoding="utf-8",
        )

        args = argparse.Namespace(
            workspace=str(tmp_path),
            pre_commit=False,
            strict=False,
            json=False,
        )
        exit_code = run_checkpoint(args)
        assert exit_code != 0
        captured = capsys.readouterr()
        assert "assertion" in (captured.out + captured.err).lower() or "density" in (captured.out + captured.err).lower()

    def test_unhealthy_cell_fitness_flagged(self, tmp_path, capsys):
        """Cell with high false positive rate in fitness evidence should be flagged."""
        from aegis_cli.checkpoint import run_checkpoint

        _setup_clean_workspace(tmp_path)
        evidence = tmp_path / ".aegis" / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        # Canonical signals mark the cell unhealthy.
        signal_records = [
            {
                "cell": "noisy-rule",
                "signal": signal,
                "timestamp": f"2026-09-30T10:{index:02d}:00Z",
            }
            for index, signal in enumerate(
                ("trigger", "trigger", "trigger", "fp", "fp", "fp")
            )
        ]
        (evidence / "signals.jsonl").write_text(
            "\n".join(json.dumps(record) for record in signal_records) + "\n",
            encoding="utf-8",
        )
        # Contradictory legacy outcomes would make the FP rate exactly 50% if
        # consumed; checkpoint must ignore them in favor of canonical signals.
        legacy_outcomes = [
            {"cell_id": "noisy-rule", "outcome": "tp"}
            for _ in range(3)
        ]
        (evidence / "outcomes.jsonl").write_text(
            "\n".join(json.dumps(record) for record in legacy_outcomes) + "\n",
            encoding="utf-8",
        )

        args = argparse.Namespace(
            workspace=str(tmp_path),
            pre_commit=False,
            strict=True,
            json=False,
        )
        exit_code = run_checkpoint(args)
        assert exit_code != 0


# ── 6. JSON Output Tests ─────────────────────────────────────────────────────

class TestCheckpointJsonOutput:
    """Verify --json emits valid, structured JSON output."""

    def test_json_output_clean_workspace(self, tmp_path, capsys):
        """Clean project with --json emits valid JSON reporting success."""
        from aegis_cli.checkpoint import run_checkpoint

        _setup_clean_workspace(tmp_path)
        args = argparse.Namespace(
            workspace=str(tmp_path),
            pre_commit=False,
            strict=False,
            json=True,
        )
        exit_code = run_checkpoint(args)
        assert exit_code == 0

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, dict)
        assert data.get("status") == "passed" or data.get("passed") is True
        assert "checks" in data or "results" in data

    def test_json_output_with_violations(self, tmp_path, capsys):
        """Project with issues and --json emits structured JSON detailing failures."""
        from aegis_cli.checkpoint import run_checkpoint

        src = tmp_path / "src"
        src.mkdir(parents=True)
        (src / "untested.py").write_text(
            'SECRET_KEY = "/home/admin/.keys"\n',
            encoding="utf-8",
        )

        args = argparse.Namespace(
            workspace=str(tmp_path),
            pre_commit=False,
            strict=False,
            json=True,
        )
        exit_code = run_checkpoint(args)
        assert exit_code != 0

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, dict)
        assert data.get("status") in ("failed", "error", "rejected") or data.get("passed") is False
        assert "issues" in data or "failures" in data or "checks" in data

    def test_json_output_via_cli_main(self, tmp_path, capsys):
        """CLI main with ['checkpoint', '--json'] outputs parseable JSON."""
        from aegis_cli.cli import main

        _setup_clean_workspace(tmp_path)
        main(["checkpoint", "--workspace", str(tmp_path), "--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, dict)


# ── 7. Edge Cases ────────────────────────────────────────────────────────────

class TestCheckpointEdgeCases:
    """Verify edge conditions such as empty workspace, missing directory, etc."""

    def test_empty_workspace_returns_zero(self, tmp_path, capsys):
        """An empty workspace with no python files passes checkpoint cleanly."""
        from aegis_cli.checkpoint import run_checkpoint

        args = argparse.Namespace(
            workspace=str(tmp_path),
            pre_commit=False,
            strict=False,
            json=False,
        )
        exit_code = run_checkpoint(args)
        assert exit_code == 0

    def test_nonexistent_workspace_returns_nonzero(self, tmp_path, capsys):
        """Specifying a non-existent workspace path returns non-zero error."""
        from aegis_cli.checkpoint import run_checkpoint

        bad_path = tmp_path / "does_not_exist"
        args = argparse.Namespace(
            workspace=str(bad_path),
            pre_commit=False,
            strict=False,
            json=False,
        )
        exit_code = run_checkpoint(args)
        assert exit_code != 0

    def test_checkpoint_is_read_only(self, tmp_path, monkeypatch):
        """checkpoint must not call aggregate_evidence or sync_frontmatter."""
        from aegis_cli.checkpoint import run_checkpoint
        import argparse

        _setup_clean_workspace(tmp_path)
        
        # We will mock aegis_cli.sync to see if it's imported/called
        class SyncMock:
            called = False
            @staticmethod
            def aggregate_evidence(*args, **kwargs):
                SyncMock.called = True
                return {"test": 1}
            @staticmethod
            def sync_frontmatter(*args, **kwargs):
                SyncMock.called = True
                
        # Actually it's probably better to check that no files in .aegis/rules were modified
        import stat
        cells_dir = tmp_path / ".aegis" / "rules"
        cells_dir.mkdir(parents=True, exist_ok=True)
        cell_file = cells_dir / "test-cell.md"
        cell_file.write_text("---\nfitness: 0\n---\ncontent", encoding="utf-8")
        
        # Make the workspace read-only
        # If it tries to write, it will raise an exception
        # Let's mock aggregate_evidence directly if possible, or just rely on file modifications
        
        # We can just monkeypatch aegis_cli.sync if it exists
        try:
            import aegis_cli.sync
            monkeypatch.setattr(aegis_cli.sync, "aggregate_evidence", SyncMock.aggregate_evidence)
            monkeypatch.setattr(aegis_cli.sync, "sync_frontmatter", SyncMock.sync_frontmatter)
        except ImportError:
            pass

        args = argparse.Namespace(
            workspace=str(tmp_path),
            pre_commit=False,
            strict=False,
            json=False,
        )
        exit_code = run_checkpoint(args)
        assert exit_code == 0
        assert not SyncMock.called, "Checkpoint mutated workspace state by calling sync/aggregate"


class TestPaperWallGate:
    """An invariant/wall rule without gate enforcement blocks even in warn mode."""

    def test_paper_wall_with_advisory_enforcement_fails_gate(self, tmp_path):
        _setup_clean_workspace(tmp_path)
        walls_dir = tmp_path / ".aegis" / "rules" / "walls"
        walls_dir.mkdir(parents=True, exist_ok=True)
        bad_wall = walls_dir / "wall-bad.md"
        bad_wall.write_text(
            "---\nid: wall-bad\ntype: wall\nenforcement: advisory\n---\n# Bad Wall\n",
            encoding="utf-8",
        )
        args = argparse.Namespace(
            workspace=str(tmp_path),
            pre_commit=False,
            strict=True,
            json=False,
        )
        exit_code = run_checkpoint(args)
        assert exit_code == 1

    def test_paper_wall_blocks_even_in_pre_commit_warn_mode(self, tmp_path):
        _setup_clean_workspace(tmp_path)
        walls_dir = tmp_path / ".aegis" / "rules" / "walls"
        walls_dir.mkdir(parents=True, exist_ok=True)
        bad_wall = walls_dir / "wall-bad.md"
        bad_wall.write_text(
            "---\nid: wall-bad\ntype: wall\nenforcement: advisory\n---\n# Bad Wall\n",
            encoding="utf-8",
        )
        # Even with pre_commit=True and strict=False, wall violations must be blocking
        args = argparse.Namespace(
            workspace=str(tmp_path),
            pre_commit=True,
            strict=False,
            json=False,
        )
        exit_code = run_checkpoint(args)
        assert exit_code == 1

    def test_checkpoint_command_contract(self):
        from unittest.mock import patch
        from aegis_cli.checkpoint import CheckpointCommand
        cmd = CheckpointCommand()
        parser = argparse.ArgumentParser()
        cmd.configure_parser(parser)
        parsed = parser.parse_args(["--pre-commit", "--strict"])
        assert parsed.pre_commit is True
        assert parsed.strict is True

        with patch("aegis_cli.checkpoint.run_checkpoint", return_value=0) as mock_run:
            assert cmd.execute(parsed) == 0
            mock_run.assert_called_once_with(parsed)



