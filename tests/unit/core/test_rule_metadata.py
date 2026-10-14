"""Tests for rule metadata schema compliance.

Validates that every governance rule (genome + cells) has YAML frontmatter
with the fields required by the evidence enrichment pipeline:
  - 'id': unique identifier matching filename (stem)
  - 'domain': one of {efficiency, correctness, security, style, governance}

Written BEFORE adding the new fields — tests will fail on every rule
that lacks them, proving they detect the gap.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
GENOME_DIR = REPO_ROOT / "rules" if (REPO_ROOT / "rules").is_dir() else (REPO_ROOT / "genome")
ORACLES_DIR = GENOME_DIR / ".oracles"
CELLS_DIR = REPO_ROOT / ".aegis" / "rules" if (REPO_ROOT / ".aegis" / "rules").is_dir() else (REPO_ROOT / ".soma" / "cells")

# Fields required for the evidence enrichment pipeline
REQUIRED_FIELDS = {"id", "domain"}
VALID_DOMAINS = {
    "architecture", "correctness", "documentation", "efficiency",
    "governance", "portability", "security", "style", "testing",
}

# Regex to extract YAML frontmatter block
FRONTMATTER_RE = re.compile(r"^---\n(.+?)\n---\n", re.DOTALL)

# Files to skip (non-rule files)
SKIP_FILES = {"META.md", "README.md"}


def parse_frontmatter(text: str) -> dict | None:
    """Minimal YAML frontmatter parser — no pyyaml dependency.

    Handles simple key: value pairs. Does not support nested structures.
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    result = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def get_genome_rules() -> list[Path]:
    """All .md rule files in genome/ (top-level, non-hidden)."""
    if not GENOME_DIR.exists():
        return []
    return sorted(
        p for p in GENOME_DIR.glob("*.md")
        if p.name not in SKIP_FILES
    )


def get_oracle_rules() -> list[Path]:
    """All .md rule files in genome/.oracles/."""
    if not ORACLES_DIR.exists():
        return []
    return sorted(
        p for p in ORACLES_DIR.glob("*.md")
        if p.name not in SKIP_FILES
    )


def get_cell_rules() -> list[Path]:
    """All .md cell files in .soma/cells/**/ (excluding README)."""
    if not CELLS_DIR.exists():
        return []
    return sorted(
        p for p in CELLS_DIR.rglob("*.md")
        if p.name not in SKIP_FILES
    )


def get_all_rules() -> list[Path]:
    """All rule files across genome + cells."""
    return get_genome_rules() + get_oracle_rules() + get_cell_rules()


# ── Genome rules must have frontmatter ──


@pytest.mark.parametrize("rule_file", get_genome_rules(),
                         ids=lambda p: f"genome/{p.name}")
def test_genome_rule_has_frontmatter(rule_file):
    """Every genome rule MUST have YAML frontmatter."""
    meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert meta is not None, f"{rule_file.name} lacks YAML frontmatter"


@pytest.mark.parametrize("rule_file", get_genome_rules(),
                         ids=lambda p: f"genome/{p.name}")
def test_genome_rule_has_id(rule_file):
    """Every genome rule MUST have an 'id' field in frontmatter."""
    meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert meta is not None, f"{rule_file.name} lacks YAML frontmatter"
    assert "id" in meta, f"{rule_file.name} missing 'id' field"


@pytest.mark.parametrize("rule_file", get_genome_rules(),
                         ids=lambda p: f"genome/{p.name}")
def test_genome_rule_has_domain(rule_file):
    """Every genome rule MUST have a 'domain' field in frontmatter."""
    meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert meta is not None, f"{rule_file.name} lacks YAML frontmatter"
    assert "domain" in meta, f"{rule_file.name} missing 'domain' field"


# ── Oracle rules must have frontmatter ──


@pytest.mark.parametrize("rule_file", get_oracle_rules(),
                         ids=lambda p: f"oracles/{p.name}")
def test_oracle_rule_has_frontmatter(rule_file):
    """Every oracle rule MUST have YAML frontmatter."""
    meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert meta is not None, f"{rule_file.name} lacks YAML frontmatter"


@pytest.mark.parametrize("rule_file", get_oracle_rules(),
                         ids=lambda p: f"oracles/{p.name}")
def test_oracle_rule_has_id(rule_file):
    """Every oracle rule MUST have an 'id' field in frontmatter."""
    meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert meta is not None, f"{rule_file.name} lacks YAML frontmatter"
    assert "id" in meta, f"{rule_file.name} missing 'id' field"


@pytest.mark.parametrize("rule_file", get_oracle_rules(),
                         ids=lambda p: f"oracles/{p.name}")
def test_oracle_rule_has_domain(rule_file):
    """Every oracle rule MUST have a 'domain' field in frontmatter."""
    meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert meta is not None, f"{rule_file.name} lacks YAML frontmatter"
    assert "domain" in meta, f"{rule_file.name} missing 'domain' field"


# ── Cell rules must have frontmatter and domain ──


@pytest.mark.parametrize("rule_file", get_cell_rules(),
                         ids=lambda p: f"cells/{p.parent.name}/{p.name}")
def test_cell_rule_has_frontmatter(rule_file):
    """Every cell rule MUST have YAML frontmatter."""
    meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert meta is not None, f"{rule_file.name} lacks YAML frontmatter"


@pytest.mark.parametrize("rule_file", get_cell_rules(),
                         ids=lambda p: f"cells/{p.parent.name}/{p.name}")
def test_cell_rule_has_domain(rule_file):
    """Every cell rule MUST have a 'domain' field in frontmatter."""
    meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert meta is not None, f"{rule_file.name} lacks YAML frontmatter"
    assert "domain" in meta, f"{rule_file.name} missing 'domain' field"


# ── Cross-cutting validation ──


@pytest.mark.parametrize("rule_file", get_all_rules(),
                         ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_domain_is_valid(rule_file):
    """Domain must be one of the known values."""
    meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert meta is not None, f"{rule_file.name} lacks YAML frontmatter"
    assert "domain" in meta, f"{rule_file.name} missing domain"
    assert meta["domain"] in VALID_DOMAINS, (
        f"{rule_file.name}: domain '{meta['domain']}' not in {VALID_DOMAINS}"
    )


@pytest.mark.parametrize("rule_file", get_all_rules(),
                         ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_id_matches_filename(rule_file):
    """Rule ID should match the filename (without extension)."""
    meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert meta is not None, f"{rule_file.name} lacks YAML frontmatter"
    assert "id" in meta, f"{rule_file.name} missing id"
    expected = rule_file.stem
    assert meta["id"] == expected, (
        f"ID mismatch: frontmatter says '{meta['id']}', file is '{expected}'"
    )


@pytest.mark.parametrize("rule_file", get_cell_rules(),
                         ids=lambda p: f"cells/{p.parent.name}/{p.name}")
def test_cell_rule_has_id(rule_file):
    """Every cell rule MUST have an 'id' field in frontmatter."""
    meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert meta is not None, f"{rule_file.name} lacks YAML frontmatter"
    assert "id" in meta, f"{rule_file.name} missing 'id' field"


def test_no_duplicate_rule_ids():
    """All rule IDs across genome + oracles + cells must be unique."""
    ids_seen: dict[str, str] = {}
    for rule_file in get_all_rules():
        meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
        if meta and "id" in meta:
            rid = meta["id"]
            assert rid not in ids_seen, (
                f"Duplicate id '{rid}': {ids_seen[rid]} and {rule_file.name}"
            )
            ids_seen[rid] = rule_file.name


# ── Content coherence: use JIT parser for nested YAML ──


def _jit_parse(path: Path) -> dict | None:
    """Parse frontmatter using the production JIT engine parser."""
    from soma_mcp.jit_engine import parse_frontmatter as jit_parser
    return jit_parser(path.read_text(encoding="utf-8"))


def _get_vacuoles() -> list[Path]:
    """All vacuole/trap cell files."""
    vac_dir = CELLS_DIR / "traps" if (CELLS_DIR / "traps").exists() else (CELLS_DIR / "vacuoles")
    if not vac_dir.exists():
        return []
    return sorted(p for p in vac_dir.glob("*.md") if p.name not in SKIP_FILES)


def _get_walls() -> list[Path]:
    """All wall/invariant cell files."""
    wall_dir = CELLS_DIR / "invariants" if (CELLS_DIR / "invariants").exists() else (CELLS_DIR / "walls")
    if not wall_dir.exists():
        return []
    return sorted(p for p in wall_dir.glob("*.md") if p.name not in SKIP_FILES)


# ── Genome content coherence ──


@pytest.mark.parametrize("rule_file", get_genome_rules(),
                         ids=lambda p: f"genome/{p.name}")
def test_genome_has_enforcement(rule_file):
    """Genome rules must declare an enforcement level."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert "enforcement" in fm, (
        f"{rule_file.name} missing 'enforcement' field"
    )


@pytest.mark.parametrize("rule_file", get_genome_rules(),
                         ids=lambda p: f"genome/{p.name}")
def test_genome_has_body_text(rule_file):
    """Genome rules must have meaningful body text (not just frontmatter)."""
    content = rule_file.read_text(encoding="utf-8")
    # Strip frontmatter
    if content.startswith("---"):
        end = content.find("---", 3)
        body = content[end + 3:].strip() if end != -1 else ""
    else:
        body = content.strip()
    assert len(body) > 50, (
        f"{rule_file.name} body is too short ({len(body)} chars) — "
        f"rules must contain actionable guidance"
    )


# ── Vacuole content coherence ──


VACUOLE_REQUIRED_FIELDS = {"hypothesis", "target_paths", "type"}


@pytest.mark.parametrize("rule_file", _get_vacuoles(),
                         ids=lambda p: f"vacuoles/{p.name}")
def test_vacuole_has_required_fields(rule_file):
    """Vacuoles must have hypothesis, target_paths, and type."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    for field in VACUOLE_REQUIRED_FIELDS:
        assert field in fm, (
            f"{rule_file.name} missing required vacuole field '{field}'"
        )
    assert fm["type"] in ("vacuole", "trap"), (
        f"{rule_file.name} type is '{fm['type']}', expected 'vacuole' or 'trap'"
    )


@pytest.mark.parametrize("rule_file", _get_vacuoles(),
                         ids=lambda p: f"vacuoles/{p.name}")
def test_vacuole_has_fitness_block(rule_file):
    """Vacuoles should have fitness tracking (inline or external)."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    # Fitness can be tracked inline (legacy) or externally via .soma/evidence/
    if "fitness" not in fm:
        return  # External tracking — acceptable since v0.50
    fitness = fm["fitness"]
    assert isinstance(fitness, dict), (
        f"{rule_file.name} fitness must be a dict, got {type(fitness)}"
    )
    # If inline, must track triggers and true/false positives
    for key in ("triggers", "true_positives", "false_positives"):
        assert key in fitness, (
            f"{rule_file.name} fitness block missing '{key}'"
        )


@pytest.mark.parametrize("rule_file", _get_vacuoles(),
                         ids=lambda p: f"vacuoles/{p.name}")
def test_vacuole_has_expiry(rule_file):
    """Vacuoles must have expiry settings (they can't live forever)."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    has_sessions = "expiry_sessions" in fm
    has_days = "expiry_days" in fm
    assert has_sessions or has_days, (
        f"{rule_file.name} has no expiry — vacuoles must decay if unused"
    )


@pytest.mark.parametrize("rule_file", _get_vacuoles(),
                         ids=lambda p: f"vacuoles/{p.name}")
def test_vacuole_target_paths_not_empty(rule_file):
    """Vacuole target_paths must contain at least one pattern."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    tp = fm.get("target_paths", [])
    assert isinstance(tp, list) and len(tp) > 0, (
        f"{rule_file.name} target_paths is empty — vacuole won't match anything"
    )


# ── Wall content coherence ──


@pytest.mark.parametrize("rule_file", _get_walls(),
                         ids=lambda p: f"walls/{p.name}")
def test_wall_enforcement_is_gate(rule_file):
    """Walls are non-negotiable — they must have gate enforcement."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert fm.get("enforcement") == "gate", (
        f"{rule_file.name} is a wall but enforcement is "
        f"'{fm.get('enforcement')}' — walls must be 'gate'"
    )


# ── JIT matching integration ──


def test_jit_matches_new_genome_files():
    """New genome rules should match when their activation paths are touched."""
    from soma_mcp.jit_engine import load_all_cells, match_cells_to_files
    cells = load_all_cells(str(REPO_ROOT))
    test_path = "aegis_core/telemetry.py" if (REPO_ROOT / "aegis_core").is_dir() else "soma_core/telemetry.py"
    matched = match_cells_to_files(cells, [test_path])
    matched_ids = {c["id"] for c in matched}
    # At minimum, trap-schema-contract-drift targets aegis_core/*.py
    assert "trap-schema-contract-drift" in matched_ids, (
        f"trap-schema-contract-drift should match {test_path} "
        f"but matched: {matched_ids}"
    )


def test_jit_matches_vacuole_on_python_files():
    """trap-future-annotations targets **/*.py — should match any .py file."""
    from soma_mcp.jit_engine import load_all_cells, match_cells_to_files
    cells = load_all_cells(str(REPO_ROOT))
    test_path = "aegis_cli/status.py" if (REPO_ROOT / "aegis_cli").is_dir() else "soma_cli/status.py"
    matched = match_cells_to_files(cells, [test_path])
    matched_ids = {c["id"] for c in matched}
    assert "trap-future-annotations" in matched_ids, (
        f"trap-future-annotations should match {test_path} "
        f"but matched: {matched_ids}"
    )


# ── Membrane content coherence ──


def _get_membranes() -> list[Path]:
    """All membrane/boundary cell files."""
    mem_dir = CELLS_DIR / "boundaries" if (CELLS_DIR / "boundaries").exists() else (CELLS_DIR / "membranes")
    if not mem_dir.exists():
        return []
    return sorted(p for p in mem_dir.glob("*.md") if p.name not in SKIP_FILES)


@pytest.mark.parametrize("rule_file", _get_membranes(),
                         ids=lambda p: f"membranes/{p.name}")
def test_membrane_has_hypothesis(rule_file):
    """Membranes define escalation boundaries — must have a hypothesis."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert "hypothesis" in fm, (
        f"{rule_file.name} missing 'hypothesis' — membranes must "
        f"justify why this boundary requires escalation"
    )


@pytest.mark.parametrize("rule_file", _get_membranes(),
                         ids=lambda p: f"membranes/{p.name}")
def test_membrane_type_is_correct(rule_file):
    """Membrane files must declare type: membrane or boundary."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert fm.get("type") in ("membrane", "boundary"), (
        f"{rule_file.name} type is '{fm.get('type')}', expected 'membrane' or 'boundary'"
    )


# ── Chloroplast content coherence ──


def _get_chloroplasts() -> list[Path]:
    """All chloroplast/persona cell files."""
    chl_dir = CELLS_DIR / "personas" if (CELLS_DIR / "personas").exists() else (CELLS_DIR / "chloroplasts")
    if not chl_dir.exists():
        return []
    return sorted(p for p in chl_dir.glob("*.md") if p.name not in SKIP_FILES)


@pytest.mark.parametrize("rule_file", _get_chloroplasts(),
                         ids=lambda p: f"chloroplasts/{p.name}")
def test_chloroplast_has_hypothesis(rule_file):
    """Chloroplasts are specialist personas — must have a hypothesis."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert "hypothesis" in fm, (
        f"{rule_file.name} missing 'hypothesis' — chloroplasts must "
        f"justify their specialization"
    )


@pytest.mark.parametrize("rule_file", _get_chloroplasts(),
                         ids=lambda p: f"chloroplasts/{p.name}")
def test_chloroplast_type_is_correct(rule_file):
    """Chloroplast files must declare type: chloroplast or persona."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert fm.get("type") in ("chloroplast", "persona"), (
        f"{rule_file.name} type is '{fm.get('type')}', expected 'chloroplast' or 'persona'"
    )


# ── Plasmodesmata content coherence ──


def _get_plasmodesmata() -> list[Path]:
    """All plasmodesmata/contract cell files."""
    pla_dir = CELLS_DIR / "contracts" if (CELLS_DIR / "contracts").exists() else (CELLS_DIR / "plasmodesmata")
    if not pla_dir.exists():
        return []
    return sorted(p for p in pla_dir.glob("*.md") if p.name not in SKIP_FILES)


@pytest.mark.parametrize("rule_file", _get_plasmodesmata(),
                         ids=lambda p: f"plasmodesmata/{p.name}")
def test_plasmodesmata_has_hypothesis(rule_file):
    """Plasmodesmata define cross-module contracts — must have a hypothesis."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert "hypothesis" in fm, (
        f"{rule_file.name} missing 'hypothesis' — plasmodesmata must "
        f"define the contract they enforce"
    )


@pytest.mark.parametrize("rule_file", _get_plasmodesmata(),
                         ids=lambda p: f"plasmodesmata/{p.name}")
def test_plasmodesmata_type_is_correct(rule_file):
    """Plasmodesmata files must declare type: plasmodesmata or contract."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert fm.get("type") in ("plasmodesmata", "contract"), (
        f"{rule_file.name} type is '{fm.get('type')}', expected 'plasmodesmata' or 'contract'"
    )


@pytest.mark.parametrize("rule_file", _get_plasmodesmata(),
                         ids=lambda p: f"plasmodesmata/{p.name}")
def test_plasmodesmata_has_target_paths(rule_file):
    """Plasmodesmata enforce cross-module contracts — must specify target_paths."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    tp = fm.get("target_paths", [])
    assert isinstance(tp, list) and len(tp) > 0, (
        f"{rule_file.name} target_paths is empty — plasmodesmata must "
        f"specify which modules they bridge"
    )

