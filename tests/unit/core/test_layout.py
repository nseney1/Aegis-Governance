"""Unit tests for aegis_core.workspace.layout (WorkspaceLayout and LockResource)."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import pytest

from aegis_core.workspace.layout import LockResource, WorkspaceLayout


def test_workspace_layout_paths_and_immutability(tmp_path: Path):
    layout = WorkspaceLayout(root=str(tmp_path))
    assert isinstance(layout.root, Path)
    assert layout.root == tmp_path.resolve()

    assert layout.aegis_dir == layout.root / ".aegis"
    assert layout.rules_dir == layout.root / ".aegis" / "rules"
    assert layout.evidence_dir == layout.root / ".aegis" / "evidence"
    assert layout.locks_dir == layout.root / ".aegis" / "locks"
    assert layout.keys_dir == layout.root / ".aegis" / "keys"
    assert layout.metrics_dir == layout.root / ".aegis" / "metrics"
    assert layout.skills_dir == layout.root / ".aegis" / "skills"

    assert layout.signals_file == layout.evidence_dir / "signals.jsonl"
    assert layout.manifest_file == layout.rules_dir / "manifest.json"
    assert layout.manifest_key_file == layout.keys_dir / "manifest.key"

    with pytest.raises(FrozenInstanceError):
        layout.root = tmp_path / "other"  # type: ignore[misc]


def test_lock_resource_constants_and_lock_file_resolution(tmp_path: Path):
    layout = WorkspaceLayout(root=tmp_path)
    for resource in (
        LockResource.RULES,
        LockResource.EVIDENCE,
        LockResource.SIGNALS,
        LockResource.FITNESS,
        LockResource.RECEIPTS,
        LockResource.MIGRATION,
    ):
        lock_path = layout.lock_file(resource)
        assert lock_path == layout.locks_dir / f"{resource}.lock"
