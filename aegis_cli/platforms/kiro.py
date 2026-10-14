"""Kiro platform installation adapter."""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from aegis_cli.platforms.base import PlatformAdapter, PlatformInstallResult


class KiroAdapter(PlatformAdapter):
    """Platform adapter for Kiro steering environments."""

    name: str = "kiro"

    def get_target_dirs(self, local: bool = False) -> tuple[Path, Path]:
        """Return (steering_dir, skills_dir)."""
        if local:
            base = self.workspace / ".aegis"
            return base / "steering", base / "skills"
        base = self.home / ".kiro"
        return base / "steering", base / "skills"

    def install(self, local: bool = False, dry_run: bool = False) -> PlatformInstallResult:
        result = PlatformInstallResult(
            platform=self.name,
            success=True,
            scope="local" if local else "global",
        )
        steering_dir, skills_dir = self.get_target_dirs(local=local)

        if not dry_run:
            steering_dir.mkdir(parents=True, exist_ok=True)
            skills_dir.mkdir(parents=True, exist_ok=True)

        for src_rule in self.get_source_rules():
            dest = steering_dir / src_rule.name
            if dry_run:
                result.installed_files.append(dest)
            else:
                try:
                    shutil.copy2(src_rule, dest)
                    result.installed_files.append(dest)
                except Exception as exc:
                    result.errors.append(f"Failed to copy rule {src_rule.name}: {exc}")
                    result.success = False

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

        result.messages.append(f"Installed {len(result.installed_files)} items to {self.name}")
        return result

    def uninstall(self, local: bool = False, dry_run: bool = False) -> PlatformInstallResult:
        result = PlatformInstallResult(
            platform=self.name,
            success=True,
            scope="local" if local else "global",
        )
        steering_dir, skills_dir = self.get_target_dirs(local=local)

        for src_rule in self.get_source_rules():
            dest = steering_dir / src_rule.name
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

        result.messages.append(f"Uninstalled {len(result.uninstalled_files)} items from {self.name}")
        return result

    def verify(self, local: bool = False) -> bool:
        steering_dir, _ = self.get_target_dirs(local=local)
        if not steering_dir.is_dir():
            return False
        source_rules = self.get_source_rules()
        if source_rules and not any((steering_dir / r.name).is_file() for r in source_rules):
            return False
        return True

    def render_config(self) -> dict[str, Any]:
        return {"platform": "kiro", "steering_enabled": True}
