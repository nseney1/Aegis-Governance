"""Model Context Protocol (MCP) configuration adapter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aegis_cli.platforms.base import PlatformAdapter, PlatformInstallResult


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
                "soma": dict(entry),
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

        if dry_run:
            result.installed_files.append(target)
        else:
            try:
                if target.is_file():
                    try:
                        existing = json.loads(target.read_text(encoding="utf-8"))
                    except Exception:
                        existing = {}
                    servers = existing.setdefault("mcpServers", {})
                    for srv_name, srv_cfg in config["mcpServers"].items():
                        servers[srv_name] = srv_cfg
                    target.write_text(json.dumps(existing, indent=2), encoding="utf-8")
                else:
                    target.write_text(json.dumps(config, indent=2), encoding="utf-8")
                result.installed_files.append(target)
            except Exception as exc:
                result.errors.append(f"Failed to write {target}: {exc}")
                result.success = False

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
                            target.write_text(json.dumps(data, indent=2), encoding="utf-8")
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

