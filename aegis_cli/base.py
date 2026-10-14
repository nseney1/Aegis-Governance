"""Declarative CLI Command Protocol and Category Definitions."""
from __future__ import annotations

from abc import ABC, abstractmethod
import argparse
from enum import Enum
from typing import Optional, Tuple

__all__ = ["CommandCategory", "SomaCommand"]


class CommandCategory(str, Enum):
    """Categorical grouping for Soma commands in help screens and documentation."""
    SETUP = "Setup & Environment"
    WORKFLOW = "Daily Workflow & Verification"
    LIFECYCLE = "Rule Evolution & Intelligence"
    PLUMBING = "Plumbing & Swarm Protocol"


class SomaCommand(ABC):
    """Abstract Base Class defining the lifecycle contract for all Soma CLI subcommands."""

    name: str
    aliases: Tuple[str, ...] = ()
    category: CommandCategory
    help: str
    description: Optional[str] = None

    def get_names(self) -> Tuple[str, ...]:
        """Return the primary command name and all registered aliases."""
        return (self.name, *self.aliases)

    @abstractmethod
    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        """Register command-specific flags and arguments onto its subparser."""
        ...

    @abstractmethod
    def execute(self, args: argparse.Namespace) -> int:
        """Execute command logic. Common options are pre-handled by the dispatcher."""
        ...
