"""Unit tests for aegis_core.proposals."""
from __future__ import annotations

import os
from pathlib import Path
import pytest

from aegis_core.proposals import (
    TTCVerifier,
    VERDICT_APPROVED,
    VERDICT_REJECTED,
    _classify_cell,
    generate_checkpoint,
    get_escalation_protocol,
    load_oracles,
    self_test_verifier,
    soma_propose_change,
)


class TestArbitrationCore:
    def test_ttc_verifier_playbook_matching(self):
        playbooks = [
            {
                "name": "chloroplast-react-idioms",
                "hypothesis": "React components must be functional.",
                "guidance": "class component syntax is disallowed",
            }
        ]
        verifier = TTCVerifier(playbooks)
        diff_bad = "+ class LegacyApp extends Component {"
        res = verifier.verify_proposal(diff_bad, "src/App.jsx")
        assert res["status"] == VERDICT_REJECTED
        assert "no-class-components" in res["reason"]

        diff_good = "+ const ModernApp = () => <div />;"
        res = verifier.verify_proposal(diff_good, "src/App.jsx")
        assert res["status"] == VERDICT_APPROVED

    def test_escalation_protocol_classification(self):
        assert get_escalation_protocol("enzymes/common.sh", "/tmp") == "trident"
        assert get_escalation_protocol("install.sh", "/tmp") == "trident"
        assert get_escalation_protocol("tests/test_foo.py", "/tmp") == "gale"
        assert get_escalation_protocol("README.md", "/tmp") == "breeze"

    def test_soma_propose_change_containment(self, tmp_path: Path):
        ws = tmp_path / "workspace"
        (ws / ".soma" / "cells").mkdir(parents=True)

        res = soma_propose_change("../escaped.py", "content", [], workspace=str(ws))
        assert "VERDICT: REJECTED" in res
        assert "path traversal blocked" in res

    def test_checkpoint_generation_on_empty_workspace(self, tmp_path: Path):
        ws = tmp_path / "empty_ws"
        (ws / ".soma" / "cells").mkdir(parents=True)
        (ws / ".soma" / "evidence").mkdir(parents=True)

        report = generate_checkpoint(str(ws))
        assert report["total_cells"] == 0
        assert report["classifications"] == {}
        assert "timestamp" in report

    def test_checkpoint_generation_with_cell(self, tmp_path: Path):
        ws = tmp_path / "ws_with_cell"
        cells_dir = ws / ".soma" / "cells" / "walls"
        cells_dir.mkdir(parents=True)
        (ws / ".soma" / "evidence").mkdir(parents=True)
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

    def test_self_test_verifier(self):
        assert self_test_verifier() == 0

    def test_load_oracles_missing_dir(self, tmp_path: Path):
        assert load_oracles(tmp_path) == []

    def test_load_oracles_rules_dir(self, tmp_path: Path):
        oracles_dir = tmp_path / "rules" / ".oracles"
        oracles_dir.mkdir(parents=True)
        (oracles_dir / "b_oracle.md").write_text("# Oracle B", encoding="utf-8")
        (oracles_dir / "a_oracle.md").write_text("# Oracle A", encoding="utf-8")
        (oracles_dir / "ignore.txt").write_text("not markdown", encoding="utf-8")

        res = load_oracles(str(tmp_path))
        assert len(res) == 2
        assert res[0] == ("a_oracle.md", "# Oracle A")
        assert res[1] == ("b_oracle.md", "# Oracle B")

    def test_load_oracles_genome_fallback(self, tmp_path: Path):
        oracles_dir = tmp_path / "genome" / ".oracles"
        oracles_dir.mkdir(parents=True)
        (oracles_dir / "fallback.md").write_text("# Fallback Oracle", encoding="utf-8")

        res = load_oracles(tmp_path)
        assert len(res) == 1
        assert res[0] == ("fallback.md", "# Fallback Oracle")
