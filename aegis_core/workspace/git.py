"""GitWorkspace subclass and Git operations for Soma (Layer 0 Core).

Inherits from Workspace to provide zero-subprocess fast paths for HEAD commit parsing,
branch name extraction, worktree discovery, and repository-relative diff inspection.
Strictly zero-dependency: uses only Python standard library.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aegis_core.workspace.base import Workspace
from aegis_core.workspace.hooks import _find_git_dirs, resolve_git_hooks_dir


def _parse_worktree_porcelain(stdout: str) -> list[dict[str, Any]]:
    """Parse output of git worktree list --porcelain."""
    worktrees: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            if current and "path" in current:
                worktrees.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            if current and "path" in current:
                worktrees.append(current)
                current = {}
            current["path"] = Path(line[9:].strip())
            current["bare"] = False
            current["detached"] = False
            current["branch"] = None
            current["head"] = ""
        elif line.startswith("HEAD "):
            current["head"] = line[5:].strip()
        elif line.startswith("branch "):
            ref = line[7:].strip()
            prefix = "refs/heads/"
            current["branch"] = ref[len(prefix):] if ref.startswith(prefix) else ref
        elif line == "bare":
            current["bare"] = True
        elif line == "detached":
            current["detached"] = True
    if current and "path" in current:
        worktrees.append(current)
    return worktrees


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
    def head_commit(self) -> str | None:
        """Commit hash of HEAD, resolved using zero-subprocess fast paths when possible."""
        if not self.git_dir or not self.git_dir.exists():
            return None
        head_file = self.git_dir / "HEAD"
        if not head_file.is_file():
            return None
        try:
            head_content = head_file.read_text(encoding="utf-8", errors="replace").strip()
            if not head_content:
                return None
            if not head_content.startswith("ref:"):
                # Detached HEAD: direct commit SHA
                if len(head_content) in (40, 64) and all(c in "0123456789abcdefABCDEF" for c in head_content):
                    return head_content
                return None

            ref_path_rel = head_content[4:].strip()
            # Try loose ref in git_dir, then git_common_dir
            for base_dir in (self.git_dir, self.git_common_dir):
                if base_dir is None:
                    continue
                candidate_ref = base_dir / ref_path_rel
                if candidate_ref.is_file():
                    sha = candidate_ref.read_text(encoding="utf-8", errors="replace").strip()
                    if sha:
                        return sha

            # Try packed-refs in git_common_dir
            if self.git_common_dir is not None:
                packed_refs_file = self.git_common_dir / "packed-refs"
                if packed_refs_file.is_file():
                    for line in packed_refs_file.read_text(encoding="utf-8", errors="replace").splitlines():
                        line = line.strip()
                        if not line or line.startswith(("#", "^")):
                            continue
                        parts = line.split(maxsplit=1)
                        if len(parts) == 2 and parts[1] == ref_path_rel:
                            return parts[0]
        except (OSError, UnicodeError, ValueError):
            pass

        # Fallback to subprocess
        res = self._run_git(["git", "rev-parse", "HEAD"])
        if res.returncode == 0:
            out = res.stdout.strip()
            if out:
                return out
        return None

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

    def get_diff(self, staged: bool = False, base: str | None = None) -> str:
        """Extract unified diff from working tree, staged index, or base commit."""
        cmd = ["git", "diff", "--no-color", "--no-ext-diff"]
        if staged:
            cmd.append("--cached")
        if base:
            cmd.append(base)
        res = self._run_git(cmd)
        return res.stdout if res.returncode == 0 else ""

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

    def get_untracked_files(self) -> list[str]:
        """List untracked files respecting .gitignore."""
        res = self._run_git(["git", "ls-files", "--others", "--exclude-standard"])
        if res.returncode != 0:
            return []
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]

    def list_worktrees(self) -> list[dict[str, Any]]:
        """Discover linked worktrees associated with this repository."""
        res = self._run_git(["git", "worktree", "list", "--porcelain"])
        if res.returncode != 0:
            return [{
                "path": self.root,
                "bare": False,
                "head": self.head_commit or "",
                "branch": self.branch_name,
                "detached": self.branch_name is None,
            }]
        return _parse_worktree_porcelain(res.stdout)

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
    "_parse_worktree_porcelain",
]
