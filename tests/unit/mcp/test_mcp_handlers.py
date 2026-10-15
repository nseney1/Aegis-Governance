"""Direct tests of the four MCP handlers (one implementation each)."""
from __future__ import annotations

from pathlib import Path

import pytest

import aegis_mcp.handlers.telemetry as telemetry_handlers
from aegis_core.yaml_engine.serializer import dump_frontmatter
from aegis_mcp.handlers.core import handle_scan
from aegis_mcp.handlers.governance import handle_create_rule, handle_list_rules
from aegis_mcp.handlers.telemetry import handle_report_outcome

BAD_WORKSPACE = "/invalid\0path"


@pytest.fixture
def mcp_workspace(tmp_path: Path) -> Path:
    rules_dir = tmp_path / ".aegis" / "rules" / "traps"
    rules_dir.mkdir(parents=True, exist_ok=True)
    fm = {
        "id": "sample-rule",
        "type": "trap",
        "target_paths": ["src/*.py"],
        "hypothesis": "Sample hypothesis",
    }
    (rules_dir / "sample-rule.md").write_text(f"---\n{dump_frontmatter(fm)}---\n\n# Body\n", encoding="utf-8")
    return tmp_path


def test_scan_matches_rules_for_the_given_files(mcp_workspace: Path):
    res = handle_scan({"workspace": str(mcp_workspace), "files": ["src/main.py"]})
    assert [r["name"] for r in res["relevant_rules"]] == ["sample-rule"]


@pytest.mark.parametrize("args,error", [
    ({"workspace": BAD_WORKSPACE}, None),
    ({"files": "not-a-list"}, "'files' must be a list of file paths"),
    ({"files": [3]}, "'files' must be a list of file paths"),
])
def test_scan_rejects_bad_arguments(mcp_workspace: Path, args, error):
    res = handle_scan({"workspace": str(mcp_workspace), **args})
    assert res["status"] == "FAIL"
    if error:
        assert res["error"] == error


def test_scan_blocks_path_traversal(mcp_workspace: Path):
    res = handle_scan({"workspace": str(mcp_workspace), "files": ["../outside.py"]})
    assert res["status"] == "FAIL"
    assert "path traversal blocked" in res["error"].lower()


def test_create_rule_returns_a_prompt_built_from_existing_rules(mcp_workspace: Path):
    res = handle_create_rule({
        "workspace": str(mcp_workspace),
        "description": "Rule to test something",
        "domain": "testing",
        "rule_type": "trap",
    })
    assert "Sample hypothesis" in res["prompt"]
    assert 'User description: "Rule to test something"' in res["prompt"]
    assert "Preferred rule type: trap" in res["prompt"]
    assert ".aegis/rules/" in res["instruction"]


@pytest.mark.parametrize("description", [None, "", "   ", 5])
def test_create_rule_needs_a_description(mcp_workspace: Path, description):
    res = handle_create_rule({"workspace": str(mcp_workspace), "description": description})
    assert res == {"error": "'description' must be a non-empty string.", "status": "FAIL"}


def test_create_rule_rejects_bad_workspace():
    res = handle_create_rule({"workspace": BAD_WORKSPACE, "description": "x"})
    assert res["status"] == "FAIL"


def test_list_rules_returns_frontmatter_records(mcp_workspace: Path):
    res = handle_list_rules({"workspace": str(mcp_workspace)})["rules"]
    assert [r["id"] for r in res] == ["sample-rule"]
    assert res[0]["_path"] == ".aegis/rules/traps/sample-rule.md"


def test_list_rules_filters_by_type(mcp_workspace: Path):
    invariants = mcp_workspace / ".aegis" / "rules" / "invariants"
    invariants.mkdir()
    (invariants / "inv.md").write_text("---\nid: inv\ntype: invariant\n---\n", encoding="utf-8")
    def ids(rule_type):
        return [r["id"] for r in handle_list_rules({"workspace": str(mcp_workspace), "rule_type": rule_type})["rules"]]

    assert ids("invariant") == ["inv"]
    assert ids("trap") == ["sample-rule"]


def test_list_rules_rejects_bad_workspace():
    assert handle_list_rules({"workspace": BAD_WORKSPACE})["status"] == "FAIL"


def test_report_outcome_without_rules_is_rejected(mcp_workspace: Path):
    res = handle_report_outcome({"workspace": str(mcp_workspace), "outcome": "success", "idempotency_key": "k"})
    assert res == {
        "status": "FAIL",
        "error": "'rules_used' must name at least one rule from aegis_scan: "
                 "an outcome with no rule has nothing to credit.",
    }
    assert not (mcp_workspace / ".aegis" / "state" / "ledger.jsonl").exists()


def test_report_outcome_rejects_bad_workspace():
    res = handle_report_outcome({"workspace": BAD_WORKSPACE, "outcome": "tp", "idempotency_key": "k"})
    assert res["status"] == "FAIL"


def test_report_outcome_surfaces_a_ledger_write_failure(mcp_workspace: Path, monkeypatch):
    def disk_full(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(telemetry_handlers.ledger, "append", disk_full)
    res = handle_report_outcome({
        "workspace": str(mcp_workspace),
        "outcome": "success",
        "rules_used": ["sample-rule"],
        "idempotency_key": "k-fail",
    })
    assert res == {"status": "FAIL", "error": "Failed to record outcome: disk full"}

