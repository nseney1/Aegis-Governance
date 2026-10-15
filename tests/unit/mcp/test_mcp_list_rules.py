"""aegis_list_rules reports each rule's fitness from the outcome ledger, never from
the fitness block a rule file may still carry in its frontmatter.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aegis_core.scoring import compute_cell_fitness
from aegis_core.telemetry_engine.ledger import append_signals
from aegis_mcp.tools import execute_tool


def _rule(root: Path, name: str, fitness_block: str = "") -> None:
    folder = root / ".aegis" / "rules" / "traps"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.md").write_text(
        f"---\nid: {name}\ntype: trap\nhypothesis: h\n{fitness_block}---\nbody\n",
        encoding="utf-8",
    )


def _signals(root: Path, rule: str, *signals: str) -> None:
    events = [
        {"cell_name": rule, "signal_type": signal, "source": "ci", "principal": "test",
         "idempotency_scope": "t", "idempotency_key": f"{rule}-{i}"}
        for i, signal in enumerate(signals)
    ]
    append_signals(str(root), events)


def _by_name(result):
    return {rule["_name"]: rule for rule in result}


@pytest.fixture
def workspace(tmp_path):
    _rule(tmp_path, "inflated", fitness_block=(
        "fitness:\n  triggers: 99\n  true_positives: 99\n  false_positives: 0\n  score: 0.99\n"
    ))
    _rule(tmp_path, "unobserved")
    _signals(tmp_path, "inflated", "trigger", "trigger", "trigger", "tp", "tp", "fp")
    return tmp_path


def test_fitness_comes_from_the_ledger_not_the_frontmatter(workspace):
    rules = _by_name(execute_tool("aegis_list_rules", {"workspace": str(workspace)}))

    fitness = rules["inflated"]["fitness"]
    assert {k: fitness[k] for k in ("triggers", "tp", "fp")} == {"triggers": 3, "tp": 2, "fp": 1}
    expected = compute_cell_fitness({"fitness": {"triggers": 3, "true_positives": 2, "false_positives": 1}})
    assert fitness["score"] == pytest.approx(expected)
    assert fitness["score"] != 0.99


def test_a_rule_with_no_ledger_rows_is_unobserved(workspace):
    fitness = _by_name(execute_tool("aegis_list_rules", {"workspace": str(workspace)}))["unobserved"]["fitness"]
    assert fitness == {"triggers": 0, "tp": 0, "fp": 0, "score": compute_cell_fitness({})}


def test_outcome_rows_without_trigger_rows_still_count_as_observations(tmp_path):
    _rule(tmp_path, "reported")
    _signals(tmp_path, "reported", "tp", "tp", "tp")

    fitness = _by_name(execute_tool("aegis_list_rules", {"workspace": str(tmp_path)}))["reported"]["fitness"]

    assert fitness["tp"] == 3
    assert 0.0 < fitness["score"] <= 1.0


def test_unreadable_ledger_rows_do_not_break_the_listing(workspace):
    ledger = workspace / ".aegis" / "evidence" / "signals.jsonl"
    with ledger.open("a", encoding="utf-8") as f:
        f.write("{not json\n")
    rules = _by_name(execute_tool("aegis_list_rules", {"workspace": str(workspace)}))
    assert rules["inflated"]["fitness"]["tp"] == 2


def test_list_rules_payload_is_json_serializable(workspace):
    json.dumps(execute_tool("aegis_list_rules", {"workspace": str(workspace)}))


def test_diagnostic_records_carry_no_fitness(tmp_path):
    bad = tmp_path / ".aegis" / "rules" / "traps" / "bad.md"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"---\nid: bad\n---\n\xff\n")

    record, = execute_tool("aegis_list_rules", {"workspace": str(tmp_path)})

    assert "UTF-8" in record["_error"]
    assert "fitness" not in record
