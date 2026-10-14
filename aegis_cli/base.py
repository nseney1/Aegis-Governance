"""Declarative CLI Command Protocol and Category Definitions."""
from __future__ import annotations

from abc import ABC, abstractmethod
import argparse
from enum import Enum
from typing import Optional, Tuple

__all__ = ["CommandCategory", "AegisCommand", "SomaCommand"]


class CommandCategory(str, Enum):
    """Categorical grouping for Aegis commands in help screens and documentation."""
    SETUP = "Setup & Environment"
    WORKFLOW = "Daily Workflow & Verification"
    LIFECYCLE = "Rule Evolution & Intelligence"
    PLUMBING = "Plumbing & Swarm Protocol"


class AegisCommand(ABC):
    """Abstract Base Class defining the lifecycle contract for all Aegis CLI subcommands."""

    name: str
    aliases: Tuple[str, ...] = ()
    category: CommandCategory
    help: str
    description: Optional[str] = None

    def get_names(self) -> Tuple[str, ...]:
        """Return the primary command name and all registered aliases."""
        return (self.name, *self.aliases)

    def get_ui(self, args: Optional[argparse.Namespace] = None) -> "OutputContext":
        """Resolve or create the OutputContext for this command invocation."""
        from aegis_cli.ui.theme import OutputContext
        existing = getattr(args, "ui", None) if args is not None else None
        if isinstance(existing, OutputContext):
            return existing
        return OutputContext.from_env_and_args(args)

    @abstractmethod
    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        """Register command-specific flags and arguments onto its subparser."""
        ...

    @abstractmethod
    def execute(self, args: argparse.Namespace) -> int:
        """Execute command logic. Common options are pre-handled by the dispatcher."""
        ...


SomaCommand = AegisCommand
