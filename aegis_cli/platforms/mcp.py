"""Model Context Protocol (MCP) configuration adapter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aegis_cli.platforms.base import (
    McpConfigError,
    PlatformAdapter,
    PlatformInstallResult,
    load_mcp_config,
    write_json_atomic,
)


__all__ = ["McpAdapter"]


class McpAdapter(PlatformAdapter):
    """Platform adapter managing .mcp.json server configuration."""

    name: str = "mcp"

    def get_target_file(self, local: bool = True, project_root: Path | str | None = None) -> Path:
        """Return path to .mcp.json."""
        if project_root is not None:
            return Path(project_root).resolve() / ".mcp.json"
        if local:
            return self.workspace / ".mcp.json"
        return self.home / ".mcp.json"

    def render_config(
        self,
        local: bool = False,
        portable: bool = False,
        command: str = "aegis-mcp",
    ) -> dict[str, Any]:
        """Render canonical .mcp.json server configuration."""
        if portable:
            return {
                "mcpServers": {
                    "aegis": {
                        "command": command,
                        "args": [],
                    }
                }
            }
        entry = self.render_mcp_entry(local=local, command=command)
        return {
            "mcpServers": {
                "aegis": dict(entry),
            }
        }

    def install(
        self,
        local: bool | Path | str = True,
        dry_run: bool = False,
        portable: bool = False,
        command: str = "aegis-mcp",
    ) -> PlatformInstallResult:
        project_root: Path | None = None
        if isinstance(local, (Path, str)):
            project_root = Path(local).resolve()
            is_local = True
        else:
            is_local = bool(local)

        result = PlatformInstallResult(
            platform=self.name,
            success=True,
            scope="local" if is_local else "global",
        )
        target = self.get_target_file(local=is_local, project_root=project_root)
        config = self.render_config(
            local=(False if portable else is_local),
            portable=portable,
            command=command,
        )

        # A project-scoped .mcp.json may be a symlink shipped by the repo; only the
        # home-scoped one is allowed to point elsewhere (dotfile managers).
        confine_to = (project_root or self.workspace) if is_local else None
        try:
            existing = load_mcp_config(target, confine_to=confine_to)
        except McpConfigError as exc:
            result.errors.append(str(exc))
            result.success = False
            return result

        if dry_run:
            result.installed_files.append(target)
        else:
            existing.setdefault("mcpServers", {}).update(config["mcpServers"])
            try:
                write_json_atomic(target, existing)
            except OSError as exc:
                result.errors.append(f"Failed to write {target}: {exc}")
                result.success = False
                return result
            result.installed_files.append(target)

        result.messages.append(f"Configured MCP server in {target}")
        return result

    def uninstall(self, local: bool = True, dry_run: bool = False) -> PlatformInstallResult:
        result = PlatformInstallResult(
            platform=self.name,
            success=True,
            scope="local" if local else "global",
        )
        target = self.get_target_file(local=local)
        if target.is_file():
            if dry_run:
                result.uninstalled_files.append(target)
            else:
                try:
                    data = json.loads(target.read_text(encoding="utf-8"))
                    servers = data.get("mcpServers")
                    if isinstance(servers, dict):
                        removed = False
                        for key in ("soma", "aegis"):
                            if key in servers:
                                del servers[key]
                                removed = True
                        if removed:
                            write_json_atomic(target, data)
                            result.uninstalled_files.append(target)
                except Exception as exc:
                    result.errors.append(f"Failed to update {target}: {exc}")
                    result.success = False

        action = "[dry-run] Would remove" if dry_run else "Removed"
        result.messages.append(f"{action} soma MCP server from {target}")
        return result

    def verify(self, local: bool = True) -> bool:
        target = self.get_target_file(local=local)
        if not target.is_file():
            return False
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            servers = data.get("mcpServers", {})
            return "aegis" in servers or "soma" in servers
        except Exception:
            return False

