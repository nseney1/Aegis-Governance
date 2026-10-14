"""Abstract base class and models for platform installation adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
from typing import Any, Optional


__all__ = ["PlatformAdapter", "PlatformInstallResult"]


@dataclass
class PlatformInstallResult:
    """Result of a platform installation or uninstallation operation."""
    platform: str
    success: bool
    scope: str = "global"  # "global" or "local"
    installed_files: list[Path] = field(default_factory=list)
    uninstalled_files: list[Path] = field(default_factory=list)
    skipped_files: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


class PlatformAdapter(ABC):
    """Abstract platform adapter providing pure-Python installation and verification."""

    name: str = "base"

    def __init__(
        self,
        workspace: Path | str | None = None,
        home: Path | str | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve() if workspace else Path.cwd().resolve()
        self.home = Path(home).resolve() if home else Path.home().resolve()

    def get_source_rules(self) -> list[Path]:
        """Locate genome rules in repository workspace or bundled starter_rules."""
        rules_dir = (self.workspace / "rules") if (self.workspace / "rules").is_dir() else (self.workspace / "genome")
        if rules_dir.is_dir():
            rules = [p for p in rules_dir.glob("*.md") if p.name not in {"README.md"}]
            oracles_dir = rules_dir / ".oracles"
            if oracles_dir.is_dir():
                rules.extend([p for p in oracles_dir.glob("*.md") if p.name not in {"README.md"}])
            if rules:
                return sorted(rules)
        try:
            import importlib.resources
            pkg = importlib.resources.files("aegis_cli") / "starter_rules"
            pkg_path = Path(str(pkg))
            if pkg_path.is_dir():
                return sorted([p for p in pkg_path.glob("*.md") if p.name not in {"README.md"}])
        except Exception:
            pass
        fallback = Path(__file__).resolve().parent.parent / "starter_rules"
        if fallback.is_dir():
            return sorted([p for p in fallback.glob("*.md") if p.name not in {"README.md"}])
        return []

    def get_source_skills(self) -> list[Path]:
        """Locate skills/organs in repository workspace."""
        skills_dir = (self.workspace / "skills") if (self.workspace / "skills").is_dir() else (self.workspace / "organs")
        if not skills_dir.is_dir():
            return []
        skills = []
        for d in skills_dir.iterdir():
            if d.is_dir() and (d / "SKILL.md").is_file():
                skills.append(d)
        return sorted(skills)

    @abstractmethod
    def install(self, local: bool = False, dry_run: bool = False) -> PlatformInstallResult:
        """Install rules, skills, and configuration for this platform."""
        raise NotImplementedError

    @abstractmethod
    def uninstall(self, local: bool = False, dry_run: bool = False) -> PlatformInstallResult:
        """Uninstall rules, skills, and configuration for this platform."""
        raise NotImplementedError

    @abstractmethod
    def verify(self, local: bool = False) -> bool:
        """Verify that platform rules and configuration are correctly installed."""
        raise NotImplementedError

    @abstractmethod
    def render_config(self) -> dict[str, Any] | str:
        """Render the platform-specific configuration."""
        raise NotImplementedError
