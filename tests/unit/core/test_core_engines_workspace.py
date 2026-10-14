"""Tests for Phase 17: Core Engines Workspace Migration (v0.114.0).

Verifies that lifecycle, arbitration, outcomes, defects, and sync engines
operate directly with strongly-typed Workspace value objects, and that
legacy standalone getters emit DeprecationWarning while preserving backward compatibility.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pytest
import warnings

from aegis_core.proposals import (
    generate_checkpoint,
    get_escalation_protocol,
    soma_propose_change,
)
from aegis_core.defects import audit_expiry, load_registry
from aegis_core.enforcement import (
    _match_cells,
    generate_ci_report,
    verify_readme_claims,
    verify_regression_tests,
)
from aegis_core.lifecycle.creation import create_cell, transfer_cell
from aegis_core.lifecycle.decay import compute_cells_fitness
from aegis_core.lifecycle.parsers import find_cell_file, _load_cells, _load_evidence
from aegis_core.lifecycle.promotion import evaluate_demotions, evaluate_promotions
from aegis_core.lifecycle.selection import run_cell_selection
from aegis_core.outcomes import harvest_git_history, run_outcome_engine
from aegis_core.sync import load_soma_config, run_post_session_hook
from aegis_core.workspace import Workspace


@pytest.fixture
def mock_soma_workspace(tmp_path: Path) -> Workspace:
    """Create a temporary initialized Soma workspace structure."""
    cells_dir = tmp_path / ".aegis" / "rules"
    traps_dir = cells_dir / "traps"
    walls_dir = cells_dir / "invariants"
    metrics_dir = tmp_path / ".aegis" / "metrics"
    evidence_dir = tmp_path / ".aegis" / "evidence"
    for d in (traps_dir, walls_dir, metrics_dir, evidence_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Add a sample cell
    sample_cell = traps_dir / "test-rule.md"
    sample_cell.write_text(
        "---\n"
        "id: test-rule\n"
        "type: trap\n"
        "enforcement: advisory\n"
        "hypothesis: \"Avoid raw SQL queries\"\n"
        "prediction: \"SQL injection risk reduced\"\n"
        "falsification: \"ORM eliminates vulnerability\"\n"
        "created: \"2026-01-01\"\n"
        "target_paths: [\"*.py\"]\n"
        "fitness:\n"
        "  triggers: 5\n"
        "  true_positives: 4\n"
        "  false_positives: 1\n"
        "  score: 0.8\n"
        "---\n"
        "## Trap: Avoid raw SQL queries\n"
        "Always use parameterized queries or an ORM.\n",
        encoding="utf-8",
    )

    signals_file = evidence_dir / "signals.jsonl"
    signals_file.write_text(
        json.dumps({
            "cell": "test-rule",
            "signal_type": "trigger",
            "timestamp": "2026-01-02T00:00:00Z",
        }) + "\n" +
        json.dumps({
            "cell": "test-rule",
            "signal_type": "tp",
            "timestamp": "2026-01-02T00:00:00Z",
        }) + "\n",
        encoding="utf-8",
    )

    return Workspace(root=tmp_path)


class TestPurgedLegacyGetters:
    """Verify that legacy standalone path getters have been permanently purged in v0.120.0."""

    def test_legacy_getters_purged_from_workspace_module(self):
        import aegis_core.workspace as scw
        for getter in ("get_cells_dir", "get_metrics_dir", "get_signals_file", "get_outcomes_file"):
            assert not hasattr(scw, getter), f"{getter} must be purged from aegis_core.workspace"
            assert getter not in scw.__all__, f"{getter} must not be in aegis_core.workspace.__all__"


class TestLifecycleWorkspaceInteroperability:
    """Verify lifecycle subsystem functions accept Workspace directly."""

    def test_create_cell_with_workspace_instance(self, mock_soma_workspace: Workspace):
        created = create_cell(
            cell_type="trap",
            hypothesis="Always validate user inputs",
            workspace=mock_soma_workspace,
        )
        assert isinstance(created, Path)
        assert created.is_file()
        assert str(mock_soma_workspace.rules_dir) in str(created)

    def test_transfer_cell_with_workspace_instance(self, mock_soma_workspace: Workspace, tmp_path: Path):
        dest_dir = tmp_path / "dest_repo"
        (dest_dir / ".aegis" / "rules").mkdir(parents=True)

        res = transfer_cell(
            cell_id="test-rule",
            target_dir_str=str(dest_dir),
            source_workspace=mock_soma_workspace,
        )
        assert res == 0
        dest_cell = dest_dir / ".aegis" / "rules" / "traps" / "test-rule.md"
        assert dest_cell.is_file()

    def test_compute_cells_fitness_with_workspace_instance(self, mock_soma_workspace: Workspace):
        fitness_list = compute_cells_fitness(workspace=mock_soma_workspace)
        assert len(fitness_list) >= 1
        names = [f["cell"] for f in fitness_list]
        assert "test-rule.md" in names

    def test_run_cell_selection_with_workspace_instance(self, mock_soma_workspace: Workspace):
        res = run_cell_selection(workspace=mock_soma_workspace, execute=False)
        assert res == 0

    def test_parsers_and_promotions_with_workspace_instance(self, mock_soma_workspace: Workspace):
        cells = _load_cells(mock_soma_workspace)
        assert len(cells) >= 1
        assert any(c["id"] == "test-rule" for c in cells)

        evidence = _load_evidence(mock_soma_workspace)
        assert "test-rule" in evidence

        cand_file, ctype = find_cell_file(mock_soma_workspace, "test-rule")
        assert cand_file is not None
        assert cand_file.is_file()
        assert ctype == "trap"

        promotions = evaluate_promotions(mock_soma_workspace)
        assert isinstance(promotions, list)

        demotions = evaluate_demotions(mock_soma_workspace)
        assert isinstance(demotions, list)


class TestArbitrationWorkspaceInteroperability:
    """Verify arbitration functions accept Workspace directly."""

    def test_generate_checkpoint_with_workspace_instance(self, mock_soma_workspace: Workspace):
        report = generate_checkpoint(workspace=mock_soma_workspace)
        assert report["workspace"] == str(mock_soma_workspace.root)
        assert "total_cells" in report

    def test_get_escalation_protocol_with_workspace_instance(self, mock_soma_workspace: Workspace):
        proto = get_escalation_protocol("soma_core/test.py", workspace=mock_soma_workspace)
        assert proto in ("patrol", "sweep", "vanguard", "bulwark", "fortress", "citadel", "unknown")

    def test_soma_propose_change_with_workspace_instance(self, mock_soma_workspace: Workspace):
        target = mock_soma_workspace.root / "example.txt"
        target.write_text("initial content\n", encoding="utf-8")
        verdict = soma_propose_change(
            file_path="example.txt",
            proposed_content="updated content\n",
            workspace=mock_soma_workspace,
        )
        assert "APPROVED" in verdict or "ESCALATION_REQUIRED" in verdict


class TestOutcomesAndSyncWorkspaceInteroperability:
    """Verify outcomes, defects, enforcement, and sync accept Workspace directly."""

    def test_harvest_git_history_with_workspace_instance(self, mock_soma_workspace: Workspace):
        result = harvest_git_history(workspace=mock_soma_workspace, dry_run=True)
        assert "commits_inspected" in result
        assert "cells_matched" in result

    def test_run_outcome_engine_with_workspace_instance(self, mock_soma_workspace: Workspace):
        code = run_outcome_engine(workspace=mock_soma_workspace)
        assert code in (0, 1)

    def test_defects_and_enforcement_with_workspace_instance(self, mock_soma_workspace: Workspace):
        # Create dummy bug registry
        reg_dir = mock_soma_workspace.root / "docs" / "project"
        reg_dir.mkdir(parents=True, exist_ok=True)
        reg_file = reg_dir / "BUG_REGISTRY.json"
        reg_file.write_text(json.dumps({"bugs": []}), encoding="utf-8")

        reg = load_registry(mock_soma_workspace)
        assert reg == {"bugs": []}

        audit = audit_expiry(mock_soma_workspace)
        assert isinstance(audit, list)

        matched = _match_cells(mock_soma_workspace, ["some_file.py"])
        assert isinstance(matched, list)

    def test_sync_with_workspace_instance(self, mock_soma_workspace: Workspace):
        # Create a dummy aegis.conf
        conf_file = mock_soma_workspace.root / "aegis.conf"
        conf_file.write_text("TEAM_REPO=/tmp/team\n", encoding="utf-8")
        cfg = load_soma_config(repo_dir=mock_soma_workspace)
        assert cfg.get("TEAM_REPO") == "/tmp/team"

        dummy_transcript = mock_soma_workspace.root / "transcript.jsonl"
        dummy_transcript.write_text("{}\n", encoding="utf-8")
        res = run_post_session_hook(
            transcript_path=dummy_transcript,
            repo_root=mock_soma_workspace,
        )
        assert res in (0, 1)

    def test_generate_ci_report_with_workspace_instance(self, mock_soma_workspace: Workspace):
        report = generate_ci_report(
            workspace=mock_soma_workspace,
            changed_files=["tests/test_core.py"],
            test_passed=True,
            commit_sha="abcdef123456",
        )
        assert "matched_rules" in report
        assert "summary" in report
        assert "Aegis CI Outcome Report" in report["summary"]


    def test_verify_registry_and_claims_with_workspace_instance(self, mock_soma_workspace: Workspace):
        # Regression tests on empty registry
        reg = {"bugs": []}
        errors = verify_regression_tests(reg, workspace=mock_soma_workspace)
        assert errors == []

        # Claim registry verification when missing file
        ok, fails = verify_readme_claims(workspace=mock_soma_workspace)
        assert not ok
        assert any("Claim registry not found" in f for f in fails)


