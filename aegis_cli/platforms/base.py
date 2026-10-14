"""Abstract base class and models for platform installation adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
from typing import Any, Optional


__all__ = ["PlatformAdapter", "PlatformInstallResult", "detect_platform", "get_rules_dir"]


def detect_platform(project_root: Path | str) -> str:
    """Detect the AI platform from directory markers.

    Returns: 'gemini' | 'claude' | 'cursor' | 'copilot' | 'kiro' | 'unknown'
    """
    project_root = Path(project_root)

    if (project_root / ".gemini").is_dir():
        return "gemini"
    if (project_root / ".claude").is_dir():
        return "claude"
    if (project_root / ".cursor").is_dir() or (project_root / ".cursorrules").is_file():
        return "cursor"
    if (project_root / ".github" / "copilot").is_dir() or (project_root / ".github" / "copilot-instructions.md").is_file():
        return "copilot"
    if (project_root / ".kiro").is_dir():
        return "kiro"

    return "unknown"


def get_rules_dir(
    platform: str,
    home: Path | None = None,
    project_root: Path | None = None,
    local: bool = False,
) -> Path:
    """Return the target rules directory for the given platform."""
    if home is None:
        home = Path(os.environ.get("HOME") or Path.home())
    home = Path(home)
    if project_root is None:
        project_root = Path.cwd()
    project_root = Path(project_root)

    if local:
        local_dirs = {
            "gemini": project_root / ".gemini" / "rules",
            "claude": project_root / ".claude",
            "cursor": project_root / ".cursor" / "rules",
            "copilot": project_root / ".github" / "copilot",
            "kiro": project_root / ".kiro" / "steering",
        }
        if platform not in local_dirs:
            raise ValueError(
                f"Unsupported platform: '{platform}'. "
                f"Supported: {', '.join(sorted(local_dirs))}"
            )
        return local_dirs[platform]

    dirs = {
        "gemini": home / ".gemini" / "config" / "rules",
        "claude": home / ".claude",
        "cursor": home / ".cursor" / "rules",
        "copilot": project_root / ".github" / "copilot",
        "kiro": home / ".kiro" / "steering",
    }
    if platform not in dirs:
        raise ValueError(
            f"Unsupported platform: '{platform}'. "
            f"Supported: {', '.join(sorted(dirs))}"
        )
    return dirs[platform]


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
        """Locate genome rules in repository workspace or bundled rules/starter_rules."""
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
            pkg_rules = Path(str(importlib.resources.files("rules")))
            if pkg_rules.is_dir():
                rules = [p for p in pkg_rules.glob("*.md") if p.name not in {"README.md", "__init__.py"}]
                oracles_dir = pkg_rules / ".oracles"
                if oracles_dir.is_dir():
                    rules.extend([p for p in oracles_dir.glob("*.md") if p.name not in {"README.md", "__init__.py"}])
                if rules:
                    return sorted(rules)
        except Exception:
            pass
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
        """Locate skills in repository workspace or bundled skills package."""
        skills_dir = (self.workspace / "skills") if (self.workspace / "skills").is_dir() else (self.workspace / "organs")
        if skills_dir.is_dir():
            skills = [
                d for d in skills_dir.iterdir()
                if d.is_dir() and (d / "SKILL.md").is_file()
            ]
            if skills:
                return sorted(skills)
        try:
            import importlib.resources
            pkg_skills = Path(str(importlib.resources.files("skills")))
            if pkg_skills.is_dir():
                return sorted([
                    d for d in pkg_skills.iterdir()
                    if d.is_dir() and (d / "SKILL.md").is_file()
                ])
        except Exception:
            pass
        return []

    def render_mcp_entry(self, local: bool = False, command: str = "soma-mcp") -> dict[str, Any]:
        """Render MCP server entry; include AEGIS_WORKSPACE only for local installs."""
        entry: dict[str, Any] = {
            "command": command,
            "args": [],
        }
        if local:
            entry["env"] = {"AEGIS_WORKSPACE": str(self.workspace)}
        return entry

    def render_mcp_config(self, local: bool = False) -> dict[str, Any]:
        """Render standard MCP server configuration."""
        return {
            "mcpServers": {
                "soma": self.render_mcp_entry(local=local),
            }
        }

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

