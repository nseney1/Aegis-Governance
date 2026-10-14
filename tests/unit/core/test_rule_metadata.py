"""Tests for rule metadata schema compliance.

Validates that every governance rule (core rules + workspace rules) has YAML frontmatter
with the fields required by the evidence enrichment pipeline:
  - 'id': unique identifier matching filename (stem)
  - 'domain': one of {efficiency, correctness, security, style, governance, ...}

Written BEFORE adding the new fields — tests will fail on every rule
that lacks them, proving they detect the gap.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
CORE_RULES_DIR = REPO_ROOT / "rules"
ORACLES_DIR = CORE_RULES_DIR / ".oracles"
WORKSPACE_RULES_DIR = REPO_ROOT / ".aegis" / "rules"

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


def get_core_rules() -> list[Path]:
    """All .md rule files in rules/ (top-level, non-hidden)."""
    if not CORE_RULES_DIR.exists():
        return []
    return sorted(
        p for p in CORE_RULES_DIR.glob("*.md")
        if p.name not in SKIP_FILES
    )


def get_oracle_rules() -> list[Path]:
    """All .md rule files in rules/.oracles/."""
    if not ORACLES_DIR.exists():
        return []
    return sorted(
        p for p in ORACLES_DIR.glob("*.md")
        if p.name not in SKIP_FILES
    )


def get_workspace_rules() -> list[Path]:
    """All .md rule files in .aegis/rules/**/ (excluding README)."""
    if not WORKSPACE_RULES_DIR.exists():
        return []
    return sorted(
        p for p in WORKSPACE_RULES_DIR.rglob("*.md")
        if p.name not in SKIP_FILES
    )


def get_all_rules() -> list[Path]:
    """All rule files across core rules + oracles + workspace rules."""
    return get_core_rules() + get_oracle_rules() + get_workspace_rules()


# ── Core rules must have frontmatter ──


@pytest.mark.parametrize("rule_file", get_core_rules(),
                         ids=lambda p: f"rules/{p.name}")
def test_core_rule_has_frontmatter(rule_file):
    """Every core rule MUST have YAML frontmatter."""
    meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert meta is not None, f"{rule_file.name} lacks YAML frontmatter"


@pytest.mark.parametrize("rule_file", get_core_rules(),
                         ids=lambda p: f"rules/{p.name}")
def test_core_rule_has_id(rule_file):
    """Every core rule MUST have an 'id' field in frontmatter."""
    meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert meta is not None, f"{rule_file.name} lacks YAML frontmatter"
    assert "id" in meta, f"{rule_file.name} missing 'id' field"


@pytest.mark.parametrize("rule_file", get_core_rules(),
                         ids=lambda p: f"rules/{p.name}")
def test_core_rule_has_domain(rule_file):
    """Every core rule MUST have a 'domain' field in frontmatter."""
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


# ── Workspace rules must have frontmatter and domain ──


@pytest.mark.parametrize("rule_file", get_workspace_rules(),
                         ids=lambda p: f"workspace/{p.parent.name}/{p.name}")
def test_workspace_rule_has_frontmatter(rule_file):
    """Every workspace rule MUST have YAML frontmatter."""
    meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert meta is not None, f"{rule_file.name} lacks YAML frontmatter"


@pytest.mark.parametrize("rule_file", get_workspace_rules(),
                         ids=lambda p: f"workspace/{p.parent.name}/{p.name}")
def test_workspace_rule_has_domain(rule_file):
    """Every workspace rule MUST have a 'domain' field in frontmatter."""
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


@pytest.mark.parametrize("rule_file", get_workspace_rules(),
                         ids=lambda p: f"workspace/{p.parent.name}/{p.name}")
def test_workspace_rule_has_id(rule_file):
    """Every workspace rule MUST have an 'id' field in frontmatter."""
    meta = parse_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert meta is not None, f"{rule_file.name} lacks YAML frontmatter"
    assert "id" in meta, f"{rule_file.name} missing 'id' field"


def test_no_duplicate_rule_ids():
    """All rule IDs across core rules + oracles + workspace rules must be unique."""
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
    from aegis_mcp.jit_engine import parse_frontmatter as jit_parser
    return jit_parser(path.read_text(encoding="utf-8"))


def _get_traps() -> list[Path]:
    """All trap rule files in .aegis/rules/traps/."""
    traps_dir = WORKSPACE_RULES_DIR / "traps"
    if not traps_dir.exists():
        return []
    return sorted(p for p in traps_dir.glob("*.md") if p.name not in SKIP_FILES)


def _get_invariants() -> list[Path]:
    """All invariant rule files in .aegis/rules/invariants/."""
    inv_dir = WORKSPACE_RULES_DIR / "invariants"
    if not inv_dir.exists():
        return []
    return sorted(p for p in inv_dir.glob("*.md") if p.name not in SKIP_FILES)


# ── Core rule content coherence ──


@pytest.mark.parametrize("rule_file", get_core_rules(),
                         ids=lambda p: f"rules/{p.name}")
def test_core_rule_has_enforcement(rule_file):
    """Core rules must declare an enforcement level."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert "enforcement" in fm, (
        f"{rule_file.name} missing 'enforcement' field"
    )


@pytest.mark.parametrize("rule_file", get_core_rules(),
                         ids=lambda p: f"rules/{p.name}")
def test_core_rule_has_body_text(rule_file):
    """Core rules must have meaningful body text (not just frontmatter)."""
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


# ── Trap rule content coherence ──


TRAP_REQUIRED_FIELDS = {"hypothesis", "target_paths", "type"}


@pytest.mark.parametrize("rule_file", _get_traps(),
                         ids=lambda p: f"traps/{p.name}")
def test_trap_rule_has_required_fields(rule_file):
    """Traps must have hypothesis, target_paths, and type."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    for field in TRAP_REQUIRED_FIELDS:
        assert field in fm, (
            f"{rule_file.name} missing required trap field '{field}'"
        )
    assert fm["type"] == "trap", (
        f"{rule_file.name} type is '{fm['type']}', expected 'trap'"
    )


@pytest.mark.parametrize("rule_file", _get_traps(),
                         ids=lambda p: f"traps/{p.name}")
def test_trap_rule_has_fitness_block(rule_file):
    """Traps should have fitness tracking (inline or external)."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    if "fitness" not in fm:
        return  # External tracking
    fitness = fm["fitness"]
    assert isinstance(fitness, dict), (
        f"{rule_file.name} fitness must be a dict, got {type(fitness)}"
    )
    for key in ("triggers", "true_positives", "false_positives"):
        assert key in fitness, (
            f"{rule_file.name} fitness block missing '{key}'"
        )


@pytest.mark.parametrize("rule_file", _get_traps(),
                         ids=lambda p: f"traps/{p.name}")
def test_trap_rule_has_expiry(rule_file):
    """Traps must have expiry settings (they can't live forever)."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    has_sessions = "expiry_sessions" in fm
    has_days = "expiry_days" in fm
    assert has_sessions or has_days, (
        f"{rule_file.name} has no expiry — traps must decay if unused"
    )


@pytest.mark.parametrize("rule_file", _get_traps(),
                         ids=lambda p: f"traps/{p.name}")
def test_trap_rule_target_paths_not_empty(rule_file):
    """Trap target_paths must contain at least one pattern."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    tp = fm.get("target_paths", [])
    assert isinstance(tp, list) and len(tp) > 0, (
        f"{rule_file.name} target_paths is empty — trap won't match anything"
    )


# ── Invariant rule content coherence ──


@pytest.mark.parametrize("rule_file", _get_invariants(),
                         ids=lambda p: f"invariants/{p.name}")
def test_invariant_rule_enforcement_is_gate(rule_file):
    """Invariants are non-negotiable — they must have gate enforcement."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert fm.get("enforcement") == "gate", (
        f"{rule_file.name} is an invariant but enforcement is "
        f"'{fm.get('enforcement')}' — invariants must be 'gate'"
    )


# ── JIT matching integration ──


def test_jit_matches_rules_on_core_files():
    """Rules should match when their target paths in aegis_core are touched."""
    from aegis_mcp.jit_engine import load_all_cells, match_cells_to_files
    rules = load_all_cells(str(REPO_ROOT))
    test_path = "aegis_core/telemetry.py"
    matched = match_cells_to_files(rules, [test_path])
    matched_ids = {c["id"] for c in matched}
    assert "trap-schema-contract-drift" in matched_ids, (
        f"trap-schema-contract-drift should match {test_path} "
        f"but matched: {matched_ids}"
    )


def test_jit_matches_trap_rule_on_python_files():
    """trap-future-annotations targets **/*.py — should match any .py file."""
    from aegis_mcp.jit_engine import load_all_cells, match_cells_to_files
    rules = load_all_cells(str(REPO_ROOT))
    test_path = "aegis_cli/status.py"
    matched = match_cells_to_files(rules, [test_path])
    matched_ids = {c["id"] for c in matched}
    assert "trap-future-annotations" in matched_ids, (
        f"trap-future-annotations should match {test_path} "
        f"but matched: {matched_ids}"
    )


# ── Boundary rule content coherence ──


def _get_boundaries() -> list[Path]:
    """All boundary rule files in .aegis/rules/boundaries/."""
    bnd_dir = WORKSPACE_RULES_DIR / "boundaries"
    if not bnd_dir.exists():
        return []
    return sorted(p for p in bnd_dir.glob("*.md") if p.name not in SKIP_FILES)


@pytest.mark.parametrize("rule_file", _get_boundaries(),
                         ids=lambda p: f"boundaries/{p.name}")
def test_boundary_rule_has_hypothesis(rule_file):
    """Boundaries define escalation boundaries — must have a hypothesis."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert "hypothesis" in fm, (
        f"{rule_file.name} missing 'hypothesis' — boundaries must "
        f"justify why this boundary requires escalation"
    )


@pytest.mark.parametrize("rule_file", _get_boundaries(),
                         ids=lambda p: f"boundaries/{p.name}")
def test_boundary_rule_type_is_correct(rule_file):
    """Boundary files must declare type: boundary."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert fm.get("type") == "boundary", (
        f"{rule_file.name} type is '{fm.get('type')}', expected 'boundary'"
    )


# ── Persona rule content coherence ──


def _get_personas() -> list[Path]:
    """All persona rule files in .aegis/rules/personas/."""
    per_dir = WORKSPACE_RULES_DIR / "personas"
    if not per_dir.exists():
        return []
    return sorted(p for p in per_dir.glob("*.md") if p.name not in SKIP_FILES)


@pytest.mark.parametrize("rule_file", _get_personas(),
                         ids=lambda p: f"personas/{p.name}")
def test_persona_rule_has_hypothesis(rule_file):
    """Personas are specialist lenses — must have a hypothesis."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert "hypothesis" in fm, (
        f"{rule_file.name} missing 'hypothesis' — personas must "
        f"justify their specialization"
    )


@pytest.mark.parametrize("rule_file", _get_personas(),
                         ids=lambda p: f"personas/{p.name}")
def test_persona_rule_type_is_correct(rule_file):
    """Persona files must declare type: persona."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert fm.get("type") == "persona", (
        f"{rule_file.name} type is '{fm.get('type')}', expected 'persona'"
    )


# ── Contract rule content coherence ──


def _get_contracts() -> list[Path]:
    """All contract rule files in .aegis/rules/contracts/."""
    con_dir = WORKSPACE_RULES_DIR / "contracts"
    if not con_dir.exists():
        return []
    return sorted(p for p in con_dir.glob("*.md") if p.name not in SKIP_FILES)


@pytest.mark.parametrize("rule_file", _get_contracts(),
                         ids=lambda p: f"contracts/{p.name}")
def test_contract_rule_has_hypothesis(rule_file):
    """Contracts define cross-module contracts — must have a hypothesis."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert "hypothesis" in fm, (
        f"{rule_file.name} missing 'hypothesis' — contracts must "
        f"define the contract they enforce"
    )


@pytest.mark.parametrize("rule_file", _get_contracts(),
                         ids=lambda p: f"contracts/{p.name}")
def test_contract_rule_type_is_correct(rule_file):
    """Contract files must declare type: contract."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert fm.get("type") == "contract", (
        f"{rule_file.name} type is '{fm.get('type')}', expected 'contract'"
    )


@pytest.mark.parametrize("rule_file", _get_contracts(),
                         ids=lambda p: f"contracts/{p.name}")
def test_contract_rule_has_target_paths(rule_file):
    """Contracts enforce cross-module boundaries — must specify target_paths."""
    fm = _jit_parse(rule_file)
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    tp = fm.get("target_paths", [])
    assert isinstance(tp, list) and len(tp) > 0, (
        f"{rule_file.name} target_paths is empty — contracts must "
        f"specify which modules they bridge"
    )


# ── Antigravity Rule Loader Trigger & Description Compliance ──


@pytest.mark.parametrize(
    "rule_file",
    get_core_rules() + get_oracle_rules(),
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_core_and_oracle_rules_declare_antigravity_trigger_and_description(rule_file: Path):
    """Every core and oracle rule must declare trigger and description so the IDE loads it into <user_rules>."""
    from aegis_core.yaml import parse_frontmatter as parse_yaml_frontmatter

    fm = parse_yaml_frontmatter(rule_file.read_text(encoding="utf-8"))
    assert fm, f"{rule_file.name} has no parseable frontmatter"
    assert fm.get("trigger") in ("always_on", "model_decision"), (
        f"{rule_file.name} must set trigger to 'always_on' or 'model_decision' (got {fm.get('trigger')!r})"
    )
    desc = fm.get("description")
    assert isinstance(desc, str) and len(desc.strip()) > 10, (
        f"{rule_file.name} must define a non-empty 'description' for conditional/active rule loading"
    )


def test_meta_and_gitflow_review_gate_declare_always_on_trigger():
    """META.md and gitflow-review-gate.md must declare trigger: always_on so JIT scanning and PR review gates are always active."""
    from aegis_core.yaml import parse_frontmatter as parse_yaml_frontmatter

    rules_root = REPO_ROOT / "rules"
    meta_file = rules_root / "META.md"
    gate_file = rules_root / "gitflow-review-gate.md"
    assert meta_file.is_file()
    assert gate_file.is_file()

    meta_fm = parse_yaml_frontmatter(meta_file.read_text(encoding="utf-8"))
    gate_fm = parse_yaml_frontmatter(gate_file.read_text(encoding="utf-8"))
    assert meta_fm and meta_fm.get("trigger") == "always_on"
    assert isinstance(meta_fm.get("description"), str) and len(meta_fm["description"].strip()) > 10
    assert gate_fm and gate_fm.get("trigger") == "always_on"
    assert isinstance(gate_fm.get("description"), str) and len(gate_fm["description"].strip()) > 10



