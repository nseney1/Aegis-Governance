"""Tests for Closed-Loop Attribution Correlation Mapping (Phase 22 / v0.119.0).

Validates:
1. Layer 1 tool failures attribute True Positives (TP) to matching cells.
2. Spurious/dismissed predictions attribute False Positives (FP) to matching cells.
3. Fallback inference maps cell ID and tags to RiskCategory taxonomy.
4. Attribution updates cell markdown frontmatter (triggers, true_positives, false_positives, last_trigger_date).
5. Attribution appends structured signal records to .soma/evidence/signals.jsonl.
6. VerificationPipeline auto-invokes attribution on verified runs.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from aegis_core.attribution import (
    attribute_verification_outcome,
    infer_cell_risk_categories,
)
from aegis_core.yaml import parse_frontmatter
from aegis_core.verification import (
    ArbitrationResult,
    Claim,
    Divergence,
    Prediction,
    RiskCategory,
    Severity,
    ToolEvidence,
    Verdict,
)
from aegis_core.verification.pipeline import (
    DeterministicVerifier,
    VerificationPipeline,
)


@pytest.fixture
def workspace_with_cells(tmp_path: Path) -> Path:
    """Create a minimal mock workspace with governance cells and evidence directory."""
    cells_dir = tmp_path / ".soma" / "cells"
    walls_dir = cells_dir / "walls"
    walls_dir.mkdir(parents=True)
    evidence_dir = tmp_path / ".soma" / "evidence"
    evidence_dir.mkdir(parents=True)

    # Cell 1: Explicit risk_categories
    cell1 = walls_dir / "wall-import-boundary.md"
    cell1.write_text(
        "---\n"
        "id: wall-import-boundary\n"
        "type: wall\n"
        "enforcement: gate\n"
        "risk_categories:\n"
        "  - boundary_violation\n"
        "fitness:\n"
        "  triggers: 0\n"
        "  true_positives: 0\n"
        "  false_positives: 0\n"
        "---\n\n"
        "# Import Boundary Rule\n"
        "Do not violate import boundaries.\n",
        encoding="utf-8",
    )

    # Cell 2: Infer from ID
    cell2 = walls_dir / "wall-persistence-gap.md"
    cell2.write_text(
        "---\n"
        "id: wall-persistence-gap\n"
        "type: wall\n"
        "enforcement: gate\n"
        "fitness:\n"
        "  triggers: 2\n"
        "  true_positives: 2\n"
        "  false_positives: 0\n"
        "---\n\n"
        "# Persistence Invariant\n"
        "Ensure state is saved.\n",
        encoding="utf-8",
    )

    return tmp_path


class TestClosedLoopAttribution:
    """Verifies outcome attribution to cells and signals.jsonl."""

    def test_infer_cell_risk_categories(self):
        """Infers RiskCategory from explicit frontmatter, tags, or cell ID."""
        # 1. Explicit
        cell_explicit = {"risk_categories": ["boundary_violation", "code_injection"]}
        cats = infer_cell_risk_categories(cell_explicit)
        assert RiskCategory.BOUNDARY_VIOLATION in cats
        assert RiskCategory.CODE_INJECTION in cats

        # 2. Inferred from tags
        cell_tagged = {"tags": ["dead_code", "security"]}
        cats_tagged = infer_cell_risk_categories(cell_tagged)
        assert RiskCategory.DEAD_CODE in cats_tagged

        # 3. Inferred from ID
        cell_id = {"id": "wall-import-boundary-check"}
        cats_id = infer_cell_risk_categories(cell_id)
        assert RiskCategory.BOUNDARY_VIOLATION in cats_id

    def test_layer1_failure_attributes_true_positive(self, workspace_with_cells: Path):
        """Layer 1 tool failure attributes a TP to the matching cell and increments TP + triggers."""
        evidence = [
            ToolEvidence(
                tool="import_guard",
                target="soma_core/bad_import.py",
                verdict=False,
                detail="Forbidden import of torch",
                lines=[5],
            )
        ]

        signals = attribute_verification_outcome(
            workspace=workspace_with_cells,
            layer1_evidence=evidence,
            arbitration_result=None,
        )

        assert len(signals) >= 1
        tp_sig = next(s for s in signals if s["cell_id"] == "wall-import-boundary")
        assert tp_sig["attribution"] == "TP"
        assert tp_sig["risk_category"] == "boundary_violation"

        # Verify cell frontmatter updated on disk
        cell_path = workspace_with_cells / ".soma" / "cells" / "walls" / "wall-import-boundary.md"
        fm = parse_frontmatter(cell_path.read_text(encoding="utf-8"))
        fitness = fm["fitness"]
        assert fitness["true_positives"] == 1
        assert fitness["triggers"] == 1
        assert "last_trigger_date" in fitness

        # Verify written to signals.jsonl
        signals_file = workspace_with_cells / ".soma" / "evidence" / "signals.jsonl"
        assert signals_file.is_file()
        lines = signals_file.read_text(encoding="utf-8").strip().split("\n")
        assert any("wall-import-boundary" in line and "TP" in line for line in lines)

    def test_spurious_prediction_attributes_false_positive(self, workspace_with_cells: Path):
        """Spurious or dismissed prediction attributes FP and increments FP + triggers."""
        pred = Prediction(
            category=RiskCategory.PERSISTENCE_GAP,
            severity=Severity.HIGH,
            risk="Possible unsaved state",
            mechanism="State mutated in memory but not flushed",
            affected_function="save_state",
        )
        divergence = Divergence(
            divergence_type="dismissed_prediction",
            category=RiskCategory.PERSISTENCE_GAP,
            prediction=pred,
            resolution="Dismissed: state is persisted via transaction commit",
        )
        arb_result = ArbitrationResult(
            divergences=[divergence],
            convergences=[],
            verdict=Verdict.SHIP,
            layer1_results=[],
            predictions=[pred],
            claims=[],
        )

        signals = attribute_verification_outcome(
            workspace=workspace_with_cells,
            layer1_evidence=[],
            arbitration_result=arb_result,
        )

        assert len(signals) >= 1
        fp_sig = next(s for s in signals if s["cell_id"] == "wall-persistence-gap")
        assert fp_sig["attribution"] == "FP"
        assert fp_sig["risk_category"] == "persistence_gap"

        # Verify cell frontmatter updated
        cell_path = workspace_with_cells / ".soma" / "cells" / "walls" / "wall-persistence-gap.md"
        fm = parse_frontmatter(cell_path.read_text(encoding="utf-8"))
        fitness = fm["fitness"]
        assert fitness["triggers"] == 3  # Initial 2 + 1
        assert fitness["false_positives"] == 1

    def test_pipeline_integration_auto_attributes(self, workspace_with_cells: Path):
        """VerificationPipeline.verify(..., attribute=True) automatically attributes outcomes."""
        src_file = workspace_with_cells / "module.py"
        src_file.write_text("import google.genai\n", encoding="utf-8")

        pipeline = VerificationPipeline()
        res = pipeline.verify(
            changed_files=["module.py"],
            workspace=workspace_with_cells,
            attribute=True,
        )

        # Layer 1 failed because of unguarded import
        assert not res.layer1_passed
        # Check signals file for attribution
        signals_file = workspace_with_cells / ".soma" / "evidence" / "signals.jsonl"
        assert signals_file.is_file()
        content = signals_file.read_text(encoding="utf-8")
        assert "wall-import-boundary" in content
