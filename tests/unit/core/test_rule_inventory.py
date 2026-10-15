"""Regression tests for the rule inventory, the byte snapshot the one loader projects (#19)."""
import os
import time

import pytest


def _write_rule(path, rule_id="rule-a"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"id: {rule_id}\n"
        "domain: testing\n"
        "type: invariant\n"
        "enforcement: gate\n"
        "target_paths: ['src/*.py']\n"
        "---\n"
        "# Rule\n",
        encoding="utf-8",
    )


def test_inventory_is_stable_and_captures_exact_bytes(tmp_path):
    from aegis_core.rule_inventory import inventory_rules

    first_path = tmp_path / ".aegis" / "rules" / "invariants" / "b.md"
    second_path = tmp_path / ".aegis" / "rules" / "traps" / "a.md"
    _write_rule(first_path, "b")
    _write_rule(second_path, "a")

    first = inventory_rules(str(tmp_path))
    second = inventory_rules(str(tmp_path))

    assert [entry.relative_path for entry in first.entries] == [
        ".aegis/rules/invariants/b.md",
        ".aegis/rules/traps/a.md",
    ]
    assert first.fingerprint == second.fingerprint
    assert first.entries == second.entries
    for entry in first.entries:
        assert os.path.isabs(entry.absolute_path)
        assert entry.size == len(entry.content)
        assert len(entry.digest) == 64
        assert entry.content == open(entry.absolute_path, "rb").read()


def test_rule_edited_after_creation_is_inventoried(tmp_path):
    """BUG-035: on Windows os.stat reports st_ctime as creation time but
    os.fstat reports it as last-change time, so any rule edited after it was
    created was rejected as 'changed before it was opened'."""
    from aegis_core.rule_inventory import inventory_rules

    cell = tmp_path / ".aegis" / "rules" / "invariants" / "edited.md"
    _write_rule(cell, "edited")
    time.sleep(0.05)
    with open(cell, "a", encoding="utf-8") as f:
        f.write("Edited after creation.\n")

    inventory = inventory_rules(str(tmp_path))
    assert [entry.relative_path for entry in inventory.entries] == [
        ".aegis/rules/invariants/edited.md"
    ]
    assert inventory.entries[0].content == cell.read_bytes()
    assert b"Edited after creation." in inventory.entries[0].content


def test_missing_rules_directory_has_stable_empty_inventory(tmp_path):
    from aegis_core.rule_inventory import inventory_rules

    inventory = inventory_rules(str(tmp_path))
    assert inventory.entries == ()
    assert len(inventory.fingerprint) == 64


def test_symlinked_rule_is_rejected(tmp_path):
    from aegis_core.rule_inventory import RuleInventoryError, inventory_rules

    outside = tmp_path / "outside.md"
    _write_rule(outside, "outside")
    link = tmp_path / ".aegis" / "rules" / "invariants" / "linked.md"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")

    with pytest.raises(RuleInventoryError, match="symlink"):
        inventory_rules(str(tmp_path))


def test_symlinked_directory_that_would_feed_the_scan_fails_it_closed(tmp_path):
    from aegis_core.rules import RuleCache
    import aegis_core.scan as scan_service

    outside = tmp_path / "outside" / "invariants"
    _write_rule(outside / "external.md", "external")
    rules_dir = tmp_path / "workspace" / ".aegis" / "rules"
    rules_dir.mkdir(parents=True)
    link = rules_dir / "invariants"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")

    previous = scan_service.RULE_CACHE
    scan_service.RULE_CACHE = RuleCache()
    try:
        result = scan_service.scan(str(tmp_path / "workspace"), changed_files=["src/app.py"])
    finally:
        scan_service.RULE_CACHE = previous
    assert result["status"] == "FAIL"
    assert "symlinked directory is not allowed" in result["error"]
    assert "relevant_rules" not in result


def test_rules_are_matched_to_changed_files(tmp_path):
    from aegis_core.outcomes.engine import match_rules_to_changes

    _write_rule(tmp_path / ".aegis" / "rules" / "invariants" / "test-wall.md", "test-wall")

    matches = match_rules_to_changes(tmp_path, ["src/index.py"])
    assert [(m["_name"], m["_matched_files"]) for m in matches] == [("test-wall", ["src/index.py"])]
    assert match_rules_to_changes(tmp_path, ["other/file.txt"]) == []
    assert match_rules_to_changes(tmp_path, []) == []
    assert match_rules_to_changes(tmp_path / "nonexistent", ["src/index.py"]) == []


def test_inventory_covers_the_workspace_rules_directory(tmp_path):
    from aegis_core.rule_inventory import inventory_rules

    rule = tmp_path / ".aegis" / "rules" / "invariants" / "inv1.md"
    _write_rule(rule, "inv1")
    inventory = inventory_rules(str(tmp_path))
    assert [e.relative_path for e in inventory.entries] == [".aegis/rules/invariants/inv1.md"]
