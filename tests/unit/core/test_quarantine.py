"""Tests for quarantine management and CLI subcommand."""
import json
import time
from pathlib import Path

import pytest

from aegis_core.quarantine import (
    safe_parse_cell_file,
    list_quarantine,
    inspect_quarantined_file,
    prune_quarantine,
    quarantine_file,
)
from aegis_cli.cli import main as cli_main


@pytest.fixture
def workspace_with_quarantine(tmp_path: Path) -> Path:
    ws = tmp_path / "test_ws"
    ws.mkdir(parents=True)
    (ws / ".soma" / "cells").mkdir(parents=True)
    q_dir = ws / ".soma" / "quarantine"
    q_dir.mkdir(parents=True)
    return ws


def test_safe_parse_cell_with_bom(workspace_with_quarantine: Path):
    cell_file = workspace_with_quarantine / ".soma" / "cells" / "test_cell.md"
    # Write UTF-8 BOM + valid frontmatter
    cell_file.write_bytes(b"\xef\xbb\xbf---\nid: test_cell\ntype: membrane\n---\nBody here\n")

    metadata, body, status = safe_parse_cell_file(cell_file, workspace=workspace_with_quarantine)
    assert status == "ok"
    assert metadata.get("id") == "test_cell"
    assert "Body here" in body
    # Ensure it was NOT quarantined
    q_dir = workspace_with_quarantine / ".soma" / "quarantine"
    assert list(q_dir.glob("*.corrupt")) == []


def test_list_quarantine(workspace_with_quarantine: Path):
    bad_file = workspace_with_quarantine / "bad.json"
    bad_file.write_text("{corrupt json", encoding="utf-8")
    quarantine_file(bad_file, reason="syntax error", workspace=workspace_with_quarantine)

    items = list_quarantine(workspace=workspace_with_quarantine)
    assert len(items) == 1
    assert items[0]["filename"].endswith(".corrupt")
    assert items[0]["reason"] == "syntax error"
    assert items[0]["size_bytes"] > 0
    assert "timestamp" in items[0]


def test_inspect_quarantined_file(workspace_with_quarantine: Path):
    bad_file = workspace_with_quarantine / "bad.txt"
    bad_file.write_text("damaged payload", encoding="utf-8")
    q_path = quarantine_file(bad_file, reason="damaged", workspace=workspace_with_quarantine)

    detail = inspect_quarantined_file(q_path.name, workspace=workspace_with_quarantine)
    assert detail is not None
    assert detail["filename"] == q_path.name
    assert detail["reason"] == "damaged"
    assert "damaged payload" in detail["preview"]


def test_prune_quarantine(workspace_with_quarantine: Path):
    q_dir = workspace_with_quarantine / ".soma" / "quarantine"

    # Create an old corrupt file (simulating 40 days ago)
    old_ts = int(time.time()) - (40 * 86400)
    old_file = q_dir / f"old_item.{old_ts}.corrupt"
    old_file.write_text("ancient corrupt", encoding="utf-8")

    # Create a fresh corrupt file (simulating 1 day ago)
    new_ts = int(time.time()) - (1 * 86400)
    new_file = q_dir / f"new_item.{new_ts}.corrupt"
    new_file.write_text("fresh corrupt", encoding="utf-8")

    # Record both in log
    log_file = q_dir / "quarantine_log.jsonl"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"quarantined_file": old_file.name, "timestamp": "2026-08-01T00:00:00Z", "reason": "old"}) + "\n")
        f.write(json.dumps({"quarantined_file": new_file.name, "timestamp": "2026-10-04T00:00:00Z", "reason": "new"}) + "\n")

    # Prune items older than 30 days
    pruned_count = prune_quarantine(older_than_days=30, workspace=workspace_with_quarantine)
    assert pruned_count == 1
    assert not old_file.exists()
    assert new_file.exists()



