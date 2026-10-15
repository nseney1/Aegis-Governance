"""Unit tests for the oracle checkpoint in aegis_core.proposals."""
from __future__ import annotations

import os
from pathlib import Path
import pytest

from aegis_core.proposals import _classify_cell, generate_checkpoint


class TestArbitrationCore:
    def test_checkpoint_generation_on_empty_workspace(self, tmp_path: Path):
        ws = tmp_path / "empty_ws"
        (ws / ".aegis" / "rules").mkdir(parents=True)
        (ws / ".aegis" / "evidence").mkdir(parents=True)

        report = generate_checkpoint(str(ws))
        assert report["total_cells"] == 0
        assert report["classifications"] == {}
        assert "timestamp" in report

    def test_checkpoint_generation_with_cell(self, tmp_path: Path):
        ws = tmp_path / "ws_with_cell"
        cells_dir = ws / ".aegis" / "rules" / "walls"
        cells_dir.mkdir(parents=True)
        (ws / ".aegis" / "evidence").mkdir(parents=True)
        (cells_dir / "wall1.md").write_text(
            "---\nid: wall1\ntype: wall\nenforcement: gate\n---\n# Wall 1\n",
            encoding="utf-8",
        )
        report = generate_checkpoint(str(ws))
        assert report["total_cells"] == 1
        assert "unobserved" in report["classifications"]
        assert report["classifications"]["unobserved"][0]["cell_id"] == "wall1"

    def test_classify_cell_logic(self):
        cell = {"id": "test-cell", "type": "vacuole"}
        evidence = {
            "test-cell": {
                "triggers": 10,
                "tp": 9,
                "fp": 1,
                "has_outcomes": True,
            }
        }
        cat, details = _classify_cell(cell, evidence, set())
        assert cat == "healthy"
        assert "9/10 true positives" in details

        noisy_evidence = {
            "test-cell": {
                "triggers": 10,
                "tp": 2,
                "fp": 8,
                "has_outcomes": True,
            }
        }
        cat, details = _classify_cell(cell, noisy_evidence, set())
        assert cat == "noisy"
