from pathlib import Path
"""TDD tests for Supercell-derived antipattern cells.

Verifies that ALL antipattern cells from Supercell Cycle 1 RCA exist,
have valid frontmatter, and contain the required fields.
"""
import os
import sys

import pytest

from soma_core.somayaml import parse_frontmatter

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
CELLS_DIR = os.path.join(REPO_ROOT, ".aegis", "rules") if os.path.isdir(os.path.join(REPO_ROOT, ".aegis", "rules")) else os.path.join(REPO_ROOT, ".soma", "cells")


DIR_MAP = {
    "walls": ["invariants", "walls"],
    "vacuoles": ["traps", "vacuoles"],
}
TYPE_MAP = {
    "walls": ("wall", "invariant", "trap"),
    "vacuoles": ("vacuole", "trap"),
}


def _find_cell_file(cell_id, cell_type):
    candidates = DIR_MAP.get(cell_type, [cell_type])
    for cand in candidates:
        path = os.path.join(CELLS_DIR, cand, f"{cell_id}.md")
        if os.path.isfile(path):
            return path
    for root, _, files in os.walk(CELLS_DIR):
        if f"{cell_id}.md" in files:
            return os.path.join(root, f"{cell_id}.md")
    return os.path.join(CELLS_DIR, candidates[0], f"{cell_id}.md")


# ALL antipattern cells derived from Supercell Cycle 1 RCA
SUPERCELL_CELLS = {
    # Security antipatterns (from S1, S2)
    "trap-format-code-injection": {
        "type": "walls",
        "domain": "security",
        "enforcement": "blocking",
    },
    "trap-path-traversal": {
        "type": "walls",
        "domain": "security",
        "enforcement": "gate",
    },
    # Correctness antipatterns (from C1, C2, C3)
    "trap-schema-contract-drift": {
        "type": "walls",
        "domain": "correctness",
        "enforcement": "gate",
    },
    "trap-orphaned-module": {
        "type": "vacuoles",
        "domain": "correctness",
    },
    "trap-threshold-spec-drift": {
        "type": "walls",
        "domain": "correctness",
        "enforcement": "gate",
    },
    # Quality / process antipatterns (from doc-drift RCA)
    "trap-doc-feature-drift": {
        "type": "walls",
        "domain": "documentation",
        "enforcement": "gate",
    },
    "trap-ascii-art-render": {
        "type": "vacuoles",
        "domain": "documentation",
    },
    "trap-test-coverage-horizon": {
        "type": "vacuoles",
        "domain": "testing",
    },
    # Architecture antipatterns (from C5, C6)
    "trap-layer-violation": {
        "type": "walls",
        "domain": "architecture",
        "enforcement": "gate",
    },
    "trap-shell-true-portability": {
        "type": "walls",
        "domain": "portability",
        "enforcement": "gate",
    },
}

REQUIRED_FIELDS = [
    "id", "domain", "type", "enforcement", "hypothesis",
    "prediction", "falsification", "target_paths", "triggers",
]


def _load_cell(cell_id, cell_type):
    """Load a cell's frontmatter by ID and type directory."""
    path = _find_cell_file(cell_id, cell_type)
    assert os.path.isfile(path), f"Cell file not found: {path}"
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert content.startswith("---"), f"Cell {cell_id} missing YAML frontmatter"
    fm = parse_frontmatter(content)
    assert isinstance(fm, dict), f"Cell {cell_id} frontmatter is not a dict"
    return fm


class TestSupercellCells:
    """Verify Supercell-derived antipattern cells."""

    @pytest.mark.parametrize("cell_id,spec", list(SUPERCELL_CELLS.items()))
    def test_cell_exists(self, cell_id, spec):
        """Each Supercell cell must exist in the correct type directory."""
        path = _find_cell_file(cell_id, spec["type"])
        assert os.path.isfile(path), f"Missing cell: {path}"

    @pytest.mark.parametrize("cell_id,spec", list(SUPERCELL_CELLS.items()))
    def test_cell_has_required_fields(self, cell_id, spec):
        """Each cell must have all required frontmatter fields."""
        fm = _load_cell(cell_id, spec["type"])
        for field in REQUIRED_FIELDS:
            assert field in fm, f"Cell {cell_id} missing field: {field}"

    @pytest.mark.parametrize("cell_id,spec", list(SUPERCELL_CELLS.items()))
    def test_cell_id_matches_filename(self, cell_id, spec):
        """Frontmatter id must match the filename."""
        fm = _load_cell(cell_id, spec["type"])
        assert fm["id"] == cell_id

    @pytest.mark.parametrize("cell_id,spec", list(SUPERCELL_CELLS.items()))
    def test_cell_domain_matches(self, cell_id, spec):
        """Frontmatter domain must match expected domain."""
        fm = _load_cell(cell_id, spec["type"])
        assert fm["domain"] == spec["domain"]

    @pytest.mark.parametrize("cell_id,spec", list(SUPERCELL_CELLS.items()))
    def test_cell_type_matches_directory(self, cell_id, spec):
        """Frontmatter type must match the directory name."""
        fm = _load_cell(cell_id, spec["type"])
        allowed = TYPE_MAP.get(spec["type"], (spec["type"].rstrip("s"),))
        assert fm["type"] in allowed

    @pytest.mark.parametrize("cell_id,spec", [
        (k, v) for k, v in SUPERCELL_CELLS.items()
        if v.get("enforcement") == "gate"
    ])
    def test_gate_cells_are_walls(self, cell_id, spec):
        """Gate enforcement cells must be in walls/ or invariants/ directory."""
        fm = _load_cell(cell_id, spec["type"])
        assert fm["enforcement"] == "gate"
        assert spec["type"] in ("walls", "invariants")

    def test_security_cells_target_python(self):
        """Security antipattern cells must target Python files."""
        for cell_id in ("trap-format-code-injection", "trap-path-traversal"):
            fm = _load_cell(cell_id, "walls")
            targets = fm.get("target_paths", [])
            assert any("*.py" in t or "**/*.py" in t for t in targets), (
                f"{cell_id} must target Python files"
            )

    def test_doc_drift_targets_docs(self):
        """trap-doc-feature-drift must target documentation files."""
        fm = _load_cell("trap-doc-feature-drift", "walls")
        targets = fm.get("target_paths", [])
        assert any("README" in t or "*.md" in t or "CHANGELOG" in t for t in targets)
