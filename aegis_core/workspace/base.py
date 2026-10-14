"""Strongly-typed Workspace value object for Soma (Layer 0 Core).

Implements os.PathLike[str] for seamless interoperability with open(),
Path(), and os.path routines. Strictly zero-dependency (Python standard library only).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aegis_core.errors import WorkspaceError
from aegis_core.workspace.confinement import confine_path_internal, validate_workspace_path
from aegis_core.workspace.discovery import is_aegis_repo, resolve_workspace_root
from aegis_core.workspace.hooks import _find_git_dirs, resolve_git_hooks_dir
from aegis_core.workspace.scaffold import scaffold_workspace

if TYPE_CHECKING:
    from aegis_core.workspace.git import GitWorkspace


@dataclass(frozen=True, eq=False)
class Workspace(os.PathLike[str]):
    """Immutable, strongly-typed representation of an Aegis project workspace.

    Implements os.PathLike[str] for seamless interoperability with open(),
    Path(), and os.path routines.
    """

    root: Path
    git_hooks_dir: Path | None = field(default=None)
    is_worktree: bool = field(default=False)

    def __post_init__(self) -> None:
        resolved_root = Path(self.root).resolve()
        object.__setattr__(self, "root", resolved_root)

        dot_git = resolved_root / ".git"
        is_wt = dot_git.is_file()
        object.__setattr__(self, "is_worktree", is_wt)

        if self.git_hooks_dir is None:
            hooks = resolve_git_hooks_dir(resolved_root)
            object.__setattr__(self, "git_hooks_dir", hooks)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Workspace):
            return self.root == other.root
        if isinstance(other, (str, Path, os.PathLike)):
            try:
                return self.root == Path(os.fspath(other)).resolve()
            except (TypeError, ValueError, OSError):
                return False
        return False

    def __hash__(self) -> int:
        return hash(self.root)

    @property
    def aegis_dir(self) -> Path:
        """Path to .aegis directory."""
        return self.root / ".aegis"

    @property
    def soma_dir(self) -> Path:
        """Path to .aegis directory."""
        return self.aegis_dir

    @property
    def rules_dir(self) -> Path:
        """Path to active rules directory (.aegis/rules)."""
        return self.aegis_dir / "rules"

    @property
    def cells_dir(self) -> Path:
        """Path to active rules directory (.aegis/rules)."""
        return self.rules_dir

    @property
    def metrics_dir(self) -> Path:
        """Path to metrics directory."""
        return self.aegis_dir / "metrics"

    @property
    def evidence_dir(self) -> Path:
        """Path to evidence directory."""
        return self.aegis_dir / "evidence"

    @property
    def locks_dir(self) -> Path:
        """Path to locks directory."""
        return self.aegis_dir / "locks"

    @property
    def signals_file(self) -> Path:
        """Path to signals.jsonl file."""
        return self.evidence_dir / "signals.jsonl"

    @property
    def is_git(self) -> bool:
        """True if this workspace is backed by a Git repository or worktree."""
        return (self.root / ".git").exists() or self.git_hooks_dir is not None

    @property
    def is_aegis_repo(self) -> bool:
        """True if this workspace is the core Aegis Governance repository."""
        return is_aegis_repo(self.root)

    def __fspath__(self) -> str:
        return str(self.root)

    def __str__(self) -> str:
        return str(self.root)

    def __repr__(self) -> str:
        return f"Workspace(root={self.root!r}, is_worktree={self.is_worktree})"

    def __truediv__(self, other: str | Path | os.PathLike[str]) -> Path:
        return self.root / other

    @classmethod
    def for_init(cls, path: str | Path | os.PathLike[str]) -> Workspace:
        """Construct a Workspace for initialization without requiring pre-existing .aegis directory.

        Guards against symlink traversal escapes and non-directory files.
        Polymorphically returns GitWorkspace if a git repository is present.
        """
        p = Path(path)
        if p.is_symlink():
            raise WorkspaceError(f"Workspace path cannot be a symlink: {p}")
        resolved = p.resolve()
        if resolved.is_file():
            raise WorkspaceError(f"Workspace path must be a directory, not a file: {resolved}")
        if cls is Workspace:
            dot_git = resolved / ".git"
            if dot_git.exists() or _find_git_dirs(resolved)[0] is not None:
                from aegis_core.workspace.git import GitWorkspace
                return GitWorkspace(root=resolved)
        return cls(root=resolved)

    def scaffold(self, minimal: bool = False, dry_run: bool = False) -> list[Path]:
        """Scaffold standard directory structure for Aegis governance.

        Creates .aegis/rules/ and .aegis/evidence/ (and .aegis/metrics/).
        Guards against bare git repositories.
        """
        return scaffold_workspace(
            root=self.root,
            cells_dir=self.rules_dir,
            evidence_dir=self.evidence_dir,
            metrics_dir=self.metrics_dir,
            minimal=minimal,
            dry_run=dry_run,
        )

    @classmethod
    def resolve(
        cls,
        start: str | Path | os.PathLike[str] | Workspace | None = None,
        caller_file: str | Path | os.PathLike[str] | None = None,
        strict_env: bool = False,
    ) -> Workspace:
        """Find the project root containing .aegis/rules/ or .aegis/.

        Polymorphically returns GitWorkspace if backed by a Git repository or worktree.
        """
        from aegis_core.workspace.git import GitWorkspace

        def _make_ws(cand_root: Path) -> Workspace:
            resolved_root = cand_root.resolve()
            if cls is Workspace:
                dot_git = resolved_root / ".git"
                if dot_git.exists() or _find_git_dirs(resolved_root)[0] is not None:
                    return GitWorkspace(root=resolved_root)
            return cls(root=resolved_root)

        if isinstance(start, Workspace):
            if cls is GitWorkspace and not isinstance(start, GitWorkspace):
                return GitWorkspace(root=start.root)
            return start

        cand_root = resolve_workspace_root(
            start=start,
            caller_file=caller_file,
            strict_env=strict_env,
        )
        return _make_ws(cand_root)

    @classmethod
    def confine(
        cls,
        untrusted_workspace: str | Path | os.PathLike[str] | Workspace,
    ) -> Workspace:
        """Validate and confine a workspace path.

        A valid workspace must exist as a directory and contain .aegis/rules/.
        Returns a Workspace or GitWorkspace instance.
        """
        if isinstance(untrusted_workspace, Workspace):
            return untrusted_workspace

        resolved_path = validate_workspace_path(untrusted_workspace)
        if cls is Workspace:
            dot_git = resolved_path / ".git"
            if dot_git.exists() or _find_git_dirs(resolved_path)[0] is not None:
                from aegis_core.workspace.git import GitWorkspace
                return GitWorkspace(root=resolved_path)
        return cls(root=resolved_path)

    def confine_path(self, untrusted_path: str | Path | os.PathLike[str]) -> tuple[str, str]:
        """Resolve and confine a file path within this workspace.

        Returns (resolved_absolute, relative_to_workspace).
        Raises PathTraversalError if the path escapes the workspace boundary.
        """
        return confine_path_internal(self.root, untrusted_path)

    def validate_rule_names(self, rule_names: list[str]) -> list[str]:
        """Validate that rule names reference rules that actually exist.

        Returns a list of invalid names (empty list means all names are valid).
        """
        if not rule_names:
            return []

        rules_dir = self.rules_dir
        if not rules_dir.is_dir():
            return list(rule_names)

        known = set()
        for _dirpath, _dirnames, filenames in os.walk(str(rules_dir)):
            for fn in filenames:
                if fn.endswith(".md") and fn != "README.md":
                    known.add(os.path.splitext(fn)[0])

        return [name for name in rule_names if name not in known]


__all__ = ["Workspace"]
