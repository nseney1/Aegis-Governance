"""Tests for aegis_core.metrics — Metrics snapshots, token census, rule quorum, coverage, and governance grading."""
from __future__ import annotations

import json
import os
from pathlib import Path
import pytest

from aegis_core.metrics import (
    letter_grade,
    resolve_metrics_dir,
    compute_token_census,
    evaluate_quorum,
    calculate_coverage,
    calculate_cell_coverage,
    calculate_immune_grade,
    take_snapshot,
)
from aegis_core.yaml import dump_frontmatter


def test_letter_grade_thresholds() -> None:
    assert letter_grade(98.0) == "A+"
    assert letter_grade(97.0) == "A+"
    assert letter_grade(94.0) == "A"
    assert letter_grade(93.0) == "A"
    assert letter_grade(91.0) == "A-"
    assert letter_grade(90.0) == "A-"
    assert letter_grade(88.0) == "B+"
    assert letter_grade(84.0) == "B"
    assert letter_grade(81.0) == "B-"
    assert letter_grade(78.0) == "C+"
    assert letter_grade(74.0) == "C"
    assert letter_grade(71.0) == "C-"
    assert letter_grade(68.0) == "D+"
    assert letter_grade(61.0) == "D"
    assert letter_grade(59.9) == "F"
    assert letter_grade(0.0) == "F"


def test_resolve_metrics_dir_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEAM_REPO", raising=False)
    monkeypatch.delenv("METRICS_REPO", raising=False)
    metrics_dir = resolve_metrics_dir(tmp_path)
    assert metrics_dir == (tmp_path / "docs" / "snapshots").resolve()
    assert metrics_dir.is_dir()


def test_resolve_metrics_dir_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "custom_metrics"
    monkeypatch.setenv("METRICS_REPO", str(target))
    metrics_dir = resolve_metrics_dir(tmp_path)
    assert metrics_dir == target.resolve()
    assert metrics_dir.is_dir()


def test_compute_token_census(tmp_path: Path) -> None:
    (tmp_path / "soma_core").mkdir()
    (tmp_path / "soma_cli").mkdir()
    (tmp_path / "pyproject.toml").write_text('name = "soma-governance"\n', encoding="utf-8")
    genome = tmp_path / "genome"
    genome.mkdir()
    (genome / "rule1.md").write_text("---\ntrigger: always_on\n---\nRule content here with several words.", encoding="utf-8")
    (genome / "rule2.md").write_text("---\ntrigger: conditional\n---\nConditional rule content here.", encoding="utf-8")

    organs = tmp_path / "organs" / "sample-skill"
    organs.mkdir(parents=True)
    (organs / "SKILL.md").write_text("---\nname: sample\n---\nSkill documentation content here.", encoding="utf-8")

    census = compute_token_census(tmp_path)
    assert len(census["files"]) == 3
    assert census["grand_total_idle"] > 0
    assert census["subtotals"]["always_on_rules_idle_tokens"] > 0
    assert census["subtotals"]["conditional_rules_idle_tokens"] > 0
    assert census["subtotals"]["skills_idle_tokens"] > 0


def test_compute_token_census_rules_and_skills(tmp_path: Path) -> None:
    (tmp_path / "aegis_core").mkdir()
    (tmp_path / "aegis_cli").mkdir()
    (tmp_path / "pyproject.toml").write_text('name = "aegis-governance"\n', encoding="utf-8")
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "rule1.md").write_text("---\ntrigger: always_on\n---\nRule content with several words.", encoding="utf-8")

    skills = tmp_path / "skills" / "sample-skill"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: sample\n---\nSkill documentation here.", encoding="utf-8")

    census = compute_token_census(tmp_path)
    assert len(census["files"]) == 2
    assert census["grand_total_idle"] > 0
    assert census["files"][0]["filename"].startswith("rules/")


def test_evaluate_quorum_sub_threshold(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    rule_file = rules_dir / "rule1.md"
    fm = {
        "id": "rule1",
        "type": "invariant",
        "target_paths": ["src/*.py"],
        "minimum_mode": "breeze",
        "hypothesis": "Hypothesis",
    }
    rule_file.write_text(f"---\n{dump_frontmatter(fm).strip()}\n---\nBody", encoding="utf-8")

    # Only 1 rule triggered, threshold is 2 -> no quorum
    res = evaluate_quorum(rules_dir, ["src/main.py"], threshold=2)
    assert res["quorum"] is False
    assert res["rules_triggered"] == 1


def test_evaluate_quorum_escalation(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    for i, mode in enumerate(["breeze", "tempest"]):
        rfile = rules_dir / f"rule_{i}.md"
        fm = {
            "id": f"rule_{i}",
            "type": "invariant",
            "target_paths": ["src/*.py"],
            "minimum_mode": mode,
            "hypothesis": "Hypothesis",
        }
        rfile.write_text(f"---\n{dump_frontmatter(fm).strip()}\n---\nBody", encoding="utf-8")

    res = evaluate_quorum(rules_dir, ["src/main.py"], threshold=2)
    assert res["quorum"] is True
    assert res["rules_triggered"] == 2
    assert res["escalate_to"] == "tempest"


def test_calculate_coverage_and_alias(tmp_path: Path) -> None:
    assert calculate_cell_coverage == calculate_coverage
    res = calculate_coverage(str(tmp_path))
    assert "total_files" in res
    assert "covered" in res
    assert "coverage_pct" in res
    assert "by_directory" in res


def test_calculate_coverage_and_governance_grade_on_aegis_rules_workspace(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (src_dir / "unmatched.py").write_text("print('no')\n", encoding="utf-8")

    inv_dir = tmp_path / ".aegis" / "rules" / "invariants"
    inv_dir.mkdir(parents=True)
    (inv_dir / "inv-src-app.md").write_text(
        "---\n"
        "id: inv-src-app\n"
        "type: invariant\n"
        "enforcement: gate\n"
        "target_paths:\n"
        "  - src/app.py\n"
        "fitness:\n"
        "  score: 0.9\n"
        "  triggers: 25\n"
        "  true_positives: 24\n"
        "  false_positives: 1\n"
        "---\n"
        "# Invariant Src App\n",
        encoding="utf-8",
    )

    cov = calculate_coverage(str(tmp_path))
    assert cov["total_files"] == 2
    assert cov["covered"] == 1
    assert cov["coverage_pct"] == 50.0

    grade = calculate_immune_grade(str(tmp_path))
    assert grade["details"]["total_rules"] == 1
    assert grade["components"]["invariant_strength"] > 0


