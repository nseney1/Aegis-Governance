"""Tests for soma verify CLI command — TDD Gate 1.

Verifies the soma verify command interface, parsing, flags, execution modes,
exit code mappings, and file target resolution:
- CLI parsing: subparser registered with --files, --layer1-only, --dry-run, --repo-root
- --layer1-only: runs only deterministic Layer 1 checks and returns appropriate exit code
- --dry-run: reports planned verification targets without executing verification
- Exit code mapping: SHIP=0, BLOCK=1, REVISE=1
- --files flag: passes explicit file list, defaulting to git staged/changed files
- Importability: run_verify(args) importable from aegis_cli.verify and wired to CLI
"""
import argparse
import inspect
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

# Ensure repo root is on sys.path
REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_core.verification import (
    ArbitrationResult,
    Claim,
    Divergence,
    Prediction,
    RiskCategory,
    Severity,
    ToolEvidence,
    Verdict,
)
from aegis_cli.cli import _build_parser, main


class TestVerifyImport:
    """Requirement 6: Test that run_verify(args) is importable from aegis_cli.verify."""

    def test_run_verify_importable(self):
        """run_verify must be importable from aegis_cli.verify and be callable."""
        from aegis_cli.verify import run_verify
        assert callable(run_verify), "aegis_cli.verify.run_verify must be a callable function"

    def test_run_verify_accepts_args_parameter(self):
        """run_verify must accept an args parameter (argparse.Namespace)."""
        from aegis_cli.verify import run_verify
        sig = inspect.signature(run_verify)
        assert len(sig.parameters) >= 1, "run_verify must accept at least one argument (args)"
        first_param = next(iter(sig.parameters.values()))
        assert first_param.name in ("args", "argv", "options"), (
            f"Expected first parameter to be 'args', got '{first_param.name}'"
        )

    def test_cli_registers_verify_in_commands(self):
        """aegis_cli.cli.COMMANDS dict must register the 'verify' command handler."""
        from aegis_cli.cli import COMMANDS
        assert "verify" in COMMANDS, "COMMANDS dictionary in aegis_cli.cli must contain 'verify'"
        assert callable(COMMANDS["verify"]), "COMMANDS['verify'] must be a callable handler"

    def test_cli_cmd_verify_handler_exists(self):
        """aegis_cli.cli must define cmd_verify handler function."""
        import aegis_cli.cli as cli_mod
        assert hasattr(cli_mod, "cmd_verify"), "aegis_cli.cli must have cmd_verify function"
        assert callable(cli_mod.cmd_verify), "aegis_cli.cli.cmd_verify must be callable"


class TestVerifyParsing:
    """Requirement 1: Test CLI parsing — soma verify adds the right subparser with correct flags."""

    def test_verify_subparser_registered(self):
        """verify subparser must be registered in soma CLI."""
        parser = _build_parser()
        subparsers_action = next(
            (action for action in parser._actions if isinstance(action, argparse._SubParsersAction)),
            None,
        )
        assert subparsers_action is not None, "Parser must contain a subparsers action"
        assert "verify" in subparsers_action.choices, "Subparsers must include 'verify'"

    def test_verify_default_arguments(self):
        """soma verify defaults: layer1_only=False, dry_run=False, files=None, repo_root=None."""
        parser = _build_parser()
        args = parser.parse_args(["verify"])
        assert args.command == "verify"
        assert args.layer1_only is False, "Default --layer1-only must be False"
        assert args.dry_run is False, "Default --dry-run must be False"
        assert args.files is None or args.files == [], "Default --files must be None or empty"
        assert getattr(args, "workspace", None) is None, "Default --workspace must be None"

    def test_verify_layer1_only_flag(self):
        """--layer1-only flag sets args.layer1_only to True."""
        parser = _build_parser()
        args = parser.parse_args(["verify", "--layer1-only"])
        assert args.layer1_only is True

    def test_verify_dry_run_flag(self):
        """--dry-run flag sets args.dry_run to True."""
        parser = _build_parser()
        args = parser.parse_args(["verify", "--dry-run"])
        assert args.dry_run is True

    def test_verify_workspace_flag(self):
        """--workspace flag sets args.workspace to specified path string."""
        parser = _build_parser()
        args = parser.parse_args(["verify", "--workspace", "/custom/repo/path"])
        assert args.workspace == "/custom/repo/path"

    def test_verify_files_flag_single_file(self):
        """--files flag accepts a single file path."""
        parser = _build_parser()
        args = parser.parse_args(["verify", "--files", "aegis_cli/verify.py"])
        assert args.files == ["aegis_cli/verify.py"]

    def test_verify_files_flag_multiple_files(self):
        """--files flag accepts multiple file paths as a list."""
        parser = _build_parser()
        args = parser.parse_args(["verify", "--files", "file_a.py", "file_b.py", "file_c.py"])
        assert args.files == ["file_a.py", "file_b.py", "file_c.py"]

    def test_verify_combined_flags(self):
        """All flags can be combined and parsed together."""
        parser = _build_parser()
        args = parser.parse_args([
            "verify",
            "--layer1-only",
            "--dry-run",
            "--workspace", "/workspace/project",
            "--files", "pkg/mod1.py", "pkg/mod2.py",
        ])
        assert args.command == "verify"
        assert args.layer1_only is True
        assert args.dry_run is True
        assert args.workspace == "/workspace/project"
        assert args.files == ["pkg/mod1.py", "pkg/mod2.py"]

    def test_verify_help_exits_zero(self):
        """soma verify --help prints help and exits with status code 0."""
        with pytest.raises(SystemExit) as exc_info:
            main(["verify", "--help"])
        assert exc_info.value.code == 0

    def test_verify_unrecognized_argument_fails(self):
        """Unrecognized flags raise SystemExit(2)."""
        with pytest.raises(SystemExit) as exc_info:
            main(["verify", "--nonexistent-option"])
        assert exc_info.value.code == 2


class TestVerifyLayer1Only:
    """Requirement 2: Test --layer1-only runs only Layer 1 and returns appropriate exit code."""

    def test_layer1_only_clean_file_returns_zero(self, tmp_path):
        """Happy path: clean file with no Layer 1 violations returns exit code 0."""
        clean_file = tmp_path / "valid_module.py"
        clean_file.write_text(textwrap.dedent("""\
            def compute_total(a: int, b: int) -> int:
                return a + b

            def main():
                return compute_total(10, 20)
        """))

        exit_code = main([
            "verify",
            "--layer1-only",
            "--workspace", str(tmp_path),
            "--files", "valid_module.py",
        ])
        assert exit_code == 0, f"Expected exit code 0 on clean code, got {exit_code}"

    def test_layer1_only_defective_file_returns_one(self, tmp_path):
        """Sad path: file with Layer 1 violations (e.g., unguarded forbidden import) returns exit code 1."""
        defective_file = tmp_path / "broken_module.py"
        defective_file.write_text(textwrap.dedent("""\
            import unapproved_forbidden_third_party_package_xyz

            def orphaned_work():
                return 42
        """))

        exit_code = main([
            "verify",
            "--layer1-only",
            "--workspace", str(tmp_path),
            "--files", "broken_module.py",
        ])
        assert exit_code == 1, f"Expected exit code 1 on Layer 1 failure, got {exit_code}"

    def test_layer1_only_skips_layer2(self, tmp_path, capsys):
        """Edge case: Layer 1-only does not invoke Layer 2 agents or require LLM credentials."""
        clean_file = tmp_path / "fast_module.py"
        clean_file.write_text(textwrap.dedent("""\
            def run():
                return True

            def main():
                return run()
        """))

        exit_code = main([
            "verify",
            "--layer1-only",
            "--workspace", str(tmp_path),
            "--files", "fast_module.py",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        # Layer 1 only output should not mention Spec Agent or Code Agent prompt calls
        assert "Spec Agent" not in captured.out
        assert "Code Agent" not in captured.out

    def test_layer1_only_outputs_tool_evidence_summary(self, tmp_path, capsys):
        """Output should summarize Layer 1 tool evidence (e.g. call_graph, import_guard)."""
        target = tmp_path / "inspected.py"
        target.write_text(textwrap.dedent("""\
            def work():
                return "ok"

            def main():
                return work()
        """))

        exit_code = main([
            "verify",
            "--layer1-only",
            "--workspace", str(tmp_path),
            "--files", "inspected.py",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Layer 1" in captured.out or "PASSED" in captured.out, (
            f"Expected Layer 1 summary in stdout, got:\n{captured.out}"
        )


class TestVerifyDryRun:
    """Requirement 3: Test --dry-run produces output without running verification."""

    def test_dry_run_exits_zero(self, capsys):
        """--dry-run produces output and exits with code 0."""
        exit_code = main(["verify", "--dry-run", "--files", "aegis_cli/cli.py"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert len(captured.out) > 0, "--dry-run must print output to stdout"

    def test_dry_run_lists_files_to_be_verified(self, capsys):
        """--dry-run output explicitly mentions the target files that would be checked."""
        exit_code = main([
            "verify",
            "--dry-run",
            "--files", "aegis_cli/cli.py", "aegis_cli/doctor.py",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "aegis_cli/cli.py" in captured.out
        assert "aegis_cli/doctor.py" in captured.out

    def test_dry_run_does_not_fail_on_defective_files(self, tmp_path, capsys):
        """--dry-run must exit 0 without failing verification even on files with defects."""
        broken_file = tmp_path / "failing_sample.py"
        broken_file.write_text(textwrap.dedent("""\
            import invalid_pkg_that_does_not_exist
            def dead_func():
                pass
        """))

        exit_code = main([
            "verify",
            "--dry-run",
            "--workspace", str(tmp_path),
            "--files", "failing_sample.py",
        ])
        assert exit_code == 0, f"--dry-run must exit 0 even if targets have defects, got {exit_code}"
        captured = capsys.readouterr()
        assert "failing_sample.py" in captured.out

    def test_dry_run_with_layer1_only_indicates_layer1(self, capsys):
        """--dry-run with --layer1-only mentions Layer 1 checks to be run."""
        exit_code = main([
            "verify",
            "--dry-run",
            "--layer1-only",
            "--files", "aegis_cli/cli.py",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Layer 1" in captured.out or "layer1" in captured.out.lower()


class TestVerifyExitCodes:
    """Requirement 4: Test exit code mapping: SHIP=0, BLOCK=1, REVISE=1."""

    def test_verdict_to_exit_code_ship_returns_zero(self):
        """Verdict.SHIP maps to exit code 0."""
        from aegis_cli.verify import verdict_to_exit_code
        assert verdict_to_exit_code(Verdict.SHIP) == 0

    def test_verdict_to_exit_code_block_returns_one(self):
        """Verdict.BLOCK maps to exit code 1."""
        from aegis_cli.verify import verdict_to_exit_code
        assert verdict_to_exit_code(Verdict.BLOCK) == 1

    def test_verdict_to_exit_code_revise_returns_one(self):
        """Verdict.REVISE maps to exit code 1."""
        from aegis_cli.verify import verdict_to_exit_code
        assert verdict_to_exit_code(Verdict.REVISE) == 1

    def test_verdict_exit_codes_dict_mapping(self):
        """VERDICT_EXIT_CODES dictionary defines exact mappings for all Verdict members."""
        from aegis_cli.verify import VERDICT_EXIT_CODES
        assert VERDICT_EXIT_CODES[Verdict.SHIP] == 0
        assert VERDICT_EXIT_CODES[Verdict.BLOCK] == 1
        assert VERDICT_EXIT_CODES[Verdict.REVISE] == 1
        assert len(VERDICT_EXIT_CODES) == 3

    def test_run_verify_returns_zero_on_ship_verdict(self, tmp_path):
        """Direct call to run_verify returning SHIP verdict yields exit code 0."""
        from aegis_cli.verify import run_verify

        clean_file = tmp_path / "healthy.py"
        clean_file.write_text(textwrap.dedent("""\
            def healthy_work():
                return 1

            def main():
                return healthy_work()
        """))

        parser = _build_parser()
        args = parser.parse_args([
            "verify",
            "--layer1-only",
            "--workspace", str(tmp_path),
            "--files", "healthy.py",
        ])
        exit_code = run_verify(args)
        assert exit_code == 0

    def test_run_verify_returns_one_on_block_verdict(self, tmp_path):
        """Direct call to run_verify encountering BLOCK verdict yields exit code 1."""
        from aegis_cli.verify import run_verify

        bad_file = tmp_path / "blocked.py"
        bad_file.write_text(textwrap.dedent("""\
            import unauthorized_external_dep_xyz
        """))

        parser = _build_parser()
        args = parser.parse_args([
            "verify",
            "--layer1-only",
            "--workspace", str(tmp_path),
            "--files", "blocked.py",
        ])
        exit_code = run_verify(args)
        assert exit_code == 1


class TestVerifyFilesFlag:
    """Requirement 5: Test --files flag passes file list through and defaults appropriately."""

    def test_files_flag_targets_only_specified_files(self, tmp_path):
        """Passing --files ensures only specified files are verified, ignoring other broken files."""
        clean_file = tmp_path / "clean_target.py"
        clean_file.write_text(textwrap.dedent("""\
            def answer():
                return 42

            def main():
                return answer()
        """))

        # Broken file in the same directory, but NOT in --files
        broken_file = tmp_path / "ignored_broken.py"
        broken_file.write_text("import broken_forbidden_package_abc\n")

        exit_code = main([
            "verify",
            "--layer1-only",
            "--workspace", str(tmp_path),
            "--files", "clean_target.py",
        ])
        assert exit_code == 0, f"clean_target.py should pass verification; got {exit_code}"

    def test_files_flag_multiple_files_fails_if_any_file_fails(self, tmp_path):
        """When multiple files are passed, verification fails if any file is defective."""
        good_file = tmp_path / "good.py"
        good_file.write_text("def main(): return 1\n")

        bad_file = tmp_path / "bad.py"
        bad_file.write_text("import missing_forbidden_pkg\n")

        exit_code = main([
            "verify",
            "--layer1-only",
            "--workspace", str(tmp_path),
            "--files", "good.py", "bad.py",
        ])
        assert exit_code == 1, f"Expected exit code 1 when one of multiple files fails; got {exit_code}"

    def test_resolve_target_files_uses_explicit_files(self):
        """resolve_target_files returns explicit files list when --files is provided."""
        from aegis_cli.verify import resolve_target_files

        parser = _build_parser()
        args = parser.parse_args(["verify", "--files", "src/foo.py", "src/bar.py"])
        resolved = resolve_target_files(args)
        assert resolved == ["src/foo.py", "src/bar.py"]

    def test_resolve_target_files_defaults_to_git_changes_when_no_files_flag(self):
        """When --files is omitted, resolve_target_files queries git staged/changed files."""
        from aegis_cli.verify import resolve_target_files

        parser = _build_parser()
        args = parser.parse_args(["verify"])
        resolved = resolve_target_files(args)
        assert isinstance(resolved, list), "resolve_target_files must return a list of file paths"

    def test_files_flag_nonexistent_file_returns_error(self, tmp_path):
        """Passing a nonexistent file to --files returns exit code 1."""
        exit_code = main([
            "verify",
            "--layer1-only",
            "--workspace", str(tmp_path),
            "--files", "nonexistent_file_xyz.py",
        ])
        assert exit_code == 1

    def test_resolve_rejects_out_of_tree_paths(self, tmp_path):
        """Files outside repo_root should be skipped with warning."""
        from aegis_cli.verify import resolve_target_files

        # Create a repo structure
        repo = tmp_path / "myrepo"
        repo.mkdir()

        parser = _build_parser()
        args = parser.parse_args([
            "verify",
            "--workspace", str(repo),
            "--files", "../../etc/passwd", "good.py",
        ])
        resolved = resolve_target_files(args)
        # The traversal path should be filtered out
        assert "../../etc/passwd" not in resolved
        # The in-tree file should remain
        assert "good.py" in resolved

    def test_all_out_of_tree_files_exits_one(self, tmp_path):
        """When ALL --files are out-of-tree, should exit 1."""
        repo = tmp_path / "myrepo"
        repo.mkdir()

        exit_code = main([
            "verify",
            "--workspace", str(repo),
            "--files", "../../etc/passwd", "../../../tmp/evil.py",
        ])
        assert exit_code == 1


class TestVerifyRepoRoot:
    """Test --repo-root parameter resolution and override behavior."""

    def test_repo_root_override_resolves_files_correctly(self, tmp_path):
        """--repo-root allows verifying files inside an arbitrary project root."""
        src_dir = tmp_path / "subproject"
        src_dir.mkdir()
        code_file = src_dir / "app.py"
        code_file.write_text(textwrap.dedent("""\
            def calculate():
                return 100

            def main():
                return calculate()
        """))

        exit_code = main([
            "verify",
            "--layer1-only",
            "--workspace", str(src_dir),
            "--files", "app.py",
        ])
        assert exit_code == 0

    def test_repo_root_invalid_directory_returns_error(self):
        """Passing an invalid/nonexistent --repo-root returns exit code 1."""
        exit_code = main([
            "verify",
            "--workspace", "/nonexistent/directory/path/that/does/not/exist",
            "--files", "app.py",
        ])
        assert exit_code == 1


class TestVerifyPlanParsing:
    """Test CLI parsing for --plan and --plan-file."""

    def test_verify_accepts_plan_flag(self):
        """--plan flag accepts a natural language plan string."""
        parser = _build_parser()
        args = parser.parse_args(["verify", "--plan", "Refactor authentication layer"])
        assert args.plan == "Refactor authentication layer"

    def test_verify_accepts_plan_file_flag(self):
        """--plan-file flag accepts a path to a plan file."""
        parser = _build_parser()
        args = parser.parse_args(["verify", "--plan-file", "docs/plan.md"])
        assert args.plan_file == "docs/plan.md"

class TestVerifyPlanResolution:
    """Test plan resolution logic in aegis_cli.verify."""

    def test_resolve_task_plan_from_argument(self, tmp_path):
        """Explicit --plan string takes highest precedence."""
        from aegis_cli.verify import resolve_task_plan
        args = argparse.Namespace(plan="Implement caching", plan_file=None)
        plan = resolve_task_plan(args, str(tmp_path))
        assert plan == "Implement caching"

    def test_resolve_task_plan_from_file(self, tmp_path):
        """--plan-file reads the plan file from disk."""
        from aegis_cli.verify import resolve_task_plan
        plan_doc = tmp_path / "task_spec.md"
        plan_doc.write_text("Build persistent ledger")
        args = argparse.Namespace(plan=None, plan_file="task_spec.md")
        plan = resolve_task_plan(args, str(tmp_path))
        assert plan == "Build persistent ledger"

    def test_resolve_task_plan_missing_file_returns_none(self, tmp_path, capsys):
        """Missing --plan-file prints error and returns None."""
        from aegis_cli.verify import resolve_task_plan
        args = argparse.Namespace(plan=None, plan_file="nonexistent_spec.md")
        plan = resolve_task_plan(args, str(tmp_path))
        assert plan is None
        captured = capsys.readouterr()
        assert "plan file not found" in captured.err.lower()


class TestVerifyLayer2Execution:
    """Layer 2 telemetry; the CLI Layer 2 behavior is tested in test_cli_check.py."""

    def test_run_verify_records_telemetry_on_layer2(self, tmp_path, monkeypatch):
        """run_verify records telemetry on Layer 2 completion."""
        from aegis_cli.verify import run_verify

        telemetry_calls = []
        def mock_record(**kwargs):
            telemetry_calls.append(kwargs)
        monkeypatch.setattr("aegis_core.outcomes.record_verification_telemetry", mock_record)

        fake_llm = tmp_path / "fake_llm.py"
        fake_llm.write_text("import sys\nsys.stdin.read()\nprint('[]')\n", encoding="utf-8")

        target = tmp_path / "worker.py"
        target.write_text("def compute(x: int) -> int:\n    return x\n\ndef main():\n    return compute(1)\n")

        args = argparse.Namespace(
            files=["worker.py"],
            repo_root=str(tmp_path),
            workspace=str(tmp_path),
            plan="Implement worker",
            llm_cmd=f"{sys.executable} {fake_llm}",
            layer1_only=False,
            dry_run=False,
            plain=False,
            no_emoji=False,
            strict=False,
        )

        exit_code = run_verify(args)
        assert exit_code == 0
        assert len(telemetry_calls) >= 1
        assert telemetry_calls[-1]["passed"] is True
        assert telemetry_calls[-1]["verdict"] == Verdict.SHIP

class TestVerifyCleanRepository:
    """Test verify behavior when repository has no changed files."""

    def test_verify_clean_repo_layer1_only_exits_zero(self, tmp_path, capsys):
        """When no files are changed/staged, verify --layer1-only exits 0."""
        exit_code = main(["verify", "--layer1-only", "--workspace", str(tmp_path)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "clean" in captured.out.lower() or "0 files" in captured.out.lower()

    def test_verify_clean_repo_full_verify_exits_zero(self, tmp_path, capsys):
        """When no files are changed/staged, full verify exits 0."""
        exit_code = main(["verify", "--workspace", str(tmp_path)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "clean" in captured.out.lower() or "0 files" in captured.out.lower()


class TestResolveTargetFilesFallbacks:
    """resolve_target_files falls back from the working tree to branch diffs."""

    def test_resolve_target_files_github_base_ref(self, tmp_path, monkeypatch):
        """resolve_target_files falls back to GITHUB_BASE_REF when repo diff is empty."""
        from aegis_cli.verify import resolve_target_files
        import subprocess

        monkeypatch.setenv("GITHUB_BASE_REF", "main")
        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "diff":
                if "origin/main...HEAD" in cmd:
                    assert kwargs.get("timeout") == 10
                    assert kwargs.get("capture_output") is True
                    assert kwargs.get("text") is True
                    return subprocess.CompletedProcess(cmd, 0, stdout="aegis_core/mod.py\n", stderr="")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", mock_run)

        args = argparse.Namespace(files=None, workspace=str(tmp_path))
        files = resolve_target_files(args)
        assert files == ["aegis_core/mod.py"]

    def test_resolve_target_files_preserves_existing_files_when_github_base_ref_set(self, tmp_path, monkeypatch):
        """resolve_target_files does not query GITHUB_BASE_REF if files were already discovered."""
        from aegis_cli.verify import resolve_target_files
        import subprocess

        monkeypatch.setenv("GITHUB_BASE_REF", "main")
        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "diff":
                if "--cached" in cmd:
                    return subprocess.CompletedProcess(cmd, 0, stdout="staged_file.py\n", stderr="")
                if "origin/main...HEAD" in cmd:
                    return subprocess.CompletedProcess(cmd, 0, stdout="ci_file.py\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", mock_run)

        args = argparse.Namespace(files=None, workspace=str(tmp_path))
        files = resolve_target_files(args)
        assert files == ["staged_file.py"]

    def test_resolve_target_files_github_base_ref_subprocess_error(self, tmp_path, monkeypatch):
        """resolve_target_files handles SubprocessError when querying GITHUB_BASE_REF."""
        from aegis_cli.verify import resolve_target_files
        import subprocess

        monkeypatch.setenv("GITHUB_BASE_REF", "main")
        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "diff":
                if any("HEAD" in c for c in cmd):
                    raise subprocess.SubprocessError("git diff error")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", mock_run)

        args = argparse.Namespace(files=None, workspace=str(tmp_path))
        files = resolve_target_files(args)
        assert files == []

    def test_resolve_target_files_clean_tree_branch_diff_fallback(self, tmp_path, monkeypatch):
        """resolve_target_files queries origin/main...HEAD when working tree is clean."""
        from aegis_cli.verify import resolve_target_files
        import subprocess

        monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "diff":
                if "origin/main...HEAD" in cmd:
                    return subprocess.CompletedProcess(cmd, 0, stdout="core/branch_file.py\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", mock_run)

        args = argparse.Namespace(files=None, workspace=str(tmp_path))
        files = resolve_target_files(args)
        assert files == ["core/branch_file.py"]
        assert getattr(args, "_diff_base", None) == "origin/main...HEAD"

    def test_resolve_target_files_head_parent_fallback(self, tmp_path, monkeypatch):
        """resolve_target_files falls back to HEAD~1 when branch diffs are unavailable."""
        from aegis_cli.verify import resolve_target_files
        import subprocess

        monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "diff":
                if "HEAD~1" in cmd:
                    return subprocess.CompletedProcess(cmd, 0, stdout="core/last_commit_file.py\n", stderr="")
                if any("HEAD" in c for c in cmd):
                    return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="branch error")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", mock_run)

        args = argparse.Namespace(files=None, workspace=str(tmp_path))
        files = resolve_target_files(args)
        assert files == ["core/last_commit_file.py"]
        assert getattr(args, "_diff_base", None) == "HEAD~1"

    def test_resolve_target_files_github_base_ref(self, tmp_path, monkeypatch):
        """resolve_target_files honors GITHUB_BASE_REF when present in environment."""
        from aegis_cli.verify import resolve_target_files
        import subprocess

        monkeypatch.setenv("GITHUB_BASE_REF", "release-1.0")
        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "diff":
                if "origin/release-1.0...HEAD" in cmd:
                    return subprocess.CompletedProcess(cmd, 0, stdout="core/pr_feature.py\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", mock_run)

        args = argparse.Namespace(files=None, workspace=str(tmp_path))
        files = resolve_target_files(args)
        assert files == ["core/pr_feature.py"]

    def test_resolve_target_files_github_base_ref_local_branch_fallback(self, tmp_path, monkeypatch):
        """resolve_target_files falls back to local ref when origin/ref returns empty."""
        from aegis_cli.verify import resolve_target_files
        import subprocess

        monkeypatch.setenv("GITHUB_BASE_REF", "main")
        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "diff":
                if "main...HEAD" in cmd and "origin/main...HEAD" not in cmd:
                    return subprocess.CompletedProcess(cmd, 0, stdout="aegis_core/local.py\n", stderr="")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", mock_run)

        args = argparse.Namespace(files=None, workspace=str(tmp_path))
        files = resolve_target_files(args)
        assert files == ["aegis_core/local.py"]

def test_verify_command_contract():
    import argparse
    from unittest.mock import patch
    from aegis_cli.verify import VerifyCommand
    cmd = VerifyCommand()
    parser = argparse.ArgumentParser()
    cmd.configure_parser(parser)
    parsed = parser.parse_args([
        "--files", "foo.py", "--layer1-only", "--dry-run",
        "--plan", "task", "--plan-file", "p.md",
    ])
    assert parsed.files == ["foo.py"]
    assert parsed.layer1_only is True
    assert parsed.dry_run is True
    assert parsed.plan == "task"
    assert parsed.plan_file == "p.md"

    with patch("aegis_cli.verify.run_verify", return_value=0) as mock_run:
        assert cmd.execute(parsed) == 0
        mock_run.assert_called_once_with(parsed)


def test_verify_command_hook_mode():
    import argparse
    from unittest.mock import patch
    from aegis_cli.verify import VerifyCommand, run_verify

    cmd = VerifyCommand()
    parser = argparse.ArgumentParser()
    cmd.configure_parser(parser)
    parsed = parser.parse_args(["--hook"])
    assert parsed.hook is True

    with patch("aegis_cli.check.run_check", return_value=0) as mock_check:
        rc = run_verify(parsed)
        assert rc == 0
        mock_check.assert_called_once_with(parsed)









