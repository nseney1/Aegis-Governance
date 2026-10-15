"""GitWorkspace subclass and Git operations for Soma (Layer 0 Core).

Inherits from Workspace to provide zero-subprocess fast paths for HEAD commit parsing,
branch name extraction, worktree discovery, and repository-relative diff inspection.
Strictly zero-dependency: uses only Python standard library.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from aegis_core.workspace.base import Workspace
from aegis_core.workspace.hooks import _find_git_dirs, resolve_git_hooks_dir


@dataclass(frozen=True, eq=False)
class GitWorkspace(Workspace):
    """A Soma workspace backed by a Git repository or linked worktree."""

    git_dir: Path | None = field(default=None)
    git_common_dir: Path | None = field(default=None)

    def __post_init__(self) -> None:
        super().__post_init__()
        resolved_root = self.root
        git_dir, common_dir = _find_git_dirs(resolved_root)
        if git_dir is not None:
            object.__setattr__(self, "git_dir", git_dir)
            object.__setattr__(self, "git_common_dir", common_dir or git_dir)
            if self.git_hooks_dir is None:
                hooks = resolve_git_hooks_dir(resolved_root)
                object.__setattr__(self, "git_hooks_dir", hooks)

    @property
    def is_git(self) -> bool:
        """True if this workspace is backed by a Git repository or worktree."""
        return bool(self.git_dir is not None and self.git_dir.exists())

    def __repr__(self) -> str:
        return f"GitWorkspace(root={self.root!r}, branch={self.branch_name!r}, is_worktree={self.is_worktree})"

    @property
    def branch_name(self) -> str | None:
        """Active branch name, or None if in detached HEAD state."""
        if not self.git_dir or not self.git_dir.exists():
            return None
        head_file = self.git_dir / "HEAD"
        if not head_file.is_file():
            return None
        try:
            head_content = head_file.read_text(encoding="utf-8", errors="replace").strip()
            prefix = "ref: refs/heads/"
            if head_content.startswith(prefix):
                return head_content[len(prefix):].strip()
            if head_content.startswith("ref:"):
                return None
            return None
        except (OSError, UnicodeError):
            pass

        # Fallback to subprocess
        res = self._run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if res.returncode == 0:
            b = res.stdout.strip()
            if b and b != "HEAD":
                return b
        return None

    def get_changed_files(self, staged: bool = False, base: str | None = None) -> list[str]:
        """List repo-relative paths of modified or added files."""
        cmd = ["git", "diff", "--name-only"]
        if staged:
            cmd.append("--cached")
        if base:
            cmd.append(base)
        res = self._run_git(cmd)
        if res.returncode != 0:
            return []
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]

    def _run_git(self, cmd: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
        """Execute a git command confined to this repository root."""
        try:
            return subprocess.run(
                cmd,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=1,
                stdout="",
                stderr=str(exc),
            )


__all__ = [
    "GitWorkspace",
]
