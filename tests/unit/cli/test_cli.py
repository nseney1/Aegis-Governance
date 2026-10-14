from pathlib import Path
"""Tests for soma_cli — Phase A test gate.

Verifies the CLI skeleton installs correctly and all subcommands
have help text and exit cleanly.
"""
import os
import subprocess
import sys

import pytest

import aegis_cli.cli as cli


SUBCOMMANDS = ["init", "status", "check", "rule", "system"]


class TestCLIImport:
    """Verify the CLI module is importable without side effects."""

    def test_cli_importable(self):
        from aegis_cli.cli import main
        assert callable(main)

    def test_cli_build_parser(self):
        from aegis_cli.cli import _build_parser
        parser = _build_parser()
        assert parser.prog in ("aegis", "soma")


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
        ("system", ["doctor"]),
    ])
    def test_subcommand_runs_without_crash(self, cmd, extra_args, capsys):
        from aegis_cli.cli import main
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

    def test_soma_dash_dash_help_via_subprocess(self):
        """Run `python -m aegis_cli.cli --help` to test without requiring
        pip install."""
        repo_root = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
        proc = subprocess.run(
            [sys.executable, "-m", "aegis_cli.cli", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=repo_root,
        )
        assert proc.returncode == 0
        assert "Aegis Governance" in proc.stdout or "Soma Governance" in proc.stdout


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


class TestRulePresetFull:
    """--rules full should discover and install all genome rules."""

    def test_init_full_discovers_genome_rules(self, tmp_path):
        """--rules full should install more rules than standard."""
        rc = _run_init_in(tmp_path, ["--rules", "full"])
        assert rc == 0
        installed = _installed_rules(tmp_path)
        # genome/ has 11 files + .oracles/ has 8 files minus META.md = 18
        assert len(installed) > 5, (
            f"Full preset should install >5 rules, got {len(installed)}: {installed}"
        )

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

        # Rules: more than standard
        installed = _installed_rules(tmp_path)
        assert len(installed) > 5, f"Full preset should install >5 rules, got {len(installed)}"

        # MCP config exists
        mcp_file = tmp_path / ".mcp.json"
        assert mcp_file.exists(), ".mcp.json was not created"
        data = json.loads(mcp_file.read_text())
        assert "aegis" in data.get("mcpServers", {}) or "soma" in data.get("mcpServers", {})


# ── Porcelain CLI Facade Tests ─────────────────────────────────────────────


class TestPorcelainCLIFacade:
    """Verify porcelain subcommands, aliases, and plumbing flags."""

    def test_rules_alias_dispatches_same_as_status(self, monkeypatch):
        from aegis_cli import cli
        assert cli.COMMANDS["rules"] is cli.COMMANDS["status"]
        dispatched = []
        monkeypatch.setitem(cli.COMMANDS, "status", lambda args: dispatched.append(args.command) or 0)
        monkeypatch.setitem(cli.COMMANDS, "rules", lambda args: dispatched.append(args.command) or 0)
        assert cli.main(["status"]) == 0
        assert cli.main(["rules"]) == 0
        assert dispatched == ["status", "rules"]

    @pytest.mark.parametrize("flag", ["--plumbing", "--internal"])
    def test_root_plumbing_flags_parse(self, flag):
        from aegis_cli.cli import _build_parser, main
        parser = _build_parser()
        args = parser.parse_args([flag, "rules"])
        assert getattr(args, "plumbing", False) is True

        # Test main handles root-level flag without crashing
        assert main([flag, "rules"]) in (0, 1)

    def test_global_flags_verbose_quiet_format(self):
        from aegis_cli.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["rules", "--format", "json", "-v", "-q"])
        assert args.format == "json"
        assert args.verbose is True
        assert args.quiet is True

    def test_subparsers_use_soma_parser_class(self):
        from aegis_cli.cli import _build_parser, SomaParser
        parser = _build_parser()
        for action in parser._actions:
            if hasattr(action, "choices") and isinstance(action.choices, dict):
                for subparser in action.choices.values():
                    assert isinstance(subparser, SomaParser)


def test_cli_registry_fallback_dispatch(tmp_path):
    # If a command is in registry but not in COMMANDS dict
    import argparse
    from unittest.mock import MagicMock, patch
    from aegis_cli.base import CommandCategory, SomaCommand
    from aegis_cli.registry import CommandRegistry

    class CustomTestCommand(SomaCommand):
        name = "custom-test"
        category = CommandCategory.WORKFLOW
        help = "Custom test command"
        def configure_parser(self, parser): pass
        def execute(self, args): return 0

    test_reg = CommandRegistry()
    cmd = CustomTestCommand()
    test_reg.register(cmd)

    # Dispatch via registry fallback
    ns = argparse.Namespace(command="custom-test", workspace=str(tmp_path), format=None, json=False, plumbing=False)
    with patch.object(cli, "_build_parser") as mock_build, \
         patch("aegis_cli.cli.get_default_registry", return_value=test_reg):
        parser_mock = MagicMock()
        parser_mock.parse_args.return_value = ns
        mock_build.return_value = parser_mock
        rc = cli.main(["custom-test", "--workspace", str(tmp_path)])
        assert rc == 0

    # Test unknown command prints help and returns 1
    ns_unknown = argparse.Namespace(command="definitely-unknown-xyz", workspace=str(tmp_path), format=None, json=False, plumbing=False)
    with patch.object(cli, "_build_parser") as mock_build:
        parser_mock = MagicMock()
        parser_mock.parse_args.return_value = ns_unknown
        mock_build.return_value = parser_mock
        rc = cli.main(["definitely-unknown-xyz"])
        assert rc == 1
        parser_mock.print_help.assert_called()


def test_cmd_handlers_direct():
    import aegis_cli.check
    import aegis_cli.rule
    import aegis_cli.system
    import aegis_cli.agent
    from aegis_cli.cli import cmd_check, cmd_rule, cmd_system, cmd_agent, cmd_verify, cmd_checkpoint
    from aegis_cli.verify import run_verify
    import argparse
    from unittest.mock import patch

    with patch.object(aegis_cli.check, "run_check", return_value=0):
        assert cmd_check(argparse.Namespace()) == 0
        assert cmd_verify(argparse.Namespace()) == 0
        assert cmd_checkpoint(argparse.Namespace()) == 0
        assert run_verify(argparse.Namespace(hook=True)) == 0
    with patch.object(aegis_cli.rule, "run_rule", return_value=0):
        assert cmd_rule(argparse.Namespace()) == 0
    with patch.object(aegis_cli.system, "run_system", return_value=0):
        assert cmd_system(argparse.Namespace()) == 0
    with patch.object(aegis_cli.agent, "run_agent", return_value=0):
        assert cmd_agent(argparse.Namespace()) == 0






