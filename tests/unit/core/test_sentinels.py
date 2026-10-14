"""Tests for aegis_core.sentinels — Subagent liveness, deadlock detection, and escalation sentinels."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pytest

from aegis_core.sentinels import (
    check_boundary_overrides,
    check_liveness,
    classify_file,
    is_test_file,
    set_review_mode,
    write_frontmatter,
    recommend_protocol,
)
from aegis_core.yaml import parse_frontmatter


def test_check_liveness_healthy_and_stalled() -> None:
    now = datetime.now(timezone.utc).isoformat()
    old = "2020-01-01T00:00:00Z"
    payload = {
        "agents": [
            {"name": "agent-healthy", "dispatched": now, "timeout_seconds": 600},
            {"name": "agent-stalled", "dispatched": old, "timeout_seconds": 10},
            {"name": "agent-bad-date", "dispatched": "invalid-date", "timeout_seconds": 10},
        ]
    }
    ret = check_liveness(json.dumps(payload))
    assert ret == 0


def test_check_liveness_invalid_json() -> None:
    ret = check_liveness("not-json")
    assert ret == 1


def test_classify_file_sensitivity() -> None:
    assert classify_file("Makefile") == "HIGH"
    assert classify_file("install.sh") == "HIGH"
    assert classify_file("aegis_core/auth.py") == "HIGH"
    assert classify_file(".github/workflows/ci.yml") == "HIGH"
    assert classify_file("requirements.txt") == "HIGH"

    assert classify_file("docs/readme.md") == "LOW"
    assert classify_file("README.md") == "LOW"
    assert classify_file("LICENSE") == "LOW"
    assert classify_file("data.json") == "LOW"

    assert classify_file("aegis_core/lifecycle.py") == "MEDIUM"
    assert classify_file("rules/testing.md") == "MEDIUM"


def test_is_test_file() -> None:
    assert is_test_file("tests/test_sentinels.py") is True
    assert is_test_file("src/foo_test.go") is True
    assert is_test_file("components/button.test.ts") is True
    assert is_test_file("src/app.py") is False


def test_set_review_mode(tmp_path: Path) -> None:
    conf = tmp_path / "steering.conf"
    conf.write_text("REVIEW_MODE=BREEZE\nOTHER=1\n", encoding="utf-8")
    set_review_mode(str(tmp_path), "TEMPEST")
    content = conf.read_text(encoding="utf-8")
    assert "REVIEW_MODE=TEMPEST\n" in content
    assert "OTHER=1\n" in content


def test_write_frontmatter(tmp_path: Path) -> None:
    target = tmp_path / "rule.md"
    metadata = {"id": "test-rule", "type": "invariant"}
    body = "Body description\n"
    write_frontmatter(str(target), metadata, body)

    content = target.read_text(encoding="utf-8")
    fm = parse_frontmatter(content)
    assert fm["id"] == "test-rule"
    assert fm["type"] == "invariant"
    assert "Body description" in content


def test_recommend_protocol_no_changes(tmp_path: Path) -> None:
    ret = recommend_protocol("--staged", [], tmp_path)
    assert ret == 1


def test_check_boundary_overrides_escalates_on_aegis_boundaries_and_invariants(tmp_path: Path) -> None:
    boundaries_dir = tmp_path / ".aegis" / "rules" / "boundaries"
    invariants_dir = tmp_path / ".aegis" / "rules" / "invariants"
    boundaries_dir.mkdir(parents=True)
    invariants_dir.mkdir(parents=True)

    (boundaries_dir / "boundary-core.md").write_text(
        "---\n"
        "id: boundary-core\n"
        "type: boundary\n"
        "target_paths:\n"
        "  - aegis_core/**\n"
        "minimum_mode: GALE\n"
        "---\n"
        "# Boundary Core\n",
        encoding="utf-8",
    )
    (invariants_dir / "inv-auth.md").write_text(
        "---\n"
        "id: inv-auth\n"
        "type: invariant\n"
        "target_paths:\n"
        "  - aegis_core/auth.py\n"
        "minimum_mode: TEMPEST\n"
        "---\n"
        "# Invariant Auth\n",
        encoding="utf-8",
    )

    mode, rule_id = check_boundary_overrides(["aegis_core/engine.py"], str(tmp_path), "BREEZE")
    assert mode == "GALE"
    assert rule_id == "boundary-core"

    mode2, rule_id2 = check_boundary_overrides(["aegis_core/auth.py"], str(tmp_path), "BREEZE")
    assert mode2 == "TEMPEST"
    assert rule_id2 == "inv-auth"


