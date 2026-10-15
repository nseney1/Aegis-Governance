"""Claude platform installation adapter."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

from aegis_cli.platforms.base import (
    McpConfigError,
    PlatformAdapter,
    PlatformInstallResult,
    load_mcp_config,
    write_json_atomic,
)


SOMA_MARKER_START = "<!-- SOMA:START -->"
SOMA_MARKER_END = "<!-- SOMA:END -->"
_LEGACY_HEADERS = ("# Soma Governance Integration", "# Soma Governance Rules")

__all__ = ["ClaudeAdapter", "SOMA_MARKER_START", "SOMA_MARKER_END"]


def _has_soma_section(text: str) -> bool:
    """Return True if text contains either SOMA markers or legacy Soma headers."""
    return (
        (SOMA_MARKER_START in text and SOMA_MARKER_END in text)
        or any(h in text for h in _LEGACY_HEADERS)
    )


def _inject_soma_section(existing: str, section: str) -> str:
    """Inject or update Soma configuration section in markdown text."""
    if not existing.strip():
        return section
    if SOMA_MARKER_START in existing and SOMA_MARKER_END in existing:
        start_idx = existing.index(SOMA_MARKER_START)
        end_idx = existing.index(SOMA_MARKER_END) + len(SOMA_MARKER_END)
        return f"{existing[:start_idx]}{section}{existing[end_idx:]}".strip() + "\n"
    if "Soma Governance Integration" not in existing:
        return f"{existing.rstrip()}\n\n{section}"
    return existing


def _strip_soma_section(text: str) -> tuple[str, bool]:
    """Strip Soma section from markdown, returning (cleaned_text, had_soma)."""
    if SOMA_MARKER_START in text and SOMA_MARKER_END in text:
        start_idx = text.index(SOMA_MARKER_START)
        end_idx = text.index(SOMA_MARKER_END) + len(SOMA_MARKER_END)
        cleaned = (text[:start_idx] + text[end_idx:]).strip()
        return cleaned, True

    if any(h in text for h in _LEGACY_HEADERS):
        kept_lines: list[str] = []
        skipping = False
        for line in text.splitlines():
            if line.strip() in _LEGACY_HEADERS:
                skipping = True
            elif skipping and line.startswith("# ") and line.strip() not in _LEGACY_HEADERS:
                skipping = False
                kept_lines.append(line)
            elif not skipping:
                kept_lines.append(line)
        return "\n".join(kept_lines).strip(), True

    return text.strip(), False


def _uninstall_claude_md(path: Path, dry_run: bool = False) -> bool:
    """Remove Soma section from CLAUDE.md or delete file if only Soma was present.

    Returns True if the file was modified or removed.
    """
    if not path.is_file():
        return False

    text = path.read_text(encoding="utf-8")
    remaining, had_soma = _strip_soma_section(text)
    if not had_soma:
        return False

    if not dry_run:
        if not remaining:
            path.unlink()
        else:
            path.write_text(remaining + "\n", encoding="utf-8")
    return True


def _clean_mcp_config(path: Path, server_name: str = "soma", dry_run: bool = False) -> bool:
    """Remove a server from an MCP JSON config. Return True if modified."""
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers")
        if not isinstance(servers, dict) or server_name not in servers:
            return False
        if dry_run:
            return True
        del servers[server_name]
        if not servers and len(data) == 1:
            path.unlink()
        else:
            write_json_atomic(path, data)
        return True
    except Exception:
        return False


class ClaudeAdapter(PlatformAdapter):
    """Platform adapter for Anthropic Claude Code / Desktop environments."""

    name: str = "claude"

    def get_target_paths(self, local: bool = False) -> tuple[Path, Path]:
        """Return (claude_md_path, mcp_config_path)."""
        if local:
            return self.workspace / "CLAUDE.md", self.workspace / ".mcp.json"
        claude_dir = self.home / ".claude"
        return claude_dir / "CLAUDE.md", self.home / ".claude.json"

    def render_config(self) -> str:
        """Render governance instructions to embed in CLAUDE.md."""
        rules = [r for r in self.get_source_rules() if r.parent.name != ".oracles"]
        sections = []
        for r in rules:
            try:
                content = r.read_text(encoding="utf-8").strip()
                sections.append(f"## {r.stem}\n\n{content}")
            except Exception:
                pass
        platform_map = (
            "> **Claude Platform Mapping**: When rules reference cross-platform tiers or tools, "
            "map `flash` / `flash_lite` -> `haiku` (or `sonnet`), `inherit` / `pro` -> `sonnet` / `opus`, "
            "`invoke_subagent` -> `Task` / `Agent`, `view_file` -> `Read`, `replace_file_content` -> `Edit`, "
            "and `grep_search` -> `Grep`.\n\n"
        )
        if sections:
            body = (
                "# Soma Governance Rules\n\n"
                + platform_map
                + "\n\n---\n\n".join(sections)
                + "\n\nRun `aegis doctor` to verify system health.\n"
            )
        else:
            body = (
                "# Soma Governance Integration\n\n"
                "This project is governed by Soma. Rules are checked adaptively.\n\n"
                + platform_map
                + "Run `aegis doctor` to verify system health.\n"
            )
        return f"{SOMA_MARKER_START}\n{body}\n{SOMA_MARKER_END}\n"

    def render_mcp_config(self, local: bool = False) -> dict[str, Any]:
        """Render standard MCP server configuration for Claude."""
        entry = self.render_mcp_entry(local=local)
        return {
            "mcpServers": {
                "aegis": entry,
            }
        }

    def install_desktop_mcp(self, dry_run: bool = False) -> Path:
        """Merge the 'aegis' MCP server entry into ~/.config/Claude/claude_desktop_config.json.

        Raises McpConfigError when the existing file cannot be parsed (it is left
        untouched) and OSError when the write fails (the old file survives).
        """
        config_path = self._desktop_config_path()
        data = load_mcp_config(config_path)
        if dry_run:
            return config_path

        data.setdefault("mcpServers", {})["aegis"] = self.render_mcp_entry(local=False)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(config_path, data)
        return config_path

    def _desktop_config_path(self) -> Path:
        return self.home / ".config" / "Claude" / "claude_desktop_config.json"

    def install(self, local: bool = False, dry_run: bool = False) -> PlatformInstallResult:
        result = PlatformInstallResult(
            platform=self.name,
            success=True,
            scope="local" if local else "global",
        )
        claude_md, _ = self.get_target_paths(local=local)
        rules_dir = self.workspace / ".claude" if local else self.home / ".claude"
        skills_dir = rules_dir / "skills"
        wants_desktop = not local and self._desktop_config_path().parent.is_dir()

        # 0. Fail fast: a Desktop config we would refuse to merge stops the whole
        # install, rather than leaving rules installed beside an unconfigured server.
        if wants_desktop:
            try:
                load_mcp_config(self._desktop_config_path())
            except McpConfigError as exc:
                result.errors.append(f"{exc} (nothing was installed)")
                result.success = False
                return result

        # 1. Install rule files
        for rule in self.get_source_rules():
            dest = (
                (rules_dir / ".oracles" / rule.name)
                if rule.parent.name == ".oracles"
                else (rules_dir / rule.name)
            )
            if not dest.exists():
                if not dry_run:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(rule, dest)
                result.installed_files.append(dest)

        # 2. Install skills
        for src_skill_dir in self.get_source_skills():
            dest_skill_dir = skills_dir / src_skill_dir.name
            if dry_run:
                result.installed_files.append(dest_skill_dir / "SKILL.md")
            else:
                try:
                    skills_dir.mkdir(parents=True, exist_ok=True)
                    if dest_skill_dir.exists():
                        shutil.rmtree(dest_skill_dir)
                    shutil.copytree(src_skill_dir, dest_skill_dir)
                    result.installed_files.append(dest_skill_dir / "SKILL.md")
                except Exception as exc:
                    result.errors.append(f"Failed to copy skill {src_skill_dir.name}: {exc}")
                    result.success = False

        # 3. Install Claude Desktop MCP config when global and ~/.config/Claude exists
        if wants_desktop:
            try:
                result.installed_files.append(self.install_desktop_mcp(dry_run=dry_run))
            except McpConfigError as exc:
                result.errors.append(str(exc))
                result.success = False
            except OSError as exc:
                result.errors.append(f"Failed to write Claude Desktop MCP config: {exc}")
                result.success = False

        if dry_run:
            result.installed_files.append(claude_md)
            result.messages.append(f"[dry-run] Would install Claude configuration to {claude_md}")
            return result

        try:
            claude_md.parent.mkdir(parents=True, exist_ok=True)
            existing = claude_md.read_text(encoding="utf-8") if claude_md.is_file() else ""
            updated = _inject_soma_section(existing, self.render_config())
            claude_md.write_text(updated, encoding="utf-8")
            result.installed_files.append(claude_md)
        except Exception as exc:
            result.errors.append(f"Failed to write {claude_md}: {exc}")
            result.success = False

        result.messages.append(f"Installed Claude configuration to {claude_md}")
        return result

    def uninstall(self, local: bool = False, dry_run: bool = False) -> PlatformInstallResult:
        result = PlatformInstallResult(
            platform=self.name,
            success=True,
            scope="local" if local else "global",
        )
        claude_md, mcp_json = self.get_target_paths(local=local)
        rules_dir = self.workspace / ".claude" if local else self.home / ".claude"
        skills_dir = rules_dir / "skills"

        # 1. Clean CLAUDE.md
        try:
            if _uninstall_claude_md(claude_md, dry_run=dry_run):
                result.uninstalled_files.append(claude_md)
        except Exception as exc:
            result.errors.append(f"Failed to remove {claude_md}: {exc}")
            result.success = False

        # 2. Clean rule files from rules_dir
        if rules_dir.is_dir():
            for rule in self.get_source_rules():
                rule_file = (
                    (rules_dir / ".oracles" / rule.name)
                    if rule.parent.name == ".oracles"
                    else (rules_dir / rule.name)
                )
                if rule_file.is_file():
                    if dry_run:
                        result.uninstalled_files.append(rule_file)
                    else:
                        try:
                            rule_file.unlink()
                            result.uninstalled_files.append(rule_file)
                        except Exception as exc:
                            result.errors.append(f"Failed to remove {rule_file}: {exc}")
                            result.success = False

        # 3. Clean skills from skills_dir
        if skills_dir.is_dir():
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

        # 4. Clean MCP config (check both target mcp_json, workspace .mcp.json, and desktop config)
        mcp_targets = [mcp_json]
        ws_mcp = self.workspace / ".mcp.json"
        if ws_mcp not in mcp_targets and ws_mcp.is_file():
            mcp_targets.append(ws_mcp)
        if not local:
            desktop_mcp = self.home / ".config" / "Claude" / "claude_desktop_config.json"
            if desktop_mcp not in mcp_targets and desktop_mcp.is_file():
                mcp_targets.append(desktop_mcp)

        for target in mcp_targets:
            modified = False
            for srv in ("soma", "aegis"):
                if _clean_mcp_config(target, server_name=srv, dry_run=dry_run):
                    modified = True
            if modified:
                result.uninstalled_files.append(target)

        action = "[dry-run] Would uninstall" if dry_run else "Uninstalled"
        result.messages.append(f"{action} Claude configuration from {claude_md}")
        return result

    def verify(self, local: bool = False) -> bool:
        claude_md, _ = self.get_target_paths(local=local)
        if not claude_md.is_file():
            return False
        return _has_soma_section(claude_md.read_text(encoding="utf-8"))
