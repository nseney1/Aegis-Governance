"""Workspace scaffolding and initialization for Soma (Layer 0 Core).

Creates canonical directory structure (.soma/cells/{walls,vacuoles,gates}, .soma/evidence, .soma/metrics).
Guards against bare git repositories.
Strictly zero-dependency: uses only Python standard library.
"""
from __future__ import annotations

from pathlib import Path

from aegis_core.errors import WorkspaceBareRepoError


def scaffold_workspace(
    root: Path,
    cells_dir: Path,
    evidence_dir: Path,
    metrics_dir: Path,
    minimal: bool = False,
    dry_run: bool = False,
) -> list[Path]:
    """Scaffold standard directory structure for Aegis governance.

    Creates .aegis/rules/ and .aegis/evidence/ (and .aegis/metrics/).
    Guards against bare git repositories.
    """
    if (
        (root / "HEAD").is_file()
        and (root / "config").is_file()
        and (root / "objects").is_dir()
        and not (root / ".git").exists()
    ):
        raise WorkspaceBareRepoError(
            f"Cannot scaffold aegis in a bare git repository: {root}"
        )

    dirs_to_create: list[Path] = [
        cells_dir / "invariants",
        evidence_dir,
    ]
    if not minimal:
        dirs_to_create.extend([
            cells_dir / "traps",
            cells_dir / "gates",
            metrics_dir,
        ])

    if not dry_run:
        for d in dirs_to_create:
            d.mkdir(parents=True, exist_ok=True)

    return dirs_to_create


__all__ = ["scaffold_workspace"]
