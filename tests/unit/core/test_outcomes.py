"""Frontmatter parsing edge cases the outcome paths depend on."""
from __future__ import annotations

from pathlib import Path


def test_frontmatter_consolidation_handles_embedded_dashes(tmp_path: Path) -> None:
    """A quoted '---' inside a scalar does not end the frontmatter block."""
    from aegis_core.yaml_engine.frontmatter import _get_body, parse_frontmatter

    content = '---\nid: rule-embedded-dashes\ntype: invariant\nhypothesis: "Avoid --- inline delimiters"\n---\nActual body text.\n'
    meta = parse_frontmatter(content)
    assert meta["id"] == "rule-embedded-dashes"
    assert meta["hypothesis"] == "Avoid --- inline delimiters"
    assert _get_body(content).strip() == "Actual body text."
