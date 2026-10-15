"""The aegis_scan payload: one name per field, path-only matching, and a token budget
that bounds the whole payload, gate and invariant rules included.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aegis_core.yaml import dump_frontmatter
from aegis_mcp.jit_engine import estimate_tokens, express
from aegis_mcp.tools import execute_tool

TOP_LEVEL_KEYS = {
    "relevant_rules",
    "guidance",
    "genome_guidance",
    "invariant_warnings",
    "rules_staged",
    "stats",
}
STATS_KEYS = {
    "total_rules",
    "matched",
    "budget",
    "changed_files",
    "estimated_tokens",
    "max_tokens_budget",
    "clamped",
    "omitted",
}
RULE_KEYS = {"name", "_path", "type", "enforcement", "hypothesis", "prediction", "matched_files", "fitness"}


def _rule(root: Path, name: str, rule_type: str = "trap", enforcement: str = "advisory",
          target_paths=("src/*.py",), body: str = "Body.", **extra) -> None:
    folder = root / ".aegis" / "rules" / f"{rule_type}s"
    folder.mkdir(parents=True, exist_ok=True)
    fm = {
        "id": name,
        "type": rule_type,
        "enforcement": enforcement,
        "hypothesis": f"{name} hypothesis",
        "prediction": f"{name} prediction",
        **extra,
    }
    if target_paths is not None:
        fm["target_paths"] = list(target_paths)
    (folder / f"{name}.md").write_text(dump_frontmatter(fm, body=body + "\n"), encoding="utf-8")


def test_scan_payload_has_one_name_per_field(tmp_path):
    _rule(tmp_path, "inv-a", rule_type="invariant", enforcement="gate")
    _rule(tmp_path, "trap-b")

    res = execute_tool("aegis_scan", {"workspace": str(tmp_path), "files": ["src/app.py"]})

    assert set(res) == TOP_LEVEL_KEYS
    assert set(res["stats"]) == STATS_KEYS
    assert res["rules_staged"] == len(res["relevant_rules"]) == 2
    assert res["stats"]["total_rules"] == 2
    for item in res["relevant_rules"]:
        assert set(item) == RULE_KEYS
    assert [w["name"] for w in res["invariant_warnings"]] == ["inv-a"]


def test_scan_without_changes_has_the_same_shape(tmp_path):
    (tmp_path / ".aegis" / "rules").mkdir(parents=True)
    res = express(str(tmp_path), changed_files=[])
    assert set(res) == TOP_LEVEL_KEYS
    assert set(res["stats"]) == STATS_KEYS
    assert res["rules_staged"] == 0


def test_rules_match_by_path_only(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("import pickle\neval('1')\n", encoding="utf-8")
    _rule(tmp_path, "ast-only", target_paths=None, ast_triggers={"imports": ["pickle"]})
    _rule(tmp_path, "forbid-and-path", rule_type="gate", enforcement="gate",
          forbid_ast={"calls": ["eval"]})

    res = express(str(tmp_path), changed_files=["src/app.py"])

    assert [r["name"] for r in res["relevant_rules"]] == ["forbid-and-path"]


def test_gate_type_rule_is_mandatory_beyond_the_rule_count_budget(tmp_path):
    _rule(tmp_path, "trap-a")
    _rule(tmp_path, "gate-typed", rule_type="gate", enforcement="advisory")

    res = express(str(tmp_path), changed_files=["src/app.py"], budget=0)

    assert [r["name"] for r in res["relevant_rules"]] == ["gate-typed"]


@pytest.fixture
def many_gates(tmp_path, monkeypatch):
    body = "Never ship this pattern without a reviewed exception. " * 6
    for i in range(40):
        _rule(tmp_path, f"gate-{i:02d}", rule_type="invariant", enforcement="gate", body=body)
    monkeypatch.setenv("AEGIS_MAX_JIT_TOKENS", "600")
    return tmp_path


def test_budget_bounds_the_whole_payload_including_gates(many_gates):
    res = execute_tool("aegis_scan", {"workspace": str(many_gates), "files": ["src/app.py"]})

    assert estimate_tokens(json.dumps(res)) <= 600
    assert res["stats"]["estimated_tokens"] <= 600
    assert 0 < res["rules_staged"] < 40
    omitted = res["stats"]["omitted"]
    assert omitted == 40 - res["rules_staged"]
    assert res["stats"]["clamped"] is True
    assert f"{omitted} more rules omitted (raise AEGIS_MAX_JIT_TOKENS)" in res["guidance"]


def test_invariant_warnings_cover_only_the_staged_rules(many_gates):
    res = execute_tool("aegis_scan", {"workspace": str(many_gates), "files": ["src/app.py"]})

    staged = [r["name"] for r in res["relevant_rules"]]
    assert [w["name"] for w in res["invariant_warnings"]] == staged
    assert all(f"[INVARIANT] {name}:" in res["guidance"] for name in staged)


def test_one_omitted_rule_is_reported_in_the_singular(tmp_path):
    _rule(tmp_path, "inv-a", rule_type="invariant", enforcement="gate", body="short")
    _rule(tmp_path, "inv-b", rule_type="invariant", enforcement="gate", body="word " * 400)
    small = express(str(tmp_path), changed_files=["src/app.py"], max_tokens=10_000)
    first_only = small["stats"]["estimated_tokens"] - 10

    res = express(str(tmp_path), changed_files=["src/app.py"], max_tokens=first_only)

    assert res["stats"]["omitted"] == 1
    assert "1 more rule omitted (raise AEGIS_MAX_JIT_TOKENS)" in res["guidance"]


def test_a_budget_too_small_for_any_rule_stages_none_and_says_so(tmp_path):
    _rule(tmp_path, "inv-a", rule_type="invariant", enforcement="gate", body="word " * 400)

    res = express(str(tmp_path), changed_files=["src/app.py"], max_tokens=120)

    assert res["relevant_rules"] == [] and res["invariant_warnings"] == []
    assert res["stats"]["omitted"] == 1
    assert "1 more rule omitted (raise AEGIS_MAX_JIT_TOKENS)" in res["guidance"]
