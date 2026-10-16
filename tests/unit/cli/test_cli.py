"""aegis CLI skeleton: every command has help, dispatch goes through the registry."""
from pathlib import Path
import os
import subprocess
import sys

import pytest

import aegis_cli.cli as cli


from aegis_cli.registry import get_default_registry

SUBCOMMANDS = sorted(c.name for c in get_default_registry().list_commands())


class TestCLIImport:
    """Verify the CLI module is importable without side effects."""

    def test_cli_importable(self):
        from aegis_cli.cli import main
        assert callable(main)

    def test_cli_build_parser(self):
        from aegis_cli.cli import _build_parser
        parser = _build_parser()
        assert parser.prog == "aegis"


class TestCLIHelp:
    """Verify --help works for the main command and all subcommands."""

    def test_main_help_exits_zero(self):
        from aegis_cli.cli import main
        # No args → prints help, returns 0
        assert main([]) == 0

    @pytest.mark.parametrize("cmd", SUBCOMMANDS)
    def test_subcommand_help_exits_zero(self, cmd):
        from aegis_cli.cli import main
        with pytest.raises(SystemExit) as exc_info:
            main([cmd, "--help"])
        assert exc_info.value.code == 0


class TestCLIDispatch:
    """Verify subcommands dispatch to their handlers."""

    @pytest.mark.parametrize("cmd,extra_args", [
        ("init", ["--dry-run", "--platform", "gemini", "--yes"]),
        ("status", []),
        ("check", ["--dry-run"]),
        ("rule", ["list"]),
        ("doctor", []),
        ("scan", ["src/app.py"]),
        ("hook", ["status"]),
    ])
    def test_subcommand_runs_without_crash(self, cmd, extra_args, capsys, monkeypatch):
        from aegis_cli import doctor
        from aegis_cli.cli import main

        def no_host_cli(argv, cwd, timeout):  # doctor asks codex; never a real host in tests
            raise OSError("host CLIs are not run in tests")

        monkeypatch.setattr(doctor, "_run_host_cli", no_host_cli)
        result = main([cmd] + extra_args)
        assert result in (0, 1)
        captured = capsys.readouterr()
        assert 'Traceback' not in captured.err

    def test_unknown_command_returns_nonzero(self):
        from aegis_cli.cli import main
        # argparse treats unknown subcommand as args.command = None? No,
        # it raises SystemExit(2) for unrecognized args.
        with pytest.raises(SystemExit) as exc_info:
            main(["nonexistent_command_xyz"])
        assert exc_info.value.code == 2


class TestCLIEntryPoint:
    """Verify the installed entry point resolves correctly."""

    def test_aegis_dash_dash_help_via_subprocess(self):
        """Run `python -m aegis_cli.cli --help` to test without requiring
        pip install."""
        repo_root = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
        proc = subprocess.run(
            [sys.executable, "-m", "aegis_cli.cli", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=repo_root,
        )
        assert proc.returncode == 0
        assert "Aegis Governance" in proc.stdout


class TestNonUtf8Console:
    """BUG-012: a cp1252 stdout (Windows, redirected output) made `soma
    status` exit 1 with UnicodeEncodeError on its emoji."""

    def test_status_survives_cp1252_stdout(self, tmp_path):
        repo_root = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
        home = tmp_path / "home"
        home.mkdir()
        env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONPATH=repo_root,
                   HOME=str(home), USERPROFILE=str(home))
        proc = subprocess.run(
            [sys.executable, "-m", "aegis_cli.cli", "status"],
            capture_output=True, encoding="cp1252", errors="replace",
            timeout=30, cwd=str(tmp_path), env=env,
        )
        assert "can't encode" not in proc.stderr, proc.stderr
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip()


# ── TDD Red Phase: --rules preset tests ────────────────────────────────────


def _run_init_in(tmp_path, extra_args=None):
    """Helper: invoke soma init targeting tmp_path using a subprocess."""
    argv = [sys.executable, "-m", "aegis_cli.cli", "init", "--platform", "gemini", "--yes"]
    if extra_args:
        argv.extend(extra_args)

    env = dict(os.environ, HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    repo_root = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
    env["PYTHONPATH"] = repo_root + (os.pathsep + env["PYTHONPATH"] if "PYTHONPATH" in env else "")
    proc = subprocess.run(argv, cwd=str(tmp_path), capture_output=True, text=True, env=env)
    return proc.returncode


def _installed_rules(tmp_path):
    """Return set of .md filenames in the gemini rules dir under tmp_path."""
    rules_dir = tmp_path / ".gemini" / "config" / "rules"
    if not rules_dir.is_dir():
        return set()
    return {f.name for f in rules_dir.iterdir() if f.suffix == ".md"}


class TestRulePresetMinimal:
    """--rules minimal should install exactly 2 rules."""

    def test_init_minimal_installs_two_rules(self, tmp_path):
        """--rules minimal should install exactly providence + destructive-ops."""
        rc = _run_init_in(tmp_path, ["--rules", "minimal"])
        assert rc == 0
        installed = _installed_rules(tmp_path)
        assert installed == {"providence.md", "destructive-ops.md"}, (
            f"Expected 2 minimal rules, got {installed}"
        )


class TestRulePresetStandard:
    """--rules standard (default) should install the 5 starter rules."""

    def test_init_standard_installs_five_rules(self, tmp_path):
        """--rules standard installs 5 rules (current behavior — should PASS)."""
        rc = _run_init_in(tmp_path, ["--rules", "standard"])
        assert rc == 0
        installed = _installed_rules(tmp_path)
        assert len(installed) == 5, f"Expected 5 standard rules, got {len(installed)}: {installed}"

    def test_init_default_preset_is_standard(self, tmp_path):
        """When --rules is not specified, default to standard (5 rules)."""
        rc = _run_init_in(tmp_path)  # no --rules flag
        assert rc == 0
        installed = _installed_rules(tmp_path)
        assert len(installed) == 5, f"Default should match standard (5 rules), got {len(installed)}"


# Every shipped rule in rules/ and rules/.oracles/ except META.md (D16: the
# dogfood rules live in this repo's .aegis/rules; desktop-automation is not shipped).
FULL_PRESET = {
    "cost-optimization.md", "destructive-ops.md", "providence.md", "subagent-delegation.md",
    "architectural-tenets.md", "atomic-workstream-protocol.md", "documentation.md",
    "feature-specs.md", "git-workflow.md", "polyglot-standards.md", "tdd-protocol.md", "testing.md",
}


class TestRulePresetFull:
    """--rules full should discover and install every shipped rule."""

    def test_init_full_installs_every_shipped_rule(self, tmp_path):
        """--rules full installs exactly the shipped rules, flattened."""
        rc = _run_init_in(tmp_path, ["--rules", "full"])
        assert rc == 0
        assert _installed_rules(tmp_path) == FULL_PRESET

    def test_init_full_skips_meta_md(self, tmp_path):
        """--rules full should skip META.md and README.md."""
        _run_init_in(tmp_path, ["--rules", "full"])
        installed = _installed_rules(tmp_path)
        assert "META.md" not in installed, "META.md should be excluded from full preset"
        assert "README.md" not in installed, "README.md should be excluded from full preset"


# ── TDD Red Phase: --mcp config tests ──────────────────────────────────────


import json


def _run_init_mcp(tmp_path, extra_args=None):
    """Helper: invoke run_init with --mcp targeting tmp_path."""
    argv = [sys.executable, "-m", "aegis_cli.cli", "init", "--platform", "gemini", "--yes", "--mcp"]
    if extra_args:
        argv.extend(extra_args)

    env = dict(os.environ, HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    repo_root = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
    env["PYTHONPATH"] = repo_root + (os.pathsep + env["PYTHONPATH"] if "PYTHONPATH" in env else "")
    proc = subprocess.run(argv, cwd=str(tmp_path), capture_output=True, text=True, env=env)
    return proc.returncode


class TestMCPConfig:
    """--mcp should create/merge .mcp.json with server config."""

    def test_init_mcp_creates_config(self, tmp_path):
        """--mcp should create .mcp.json with mcpServers entry."""
        rc = _run_init_mcp(tmp_path)
        assert rc == 0
        mcp_file = tmp_path / ".mcp.json"
        assert mcp_file.exists(), ".mcp.json was not created"
        data = json.loads(mcp_file.read_text())
        assert "mcpServers" in data, "Missing mcpServers key"
        assert "aegis" in data["mcpServers"] or "soma" in data["mcpServers"]

    def test_init_mcp_uses_relative_paths(self, tmp_path):
        """MCP config must use relative paths, not hardcoded absolutes."""
        _run_init_mcp(tmp_path)
        mcp_file = tmp_path / ".mcp.json"
        data = json.loads(mcp_file.read_text())
        soma_cfg = data["mcpServers"].get("aegis") or data["mcpServers"].get("soma")
        # Check cwd and AEGIS_ROOT are relative (not absolute)
        cfg_str = json.dumps(soma_cfg)
        assert "/home/" not in cfg_str, f"Absolute path detected in MCP config: {cfg_str}"

    def test_init_mcp_merges_existing(self, tmp_path):
        """--mcp should merge into existing .mcp.json, not clobber."""
        mcp_file = tmp_path / ".mcp.json"
        existing = {
            "mcpServers": {
                "gemini-api-docs": {"command": "npx", "args": ["gemini-docs"]}
            }
        }
        mcp_file.write_text(json.dumps(existing))

        _run_init_mcp(tmp_path)

        data = json.loads(mcp_file.read_text())
        assert "gemini-api-docs" in data["mcpServers"], "Existing server was clobbered"
        assert "aegis" in data["mcpServers"] or "soma" in data["mcpServers"]

    def test_init_mcp_dry_run_no_file(self, tmp_path):
        """--mcp --dry-run should NOT create .mcp.json."""
        _run_init_mcp(tmp_path, ["--dry-run"])
        mcp_file = tmp_path / ".mcp.json"
        assert not mcp_file.exists(), ".mcp.json should not be created during dry run"

    def test_init_mcp_idempotent(self, tmp_path):
        """Running --mcp twice should not duplicate config."""
        _run_init_mcp(tmp_path)
        _run_init_mcp(tmp_path)
        mcp_file = tmp_path / ".mcp.json"
        data = json.loads(mcp_file.read_text())
        # Should still have exactly one entry
        cfg = data["mcpServers"].get("aegis") or data["mcpServers"].get("soma")
        assert isinstance(cfg, dict), (
            "Server config should be a dict, not duplicated"
        )


# ── TDD Red Phase: Integration ─────────────────────────────────────────────


class TestInitIntegration:
    """Combined --rules and --mcp integration tests."""

    def test_init_full_with_mcp(self, tmp_path):
        """--rules full --mcp should install all rules AND create MCP config."""
        from aegis_cli.cli import _build_parser
        from aegis_cli.init import run_init

        argv = ["init", "--platform", "gemini", "--yes",
                "--rules", "full", "--mcp"]
        parser = _build_parser()
        args = parser.parse_args(argv)
        args._project_root = tmp_path
        args._home = tmp_path

        rc = run_init(args)
        assert rc == 0

        assert _installed_rules(tmp_path) == FULL_PRESET

        # MCP config exists
        mcp_file = tmp_path / ".mcp.json"
        assert mcp_file.exists(), ".mcp.json was not created"
        data = json.loads(mcp_file.read_text())
        assert "aegis" in data.get("mcpServers", {}) or "soma" in data.get("mcpServers", {})


# ── Registry-only dispatch ──────────────────────────────────────────────────


def test_main_dispatches_through_the_registry(tmp_path, monkeypatch):
    from aegis_cli.base import CommandCategory, AegisCommand
    from aegis_cli.registry import CommandRegistry

    seen = []

    class CustomTestCommand(AegisCommand):
        name = "custom-test"
        category = CommandCategory.WORKFLOW
        help = "Custom test command"

        def configure_parser(self, parser):
            parser.add_argument("--flag", action="store_true")

        def execute(self, args):
            seen.append((args.command, args.flag, args.workspace))
            return 7

    reg = CommandRegistry()
    reg.register(CustomTestCommand)
    monkeypatch.setattr(cli, "get_default_registry", lambda: reg)
    (tmp_path / ".aegis" / "rules").mkdir(parents=True)

    assert cli.main(["custom-test", "--flag", "--workspace", str(tmp_path)]) == 7
    assert seen == [("custom-test", True, str(tmp_path.resolve()))]


def test_command_exception_is_reported_and_exits_1(tmp_path, monkeypatch, capsys):
    from aegis_cli.base import CommandCategory, AegisCommand
    from aegis_cli.registry import CommandRegistry

    class BoomCommand(AegisCommand):
        name = "boom"
        category = CommandCategory.WORKFLOW
        help = "Raises"

        def configure_parser(self, parser):
            pass

        def execute(self, args):
            raise RuntimeError("kaboom")

    reg = CommandRegistry()
    reg.register(BoomCommand)
    monkeypatch.setattr(cli, "get_default_registry", lambda: reg)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["boom"]) == 1
    assert capsys.readouterr().err == "Error: kaboom\n"
