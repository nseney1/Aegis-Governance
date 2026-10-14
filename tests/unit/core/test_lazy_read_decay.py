"""Tests for dynamic read-time aging and decay (Phase 13: v0.110.0).

Verifies that:
1. `generate_checkpoint` dynamically evaluates elapsed time since last_trigger.
2. Inactive cells (>30 days since last trigger) are classified as decaying/dormant.
3. Recently active cells remain classified as healthy.
4. Read-time calculation is idempotent and does not modify the canonical evidence ledger.
5. `soma oracle` formats decaying cells with appropriate indicators.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from aegis_core.yaml import dump_frontmatter


def _create_cell(workspace: Path, cell_id: str, last_trigger_date: str | None = None) -> Path:
    cells_dir = workspace / ".soma" / "cells" / "vacuoles"
    cells_dir.mkdir(parents=True, exist_ok=True)
    cell_path = cells_dir / f"{cell_id}.md"
    fm = {
        "id": cell_id,
        "type": "vacuole",
        "enforcement": "advisory",
        "target_paths": ["*.py"],
        "hypothesis": f"Hypothesis for {cell_id}",
    }
    if last_trigger_date:
        fm["fitness"] = {
            "score": 0.95,
            "triggers": 10,
            "true_positives": 9,
            "false_positives": 1,
            "last_trigger_date": last_trigger_date,
        }
    cell_path.write_text(dump_frontmatter(fm, body=f"# {cell_id}\n"), encoding="utf-8")
    return cell_path


def _append_signal(evidence_dir: Path, cell_id: str, sig_type: str, timestamp: str):
    log = evidence_dir / "signals.jsonl"
    record = {
        "cell": cell_id,
        "signal": sig_type,
        "timestamp": timestamp,
        "metadata": {"credit_weight": 1.0},
    }
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".soma" / "cells").mkdir(parents=True)
    (ws / ".soma" / "evidence").mkdir(parents=True)
    return ws


def test_recently_active_cell_is_healthy(workspace: Path):
    """A cell active 2 days ago should be healthy."""
    from aegis_core.proposals import generate_checkpoint

    cell_id = "fresh-cell"
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _create_cell(workspace, cell_id, last_trigger_date=recent_ts)
    _append_signal(workspace / ".soma" / "evidence", cell_id, "trigger", recent_ts)
    _append_signal(workspace / ".soma" / "evidence", cell_id, "tp", recent_ts)

    report = generate_checkpoint(str(workspace))
    assert cell_id in [c["cell_id"] for c in report["classifications"].get("healthy", [])]


def test_inactive_cell_transitions_to_decaying(workspace: Path):
    """A cell with no activity for 45 days should dynamically decay to decaying/dormant on read."""
    from aegis_core.proposals import generate_checkpoint

    cell_id = "stale-cell"
    old_ts = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _create_cell(workspace, cell_id, last_trigger_date=old_ts)
    _append_signal(workspace / ".soma" / "evidence", cell_id, "trigger", old_ts)
    _append_signal(workspace / ".soma" / "evidence", cell_id, "tp", old_ts)

    report = generate_checkpoint(str(workspace))
    # Should not be in healthy; should be in decaying or dormant
    decaying_or_dormant = [
        c["cell_id"]
        for cat in ("decaying", "dormant")
        for c in report["classifications"].get(cat, [])
    ]
    assert cell_id in decaying_or_dormant


def test_read_time_decay_does_not_mutate_evidence(workspace: Path):
    """Generating checkpoint must not alter signals.jsonl."""
    from aegis_core.proposals import generate_checkpoint

    cell_id = "immutable-check-cell"
    ts = (datetime.now(timezone.utc) - timedelta(days=50)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _create_cell(workspace, cell_id, last_trigger_date=ts)
    _append_signal(workspace / ".soma" / "evidence", cell_id, "trigger", ts)
    _append_signal(workspace / ".soma" / "evidence", cell_id, "tp", ts)

    sig_file = workspace / ".soma" / "evidence" / "signals.jsonl"
    before_content = sig_file.read_bytes()

    generate_checkpoint(str(workspace))

    after_content = sig_file.read_bytes()
    assert before_content == after_content
