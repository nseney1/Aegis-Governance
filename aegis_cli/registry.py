"""Centralized registry for Soma CLI commands with categorization and alias resolution."""
from __future__ import annotations

import argparse
from typing import Any, Dict, List, Optional, Sequence, Union

from aegis_cli.base import CommandCategory, AegisCommand

__all__ = ["CommandRegistry", "create_default_registry", "get_default_registry"]


class CommandRegistry:
    """Registry maintaining active Soma commands, aliases, and categorized discovery."""

    def __init__(self) -> None:
        self._commands: Dict[str, AegisCommand] = {}
        self._alias_map: Dict[str, AegisCommand] = {}

    def register(self, command: Union[AegisCommand, type[AegisCommand]]) -> None:
        """Register a command instance or class into the registry."""
        inst = command() if isinstance(command, type) else command
        self._commands[inst.name] = inst
        self._alias_map[inst.name] = inst
        for alias in inst.aliases:
            self._alias_map[alias] = inst

    def get(self, name_or_alias: str) -> Optional[AegisCommand]:
        """Resolve a command by its primary name or alias."""
        return self._alias_map.get(name_or_alias)

    def list_commands(self) -> List[AegisCommand]:
        """Return all unique registered primary commands."""
        return list(self._commands.values())

    def get_by_category(self, category: CommandCategory) -> List[AegisCommand]:
        """Return all registered commands belonging to a specific category."""
        return [c for c in self._commands.values() if c.category == category]

    def populate_subparsers(
        self,
        subparsers: Any,
        common_parser: Optional[argparse.ArgumentParser] = None,
    ) -> Dict[str, argparse.ArgumentParser]:
        """Configure subparsers for all registered commands."""
        parsers: Dict[str, argparse.ArgumentParser] = {}
        parents = [common_parser] if common_parser else []

        for cmd in self._commands.values():
            kwargs: Dict[str, Any] = {
                "help": cmd.help,
                "parents": parents,
            }
            if cmd.aliases:
                kwargs["aliases"] = list(cmd.aliases)
            if cmd.description:
                kwargs["description"] = cmd.description

            sub_p = subparsers.add_parser(cmd.name, **kwargs)
            try:
                cmd.configure_parser(sub_p, parents=parents)
            except TypeError:
                cmd.configure_parser(sub_p)
            parsers[cmd.name] = sub_p

        return parsers

    def format_categorized_help(
        self,
        prog: str = "aegis",
        ctx: Optional[Any] = None,
    ) -> str:
        """Render standard grouped help message showing commands by logical category."""
        from aegis_cli.ui.table import Grid
        from aegis_cli.ui.theme import OutputContext

        ui = ctx if isinstance(ctx, OutputContext) else OutputContext()
        prog_title = "Aegis" if prog == "aegis" else "Soma"
        title_line = ui.style(
            f"{prog_title} Governance — make AI coding agents trustworthy",
            "bold",
            "cyan",
        )
        lines = [
            title_line,
            "",
            f"usage: {prog} <command> [options]",
            "",
        ]

        categories = [
            CommandCategory.SETUP,
            CommandCategory.WORKFLOW,
            CommandCategory.LIFECYCLE,
            CommandCategory.PLUMBING,
        ]

        max_name_len = max((len(c.name) for c in self._commands.values()), default=12)
        col_width = max(max_name_len + 2, 14)

        for cat in categories:
            cmds = self.get_by_category(cat)
            if not cmds:
                continue

            lines.append(ui.style(f"{cat.value}:", "bold"))
            grid = Grid(ctx=ui, padding=2)
            grid.add_column(style="green")
            grid.add_column()
            for cmd in sorted(cmds, key=lambda c: c.name):
                alias_str = f" (aliases: {', '.join(cmd.aliases)})" if cmd.aliases else ""
                padded_name = f"  {cmd.name:<{col_width - 2}}"
                grid.add_row(padded_name, f"{cmd.help}{alias_str}")
            lines.append(grid.render(ui))
            lines.append("")

        lines.extend([
            ui.style("Common Options:", "bold"),
            "  --workspace PATH   Target workspace directory (default: current directory)",
            "  --json             Output results as machine-readable JSON",
            "  --plain            Disable emoji and rich styling",
            "  -v, --verbose      Enable detailed debug logging",
            "  -h, --help         Show this help message and exit",
            "",
            f"Run '{prog} <command> --help' for details on a specific command.",
        ])

        return "\n".join(lines)


_DEFAULT_REGISTRY: Optional[CommandRegistry] = None


def create_default_registry() -> CommandRegistry:
    """Create and populate a CommandRegistry with canonical verbs + plumbing."""
    reg = CommandRegistry()

    # Category 1: Setup & Environment
    from aegis_cli.doctor import DoctorCommand
    from aegis_cli.init import InitCommand
    from aegis_cli.install import InstallCommand, UninstallCommand
    from aegis_cli.migrate import MigrateCommand
    from aegis_cli.system import SystemCommand

    # Category 2: Daily Workflow & Verification
    from aegis_cli.check import CheckCommand
    from aegis_cli.report import ReportCommand
    from aegis_cli.status import StatusCommand

    # Category 3: Rule Evolution & Intelligence
    from aegis_cli.rule import RuleCommand

    # Category 4: Plumbing & Machine Protocol
    from aegis_cli.agent import AgentCommand
    from aegis_cli.completion import CompletionCommand
    from aegis_cli.hooks import HookCommand

    for cmd_cls in (
        InitCommand,
        InstallCommand,
        UninstallCommand,
        MigrateCommand,
        DoctorCommand,
        SystemCommand,
        CheckCommand,
        StatusCommand,
        ReportCommand,
        RuleCommand,
        AgentCommand,
        CompletionCommand,
        HookCommand,
    ):
        reg.register(cmd_cls)

    return reg


def get_default_registry() -> CommandRegistry:
    """Return the cached default CommandRegistry singleton."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = create_default_registry()
    return _DEFAULT_REGISTRY
