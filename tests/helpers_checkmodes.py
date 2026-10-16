"""Throwaway git repositories for the v4.2 check modes (card, baseline, partition).

Every test builds its own repository under ``tmp_path``; nothing here touches a real
HOME, a host CLI or the network.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Optional

__all__ = ["NO_EVAL", "commit", "git", "init_repo", "write"]

# A gate rule with a forbid_ast ban: every ``eval(...)`` call in a non-test file is a finding.
NO_EVAL = (
    "---\n"
    "id: no-eval\n"
    "type: invariant\n"
    "enforcement: gate\n"
    "hypothesis: Production code never evaluates strings.\n"
    "forbid_ast:\n"
    "  calls: [eval]\n"
    "---\n"
    "# No eval\n"
)


def git(root: Path, *args: str, stdin: Optional[str] = None) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=T", "-c", "commit.gpgsign=false",
         "-c", "core.autocrlf=false", *args],
        cwd=str(root), check=True, capture_output=True, text=True, input=stdin,
    ).stdout.strip()


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))


def commit(root: Path, message: str = "change") -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", message)
    return git(root, "rev-parse", "HEAD")


def init_repo(path: Path, rules: bool = True) -> Path:
    """A git repository on ``main`` with an ``.aegis`` workspace (and the no-eval gate rule)."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    (path / ".aegis").mkdir(exist_ok=True)
    if rules:
        write(path, ".aegis/rules/invariants/no-eval.md", NO_EVAL)
    return path.resolve()
