"""Contract and behavioral invariants for AegisCommand protocol and CommandRegistry."""
from __future__ import annotations

import argparse
import pytest

from aegis_cli.base import CommandCategory, AegisCommand
from aegis_cli.registry import CommandRegistry, get_default_registry


class DummyInitCommand(AegisCommand):
    name = "dummy-init"
    aliases = ("d-init", "di")
    category = CommandCategory.SETUP
    help = "Dummy initialization command"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--flag", action="store_true", help="Sample flag")

    def execute(self, args: argparse.Namespace) -> int:
        return 42 if getattr(args, "flag", False) else 0


class DummyVerifyCommand(AegisCommand):
    name = "dummy-verify"
    aliases = ("dv",)
    category = CommandCategory.WORKFLOW
    help = "Dummy verification command"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--strict", action="store_true")

    def execute(self, args: argparse.Namespace) -> int:
        return 1 if getattr(args, "strict", False) else 0


def test_command_abstract_contract():
    # Attempting to instantiate incomplete subclass should fail
    class IncompleteCommand(AegisCommand):
        pass

    with pytest.raises(TypeError):
        IncompleteCommand()


def test_command_attributes():
    cmd = DummyInitCommand()
    assert cmd.name == "dummy-init"
    assert "d-init" in cmd.aliases
    assert cmd.category == CommandCategory.SETUP
    assert cmd.help == "Dummy initialization command"
    assert cmd.get_names() == ("dummy-init", "d-init", "di")


def test_registry_registration_and_lookup():
    reg = CommandRegistry()
    init_cmd = DummyInitCommand()
    verify_cmd = DummyVerifyCommand()

    reg.register(init_cmd)
    reg.register(verify_cmd)

    # Lookup by primary name
    assert reg.get("dummy-init") is init_cmd
    assert reg.get("dummy-verify") is verify_cmd

    # Lookup by alias
    assert reg.get("d-init") is init_cmd
    assert reg.get("di") is init_cmd
    assert reg.get("dv") is verify_cmd

    # Lookup missing
    assert reg.get("nonexistent") is None


def test_registry_category_filtering():
    reg = CommandRegistry()
    init_cmd = DummyInitCommand()
    verify_cmd = DummyVerifyCommand()
    reg.register(init_cmd)
    reg.register(verify_cmd)

    setup_cmds = reg.get_by_category(CommandCategory.SETUP)
    assert init_cmd in setup_cmds
    assert verify_cmd not in setup_cmds

    workflow_cmds = reg.get_by_category(CommandCategory.WORKFLOW)
    assert verify_cmd in workflow_cmds
    assert init_cmd not in workflow_cmds


def test_registry_populates_argparse_subparsers():
    parser = argparse.ArgumentParser(prog="soma")
    sub = parser.add_subparsers(dest="command")

    reg = CommandRegistry()
    reg.register(DummyInitCommand())

    subparsers = reg.populate_subparsers(sub)
    assert "dummy-init" in subparsers

    # Test argument parsing
    args = parser.parse_args(["dummy-init", "--flag"])
    assert args.command == "dummy-init"
    assert args.flag is True

    # Test alias parsing
    args_alias = parser.parse_args(["d-init", "--flag"])
    assert args_alias.command in ("dummy-init", "d-init")
    assert args_alias.flag is True


def test_registry_formatted_help():
    reg = CommandRegistry()
    reg.register(DummyInitCommand())
    reg.register(DummyVerifyCommand())

    help_text = reg.format_categorized_help(prog="soma")
    assert "Setup & Environment:" in help_text
    assert "dummy-init" in help_text
    assert "Daily Workflow & Verification:" in help_text
    assert "dummy-verify" in help_text


def test_category_1_setup_commands():
    from aegis_cli.init import InitCommand
    from aegis_cli.system import SystemCommand

    cmds = [InitCommand(), SystemCommand()]
    reg = CommandRegistry()

    for cmd in cmds:
        assert cmd.category == CommandCategory.SETUP
        assert cmd.name in ("init", "system")
        reg.register(cmd)

    # Verify alias resolution
    assert reg.get("sys").name == "system"

    # Verify subparser creation
    parser = argparse.ArgumentParser(prog="aegis")
    sub = parser.add_subparsers(dest="command")
    reg.populate_subparsers(sub)

    args = parser.parse_args(["init", "--dry-run"])
    assert args.command == "init"
    assert args.dry_run is True

    args_sys = parser.parse_args(["system", "doctor", "--json"])
    assert args_sys.command == "system"
    assert args_sys.system_action == "doctor"
    assert args_sys.json is True


def test_category_2_workflow_commands():
    from aegis_cli.check import CheckCommand
    from aegis_cli.status import StatusCommand

    cmds = [CheckCommand(), StatusCommand()]
    reg = CommandRegistry()

    for cmd in cmds:
        assert cmd.category == CommandCategory.WORKFLOW
        assert cmd.name in ("check", "status")
        reg.register(cmd)

    # Verify alias resolution
    assert reg.get("verify").name == "check"
    assert reg.get("checkpoint").name == "check"
    assert reg.get("rules").name == "status"

    # Verify subparser creation
    parser = argparse.ArgumentParser(prog="aegis")
    sub = parser.add_subparsers(dest="command")
    reg.populate_subparsers(sub)

    args = parser.parse_args(["check", "--hook"])
    assert args.command == "check"
    assert args.hook is True

    args_status = parser.parse_args(["status"])
    assert args_status.command == "status"


def test_category_3_lifecycle_commands():
    from aegis_cli.rule import RuleCommand

    cmd = RuleCommand()
    reg = CommandRegistry()
    assert cmd.category == CommandCategory.LIFECYCLE
    assert cmd.name == "rule"
    reg.register(cmd)

    # Verify subparser creation
    parser = argparse.ArgumentParser(prog="aegis")
    sub = parser.add_subparsers(dest="command")
    reg.populate_subparsers(sub)

    args = parser.parse_args(["rule", "promote", "test-rule", "--dry-run"])
    assert args.command == "rule"
    assert args.rule_action == "promote"
    assert args.rule_id == "test-rule"
    assert args.dry_run is True

    args_demote = parser.parse_args(["rule", "demote", "bad-rule"])
    assert args_demote.command == "rule"
    assert args_demote.rule_action == "demote"
    assert args_demote.rule_id == "bad-rule"

    args_clean = parser.parse_args(["rule", "clean", "--dry-run"])
    assert args_clean.command == "rule"
    assert args_clean.rule_action == "clean"
    assert args_clean.dry_run is True


def test_category_4_plumbing_commands():
    from aegis_cli.agent import AgentCommand
    from aegis_cli.completion import CompletionCommand
    from aegis_cli.hooks import HookCommand

    cmds = [AgentCommand(), CompletionCommand(), HookCommand()]
    reg = CommandRegistry()

    for cmd in cmds:
        assert cmd.category == CommandCategory.PLUMBING
        reg.register(cmd)

    parser = argparse.ArgumentParser(prog="aegis")
    sub = parser.add_subparsers(dest="command")
    reg.populate_subparsers(sub)

    args_agent = parser.parse_args(["agent", "scan"])
    assert args_agent.command == "agent"
    assert args_agent.agent_action == "scan"

    args_grade = parser.parse_args(["agent", "grade"])
    assert args_grade.command == "agent"
    assert args_grade.agent_action == "grade"

    args_comp = parser.parse_args(["completion", "bash"])
    assert args_comp.command == "completion"
    assert args_comp.shell == "bash"

    args_hook = parser.parse_args(["hook", "status"])
    assert args_hook.command == "hook"
    assert args_hook.hook_action == "status"


def test_default_registry_completeness():
    reg = get_default_registry()
    commands = reg.list_commands()
    assert len(commands) >= 13

    expected_verbs = {
        "init",
        "migrate",
        "system",
        "sys",
        "doctor",
        "report",
        "install",
        "uninstall",
        "check",
        "verify",
        "checkpoint",
        "status",
        "rules",
        "rule",
        "agent",
        "completion",
        "hook",
    }

    for verb in expected_verbs:
        cmd = reg.get(verb)
        assert cmd is not None, f"Verb '{verb}' missing from default registry"
        assert callable(cmd.execute)


def test_aegis_command_and_parser_attach_output_context():
    from aegis_cli.cli import _build_parser
    from aegis_cli.ui.theme import OutputContext

    parser = _build_parser(prog="aegis")
    args = parser.parse_args(["status", "--plain"])
    assert isinstance(getattr(args, "ui", None), OutputContext)
    assert args.ui.plain is True
    assert args.ui.color_enabled is False

    cmd = DummyInitCommand()
    ui = cmd.get_ui(args)
    assert isinstance(ui, OutputContext)
    assert ui.plain is True

