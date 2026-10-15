"""Gemini platform installation adapter."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

from aegis_cli.platforms.base import PlatformAdapter, PlatformInstallResult


class GeminiAdapter(PlatformAdapter):
    """Platform adapter for Google Gemini / Antigravity environments."""

    name: str = "gemini"

    def get_target_dirs(self, local: bool = False) -> tuple[Path, Path, Path]:
        """Return (rules_dir, skills_dir, hooks_dir)."""
        if local:
            base = self.workspace / ".aegis"
            return base / "rules", base / "skills", base / "plugins" / "governance"
        base = self.home / ".gemini" / "config"
        return base / "rules", base / "skills", base / "plugins" / "governance"

    def install(self, local: bool = False, dry_run: bool = False) -> PlatformInstallResult:
        result = PlatformInstallResult(
            platform=self.name,
            success=True,
            scope="local" if local else "global",
        )
        rules_dir, skills_dir, hooks_dir = self.get_target_dirs(local=local)

        if not dry_run:
            rules_dir.mkdir(parents=True, exist_ok=True)
            skills_dir.mkdir(parents=True, exist_ok=True)
            hooks_dir.mkdir(parents=True, exist_ok=True)

        # 1. Install rules
        for src_rule in self.get_source_rules():
            dest = (
                (rules_dir / ".oracles" / src_rule.name)
                if src_rule.parent.name == ".oracles"
                else (rules_dir / src_rule.name)
            )
            if dry_run:
                result.installed_files.append(dest)
            else:
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_rule, dest)
                    result.installed_files.append(dest)
                except Exception as exc:
                    result.errors.append(f"Failed to copy rule {src_rule.name}: {exc}")
                    result.success = False

        # 2. Install skills
        for src_skill_dir in self.get_source_skills():
            dest_skill_dir = skills_dir / src_skill_dir.name
            if dry_run:
                result.installed_files.append(dest_skill_dir / "SKILL.md")
            else:
                try:
                    if dest_skill_dir.exists():
                        shutil.rmtree(dest_skill_dir)
                    shutil.copytree(src_skill_dir, dest_skill_dir)
                    result.installed_files.append(dest_skill_dir / "SKILL.md")
                except Exception as exc:
                    result.errors.append(f"Failed to copy skill {src_skill_dir.name}: {exc}")
                    result.success = False

        # 3. Install hooks configuration
        hooks_dest = hooks_dir / "hooks.json"
        hooks_config = self.render_config()
        if dry_run:
            result.installed_files.append(hooks_dest)
        else:
            try:
                hooks_dest.write_text(json.dumps(hooks_config, indent=2), encoding="utf-8")
                result.installed_files.append(hooks_dest)
            except Exception as exc:
                result.errors.append(f"Failed to write hooks.json: {exc}")
                result.success = False

        result.messages.append(
            f"Successfully installed {len(result.installed_files)} items to {self.name} ({result.scope})"
        )
        return result

    def uninstall(self, local: bool = False, dry_run: bool = False) -> PlatformInstallResult:
        result = PlatformInstallResult(
            platform=self.name,
            success=True,
            scope="local" if local else "global",
        )
        rules_dir, skills_dir, hooks_dir = self.get_target_dirs(local=local)

        # Remove rules
        for src_rule in self.get_source_rules():
            dest = (
                (rules_dir / ".oracles" / src_rule.name)
                if src_rule.parent.name == ".oracles"
                else (rules_dir / src_rule.name)
            )
            if dest.is_file():
                if dry_run:
                    result.uninstalled_files.append(dest)
                else:
                    try:
                        dest.unlink()
                        result.uninstalled_files.append(dest)
                    except Exception as exc:
                        result.errors.append(f"Failed to remove {dest}: {exc}")
                        result.success = False

        # Remove skills
        for src_skill_dir in self.get_source_skills():
            dest_skill_dir = skills_dir / src_skill_dir.name
            if dest_skill_dir.is_dir():
                if dry_run:
                    result.uninstalled_files.append(dest_skill_dir)
                else:
                    try:
                        shutil.rmtree(dest_skill_dir)
                        result.uninstalled_files.append(dest_skill_dir)
                    except Exception as exc:
                        result.errors.append(f"Failed to remove {dest_skill_dir}: {exc}")
                        result.success = False

        # Remove hooks
        hooks_dest = hooks_dir / "hooks.json"
        if hooks_dest.is_file():
            if dry_run:
                result.uninstalled_files.append(hooks_dest)
            else:
                try:
                    hooks_dest.unlink()
                    result.uninstalled_files.append(hooks_dest)
                except Exception as exc:
                    result.errors.append(f"Failed to remove {hooks_dest}: {exc}")
                    result.success = False

        result.messages.append(
            f"Uninstalled {len(result.uninstalled_files)} items from {self.name} ({result.scope})"
        )
        return result

    def verify(self, local: bool = False) -> bool:
        rules_dir, skills_dir, hooks_dir = self.get_target_dirs(local=local)
        if not rules_dir.is_dir() or not (hooks_dir / "hooks.json").is_file():
            return False
        # Check that core rules are present
        source_rules = self.get_source_rules()
        if source_rules and not any((rules_dir / r.name).is_file() for r in source_rules):
            return False
        return True

    def render_config(self) -> dict[str, Any]:
        """Render the Gemini/Antigravity hooks configuration.

        v4 cut the agent-side lifecycle phases (D15); only the safety gate
        remains, so a hooks.json written now never calls a removed command.
        """
        return {
            "safety-gate": {
                "PreToolUse": [
                    {
                        "matcher": "run_command",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "aegis hook safety-gate",
                                "timeout": 5,
                            }
                        ],
                    }
                ]
            },
        }


GeminiPlatformAdapter = GeminiAdapter

__all__ = ["GeminiAdapter", "GeminiPlatformAdapter"]

