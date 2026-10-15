"""Every surface sees the same rules for the same files, with the same ledger fitness.

One loader (aegis_core.rules), one matcher (aegis_core.match) and one estimator
(aegis_core.fitness) mean aegis scan, the SDK, coverage, the check telemetry, aegis
status, aegis_list_rules and aegis sync cannot disagree. This test asks each of them.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from aegis_core.rules import load_rules

RULES = {
    "trap-src-any": ["src/**/*.py"],
    "trap-top-level": ["src/*.py"],
    "trap-basename": ["conftest.py"],
    "trap-docs": ["docs/**", "README.md"],
    "trap-nothing": ["nowhere/*.go"],
}
FILES = ["src/app.py", "src/pkg/deep.py", "tests/conftest.py", "docs/guide/intro.md", "README.md", "setup.cfg"]


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    from aegis_core.telemetry_engine import ledger

    traps = tmp_path / ".aegis" / "rules" / "traps"
    traps.mkdir(parents=True)
    for rule_id, patterns in RULES.items():
        paths = "".join(f"  - '{p}'\n" for p in patterns)
        (traps / f"{rule_id}.md").write_text(
            f"---\nid: {rule_id}\ntype: trap\nhypothesis: h\ntarget_paths:\n{paths}---\nBody\n", encoding="utf-8"
        )
    for rel in FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x\n", encoding="utf-8")
    ledger.append(tmp_path, [
        {"rule": "trap-src-any", "outcome": o, "source": "ci", "key": f"k{n}"}
        for n, o in enumerate(["tp"] * 9 + ["fp"])
    ])
    return tmp_path


def _expected(rel: str) -> set:
    from aegis_core.match import first_match

    return {rule_id for rule_id, patterns in RULES.items() if first_match(patterns, rel) is not None}


def test_the_matcher_reference_is_what_the_patterns_say():
    assert {f: _expected(f) for f in FILES} == {
        "src/app.py": {"trap-src-any", "trap-top-level"},
        "src/pkg/deep.py": {"trap-src-any", "trap-top-level"},  # `*` crosses `/`
        "tests/conftest.py": {"trap-basename"},  # a slashless pattern matches the basename
        "docs/guide/intro.md": {"trap-docs"},
        "README.md": {"trap-docs"},
        "setup.cfg": set(),
    }


@pytest.mark.parametrize("rel", FILES)
def test_scan_sdk_and_check_telemetry_match_the_same_rules(ws: Path, rel: str):
    from aegis_core.outcomes.engine import match_rules_to_changes
    from aegis_core.outcomes.telemetry import record_verification_telemetry
    from aegis_core.scan import RULE_CACHE, scan
    from aegis_core.telemetry_engine import ledger
    from aegis_mcp.tools import execute_tool
    from aegis_sdk import Governance

    RULE_CACHE.invalidate()
    expected = _expected(rel)
    core = scan(ws, [rel], budget=len(RULES), max_tokens=100000)
    mcp = execute_tool("aegis_scan", {"workspace": str(ws), "files": [rel]})
    assert {r["name"] for r in core["relevant_rules"]} == expected
    assert {r["name"] for r in mcp["relevant_rules"]} <= expected  # the MCP default budget is 3 slots
    assert {r["_name"] for r in match_rules_to_changes(ws, [rel])} == expected
    assert {r["_name"] for r in Governance(ws).scan([rel])} == expected

    before = len(ledger.read(ws).rows)
    record_verification_telemetry(str(ws), [rel], passed=True, source="session", run_id=f"run-{rel}")
    assert {r["rule"] for r in ledger.read(ws).rows[before:]} == expected


def test_coverage_covers_exactly_the_files_some_rule_matches(ws: Path):
    from aegis_core.metrics import calculate_coverage

    report = calculate_coverage(str(ws))
    covered = {f for f in FILES if _expected(f)}
    assert set(report["uncovered_files"]) == set(FILES) - covered
    assert report["covered"] == len(covered)


def test_status_list_sync_scan_and_sdk_report_one_fitness(ws: Path, capsys):
    from aegis_cli.status import run_status
    from aegis_core.fitness import compute
    from aegis_core.scan import RULE_CACHE, scan
    from aegis_core.sync import sync
    from aegis_mcp.tools import execute_tool
    from aegis_sdk import Governance

    # 9 tp of 10 verdicts: the Wilson lower bound (90%) is the score everywhere.
    score = compute({"tp": 9, "fp": 1, "triggers": 10}).score
    assert score == 0.6523

    RULE_CACHE.invalidate()
    scanned = {r["name"]: r["fitness"] for r in scan(ws, ["src/app.py"], budget=5)["relevant_rules"]}
    listed = {r["_name"]: r["fitness"] for r in execute_tool("aegis_list_rules", {"workspace": str(ws)})["rules"]}
    derived = sync(ws).derived["rules"]
    landscape = {row["rule"]: row for row in Governance(ws).fitness_landscape()}
    assert run_status(argparse.Namespace(_root=ws, json=True)) == 0
    status = {r["name"]: r for r in json.loads(capsys.readouterr().out)["rules"]}

    assert scanned["trap-src-any"] == score
    assert listed["trap-src-any"] == {"triggers": 10, "tp": 9, "fp": 1, "last_ts": listed["trap-src-any"]["last_ts"], "score": score}
    assert (derived["trap-src-any"]["fitness"], derived["trap-src-any"]["triggers"]) == (score, 10)
    assert (landscape["trap-src-any"]["score"], landscape["trap-src-any"]["tp"]) == (score, 9)
    assert (status["trap-src-any"]["score"], status["trap-src-any"]["triggers"]) == (score, 10)
    # A rule with no verdicts: 0.0 where a number is required, unknown where status shows it.
    assert scanned["trap-top-level"] == listed["trap-top-level"]["score"] == derived["trap-top-level"]["fitness"] == 0.0
    assert status["trap-top-level"]["score"] is None


def test_no_rule_is_silently_dropped_by_any_surface(ws: Path):
    """Every rule the loader serves is listed, indexed by sync and visible to the SDK."""
    from aegis_core.sync import build
    from aegis_mcp.tools import execute_tool
    from aegis_sdk import Governance

    served = {r.id for r in load_rules(ws).served}
    assert served == set(RULES)
    assert {r["_name"] for r in execute_tool("aegis_list_rules", {"workspace": str(ws)})["rules"]} == served
    assert set(build(ws)["rules"]) == served
    assert {r["_name"] for r in Governance(ws).list_rules()} == served
