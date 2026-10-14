"""Unit tests for AegisTestHarness and canonical test colocality governance rule."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from aegis_core.yaml import parse_rule_frontmatter
try:
    import harness as harness_mod
    from harness import AegisTestHarness
except ImportError:
    import tests.harness as harness_mod
    from tests.harness import AegisTestHarness


def test_soma_test_harness_removed_and_helpers_rule_present():
    """Verify SomaTestHarness alias is removed and tests/helpers_rule.py exports make_rule and aegis_workspace."""
    assert not hasattr(harness_mod, "SomaTestHarness")
    from tests import helpers_rule
    assert hasattr(helpers_rule, "make_rule")
    assert hasattr(helpers_rule, "aegis_workspace")


def test_harness_workspace_structure(harness: AegisTestHarness):
    """Verify harness initializes standard rule and lock directories."""
    assert harness.locks_dir.is_dir()


def test_harness_create_cell(harness: AegisTestHarness):
    """Verify harness creates valid rules with parseable frontmatter."""
    cell_path = harness.create_rule(
        cell_id="test-wall-1",
        cell_type="wall",
        domain="testing",
        hypothesis="Test hypothesis statement",
        prediction="Test prediction statement",
        tags=["unit", "test"],
        body="# Test Wall Rule\n\nRule details.",
    )
    assert cell_path.exists()

    data, body = parse_rule_frontmatter(str(cell_path))
    assert data["id"] == "test-wall-1"
    assert data["type"] == "wall"
    assert data["domain"] == "testing"
    assert data["tags"] == ["unit", "test"]
    assert "# Test Wall Rule" in body


def test_harness_record_signal(harness: AegisTestHarness):
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


def test_harness_run_cli_isolated(harness: AegisTestHarness):
    """Verify harness executes aegis CLI out-of-process via subprocess."""
    proc = harness.run_cli(["--help"], check=False)
    assert proc.returncode == 0
    assert "usage:" in proc.stdout.lower() or "aegis" in proc.stdout.lower()


def test_governance_wall_parseable():
    """Verify invariant complies with schema."""
    candidates = [
        Path(".aegis/rules/invariants/invariant-test-canonical-colocality.md"),
        Path(".aegis/rules/invariants/wall-test-canonical-colocality.md"),
        Path(".soma/cells/walls/wall-test-canonical-colocality.md"),
    ]
    wall_file = next((p for p in candidates if p.exists()), candidates[0])
    assert wall_file.exists()

    data, body = parse_rule_frontmatter(str(wall_file))
    assert data["id"] in ("wall-test-canonical-colocality", "invariant-test-canonical-colocality")
    assert data["type"] in ("wall", "invariant")
    assert data["enforcement"] == "gate"
    assert data["domain"] == "testing"
    assert "1:1 Directory Mirroring" in body

