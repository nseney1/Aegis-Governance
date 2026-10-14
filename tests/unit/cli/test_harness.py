"""Unit tests for SomaTestHarness and canonical test colocality governance wall."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from soma_core.somayaml import parse_cell_frontmatter
try:
    from harness import SomaTestHarness
except ImportError:
    from tests.harness import SomaTestHarness


def test_harness_workspace_structure(harness: SomaTestHarness):
    """Verify harness initializes standard cell and lock directories."""
    assert (harness.cells_dir / "walls").is_dir()
    assert (harness.cells_dir / "membranes").is_dir()
    assert (harness.cells_dir / "vacuoles").is_dir()
    assert harness.locks_dir.is_dir()


def test_harness_create_cell(harness: SomaTestHarness):
    """Verify harness creates valid cells with parseable frontmatter."""
    cell_path = harness.create_cell(
        cell_id="test-wall-1",
        cell_type="wall",
        domain="testing",
        hypothesis="Test hypothesis statement",
        prediction="Test prediction statement",
        tags=["unit", "test"],
        body="# Test Wall Rule\n\nRule details.",
    )
    assert cell_path.exists()
    assert cell_path.parent.name == "walls"

    data, body = parse_cell_frontmatter(cell_path)
    assert data["id"] == "test-wall-1"
    assert data["type"] == "wall"
    assert data["domain"] == "testing"
    assert data["tags"] == ["unit", "test"]
    assert "# Test Wall Rule" in body


def test_harness_record_signal(harness: SomaTestHarness):
    """Verify harness appends JSON lines to signals.jsonl."""
    harness.record_signal(
        cell_id="test-wall-1",
        signal_type="success",
        score=0.95,
        session_id="session-xyz",
        details={"status": "ok"},
    )
    signals_file = harness.soma_dir / "signals.jsonl"
    assert signals_file.exists()

    lines = [json.loads(line) for line in signals_file.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 1
    assert lines[0]["cell_id"] == "test-wall-1"
    assert lines[0]["score"] == 0.95
    assert lines[0]["session_id"] == "session-xyz"


def test_harness_run_cli_isolated(harness: SomaTestHarness):
    """Verify harness executes soma CLI out-of-process via subprocess."""
    proc = harness.run_cli(["--help"], check=False)
    assert proc.returncode == 0
    assert "usage:" in proc.stdout.lower() or "soma" in proc.stdout.lower()


def test_governance_wall_parseable():
    """Verify wall/invariant complies with schema."""
    wall_file = Path(".aegis/rules/invariants/wall-test-canonical-colocality.md") if Path(".aegis/rules/invariants/wall-test-canonical-colocality.md").exists() else Path(".soma/cells/walls/wall-test-canonical-colocality.md")
    assert wall_file.exists()

    data, body = parse_cell_frontmatter(wall_file)
    assert data["id"] == "wall-test-canonical-colocality"
    assert data["type"] in ("wall", "invariant")
    assert data["enforcement"] == "gate"
    assert data["domain"] == "testing"
    assert "1:1 Directory Mirroring" in body
