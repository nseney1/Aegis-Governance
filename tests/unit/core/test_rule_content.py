"""Tests for governance rule CONTENT correctness.

Validates that factual claims made in governance rules match the actual
state of the codebase. This prevents rule drift — where a rule's prose
contradicts reality, causing agents to follow incorrect guidance.

Grounded in evidence: the optional-import-guard oracle listed pyyaml as
"optional" despite pyproject.toml declaring it as a required dependency.
This single incorrect table row caused 28 files of buggy guard code.
"""

import re
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # Python 3.10 fallback

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _parse_pyproject_deps():
    """Extract required dependency package names from pyproject.toml."""
    with open(PYPROJECT, "rb") as f:
        data = tomllib.load(f)
    deps = data.get("project", {}).get("dependencies", [])
    # Parse "pyyaml>=6.0" → "pyyaml"
    return {re.split(r"[><=!~\[]", d)[0].strip().lower() for d in deps}


def _parse_oracle_table(section_header, filepath):
    """Extract package names from a markdown table under a section header."""
    content = filepath.read_text(encoding="utf-8")
    packages = []
    in_section = False
    in_table = False
    for line in content.splitlines():
        if line.startswith("## ") and section_header.lower() in line.lower():
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break  # Next section
        if in_section and line.startswith("|") and "---" not in line:
            cols = [c.strip() for c in line.split("|")]
            if len(cols) >= 3 and cols[1].lower() != "package":
                # Extract package name: "`yaml` (pyyaml)" → "pyyaml"
                raw = cols[1]
                # Check for parenthetical real name: "yaml (pyyaml)" → pyyaml
                paren_match = re.search(r"\((\w+)\)", raw)
                if paren_match:
                    packages.append(paren_match.group(1).lower())
                else:
                    # Strip backticks and use raw name
                    packages.append(raw.strip("`").split(".")[0].lower())
    return set(packages)


# ── Required deps must be in pyproject.toml ──


def test_required_deps_in_pyproject():
    """Every package listed as 'Required' in optional-import-guard must be
    a declared dependency in pyproject.toml."""
    oracle = REPO_ROOT / "genome" / ".oracles" / "optional-import-guard.md"
    if not oracle.exists():
        pytest.skip("optional-import-guard oracle not found")
    required = _parse_oracle_table("Required Dependencies", oracle)
    pyproject_deps = _parse_pyproject_deps()
    for pkg in required:
        assert pkg in pyproject_deps, (
            f"Oracle lists '{pkg}' as required, but it's not in "
            f"pyproject.toml [project.dependencies]: {pyproject_deps}"
        )
    # v0.96.1 zero-dependency invariant: Soma has zero runtime dependencies
    assert len(pyproject_deps) == 0, f"Expected 0 runtime dependencies, found: {pyproject_deps}"
    assert len(required) == 0, f"Expected 0 required dependencies in oracle, found: {required}"


def test_optional_deps_not_in_required():
    """Every package listed as 'Optional' in optional-import-guard must NOT
    be a declared required dependency in pyproject.toml."""
    oracle = REPO_ROOT / "genome" / ".oracles" / "optional-import-guard.md"
    if not oracle.exists():
        pytest.skip("optional-import-guard oracle not found")
    optional = _parse_oracle_table("Known Optional Dependencies", oracle)
    pyproject_deps = _parse_pyproject_deps()
    for pkg in optional:
        assert pkg not in pyproject_deps, (
            f"Oracle lists '{pkg}' as optional, but it IS in "
            f"pyproject.toml [project.dependencies]. Move it to the "
            f"'Required Dependencies' table."
        )


# ── Rule-referenced paths should exist ──


def _collect_target_paths_from_rules():
    """Collect target_paths values from all cell frontmatter."""
    from aegis_core.yaml_engine.frontmatter import parse_frontmatter
    results = []
    cells_dir = (REPO_ROOT / ".aegis" / "rules") if (REPO_ROOT / ".aegis" / "rules").is_dir() else (REPO_ROOT / ".aegis" / "rules")
    if not cells_dir.exists():
        return results
    for md_file in cells_dir.rglob("*.md"):
        if md_file.name == "README.md":
            continue
        content = md_file.read_text(encoding="utf-8")
        try:
            fm = parse_frontmatter(content)
        except Exception:
            continue
        if fm and isinstance(fm, dict):
            tp = fm.get("target_paths", [])
            if isinstance(tp, list):
                for p in tp:
                    if isinstance(p, str) and not any(c in p for c in "*?["):
                        # Only check literal paths, not globs
                        results.append((md_file.name, p))
    return results


_literal_paths = _collect_target_paths_from_rules()

# Wave B1b deleted these modules (D7, the telemetry facade); the dogfood rules
# that still name them live in .aegis/rules, which the b1b-core lane does not
# own. Strict, so the rule edit (drop the line) must also drop the entry.
_DANGLING_PENDING_RULE_EDIT = {
    ("trap-stdout-protocol-corruption.md", "aegis_core/sync.py"):
        "aegis_core/sync.py was deleted in wave B1b; the .aegis/rules edit is deferred to the rules owner",
    ("contract-mcp-cli-parity.md", "aegis_core/telemetry.py"):
        "aegis_core/telemetry.py was deleted in wave B1b; the .aegis/rules edit is deferred to the rules owner",
}


def _target_path_params():
    params = []
    for rule_name, target_path in _literal_paths:
        reason = _DANGLING_PENDING_RULE_EDIT.get((rule_name, target_path))
        marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
        params.append(pytest.param(rule_name, target_path, marks=marks, id=f"{rule_name}:{target_path}"))
    return params


@pytest.mark.parametrize("rule_name,target_path", _target_path_params()) if _literal_paths else lambda f: f
def test_literal_target_paths_exist(rule_name, target_path):
    """Literal (non-glob) target_paths referenced by cells should exist."""
    full = REPO_ROOT / target_path
    assert full.exists(), (
        f"Cell '{rule_name}' references target_path '{target_path}' "
        f"which does not exist in the repo"
    )


# ── B.5.2: Parser divergence test ──


def test_parsers_agree_on_id_and_domain():
    """The test suite's regex parser and the production JIT engine parser
    must agree on 'id' and 'domain' for every rule file.

    If these diverge, tests pass on rules that production silently skips
    (or vice versa) — the oracle table pattern at the parser level.
    """
    from tests.unit.core.test_rule_metadata import parse_frontmatter as test_parser
    from aegis_mcp.jit_engine import parse_frontmatter as jit_parser

    rule_dirs = [
        REPO_ROOT / "rules",
        REPO_ROOT / "rules" / ".oracles",
        REPO_ROOT / "genome",
        REPO_ROOT / "genome" / ".oracles",
        REPO_ROOT / ".aegis" / "rules",
        REPO_ROOT / ".aegis" / "rules",
    ]
    checked = 0
    for rule_dir in rule_dirs:
        if not rule_dir.exists():
            continue
        for md_file in rule_dir.rglob("*.md"):
            if md_file.name == "README.md":
                continue
            content = md_file.read_text(encoding="utf-8")
            test_result = test_parser(content)
            jit_result = jit_parser(content)

            # Both must agree on presence
            if test_result is None and jit_result is None:
                continue
            if test_result is None or jit_result is None:
                rel = md_file.relative_to(REPO_ROOT)
                assert False, (
                    f"Parser disagreement on {rel}: "
                    f"test_parser={'None' if test_result is None else 'dict'}, "
                    f"jit_parser={'None' if jit_result is None else 'dict'}"
                )

            # Both must agree on id and domain values
            for key in ("id", "domain"):
                test_val = test_result.get(key)
                jit_val = jit_result.get(key)
                if test_val != str(jit_val) if jit_val is not None else test_val is not None:
                    # Test parser strips quotes and returns strings;
                    # JIT parser preserves types. Compare as strings.
                    if str(test_val) != str(jit_val):
                        rel = md_file.relative_to(REPO_ROOT)
                        assert False, (
                            f"Parser disagreement on {rel} field '{key}': "
                            f"test_parser='{test_val}', jit_parser='{jit_val}'"
                        )
            checked += 1

    assert checked > 0, "No rules were checked — test infrastructure issue"


# ── B.5.3: Glob coverage test ──


def _collect_glob_paths_from_cells():
    """Collect glob target_paths from all cell frontmatter."""
    from aegis_core.yaml_engine.frontmatter import parse_frontmatter
    results = []
    cells_dir = (REPO_ROOT / ".aegis" / "rules") if (REPO_ROOT / ".aegis" / "rules").is_dir() else (REPO_ROOT / ".aegis" / "rules")
    if not cells_dir.exists():
        return results
    for md_file in cells_dir.rglob("*.md"):
        if md_file.name == "README.md":
            continue
        content = md_file.read_text(encoding="utf-8")
        try:
            fm = parse_frontmatter(content)
        except Exception:
            continue
        if fm and isinstance(fm, dict):
            tp = fm.get("target_paths", [])
            if isinstance(tp, list):
                for p in tp:
                    if isinstance(p, str) and any(c in p for c in "*?["):
                        results.append((md_file.name, p))
    return results


_glob_paths = _collect_glob_paths_from_cells()


@pytest.mark.parametrize(
    "rule_name,glob_pattern", _glob_paths,
    ids=[f"{r}:{p}" for r, p in _glob_paths]
) if _glob_paths else lambda f: f
def test_glob_target_paths_match_files(rule_name, glob_pattern):
    """Glob target_paths in cells must match at least one file in the repo.

    A cell monitoring 'nonexistent_dir/*.py' silently covers nothing.
    """
    import glob as globmod
    matches = globmod.glob(str(REPO_ROOT / glob_pattern), recursive=True)
    assert len(matches) > 0, (
        f"Cell '{rule_name}' has target_path glob '{glob_pattern}' "
        f"which matches 0 files in the repo"
    )


# ── Meta-test: schema test coverage gap detection ──
# Validates that every cell subdirectory has corresponding parametrized
# content coherence tests in test_rule_metadata.py. Without this, adding
# a new cell type (e.g. "ribosomes/") silently lacks schema enforcement.


def test_cell_subdirs_have_test_coverage():
    """Every cell subdirectory with .md files must have a test function
    in test_rule_metadata.py that parametrizes over its files.

    This is the testable hypothesis behind trap-schema-test-gap: schema
    test gaps cause frontmatter drift in unmonitored cell types.
    """

    cells_dir = (REPO_ROOT / ".aegis" / "rules") if (REPO_ROOT / ".aegis" / "rules").is_dir() else (REPO_ROOT / ".aegis" / "rules")
    if not cells_dir.exists():
        pytest.skip("No .aegis/rules/ or .aegis/rules/ directory")

    # Find all cell subdirectories that contain .md files
    cell_subdirs = set()
    for md_file in cells_dir.rglob("*.md"):
        if md_file.name == "README.md":
            continue
        # Get the immediate subdirectory name (vacuoles, walls, etc.)
        rel = md_file.relative_to(cells_dir)
        if len(rel.parts) >= 2:
            cell_subdirs.add(rel.parts[0])

    # Parse test_rule_metadata.py to find which cell types are tested
    test_file = REPO_ROOT / "tests" / "unit" / "core" / "test_rule_metadata.py"
    source = test_file.read_text(encoding="utf-8")

    SUBDIR_ALIASES = {
        "invariants": "walls",
        "traps": "vacuoles",
        "boundaries": "membranes",
        "personas": "chloroplasts",
        "contracts": "plasmodesmata",
    }
    tested_types = set()
    for subdir in cell_subdirs:
        alias = SUBDIR_ALIASES.get(subdir, subdir)
        if subdir in source or alias in source:
            tested_types.add(subdir)

    untested = cell_subdirs - tested_types
    assert not untested, (
        f"Cell subdirectories {untested} have .md files but no "
        f"corresponding test coverage in test_rule_metadata.py. "
        f"Add parametrized content coherence tests for these types."
    )


def test_core_rules_have_content_tests():
    """Core rules must be covered by content coherence tests,
    not just structural/schema tests.

    Checks that test_rule_metadata.py contains at least one test function
    that validates core rule content beyond basic frontmatter presence.
    """
    test_file = REPO_ROOT / "tests" / "unit" / "core" / "test_rule_metadata.py"
    source = test_file.read_text(encoding="utf-8")

    # Must have at least these content tests (not just has_frontmatter/has_id)
    content_tests = [
        "test_core_rule_has_enforcement",
        "test_core_rule_has_body_text",
    ]
    missing = [t for t in content_tests if t not in source]
    assert not missing, (
        f"Missing core rule content coherence tests: {missing}. "
        f"Core rules need more than frontmatter/id checks."
    )


