"""GitHub Copilot platform installation adapter."""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from aegis_cli.platforms.base import PlatformAdapter, PlatformInstallResult


__all__ = ["CopilotAdapter"]


class CopilotAdapter(PlatformAdapter):
    """Platform adapter for GitHub Copilot Workspace and CLI."""

    name: str = "copilot"

    def get_target_files(self) -> tuple[Path, Path]:
        """Return (instructions_file, instructions_dir)."""
        github_dir = self.workspace / ".github"
        return github_dir / "copilot-instructions.md", github_dir / "instructions"

    def render_config(self) -> str:
        rules = self.get_source_rules()
        rule_lines = "\n".join(f"- **{r.stem}**: See `.github/instructions/{r.name}`" for r in rules)
        return (
            "# GitHub Copilot Governance Instructions\n\n"
            "This repository uses Soma Governance rules:\n\n"
            f"{rule_lines}\n"
        )

    def install(self, local: bool = False, dry_run: bool = False) -> PlatformInstallResult:
        result = PlatformInstallResult(
            platform=self.name,
            success=True,
            scope="local",
        )
        instructions_file, instructions_dir = self.get_target_files()

        if not dry_run:
            instructions_dir.mkdir(parents=True, exist_ok=True)

        # Write main instructions file
        content = self.render_config()
        if dry_run:
            result.installed_files.append(instructions_file)
        else:
            try:
                instructions_file.write_text(content, encoding="utf-8")
                result.installed_files.append(instructions_file)
            except Exception as exc:
                result.errors.append(f"Failed to write {instructions_file}: {exc}")
                result.success = False

        # Copy detailed rules into .github/instructions/
        for src_rule in self.get_source_rules():
            dest = instructions_dir / src_rule.name
            if dry_run:
                result.installed_files.append(dest)
            else:
                try:
                    shutil.copy2(src_rule, dest)
                    result.installed_files.append(dest)
                except Exception as exc:
                    result.errors.append(f"Failed to copy rule {src_rule.name}: {exc}")
                    result.success = False

        result.messages.append(f"Installed Copilot governance to {instructions_file}")
        return result

    def uninstall(self, local: bool = False, dry_run: bool = False) -> PlatformInstallResult:
        result = PlatformInstallResult(
            platform=self.name,
            success=True,
            scope="local",
        )
        instructions_file, instructions_dir = self.get_target_files()

        if instructions_file.is_file():
            if dry_run:
                result.uninstalled_files.append(instructions_file)
            else:
                try:
                    instructions_file.unlink()
                    result.uninstalled_files.append(instructions_file)
                except Exception as exc:
                    result.errors.append(f"Failed to remove {instructions_file}: {exc}")
                    result.success = False

        if instructions_dir.is_dir():
            if dry_run:
                result.uninstalled_files.append(instructions_dir)
            else:
                try:
                    shutil.rmtree(instructions_dir)
                    result.uninstalled_files.append(instructions_dir)
                except Exception as exc:
                    result.errors.append(f"Failed to remove {instructions_dir}: {exc}")
                    result.success = False

        action = "[dry-run] Would uninstall" if dry_run else "Uninstalled"
        result.messages.append(f"{action} Copilot governance from {self.workspace}")
        return result

    def verify(self, local: bool = False) -> bool:
        instructions_file, _ = self.get_target_files()
        return instructions_file.is_file()
