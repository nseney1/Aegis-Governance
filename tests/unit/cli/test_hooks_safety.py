"""aegis_cli.hooks.safety.log_gate_event: the safety gate's decision log, .aegis/state/gate_events.jsonl."""
from __future__ import annotations

import json
from pathlib import Path
import re

from aegis_cli.hooks.safety import log_gate_event


def _rows(ws: Path) -> list:
    text = (ws / ".aegis" / "state" / "gate_events.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_each_decision_is_appended_with_its_command_and_any_reason(tmp_path: Path):
    (tmp_path / ".aegis").mkdir()

    log_gate_event("rm -rf build", "deny", "Recursive delete", tmp_path)
    log_gate_event("ls", "allow", "", tmp_path)

    deny, allow = _rows(tmp_path)
    assert (deny["command"], deny["decision"], deny["reason"]) == ("rm -rf build", "deny", "Recursive delete")
    assert (allow["command"], allow["decision"]) == ("ls", "allow")
    assert "reason" not in allow
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", deny["timestamp"])


def test_a_logged_command_keeps_only_its_first_200_characters(tmp_path: Path):
    (tmp_path / ".aegis").mkdir()
    cmd = "echo " + "x" * 300

    log_gate_event(cmd, "allow", "", tmp_path)

    (row,) = _rows(tmp_path)
    assert row["command"] == cmd[:200]
