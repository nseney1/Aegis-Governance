"""Git hook directory resolution and worktree awareness (Layer 0 Core).

Handles standard Git repositories (.git directory), Git worktrees (.git pointer file),
and custom core.hooksPath configuration via git CLI or pure Python fallback.
Strictly zero-dependency: uses only Python standard library.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _find_git_dirs(root: Path) -> tuple[Path | None, Path | None]:
    """Find (git_dir, git_common_dir) for a workspace root, walking up if necessary."""
    curr = root.resolve()
    while True:
        dot_git = curr / ".git"
        if dot_git.is_dir():
            return dot_git, dot_git
        elif dot_git.is_file():
            try:
                content = dot_git.read_text(encoding="utf-8", errors="replace").strip()
                if content.startswith("gitdir:"):
                    gitdir_str = content[7:].strip()
                    gitdir_path = Path(gitdir_str)
                    if not gitdir_path.is_absolute():
                        gitdir_path = (curr / gitdir_path).resolve()
                    commondir_file = gitdir_path / "commondir"
                    if commondir_file.is_file():
                        common_rel = commondir_file.read_text(encoding="utf-8").strip()
                        common_dir = (gitdir_path / common_rel).resolve()
                        return gitdir_path, common_dir
                    if gitdir_path.parent.name == "worktrees" and gitdir_path.parent.parent.is_dir():
                        return gitdir_path, gitdir_path.parent.parent
                    return gitdir_path, gitdir_path
            except (OSError, UnicodeError, ValueError):
                pass
        parent = curr.parent
        if parent == curr:
            break
        curr = parent
    return None, None


def resolve_git_hooks_dir(project_root: str | Path | os.PathLike[str] | None = None) -> Path | None:
    """Resolve the git hooks directory for a project root or worktree.

    Handles:
    1. Standard repository (.git is a directory -> .git/hooks)
    2. Git worktree (.git is a file containing 'gitdir: <path>')
       Resolves common_dir or parent .git/hooks.
    3. Git rev-parse --git-path hooks fallback when git CLI is available.

    Returns Path to hooks directory, or None if not inside a git repository.
    """
    root = Path(project_root or Path.cwd()).resolve()

    dot_git = root / ".git"
    if not dot_git.exists():
        return None

    # 1. Try git CLI if available (handles core.hooksPath and custom setups)
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--git-path", "hooks"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if res.returncode == 0:
            p = res.stdout.strip()
            if p:
                hooks_path = Path(p)
                if not hooks_path.is_absolute():
                    hooks_path = (root / hooks_path).resolve()
                return hooks_path
    except (subprocess.SubprocessError, FileNotFoundError, PermissionError, UnicodeDecodeError, OSError):
        pass

    # 2. Pure Python fallback (zero external CLI dependencies)
    _git_dir, common_dir = _find_git_dirs(root)
    if common_dir is not None:
        return common_dir / "hooks"

    return None


__all__ = [
    "_find_git_dirs",
    "resolve_git_hooks_dir",
]
