"""aegis_sdk.governance.Governance: the values of its fitness and coverage reports.

test_governance_facade.py covers the public ``aegis_sdk`` surface and return shapes;
this file pins the numbers those reports compute for a known ledger and file tree.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aegis_core.telemetry_engine import ledger
from aegis_sdk.governance import Governance


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """One trap over src/*.py with 3 true and 2 false positives; one source file, one doc."""
    root = tmp_path / "proj"
    rule = root / ".aegis" / "rules" / "traps" / "trap-src.md"
    rule.parent.mkdir(parents=True)
    rule.write_text("---\nid: trap-src\ntype: trap\nhypothesis: h\ntarget_paths:\n  - src/*.py\n---\nbody\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "notes.txt").write_text("notes\n", encoding="utf-8")
    ledger.append(root, [
        {"rule": "trap-src", "outcome": outcome, "source": "ci", "key": f"run-{i}"}
        for i, outcome in enumerate(["tp", "tp", "tp", "fp", "fp"])
    ])
    return root


def test_the_landscape_adds_the_wilson_interval_only_when_asked(ws: Path) -> None:
    plain, = Governance(ws).fitness_landscape()
    assert (plain["rule"], plain["tp"], plain["fp"]) == ("trap-src", 3, 2)
    assert "bayesian" not in plain

    row, = Governance(ws).fitness_landscape(bayesian=True)
    # The 90% Wilson interval of 3 true positives in 5 verdicts, to four decimals.
    assert row["bayesian"] == {"lower": 0.2725, "upper": 0.8573}


def test_coverage_report_counts_the_files_the_rules_target(ws: Path) -> None:
    report = Governance(ws).coverage_report()
    assert (report["total_files"], report["covered"], report["uncovered_files"]) == (2, 1, ["docs/notes.txt"])

    assert Governance(ws).coverage_report(exclude="docs/")["total_files"] == 1
