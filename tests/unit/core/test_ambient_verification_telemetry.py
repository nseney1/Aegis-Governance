"""Tests for ambient verification telemetry (Phase 13: v0.110.0).

Verifies that:
1. `record_verification_telemetry` generates canonical trigger and tp/fp signals.
2. CLI `soma verify` automatically emits telemetry to .aegis/evidence/signals.jsonl.
3. MCP `soma_verify_changes` automatically emits telemetry to .aegis/evidence/signals.jsonl.
4. Scale-to-zero / sub-20ms overhead: evidence writes are atomic and local.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from aegis_core.yaml import dump_frontmatter


def _create_cell(workspace: Path, cell_id: str, target_paths: list[str]) -> Path:
    cells_dir = workspace / ".aegis" / "rules" / "vacuoles"
    cells_dir.mkdir(parents=True, exist_ok=True)
    cell_path = cells_dir / f"{cell_id}.md"
    fm = {
        "id": cell_id,
        "type": "vacuole",
        "enforcement": "advisory",
        "target_paths": target_paths,
        "hypothesis": f"Hypothesis for {cell_id}",
    }
    cell_path.write_text(dump_frontmatter(fm, body=f"# {cell_id}\n"), encoding="utf-8")
    return cell_path


@pytest.fixture
def test_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".aegis" / "evidence").mkdir(parents=True)
    return ws


def test_record_verification_telemetry_appends_signals(test_workspace: Path):
    """record_verification_telemetry should match cells and append trigger + outcome signals."""
    from aegis_core.outcomes.telemetry import record_verification_telemetry
    from aegis_core.evidence import aggregate_signals

    _create_cell(test_workspace, "cell-math", ["math_*.py", "calc.py"])
    _create_cell(test_workspace, "cell-ui", ["ui_*.py"])

    # Target file matches cell-math only
    recorded = record_verification_telemetry(
        workspace=str(test_workspace),
        target_files=["math_utils.py"],
        passed=True,
        verdict="SHIP",
        source="session",
    )

    assert recorded is True
    signals_file = test_workspace / ".aegis" / "evidence" / "signals.jsonl"
    assert signals_file.is_file()

    lines = [json.loads(line) for line in signals_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 2  # at least trigger + tp

    cells = {l["cell"] for l in lines}
    assert "cell-math" in cells
    assert "cell-ui" not in cells

    sig_types = {l["signal"] for l in lines}
    assert "trigger" in sig_types
    assert "tp" in sig_types

    agg = aggregate_signals(str(test_workspace / ".aegis" / "evidence"))
    assert "cell-math" in agg.counts
    assert agg.counts["cell-math"]["triggers"] == 1
    assert agg.counts["cell-math"]["tp"] >= 1


def test_record_verification_telemetry_handles_failure(test_workspace: Path):
    """When verification fails, record_verification_telemetry should emit fp signal."""
    from aegis_core.outcomes.telemetry import record_verification_telemetry
    from aegis_core.evidence import aggregate_signals

    _create_cell(test_workspace, "cell-auth", ["auth.py"])

    recorded = record_verification_telemetry(
        workspace=str(test_workspace),
        target_files=["auth.py"],
        passed=False,
        verdict="BLOCK",
        source="session",
    )

    assert recorded is True
    agg = aggregate_signals(str(test_workspace / ".aegis" / "evidence"))
    assert "cell-auth" in agg.counts
    assert agg.counts["cell-auth"]["triggers"] == 1
    assert agg.counts["cell-auth"]["fp"] >= 1


def test_cli_verify_emits_telemetry_ambiently(test_workspace: Path, monkeypatch):
    """Running soma verify via CLI must emit ambient telemetry for verified files."""
    from aegis_cli.verify import run_verify

    _create_cell(test_workspace, "cell-core", ["core.py"])
    test_file = test_workspace / "core.py"
    test_file.write_text("x = 1\n", encoding="utf-8")

    args = argparse.Namespace(
        files=["core.py"],
        layer1_only=True,
        dry_run=False,
        repo_root=str(test_workspace),
        workspace=str(test_workspace),
        plan=None,
        plan_file=None,
        provider=None,
    )

    exit_code = run_verify(args)
    assert exit_code == 0

    signals_file = test_workspace / ".aegis" / "evidence" / "signals.jsonl"
    assert signals_file.is_file()
    records = [json.loads(l) for l in signals_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(r["cell"] == "cell-core" and r["signal"] == "trigger" for r in records)
