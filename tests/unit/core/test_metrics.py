"""Tests for aegis_core.metrics — rule coverage and the governance report card."""
from __future__ import annotations

from pathlib import Path

from aegis_core.metrics import calculate_coverage, calculate_governance_grade, letter_grade


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


def test_calculate_coverage_shape(tmp_path: Path) -> None:
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

    grade = calculate_governance_grade(str(tmp_path))
    assert grade["details"]["total_rules"] == 1
    # The frontmatter `fitness:` block is a legacy counter: without ledger evidence the
    # invariant is not yet shown to be healthy.
    assert grade["components"]["invariant_strength"] == 0

    from aegis_core.telemetry_engine import ledger

    ledger.append(tmp_path, [{"rule": "inv-src-app", "outcome": "tp", "source": "ci", "key": f"k{n}"} for n in range(5)])
    grade = calculate_governance_grade(str(tmp_path))
    assert grade["components"]["invariant_strength"] > 0




def _metric_rule(ws: Path, rule_id: str, extra: str = "") -> None:
    path = ws / ".aegis" / "rules" / "traps" / f"{rule_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {rule_id}\nhypothesis: h\ntarget_paths: ['src/*.py']\n{extra}---\nB\n", encoding="utf-8")


def test_the_average_fitness_counts_only_rules_with_verdicts(tmp_path: Path) -> None:
    """A rule nobody has judged yet has no measured fitness; it is not averaged in as 0."""
    from aegis_core.fitness import compute
    from aegis_core.telemetry_engine import ledger

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x\n", encoding="utf-8")
    _metric_rule(tmp_path, "judged")
    _metric_rule(tmp_path, "unjudged")
    ledger.append(tmp_path, [
        {"rule": "judged", "outcome": o, "source": "ci", "key": f"k{i}"} for i, o in enumerate(["tp"] * 9 + ["fp"])
    ])

    grade = calculate_governance_grade(str(tmp_path))

    assert grade["avg_fitness"]["score"] == compute({"tp": 9, "fp": 1}).score


def test_an_expired_rule_covers_no_file(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x\n", encoding="utf-8")
    _metric_rule(tmp_path, "retired", extra="expired_at: '2026-01-01'\n")

    report = calculate_coverage(str(tmp_path))

    assert report["covered"] == 0 and report["uncovered_files"] == ["src/app.py"]
