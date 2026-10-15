"""Tests for aegis_cli/verify.py, the engine behind `aegis check`.

The command-line behavior of `aegis check` is tested in test_cli_check.py. This
module covers the helpers and the direct run_verify(args) entry point:
- verdict_to_exit_code: SHIP=0, BLOCK/REVISE (and anything unknown) = 1
- run_verify on parsed `check` arguments and on the bare namespaces older callers build
- resolve_target_files: explicit files, out-of-tree refusal, git and branch fallbacks
- resolve_task_plan: --plan, --plan-file, docs/plan.md
- telemetry on Layer 1 and Layer 2 runs
"""
import argparse
import sys
import textwrap
from pathlib import Path


# Ensure repo root is on sys.path
REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_core.verification import Verdict
from aegis_cli.cli import _build_parser


class TestVerifyExitCodes:
    """Exit code mapping: SHIP=0, BLOCK=1, REVISE=1, anything else 1 (fail closed)."""

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

    def test_verdict_to_exit_code_unknown_fails_closed(self):
        """A value that is not a Verdict never maps to success."""
        from aegis_cli.verify import verdict_to_exit_code
        assert verdict_to_exit_code("ship") == 1
        assert verdict_to_exit_code(None) == 1

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
        args = parser.parse_args(["check", "--workspace", str(tmp_path), "healthy.py"])
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
        args = parser.parse_args(["check", "--workspace", str(tmp_path), "blocked.py"])
        exit_code = run_verify(args)
        assert exit_code == 1


class TestResolveTargetFiles:
    """Positional FILES pass through; without them git supplies the changed files."""

    def test_resolve_target_files_uses_explicit_files(self):
        """resolve_target_files returns the explicit files when FILES are given."""
        from aegis_cli.verify import resolve_target_files

        parser = _build_parser()
        args = parser.parse_args(["check", "src/foo.py", "src/bar.py"])
        resolved = resolve_target_files(args)
        assert resolved == ["src/foo.py", "src/bar.py"]

    def test_resolve_target_files_defaults_to_git_changes_when_no_files_flag(self):
        """Without FILES, resolve_target_files queries git staged/changed files."""
        from aegis_cli.verify import resolve_target_files

        parser = _build_parser()
        args = parser.parse_args(["check"])
        resolved = resolve_target_files(args)
        assert isinstance(resolved, list), "resolve_target_files must return a list of file paths"

    def test_resolve_rejects_out_of_tree_paths(self, tmp_path):
        """Files outside repo_root should be skipped with warning."""
        from aegis_cli.verify import resolve_target_files

        # Create a repo structure
        repo = tmp_path / "myrepo"
        repo.mkdir()

        parser = _build_parser()
        args = parser.parse_args(["check", "--workspace", str(repo), "../../etc/passwd", "good.py"])
        resolved = resolve_target_files(args)
        # The traversal path should be filtered out
        assert "../../etc/passwd" not in resolved
        # The in-tree file should remain
        assert "good.py" in resolved

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

    def test_resolve_task_plan_falls_back_to_docs_plan_md(self, tmp_path):
        """Without --plan/--plan-file, a non-empty docs/plan.md is the plan."""
        from aegis_cli.verify import resolve_task_plan
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "plan.md").write_text("  Ship the ledger  \n", encoding="utf-8")
        args = argparse.Namespace(plan=None, plan_file=None)
        assert resolve_task_plan(args, str(tmp_path)) == "Ship the ledger"


class TestRunVerifyNamespaces:
    """run_verify accepts the bare namespaces older callers build."""

    def test_namespace_without_full_runs_layer1_only(self, tmp_path, monkeypatch):
        """No --full and no plan: the model command is never consulted, even if configured."""
        from aegis_cli.verify import run_verify

        marker = tmp_path / "llm-ran"
        monkeypatch.setenv("AEGIS_LLM_CMD", f"{sys.executable} -c \"open({str(marker)!r}, 'w')\"")
        (tmp_path / "core.py").write_text("def main():\n    return 1\n", encoding="utf-8")
        args = argparse.Namespace(
            files=["core.py"], layer1_only=True, dry_run=False, repo_root=str(tmp_path),
            workspace=str(tmp_path), plan=None, plan_file=None,
        )
        assert run_verify(args) == 0
        assert not marker.exists()

    def test_layer1_run_records_telemetry(self, tmp_path, monkeypatch):
        from aegis_cli.verify import run_verify

        calls = []
        monkeypatch.setattr("aegis_core.outcomes.record_verification_telemetry", lambda **kw: calls.append(kw))
        (tmp_path / "core.py").write_text("def main():\n    return 1\n", encoding="utf-8")
        args = argparse.Namespace(files=["core.py"], workspace=str(tmp_path), dry_run=False)
        assert run_verify(args) == 0
        assert [(c["target_files"], c["passed"], c["verdict"]) for c in calls] == [(["core.py"], True, "PASS")]


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

    def test_resolve_target_files_custom_github_base_ref(self, tmp_path, monkeypatch):
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

