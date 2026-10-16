"""aegis_core.lifecycle.creation.create_rule: the enforcement a new rule records.

Invariant and gate rules are mandatory: they are created as gates and refuse any other
tier. Every other type defaults to advisory and keeps the tier it is given.
"""
from __future__ import annotations

from pathlib import Path
import re

import pytest

from aegis_core.lifecycle.creation import create_rule
from aegis_core.yaml_engine.frontmatter import parse_frontmatter


def _ws(tmp_path: Path) -> Path:
    (tmp_path / ".aegis" / "rules").mkdir(parents=True)
    return tmp_path


@pytest.mark.parametrize("rule_type, given, stored", [
    ("trap", None, "advisory"),
    ("trap", "Mechanical", "mechanical"),
    ("boundary", "gate", "gate"),
    ("invariant", None, "gate"),
    ("invariant", "GATE", "gate"),
    ("gate", "gate", "gate"),
])
def test_the_rule_records_the_given_enforcement_or_its_type_default(tmp_path: Path, rule_type, given, stored):
    path = create_rule(rule_type, "Edits keep the contract", id_override="new-rule", workspace=_ws(tmp_path), enforcement=given)
    assert parse_frontmatter(path.read_text(encoding="utf-8"))["enforcement"] == stored


@pytest.mark.parametrize("rule_type", ["invariant", "gate"])
@pytest.mark.parametrize("given", ["advisory", "Mechanical"])
def test_a_mandatory_type_refuses_any_enforcement_but_gate_and_writes_nothing(tmp_path: Path, rule_type, given):
    ws = _ws(tmp_path)
    message = f"{rule_type.capitalize()} rules must use 'gate' enforcement, got '{given}'."
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        create_rule(rule_type, "Edits keep the contract", id_override="new-rule", workspace=ws, enforcement=given)
    assert list((ws / ".aegis" / "rules").rglob("*.md")) == []
