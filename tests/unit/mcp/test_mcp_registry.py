"""aegis_mcp.registry: the rule inventory the MCP handlers list, and the rule-creation prompt."""
from __future__ import annotations

from pathlib import Path

from aegis_core import sync
from aegis_core.workspace.base import Workspace
from aegis_mcp.registry import build_rule_create_prompt, list_rules


def _rule(root: Path, folder: str, rule_id: str, rule_type: str, extra: str = "", body: str = "body\n") -> Path:
    path = root / ".aegis" / "rules" / folder / f"{rule_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {rule_id}\ntype: {rule_type}\nhypothesis: h\n{extra}---\n{body}", encoding="utf-8")
    return path


def _ids(records: list) -> list:
    return sorted(record["id"] for record in records)


def test_a_type_filter_narrows_both_the_rules_and_the_stale_rules(tmp_path: Path):
    edited = [
        _rule(tmp_path, "traps", "trap-a", "trap"),
        _rule(tmp_path, "invariants", "inv-a", "invariant", "enforcement: gate\n"),
    ]
    sync.sync(tmp_path)
    for path in edited:  # both now differ from what sync recorded
        path.write_text(path.read_text(encoding="utf-8") + "more\n", encoding="utf-8")
    ws = Workspace.confine(tmp_path)

    every = list_rules(ws)
    assert (_ids(every["rules"]), _ids(every["stale_rules"])) == (["inv-a", "trap-a"], ["inv-a", "trap-a"])
    invariants = list_rules(ws, rule_type="invariant")
    assert (_ids(invariants["rules"]), _ids(invariants["stale_rules"])) == (["inv-a"], ["inv-a"])


def test_an_expired_rule_is_still_listed_and_marked_expired(tmp_path: Path):
    _rule(tmp_path, "traps", "retired", "trap", "expired_at: 2026-01-01T00:00:00Z\n")
    _rule(tmp_path, "traps", "live", "trap")

    records = {record["id"]: record for record in list_rules(Workspace.confine(tmp_path))["rules"]}

    assert records["retired"]["_expired"] is True
    assert "_expired" not in records["live"]


def test_the_creation_prompt_quotes_at_most_three_rules_cut_at_500_characters(tmp_path: Path):
    texts = [
        _rule(tmp_path, "traps", f"rule-{letter}", "trap", body=letter * 600 + "\n").read_text(encoding="utf-8")
        for letter in "abcd"
    ]

    prompt = build_rule_create_prompt("Flag unpinned dependencies", args={"workspace": str(tmp_path)})

    assert sum(text[:500] in prompt for text in texts) == 3
    assert not any(text[:501] in prompt for text in texts)

