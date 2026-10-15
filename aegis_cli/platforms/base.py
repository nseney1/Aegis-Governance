"""Abstract base class and models for platform installation adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import errno
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any, Optional


__all__ = [
    "McpConfigError",
    "PlatformAdapter",
    "PlatformInstallResult",
    "detect_platform",
    "detect_platforms",
    "get_rules_dir",
    "load_mcp_config",
    "write_json_atomic",
]


class McpConfigError(ValueError):
    """An existing MCP config file cannot be merged without losing the user's data."""


def _is_read_only(path: Path) -> bool:
    """True when ``path`` exists and its owner marked it read-only.

    ``os.replace`` swaps a file out regardless of the file's own mode (a rename needs
    only directory write access), so the read-only bit has to be honored explicitly.
    The mode bits are checked as well because root passes every ``os.access`` test.
    """
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return not (mode & 0o222) or not os.access(path, os.W_OK)


def load_mcp_config(path: Path | str, *, confine_to: Path | str | None = None) -> dict[str, Any]:
    """Return the JSON object stored at ``path`` for merging, or ``{}`` when it holds none.

    A missing, empty or whitespace-only file and ``"mcpServers": null`` hold nothing to
    lose and are merged into. Lenient formats (JSONC comments, trailing commas, a UTF-8
    BOM), other shapes and read-only files are refused, not repaired: re-serializing
    would drop the user's comments, and falling back to ``{}`` would drop their other
    servers (M3).

    ``confine_to`` is set for project-scoped configs: a ``.mcp.json`` that a cloned repo
    ships as a symlink must not make Aegis merge into a file outside that project.
    """
    path = Path(path)
    if confine_to is not None:
        root = Path(confine_to).resolve()
        try:
            resolved = path.resolve()
            # Path.resolve() on Windows before Python 3.10 stops at a dangling symlink
            # instead of following it; os.path.realpath follows it there.
            followed = Path(os.path.realpath(path))
        except (OSError, RuntimeError) as exc:  # RuntimeError: symlink loop on 3.9-3.12
            raise McpConfigError(f"{path}: cannot be resolved ({exc}); refusing to modify it") from exc
        for target in (resolved, followed):
            if target != root and root not in target.parents:
                raise McpConfigError(
                    f"{path}: is a symlink to {target}, outside the project {root}; "
                    "refusing to modify it. Replace the link with a regular file to register Aegis here."
                )
    if not path.exists():
        return {}
    if _is_read_only(path):
        raise McpConfigError(
            f"{path}: is read-only; refusing to modify it. Make it writable to register Aegis."
        )
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as exc:
        raise McpConfigError(f"{path}: cannot be read ({exc}); refusing to modify it") from exc
    except UnicodeDecodeError as exc:
        raise McpConfigError(f"{path}: not UTF-8 text ({exc.reason}); refusing to modify it") from exc
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpConfigError(
            f"{path}: not valid JSON ({exc.msg} at line {exc.lineno} column {exc.colno}); "
            "refusing to modify it. Comments, trailing commas and a UTF-8 BOM are not "
            "supported: fix the file or move it aside, then re-run."
        ) from exc
    if not isinstance(data, dict):
        raise McpConfigError(f"{path}: top-level value must be a JSON object; refusing to modify it")
    if "mcpServers" in data and data["mcpServers"] is None:
        data["mcpServers"] = {}
    elif not isinstance(data.get("mcpServers", {}), dict):
        raise McpConfigError(f"{path}: field 'mcpServers' must be a JSON object; refusing to modify it")
    return data


def _umask_mode(mode: int = 0o666) -> int:
    # The CLI is single-threaded, so the brief umask(0) window cannot race a file creation.
    current = os.umask(0)
    os.umask(current)
    return mode & ~current


def write_json_atomic(path: Path | str, data: Any) -> None:
    """Replace ``path`` with ``data`` serialized as JSON, in a single rename.

    On any failure the previous file is left untouched and no temp file remains. A
    symlink is written through to its target (dotfile managers link these configs;
    project-scoped callers confine it first via ``load_mcp_config``), the existing
    permission bits are kept, a new file gets the umask default, and a read-only
    file raises PermissionError instead of being swapped out. Non-ASCII text in the
    user's entries is written as-is, not as ``\\u`` escapes.
    """
    target = Path(path).resolve()
    if _is_read_only(target):
        raise PermissionError(errno.EACCES, "file is read-only; refusing to replace it", str(target))
    payload = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        mode = _umask_mode()
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _detect_markers_in_dir(root: Path) -> list[str]:
    """Return all platforms whose markers exist directly under ``root``."""
    found: list[str] = []
    if (root / ".gemini").is_dir():
        found.append("gemini")
    if (root / ".claude").is_dir() or (root / "CLAUDE.md").is_file():
        found.append("claude")
    if (root / ".cursor").is_dir() or (root / ".cursorrules").is_file():
        found.append("cursor")
    if (
        (root / ".github" / "copilot").is_dir()
        or (root / ".github" / "copilot-instructions.md").is_file()
    ):
        found.append("copilot")
    if (root / ".kiro").is_dir():
        found.append("kiro")
    return found


def detect_platforms(
    project_root: Path | str | None = None,
    home: Path | str | None = None,
) -> list[str]:
    """Detect all AI platforms from project and home directory markers in deterministic order.

    Order: ['gemini', 'claude', 'cursor', 'copilot', 'kiro'].
    Defaults to ['gemini'] if no markers match.
    """
    ordered = ["gemini", "claude", "cursor", "copilot", "kiro"]
    detected_set: set[str] = set()

    if project_root is not None:
        detected_set.update(_detect_markers_in_dir(Path(project_root)))
    else:
        detected_set.update(_detect_markers_in_dir(Path.cwd()))

    if home is not None:
        detected_set.update(_detect_markers_in_dir(Path(home)))
    elif project_root is None:
        # Path.home(), not $HOME: on Windows it is USERPROFILE, where the agent CLIs live.
        detected_set.update(_detect_markers_in_dir(Path.home()))

    result = [p for p in ordered if p in detected_set]
    return result if result else ["gemini"]


def detect_platform(project_root: Path | str) -> str:
    """Detect the primary AI platform from directory markers.

    Returns: 'gemini' | 'claude' | 'cursor' | 'copilot' | 'kiro' | 'unknown'
    """
    root = Path(project_root)
    if not _detect_markers_in_dir(root):
        return "unknown"
    return detect_platforms(root)[0]



def get_rules_dir(
    platform: str,
    home: Path | None = None,
    project_root: Path | None = None,
    local: bool = False,
) -> Path:
    """Return the target rules directory for the given platform."""
    home = Path(home) if home is not None else Path.home()
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

    def render_mcp_entry(self, local: bool = False, command: str = "aegis-mcp") -> dict[str, Any]:
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
                "aegis": self.render_mcp_entry(local=local),
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

