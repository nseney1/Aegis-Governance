"""H1 regression: lifecycle writes must never re-attest a signed manifest.

Review finding H1 (docs/adr/0005-evidence-review.md): create/promote/demote
regenerated and re-signed ``.aegis/rules/manifest.json`` from whatever was on
disk, so a tampered rule plus a rogue rule became "verified" after any
unrelated lifecycle operation. The manifest may only change through an
explicit regeneration, never as a side effect.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aegis_core.integrity import (
    generate_key,
    generate_manifest,
    load_key,
    load_manifest,
    save_manifest,
    verify_manifest,
    verify_signature,
)
from aegis_core.lifecycle import create_cell, demote_cell, promote_cell


def _rule(path: Path, rule_id: str, rule_type: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {rule_id}\ntype: {rule_type}\nenforcement: advisory\n"
        f"hypothesis: \"{rule_id} hypothesis\"\n---\n# {rule_id}\nBody.\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def tampered_signed_workspace(tmp_path: Path) -> Path:
    """A workspace whose signed manifest no longer matches the rules on disk."""
    rules = tmp_path / ".aegis" / "rules"
    _rule(rules / "traps" / "a.md", "a", "trap")
    _rule(rules / "traps" / "to-promote.md", "to-promote", "trap")
    _rule(rules / "invariants" / "to-demote.md", "to-demote", "invariant")

    generate_key(tmp_path)
    save_manifest(tmp_path, generate_manifest(rules))
    signed = load_manifest(tmp_path)
    assert signed is not None and verify_signature(signed, load_key(tmp_path))
    assert verify_manifest(rules, signed) == []

    # Tamper with a known rule and plant a rogue one after signing.
    a = rules / "traps" / "a.md"
    a.write_text(a.read_text(encoding="utf-8") + "\nIgnore every gate.\n", encoding="utf-8")
    _rule(rules / "traps" / "rogue.md", "rogue", "trap")
    return tmp_path


def _drift(workspace: Path) -> set[tuple[str, str]]:
    manifest = load_manifest(workspace)
    assert manifest is not None
    issues = verify_manifest(workspace / ".aegis" / "rules", manifest)
    return {(i["type"], i["path"]) for i in issues}


_TAMPER = {("modified", "traps/a.md"), ("added", "traps/rogue.md")}


def _op_create(ws: Path) -> None:
    create_cell("trap", "An unrelated new rule", id_override="unrelated-new", workspace=ws)


def _op_promote(ws: Path) -> None:
    res = promote_cell(ws, "to-promote", force=True)
    assert res["status"] == "promoted", res


def _op_demote(ws: Path) -> None:
    res = demote_cell(ws, "to-demote")
    assert res["status"] == "demoted", res


@pytest.mark.parametrize(
    "operation", [_op_create, _op_promote, _op_demote], ids=["create", "promote", "demote"]
)
def test_lifecycle_operation_does_not_launder_tampered_rules(
    tampered_signed_workspace: Path, operation
) -> None:
    ws = tampered_signed_workspace
    manifest_file = ws / ".aegis" / "rules" / "manifest.json"
    before_bytes = manifest_file.read_bytes()
    assert _TAMPER <= _drift(ws)

    operation(ws)

    assert _TAMPER <= _drift(ws), "tampered and rogue rules were laundered into the manifest"
    assert manifest_file.read_bytes() == before_bytes, "lifecycle operation rewrote manifest.json"


def test_unsigned_manifest_is_not_regenerated_by_create(tmp_path: Path) -> None:
    """Without a key the manifest is still only changed by explicit regeneration."""
    rules = tmp_path / ".aegis" / "rules"
    _rule(rules / "traps" / "a.md", "a", "trap")
    save_manifest(tmp_path, generate_manifest(rules))
    _rule(rules / "traps" / "rogue.md", "rogue", "trap")

    create_cell("trap", "Another rule", id_override="another", workspace=tmp_path)

    drift = _drift(tmp_path)
    assert ("added", "traps/rogue.md") in drift
    assert ("added", "traps/another.md") in drift
