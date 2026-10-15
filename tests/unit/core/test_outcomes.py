"""Tests for aegis_core.outcomes — Verifiable outcome reflection and credit assignment."""
from __future__ import annotations

from pathlib import Path

from aegis_core.outcomes.fitness import compute_credit_weights


def test_compute_credit_weights_narrowing() -> None:
    cells = [
        {"_name": "cell-a", "target_paths": ["src/a.py"]},
        {"_name": "cell-b", "target_paths": ["src/b.py"]},
        {"_name": "cell-shared", "target_paths": ["src/*.py"]},
    ]
    # src/a.py matches cell-a and cell-shared (split 0.5 each)
    # src/b.py matches cell-b and cell-shared (split 0.5 each)
    weights = compute_credit_weights(cells, ["src/a.py", "src/b.py"])
    assert weights["cell-a"] == 0.5
    assert weights["cell-b"] == 0.5
    assert weights["cell-shared"] == 1.0


def test_compute_credit_weights_empty() -> None:
    cells = [{"_name": "cell-a"}]
    assert compute_credit_weights(cells, []) == {"cell-a": 1.0}


def test_frontmatter_consolidation_handles_embedded_dashes(tmp_path: Path) -> None:
    """A quoted '---' inside a scalar does not end the frontmatter block."""
    from aegis_core.yaml_engine.frontmatter import _get_body, parse_frontmatter

    content = '---\nid: rule-embedded-dashes\ntype: invariant\nhypothesis: "Avoid --- inline delimiters"\n---\nActual body text.\n'
    meta = parse_frontmatter(content)
    assert meta["id"] == "rule-embedded-dashes"
    assert meta["hypothesis"] == "Avoid --- inline delimiters"
    assert _get_body(content).strip() == "Actual body text."
