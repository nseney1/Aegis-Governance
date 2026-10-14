"""Unit tests for aegis_core.enforcement."""
import os
import tempfile
import pytest

from aegis_core.enforcement import (
    load_bug_registry,
    bug_status,
    verify_bug_schema,
    verify_unique_ids,
    generate_ci_report,
    _match_cells,
    _compute_credit_weights,
    _format_markdown,
)


def test_enforcement_ci_report_generation(tmp_path):
    cells_dir = tmp_path / ".aegis" / "rules"
    cells_dir.mkdir(parents=True)
    cell_path = cells_dir / "membrane-test.md"
    cell_path.write_text(
        "---\nname: membrane-test\ntype: membrane\ntarget_paths:\n  - 'src/*'\n---\n# Membrane\n",
        encoding="utf-8",
    )

    report = generate_ci_report(
        workspace=str(tmp_path),
        changed_files=["src/test.py"],
        test_passed=True,
        commit_sha="c0ffee",
    )
    assert len(report["matched_cells"]) == 1
    assert report["matched_cells"][0]["cell"] == "membrane-test"
    assert report["matched_cells"][0]["credit_weight"] == 1.0
    assert report["matched_cells"][0]["proposed_signal"] == "trigger"
    assert "c0ffee" in report["summary"]


def test_enforcement_credit_weights_conservation():
    matched = [
        {"cell": "cell-a", "path": "/fake/a.md"},
        {"cell": "cell-b", "path": "/fake/b.md"},
    ]
    # No files or cells -> default weight 1.0
    weights = _compute_credit_weights(matched, [])
    assert weights["cell-a"] == 1.0


def test_gate_assertion_injection_sanitization():
    from aegis_core.enforcement import generate_gate_assertion
    import ast

    malicious_name = "cell\nmalicious_header_injection"
    malicious_hyp = 'Testing """ break out\nand newline injection'
    cell = {
        "name": malicious_name,
        "type": "wall",
        "hypothesis": malicious_hyp,
        "target_paths": ["src/*.py"],
    }
    code = generate_gate_assertion(cell, workspace="/tmp")
    assert "\nmalicious_header_injection" not in code.splitlines()[0]
    tree = ast.parse(code)
    assert tree is not None


def test_enforcement_load_cells(tmp_path):
    from aegis_core.enforcement import load_cells

    cells_dir = tmp_path / ".aegis" / "rules" / "walls"
    cells_dir.mkdir(parents=True)
    (cells_dir / "wall-1.md").write_text(
        "---\nid: wall-1\ntype: wall\nhypothesis: test\n---\nbody",
        encoding="utf-8",
    )
    cells = load_cells(str(tmp_path / ".aegis" / "rules"))
    assert len(cells) == 1
    assert cells[0]["id"] == "wall-1"

