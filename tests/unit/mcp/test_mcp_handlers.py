"""Unit and contract tests for decomposed MCP handlers (audit, governance, telemetry, verification)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import pytest

from aegis_mcp.handlers.audit import (
    _handle_audit_security,
    _handle_audit_performance,
    _handle_scan,
)
from aegis_mcp.handlers.governance import (
    _handle_create_cell,
    _handle_list_cells,
    _handle_propose_change,
    _handle_generate_manifest,
    _handle_soma_handoff,
)
from aegis_mcp.handlers.telemetry import (
    _handle_report_outcome,
    _handle_capture_insight,
    _handle_grade,
    _handle_coverage,
    _handle_fitness,
)
from aegis_mcp.handlers.verification import (
    _handle_verify_changes,
    _handle_poll_verification,
    _handle_checkpoint,
    _handle_request_receipt,
)
from aegis_core.yaml import dump_frontmatter


@pytest.fixture
def mcp_workspace(tmp_path: Path) -> Path:
    cells_dir = tmp_path / ".aegis" / "rules" / "vacuoles"
    cells_dir.mkdir(parents=True, exist_ok=True)
    cell_file = cells_dir / "sample-cell.md"
    fm = {
        "id": "sample-cell",
        "type": "vacuole",
        "target_paths": ["src/*.py"],
        "hypothesis": "Sample hypothesis",
        "fitness": {"score": 0.5, "triggers": 1, "true_positives": 1, "false_positives": 0},
    }
    cell_file.write_text(f"---\n{dump_frontmatter(fm)}---\n\n# Body\n", encoding="utf-8")
    (tmp_path / ".aegis" / "evidence").mkdir(parents=True, exist_ok=True)
    (tmp_path / "genome").mkdir(parents=True, exist_ok=True)
    return tmp_path


# ── Audit Handlers ──────────────────────────────────────────────────────────

def test_audit_security(mcp_workspace: Path):
    ws = str(mcp_workspace)
    # Clean code pass
    res_pass = _handle_audit_security({"workspace": ws, "proposed_content": "def foo(): return 1"}, None)
    assert res_pass["status"] == "PASS"

    # Hardcoded secret fail
    res_secret = _handle_audit_security({"workspace": ws, "proposed_content": "password='secret'"}, None)
    assert res_secret["status"] == "FAIL"

    # Eval injection fail
    res_eval = _handle_audit_security({"workspace": ws, "proposed_content": "eval(x)"}, None)
    assert res_eval["status"] == "FAIL"

    # XSS fail
    res_xss = _handle_audit_security({"workspace": ws, "file_path": "index.html", "proposed_content": "element.innerHTML = x"}, None)
    assert res_xss["status"] == "FAIL"

    # SQL injection fail
    res_sql = _handle_audit_security({"workspace": ws, "file_path": "query.sql", "proposed_content": "f'SELECT * FROM users'"}, None)
    assert res_sql["status"] == "FAIL"

    # Path traversal error
    res_trav = _handle_audit_security({"workspace": ws, "file_path": "../outside.py"}, None)
    assert res_trav["status"] == "FAIL"
    assert "error" in res_trav


def test_audit_performance(mcp_workspace: Path):
    ws = str(mcp_workspace)
    res_pass = _handle_audit_performance({"workspace": ws, "proposed_content": "def foo(): return 1"}, None)
    assert res_pass["status"] == "PASS"

    # Nested loops
    nested = "for a in x:\n for b in y:\n  for c in z:\n   pass"
    res_loop = _handle_audit_performance({"workspace": ws, "proposed_content": nested}, None)
    assert res_loop["status"] == "FAIL"

    # Inefficient query
    res_q = _handle_audit_performance({"workspace": ws, "proposed_content": "db.query('SELECT *')"}, None)
    assert res_q["status"] == "FAIL"

    # Wildcard import
    res_wildcard = _handle_audit_performance({"workspace": ws, "file_path": "main.py", "proposed_content": "from os import *"}, None)
    assert res_wildcard["status"] == "FAIL"

    # Path traversal error
    res_trav = _handle_audit_performance({"workspace": ws, "file_path": "../outside.py"}, None)
    assert res_trav["status"] == "FAIL"
    assert "error" in res_trav


def test_scan(mcp_workspace: Path):
    ws = str(mcp_workspace)
    # Valid scan
    res = _handle_scan({"workspace": ws, "files": ["src/main.py"]}, None)
    assert isinstance(res, dict)

    # Invalid workspace
    res_ws = _handle_scan({"workspace": "/invalid\0path"}, None)
    assert res_ws["status"] == "FAIL"

    # Non-list files
    res_files = _handle_scan({"workspace": ws, "files": "not-a-list"}, None)
    assert res_files["status"] == "FAIL"

    # Path traversal in files
    res_trav = _handle_scan({"workspace": ws, "files": ["../outside.py"]}, None)
    assert res_trav["status"] == "FAIL"


# ── Governance Handlers ─────────────────────────────────────────────────────

def test_governance_create_and_list_cells(mcp_workspace: Path):
    ws = str(mcp_workspace)
    # Dry run create cell
    res_create = _handle_create_cell({
        "workspace": ws,
        "description": "Rule to test something",
        "domain": "testing",
        "cell_type": "vacuole",
        "dry_run": True,
    }, None)
    assert "prompt" in res_create
    assert res_create.get("dry_run") is True

    # Non-dry-run create cell
    res_create_live = _handle_create_cell({
        "workspace": ws,
        "description": "Rule to test live creation",
        "domain": "testing",
        "cell_type": "vacuole",
        "dry_run": False,
    }, None)
    assert "prompt" in res_create_live
    assert "instruction" in res_create_live

    # Invalid workspace
    res_bad_ws = _handle_create_cell({"workspace": "/invalid\0path"}, None)
    assert res_bad_ws["status"] == "FAIL"

    # List cells with stdlib fallback
    res_list = _handle_list_cells({"workspace": ws}, None)
    assert isinstance(res_list, list)
    assert len(res_list) >= 1
    assert res_list[0]["id"] == "sample-cell"

    # List cells with gov object
    class MockGovSuccess:
        def list_cells(self, cell_type=None):
            return [{"id": "mock-cell"}]
    assert _handle_list_cells({"workspace": ws}, MockGovSuccess()) == [{"id": "mock-cell"}]

    # List cells with gov object raising RuntimeError
    class MockGovFail:
        def list_cells(self, cell_type=None):
            raise RuntimeError("gov list failed")
    res_gov_fail = _handle_list_cells({"workspace": ws}, MockGovFail())
    assert res_gov_fail["status"] == "FAIL"

    # List cells invalid workspace
    res_bad_ws = _handle_list_cells({"workspace": "/invalid\0path"}, None)
    assert res_bad_ws["status"] == "FAIL"


def test_governance_propose_change(mcp_workspace: Path, monkeypatch):
    ws = str(mcp_workspace)
    # Missing file_path
    res_no_file = _handle_propose_change({"workspace": ws}, None)
    assert res_no_file["status"] == "FAIL"

    # soma_propose_change is None
    import aegis_mcp.handlers.governance
    monkeypatch.setattr(aegis_mcp.handlers.governance, "soma_propose_change", None)
    assert _handle_propose_change({"workspace": ws, "file_path": "src/main.py"}, None) == {"error": "soma_propose_change not available"}
    monkeypatch.undo()

    # Invalid workspace
    res_bad_ws = _handle_propose_change({"workspace": "/invalid\0path", "file_path": "main.py"}, None)
    assert res_bad_ws["status"] == "FAIL"

    # Path traversal in file_path
    res_trav = _handle_propose_change({"workspace": ws, "file_path": "../outside.py"}, None)
    assert res_trav["status"] == "FAIL"

    # Valid propose change
    res = _handle_propose_change({
        "workspace": ws,
        "file_path": "src/main.py",
        "proposed_content": "def foo(): pass",
    }, None)
    assert isinstance(res, dict)
    assert "status" in res


def test_governance_generate_manifest(mcp_workspace: Path):
    ws = str(mcp_workspace)
    # Invalid workspace
    res_bad_ws = _handle_generate_manifest({"workspace": "/invalid\0path"}, None)
    assert res_bad_ws["status"] == "FAIL"

    # Valid manifest without key generation
    res = _handle_generate_manifest({"workspace": ws}, None)
    assert res["status"] == "OK"

    # Manifest with generate_key
    res_key = _handle_generate_manifest({"workspace": ws, "generate_key": True}, None)
    assert res_key["status"] == "OK"


def test_governance_soma_handoff(mcp_workspace: Path):
    ws = str(mcp_workspace)
    # Missing required arguments
    res_missing = _handle_soma_handoff({"workspace": ws}, None)
    assert res_missing["status"] == "FAIL"

    # Invalid workspace
    res_bad_ws = _handle_soma_handoff({
        "workspace": "/invalid\0path",
        "from_skill": "a",
        "to_skill": "b",
        "artifact_type": "DiffProposal",
        "payload": {},
    }, None)
    assert res_bad_ws["status"] == "FAIL"

    # Valid skills for handoff
    skills_dir = mcp_workspace / ".aegis" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / "scout.md").write_text("---\nid: scout\ntier: method\nproduces: [DiffProposal]\nhandoff_targets: [builder]\n---\n", encoding="utf-8")
    (skills_dir / "builder.md").write_text("---\nid: builder\nconsumes: [DiffProposal]\n---\n", encoding="utf-8")

    res_ok = _handle_soma_handoff({
        "workspace": ws,
        "from_skill": "scout",
        "to_skill": "builder",
        "artifact_type": "DiffProposal",
        "payload": {"summary": "valid proposal"},
    }, None)
    assert res_ok["status"] == "OK"
    assert "ticket" in res_ok

    # Handoff exception (unregistered target)
    res_exc = _handle_soma_handoff({
        "workspace": ws,
        "from_skill": "scout",
        "to_skill": "nonexistent_target",
        "artifact_type": "DiffProposal",
        "payload": {"summary": "invalid target"},
    }, None)
    assert res_exc["status"] == "FAIL"


# ── Telemetry Handlers ──────────────────────────────────────────────────────

def test_telemetry_report_outcome(mcp_workspace: Path, monkeypatch):
    ws = str(mcp_workspace)
    # Invalid outcome
    res_inv = _handle_report_outcome({"workspace": ws, "outcome": "invalid_val"}, None)
    assert "error" in res_inv

    # Invalid workspace
    res_bad_ws = _handle_report_outcome({"workspace": "/invalid\0path", "outcome": "tp", "idempotency_key": "k"}, None)
    assert res_bad_ws["status"] == "FAIL"

    # Missing idempotency key
    res_no_key = _handle_report_outcome({"workspace": ws, "outcome": "success", "idempotency_key": ""}, None)
    assert res_no_key["status"] == "FAIL"

    # cells_used not a list
    res_bad_cells = _handle_report_outcome({"workspace": ws, "outcome": "success", "idempotency_key": "k", "cells_used": [123]}, None)
    assert res_bad_cells["status"] == "FAIL"

    # Unknown cell
    res_unknown = _handle_report_outcome({"workspace": ws, "outcome": "success", "idempotency_key": "k", "cells_used": ["unknown_cell"]}, None)
    assert res_unknown["status"] == "FAIL"

    # No cells used (valid empty)
    res_empty_cells = _handle_report_outcome({"workspace": ws, "outcome": "success", "idempotency_key": "k_empty"}, None)
    assert res_empty_cells["status"] == "recorded"

    # rule_id argument
    res_rule_id = _handle_report_outcome({
        "workspace": ws,
        "outcome": "success",
        "rule_id": "sample-cell",
        "idempotency_key": "k_rule_id",
    }, None)
    assert res_rule_id["status"] == "recorded"

    # append_signals exception branch
    import aegis_core.telemetry
    monkeypatch.setattr(aegis_core.telemetry, "append_signals", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("disk full")))
    res_fail = _handle_report_outcome({
        "workspace": ws,
        "outcome": "success",
        "cell_id": "sample-cell",
        "idempotency_key": "k_fail",
    }, None)
    assert res_fail["status"] == "FAIL"


def test_telemetry_capture_insight(mcp_workspace: Path, monkeypatch):
    ws = str(mcp_workspace)
    # Valid capture
    res = _handle_capture_insight({
        "workspace": ws,
        "insight": "Edge case discovered",
        "was_covered": False,
        "context_files": ["src/main.py"],
    }, None)
    assert res["status"] == "recorded"

    # Invalid workspace
    res_bad_ws = _handle_capture_insight({"workspace": "/invalid\0path"}, None)
    assert res_bad_ws["status"] == "FAIL"

    # Non-list context_files
    res_bad_cf = _handle_capture_insight({"workspace": ws, "insight": "t", "context_files": "not-a-list"}, None)
    assert res_bad_cf["status"] == "FAIL"

    # Path traversal in context_files
    res_trav = _handle_capture_insight({"workspace": ws, "insight": "t", "context_files": ["../outside.py"]}, None)
    assert res_trav["status"] == "FAIL"

    # ImportError on capture_insight
    import sys
    monkeypatch.setitem(sys.modules, "aegis_core.insights", None)
    res_imp_err = _handle_capture_insight({"workspace": ws}, None)
    assert res_imp_err["status"] == "FAIL"
    assert "not importable" in res_imp_err["error"]


def test_telemetry_grade_and_coverage_and_fitness(mcp_workspace: Path, monkeypatch):
    ws = str(mcp_workspace)
    # Grade with gov
    class MockGovGrade:
        def grade(self):
            return {"overall": {"pct": 95.0, "grade": "A"}}
    assert _handle_grade({"workspace": ws}, MockGovGrade())["overall"]["grade"] == "A"

    # Grade with stdlib
    res_grade = _handle_grade({"workspace": ws}, None)
    assert isinstance(res_grade, dict)

    # Grade None result fallback
    import aegis_core.telemetry
    monkeypatch.setattr(aegis_core.telemetry, "calculate_immune_grade", lambda *a, **kw: None)
    res_none_grade = _handle_grade({"workspace": ws}, None)
    assert res_none_grade["status"] == "PASS"
    assert res_none_grade["overall"]["grade"] == "F"

    # Grade exception branch
    monkeypatch.setattr(aegis_core.telemetry, "calculate_immune_grade", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("grade err")))
    res_grade_err = _handle_grade({"workspace": ws}, None)
    assert res_grade_err["status"] == "FAIL"

    # Grade non-dict result branch
    monkeypatch.setattr(aegis_core.telemetry, "calculate_immune_grade", lambda *a, **kw: "string error")
    assert _handle_grade({"workspace": ws}, None)["status"] == "FAIL"

    # Coverage with gov
    class MockGovCoverage:
        def coverage_report(self):
            return {"coverage": 100.0}
    assert _handle_coverage({"workspace": ws}, MockGovCoverage()) == {"coverage": 100.0}

    # Coverage with stdlib
    res_cov = _handle_coverage({"workspace": ws}, None)
    assert isinstance(res_cov, dict)

    # Coverage exception branch
    monkeypatch.setattr(aegis_core.telemetry, "calculate_coverage", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("cov err")))
    assert _handle_coverage({"workspace": ws}, None)["status"] == "FAIL"

    # Coverage non-dict branch
    monkeypatch.setattr(aegis_core.telemetry, "calculate_coverage", lambda *a, **kw: "non-dict")
    assert _handle_coverage({"workspace": ws}, None)["status"] == "FAIL"

    # Fitness with gov
    class MockGovFitness:
        def fitness_landscape(self, bayesian=False):
            return {"fitness": 0.8}
    assert _handle_fitness({"workspace": ws}, MockGovFitness()) == {"fitness": 0.8}

    # Fitness with stdlib
    res_fit = _handle_fitness({"workspace": ws, "cell_name": "sample-cell"}, None)
    assert isinstance(res_fit, (dict, list))

    # Fitness exception branch
    import aegis_core.lifecycle
    monkeypatch.setattr(aegis_core.lifecycle, "compute_cells_fitness", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("fit err")))
    assert _handle_fitness({"workspace": ws}, None)["status"] == "FAIL"

    # Fitness dict with error key
    monkeypatch.setattr(aegis_core.lifecycle, "compute_cells_fitness", lambda *a, **kw: {"error": "computation failed"})
    res_fit_err = _handle_fitness({"workspace": ws}, None)
    assert res_fit_err["status"] == "FAIL"


# ── Verification Handlers ───────────────────────────────────────────────────

def test_verification_handlers(mcp_workspace: Path, monkeypatch):
    ws = str(mcp_workspace)
    # verify_changes invalid workspace
    assert _handle_verify_changes({"workspace": "/invalid\0path"}, None)["status"] == "FAIL"

    # verify_changes non-list files
    assert _handle_verify_changes({"workspace": ws, "files": "not-a-list"}, None)["status"] == "FAIL"

    # verify_changes empty files without async_mode
    assert _handle_verify_changes({"workspace": ws, "files": []}, None)["status"] == "FAIL"

    # verify_changes path traversal in files
    assert _handle_verify_changes({"workspace": ws, "files": ["../outside.py"]}, None)["status"] == "FAIL"

    # verify_changes async_mode
    res_async = _handle_verify_changes({"workspace": ws, "files": ["src/main.py"], "async_mode": True}, None)
    assert res_async["status"] == "QUEUED"
    assert "job_id" in res_async

    # verify_changes ImportError without corrupting sys.modules
    orig_import = __import__
    def fake_import(name, *args, **kwargs):
        if name == "aegis_core.verification":
            raise ImportError("aegis_core.verification is not importable")
        return orig_import(name, *args, **kwargs)
    monkeypatch.setattr("builtins.__import__", fake_import)
    assert "not importable" in _handle_verify_changes({"workspace": ws, "files": ["src/main.py"]}, None)["error"]
    monkeypatch.undo()

    # verify_changes layer1_only=False (in-band pipeline)
    src_main = mcp_workspace / "src" / "main.py"
    src_main.parent.mkdir(parents=True, exist_ok=True)
    src_main.write_text("def test_fn(): pass\n", encoding="utf-8")
    res_pipeline = _handle_verify_changes({"workspace": ws, "files": ["src/main.py"], "layer1_only": False}, None)
    assert isinstance(res_pipeline, dict)

    # verify_changes layer1_only=False without charge_sheet and with arbitration_result and telemetry error
    from types import SimpleNamespace
    from enum import Enum
    class MockVerdict(Enum):
        PASS = "PASS"
        FAIL = "FAIL"
    class MockDivCategory(Enum):
        CODE = "code"
    class MockConv(Enum):
        AGREE = "agree"

    mock_pipeline_res = SimpleNamespace(
        layer1_evidence=[],
        passed=True,
        verdict=MockVerdict.PASS,
        charge_sheet=None,
        summary="Pipeline passed",
        evidence_path="/evidence.json",
        cycle=1,
        arbitration_result=SimpleNamespace(
            divergences=[SimpleNamespace(category=MockDivCategory.CODE, divergence_type="drift", resolution="accepted")],
            convergences=[MockConv.AGREE],
        ),
    )
    class MockPipeline:
        def run(self, *a, **kw):
            return mock_pipeline_res

    import aegis_core.verification
    import aegis_core.outcomes
    monkeypatch.setattr(aegis_core.verification, "VerificationPipeline", MockPipeline)
    monkeypatch.setattr(aegis_core.outcomes, "record_verification_telemetry", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("telemetry fail")))
    res_adv = _handle_verify_changes({"workspace": ws, "files": ["src/main.py"], "layer1_only": False}, None)
    assert res_adv["status"] == "PASS"
    assert "evidence_file" in res_adv
    assert len(res_adv["divergences"]) == 1

    # verify_changes stdlib layer1 with telemetry error
    res_verify = _handle_verify_changes({"workspace": ws, "files": ["src/main.py"]}, None)
    assert isinstance(res_verify, dict)

    # checkpoint when _run_checkpoint_checks is None
    import aegis_mcp.handlers.verification
    monkeypatch.setattr(aegis_mcp.handlers.verification, "_run_checkpoint_checks", None)
    assert _handle_checkpoint({"workspace": ws}, None)["status"] == "FAIL"
    monkeypatch.undo()

    # poll_verification missing job_id
    assert _handle_poll_verification({"workspace": ws}, None)["status"] == "FAIL"

    # poll_verification nonexistent job
    assert _handle_poll_verification({"workspace": ws, "job_id": "nonexistent_job"}, None)["status"] == "FAIL"

    # poll_verification states: COMPLETED, FAILED, RUNNING, QUEUED
    from dataclasses import dataclass
    from typing import Optional, Any
    @dataclass
    class MockJob:
        job_id: str
        status: str
        completed_at: Optional[str] = "2026-01-01T00:00:00Z"
        result: Optional[Any] = None
        receipt: Optional[Any] = None
        error: Optional[str] = None
        started_at: Optional[str] = "2026-01-01T00:00:00Z"
        created_at: Optional[str] = "2026-01-01T00:00:00Z"

    import aegis_core.verification.jobs
    monkeypatch.setattr(aegis_core.verification.jobs, "get_job", lambda jid: MockJob(jid, "COMPLETED", result={"passed": True}))
    assert _handle_poll_verification({"workspace": ws, "job_id": "j1"}, None)["status"] == "COMPLETED"

    monkeypatch.setattr(aegis_core.verification.jobs, "get_job", lambda jid: MockJob(jid, "FAILED", error="job crashed"))
    assert _handle_poll_verification({"workspace": ws, "job_id": "j2"}, None)["status"] == "FAILED"

    monkeypatch.setattr(aegis_core.verification.jobs, "get_job", lambda jid: MockJob(jid, "RUNNING"))
    assert _handle_poll_verification({"workspace": ws, "job_id": "j3"}, None)["status"] == "RUNNING"

    monkeypatch.setattr(aegis_core.verification.jobs, "get_job", lambda jid: MockJob(jid, "QUEUED"))
    assert _handle_poll_verification({"workspace": ws, "job_id": "j4"}, None)["status"] == "QUEUED"

    # checkpoint invalid workspace
    assert _handle_checkpoint({"workspace": "/invalid\0path"}, None)["status"] == "FAIL"

    # checkpoint valid workspace
    res_cp = _handle_checkpoint({"workspace": ws}, None)
    assert isinstance(res_cp, dict)

    # request_receipt missing operation
    assert _handle_request_receipt({"workspace": ws}, None)["status"] == "FAIL"

    # request_receipt arguments not dict
    assert _handle_request_receipt({"workspace": ws, "operation": "op", "arguments": "bad"}, None)["status"] == "FAIL"

    # request_receipt with gov.repo_root
    class MockGovReceipt:
        repo_root = mcp_workspace
    res_rr = _handle_request_receipt({"operation": "test_op", "arguments": {"files": ["src/main.py"]}}, MockGovReceipt())
    assert res_rr["status"] == "ISSUED"

    # request_receipt digest computation failure
    import aegis_core.receipts
    monkeypatch.setattr(aegis_core.receipts, "compute_file_digest", lambda *a, **kw: (_ for _ in ()).throw(ValueError("digest failed")))
    assert _handle_request_receipt({"workspace": ws, "operation": "test_op"}, None)["status"] == "FAIL"

    aegis_core.verification.jobs.clear_all_jobs()


