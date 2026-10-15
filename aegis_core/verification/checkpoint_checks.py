"""Shared, deterministic, read-only checkpoint checks for CLI and MCP."""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import List

from aegis_core.evidence import aggregate_signals
from aegis_core.taxonomy import DIR_TO_ALLOWED_RULE_TYPES as DIR_TO_TYPE


HARDCODED_PATH_RE = re.compile(r'''(?:"|')(/home/|/Users/|/tmp/)''')
SKIP_DIRS = {
    "__pycache__", ".git", ".soma", ".aegis", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build", "egg-info",
}


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except (ValueError, OSError):
        return str(path)


def _failure(
    check: str,
    root: Path,
    path: Path,
    operation: str,
    exc: BaseException,
) -> dict:
    rel = _relative(root, path)
    return {
        "check": check,
        "file": rel,
        "message": f"{rel}: {operation} failed: {exc}",
    }


def _is_regular_file(
    check: str,
    root: Path,
    path: Path,
    issues: list[dict],
) -> bool:
    """Validate a checked input without following a symlink."""
    try:
        info = os.stat(path, follow_symlinks=False)
    except FileNotFoundError as exc:
        issues.append(_failure(check, root, path, "stat", exc))
        return False
    except (OSError, UnicodeError) as exc:
        issues.append(_failure(check, root, path, "stat", exc))
        return False
    if stat.S_ISLNK(info.st_mode):
        issues.append({
            "check": check,
            "file": _relative(root, path),
            "message": f"{_relative(root, path)}: symlinked file is not allowed",
        })
        return False
    if not stat.S_ISREG(info.st_mode):
        issues.append({
            "check": check,
            "file": _relative(root, path),
            "message": f"{_relative(root, path)}: expected a regular file",
        })
        return False
    return True


def find_python_files(root: Path, subdir: str) -> list[Path]:
    """Find source files without following symlinked directories."""
    target = root / subdir
    result = []  # type: List[Path]
    try:
        target_info = os.stat(target, follow_symlinks=False)
    except FileNotFoundError:
        return result
    if not stat.S_ISDIR(target_info.st_mode):
        return result

    def walk_error(exc: OSError) -> None:
        raise exc

    for dirpath, dirnames, filenames in os.walk(
        target, topdown=True, followlinks=False, onerror=walk_error
    ):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for filename in sorted(filenames):
            if filename.endswith(".py") and not filename.startswith("__"):
                result.append(Path(dirpath) / filename)
    return result


def _source_dirs(root: Path, check: str, issues: list[dict]) -> list[str]:
    try:
        with os.scandir(root) as it:
            candidates = sorted(it, key=lambda e: e.name)
    except (OSError, UnicodeError) as exc:
        issues.append(_failure(check, root, root, "list", exc))
        return []

    names = []
    for entry in candidates:
        name = entry.name
        if name.startswith(".") or name in SKIP_DIRS or name == "tests":
            continue
        try:
            info = entry.stat(follow_symlinks=False)
        except FileNotFoundError as exc:
            issues.append(_failure(check, root, Path(entry.path), "stat", exc))
            continue
        except (OSError, UnicodeError) as exc:
            issues.append(_failure(check, root, Path(entry.path), "stat", exc))
            continue
        candidate = Path(entry.path)
        if stat.S_ISLNK(info.st_mode):
            issues.append({
                "check": check,
                "file": _relative(root, candidate),
                "message": (
                    f"{_relative(root, candidate)}: "
                    "symlinked source directory is not allowed"
                ),
            })
            continue
        if not stat.S_ISDIR(info.st_mode):
            continue
        try:
            if find_python_files(root, name):
                names.append(name)
        except (OSError, UnicodeError) as exc:
            issues.append(_failure(check, root, candidate, "list", exc))
    return names


def _resolve_canonical_test_candidates(root: Path, source_file: Path) -> list[Path]:
    """Resolve deterministic test candidates for a source file in canonical and dynamic layouts."""
    test_dir = root / "tests"
    rel_posix = _relative(root, source_file)
    candidates: list[Path] = []

    # 1. Canonical mirrored directory paths (tests/<clean_pkg>/.../test_<stem>.py and tests/<top_pkg>/.../test_<stem>.py)
    rel_path = Path(rel_posix)
    parts = list(rel_path.parts)
    stem = rel_path.stem
    if len(parts) >= 2:
        top_pkg = parts[0]
        if top_pkg.startswith("aegis_"):
            clean_pkg = top_pkg[6:]
        elif top_pkg.startswith("soma_"):
            clean_pkg = top_pkg[5:]
        else:
            clean_pkg = top_pkg
        subparts = parts[1:-1]
        candidates.append(test_dir.joinpath(clean_pkg, *subparts, f"test_{stem}.py"))
        candidates.append(test_dir.joinpath(top_pkg, *subparts, f"test_{stem}.py"))
        candidates.append(test_dir.joinpath("unit", clean_pkg, *subparts, f"test_{stem}.py"))
        candidates.append(test_dir.joinpath("unit", top_pkg, *subparts, f"test_{stem}.py"))
        candidates.append(test_dir.joinpath("unit", clean_pkg, f"test_{stem}.py"))
        candidates.append(test_dir.joinpath("unit", top_pkg, f"test_{stem}.py"))

    # 2. Subpackage and platform suite candidates
    parent_name = source_file.parent.name
    if parent_name != "tests":
        candidates.append(test_dir / f"test_{parent_name}.py")
        candidates.append(test_dir / f"test_{parent_name}_{stem}.py")
        if len(parts) >= 2:
            clean_pkg = parts[0][6:] if parts[0].startswith("aegis_") else (parts[0][5:] if parts[0].startswith("soma_") else parts[0])
            candidates.append(test_dir / f"test_{clean_pkg}_{parent_name}.py")
            candidates.append(test_dir / f"test_{parent_name}_adapters.py")
            candidates.append(test_dir / f"test_{clean_pkg}_{parent_name}_adapters.py")
            candidates.append(test_dir / f"test_{clean_pkg}_{parent_name}_{stem}.py")

    # 3. Domain and legacy suite mappings resolved dynamically
    top_dir = parts[0] if parts else ""
    if top_dir in ("aegis_cli", "soma_cli"):
        candidates.append(test_dir / f"test_cli_{stem}.py")
        candidates.append(test_dir / "test_platforms.py")
        candidates.append(test_dir / "test_platform_adapters.py")
    elif top_dir in ("aegis_core", "soma_core"):
        candidates.append(test_dir / f"test_core_{stem}.py")
    elif top_dir in ("aegis_mcp", "soma_mcp"):
        candidates.append(test_dir / f"test_mcp_{stem}.py")
    elif top_dir in ("aegis_sdk", "soma_sdk"):
        candidates.append(test_dir / f"test_sdk_{stem}.py")

    if "ast" in parts:
        candidates.append(test_dir / f"test_ast_{stem}.py")
        candidates.append(test_dir / "unit" / "core" / f"test_ast_{stem}.py")
    if stem == "detect":
        candidates.append(test_dir / "test_ast_detect.py")
        candidates.append(test_dir / "unit" / "core" / "test_ast_detect.py")
        candidates.append(test_dir / "test_polyglot_detect.py")
        candidates.append(test_dir / "unit" / "core" / "test_polyglot_detect.py")
    if stem == "schema":
        candidates.append(test_dir / "test_ast_schema.py")
        candidates.append(test_dir / "unit" / "core" / "test_ast_schema.py")
        candidates.append(test_dir / "test_normalized_ast_schema.py")
        candidates.append(test_dir / "unit" / "core" / "test_normalized_ast_schema.py")
    if stem == "python":
        candidates.append(test_dir / "test_ast_python.py")
        candidates.append(test_dir / "unit" / "core" / "test_ast_python.py")
        candidates.append(test_dir / "test_ast_driver_runner.py")
        candidates.append(test_dir / "unit" / "core" / "test_ast_driver_runner.py")
    if stem == "rust_ast":
        candidates.append(test_dir / "test_ast_rust.py")
        candidates.append(test_dir / "unit" / "core" / "test_ast_rust.py")
        candidates.append(test_dir / "test_rust_ast_driver.py")
        candidates.append(test_dir / "unit" / "core" / "test_rust_ast_driver.py")
    if stem == "rules":
        candidates.append(test_dir / "unit" / "sdk" / "test_cells.py")
        candidates.append(test_dir / "sdk" / "test_cells.py")
        candidates.append(test_dir / "test_cells.py")
        candidates.append(test_dir / "unit" / "sdk" / "test_sdk_behavioral.py")
        candidates.append(test_dir / "test_rule_content.py")
    if stem == "checkpoint_checks":
        candidates.append(test_dir / "test_checkpoint_fail_closed.py")
    if stem in ("call_graph", "persistence_checker", "runner"):
        candidates.append(test_dir / "test_verification" / "test_layer1.py")
        candidates.append(test_dir / "unit" / "verification" / "test_layer1.py")
        candidates.append(test_dir / "unit" / "verification" / "test_call_graph_ast.py")
    if stem == "hooks":
        candidates.append(test_dir / "test_hooks_lifecycle.py")
    if stem == "errors":
        candidates.append(test_dir / "test_domain_errors.py")
        candidates.append(test_dir / "test_sdk_behavioral.py")
    if stem == "evidence":
        candidates.append(test_dir / "test_canonical_evidence_readers.py")
    if stem == "frontmatter":
        candidates.append(test_dir / "test_core_lifecycle.py")
    if stem == "rule_inventory":
        candidates.append(test_dir / "test_rule_inventory.py")
    if stem == "rule_cache":
        candidates.append(test_dir / "test_rule_cache.py")
    if stem == "integrity":
        candidates.append(test_dir / "test_evidence_integrity.py")
        candidates.append(test_dir / "unit" / "mcp" / "test_manifest_hmac.py")
    if stem == "adversarial_verify":
        candidates.append(test_dir / "unit" / "verification" / "test_adversarial_verify.py")
    if stem in ("match", "ast_match"):
        candidates.append(test_dir / "unit" / "core" / "test_ast_grep_upgrade.py")
    if stem in ("taxonomy", "operations", "layout", "discovery"):
        candidates.append(test_dir / "unit" / "core" / "test_v3_zero_legacy_invariants.py")
        candidates.append(test_dir / "unit" / "core" / "test_storage.py")
        candidates.append(test_dir / "unit" / "core" / "test_workspace.py")
    if stem == "server":
        candidates.append(test_dir / "test_mcp_dispatch.py")
    if stem == "tools":
        candidates.append(test_dir / "test_mcp_tools_contract.py")
    if stem == "analysis":
        candidates.append(test_dir / "test_sdk_analysis.py")
    if stem == "cells":
        candidates.append(test_dir / "test_rule_content.py")
    if stem == "invariants":
        candidates.append(test_dir / "test_enforcement_ladder.py")
    if parent_name == "skills" or stem in ("graph", "handoff", "slots", "skills", "artifacts"):
        candidates.append(test_dir / "test_skills_and_handoff.py")
    if parent_name == "handlers" or stem in ("registry", "projection"):
        candidates.append(test_dir / "test_mcp_tools_contract.py")
        candidates.append(test_dir / "test_mcp_dispatch.py")
        candidates.append(test_dir / "test_mcp_projection.py")
    if parent_name == "outcomes":
        candidates.append(test_dir / "test_outcome_engine.py")
        candidates.append(test_dir / "test_outcomes.py")
    if parent_name == "hooks":
        candidates.append(test_dir / "test_hooks_lifecycle.py")
    if stem in ("somayaml", "yaml"):
        candidates.append(test_dir / "test_somayaml.py")
        candidates.append(test_dir / "test_yaml.py")

    # 4. Flat root candidates
    candidates.append(test_dir / f"test_{stem}.py")
    candidates.append(test_dir / f"test_{stem}_behavioral.py")
    candidates.append(test_dir / "test_verification" / f"test_{stem}.py")
    candidates.append(test_dir / "unit" / "verification" / f"test_{stem}.py")

    expanded: list[Path] = []
    seen = set()
    for c in candidates:
        if c not in seen:
            expanded.append(c)
            seen.add(c)
        if c.parent == test_dir:
            for domain in ("core", "cli", "mcp", "sdk", "verification"):
                cand_domain = test_dir / "unit" / domain / c.name
                if cand_domain not in seen:
                    expanded.append(cand_domain)
                    seen.add(cand_domain)
            cand_integration = test_dir / "integration" / c.name
            if cand_integration not in seen:
                expanded.append(cand_integration)
                seen.add(cand_integration)

    return expanded


def check_test_coverage(root: Path) -> list[dict]:
    issues = []  # type: List[dict]
    source_files = []  # type: List[Path]
    for source_dir in _source_dirs(root, "test_coverage", issues):
        try:
            source_files.extend(find_python_files(root, source_dir))
        except (OSError, UnicodeError) as exc:
            issues.append(_failure(
                "test_coverage", root, root / source_dir, "list", exc
            ))

    for source_file in source_files:
        if not _is_regular_file(
            "test_coverage", root, source_file, issues
        ):
            continue

        candidates = _resolve_canonical_test_candidates(root, source_file)
        matched = False
        for expected in candidates:
            try:
                expected_info = os.stat(expected, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except (OSError, UnicodeError) as exc:
                issues.append(_failure("test_coverage", root, expected, "stat", exc))
                matched = True
                break
            else:
                if stat.S_ISLNK(expected_info.st_mode) or not stat.S_ISREG(expected_info.st_mode):
                    kind = "symlinked" if stat.S_ISLNK(expected_info.st_mode) else "non-regular"
                    issues.append({
                        "check": "test_coverage",
                        "file": _relative(root, expected),
                        "message": (
                            f"{_relative(root, expected)}: {kind} test file "
                            "does not satisfy coverage"
                        ),
                    })
                matched = True
                break

        if not matched:
            issues.append({
                "check": "test_coverage",
                "file": _relative(root, source_file),
                "message": (
                    f"Missing test file for {source_file.name}: "
                    f"expected tests/test_{source_file.stem}.py"
                ),
            })
    return issues


def check_hardcoded_paths(root: Path) -> list[dict]:
    issues = []  # type: List[dict]
    for source_dir in _source_dirs(root, "hardcoded_paths", issues):
        try:
            files = find_python_files(root, source_dir)
        except (OSError, UnicodeError) as exc:
            issues.append(_failure(
                "hardcoded_paths", root, root / source_dir, "list", exc
            ))
            continue
        for py_file in files:
            if not _is_regular_file(
                "hardcoded_paths", root, py_file, issues
            ):
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                issues.append(_failure(
                    "hardcoded_paths", root, py_file, "read", exc
                ))
                continue
            for line_no, line in enumerate(content.splitlines(), 1):
                if HARDCODED_PATH_RE.search(line):
                    issues.append({
                        "check": "hardcoded_paths",
                        "file": _relative(root, py_file),
                        "line": line_no,
                        "message": (
                            f"Hardcoded absolute path found in "
                            f"{py_file.name}:{line_no}"
                        ),
                    })
    return issues


def check_assertion_density(root: Path) -> list[dict]:
    """Every ``test_*`` function under tests/ must assert something and not be a stub.

    Judged per function by AST (#1): text such as "assert " in a comment, a
    docstring or a neighbouring test no longer passes a file.
    """
    from aegis_core.verification.quality_gate import check_assertion_density as density
    from aegis_core.verification.quality_gate import check_no_bare_pass as bare_pass

    issues = []  # type: List[dict]
    try:
        test_files = find_python_files(root, "tests")
    except (OSError, UnicodeError) as exc:
        return [_failure("assertion_density", root, root / "tests", "list", exc)]

    for test_file in test_files:
        if not test_file.name.startswith("test_"):
            continue
        if not _is_regular_file("assertion_density", root, test_file, issues):
            continue
        try:
            found = [density(str(test_file)), bare_pass(str(test_file))]
        except (OSError, SyntaxError, UnicodeError, ValueError) as exc:
            issues.append(_failure("assertion_density", root, test_file, "parse", exc))
            continue
        prefixes = ("Low assertion density in", "Placeholder tests in")
        for prefix, evidence in zip(prefixes, found):
            if not evidence.verdict:
                issues.append({
                    "check": "assertion_density",
                    "file": _relative(root, test_file),
                    "lines": evidence.lines,
                    "message": f"{prefix} {test_file.name}: {evidence.detail[0].lower()}{evidence.detail[1:]}",
                })
    return issues


def check_cell_fitness(root: Path) -> list[dict]:
    issues = []  # type: List[dict]
    evidence_dir = root / ".aegis" / "evidence"
    aggregation = aggregate_signals(evidence_dir)

    for error in aggregation.errors:
        error_path = Path(error.get("file") or evidence_dir / "signals.jsonl")
        rel = _relative(root, error_path)
        line = error.get("line")
        location = f" line {line}" if line is not None else ""
        issues.append({
            "check": "cell_fitness",
            "file": rel,
            "message": f"{rel}:{location} {error.get('error', 'signal aggregation failed')}",
        })

    for cell_id, counts in aggregation.counts.items():
        tp = counts["tp"]
        fp = counts["fp"]
        total = tp + fp
        if total >= 2 and fp / total > 0.5:
            rate = fp / total
            issues.append({
                "check": "cell_fitness",
                "cell_id": cell_id,
                "message": (
                    f"Rule '{cell_id}' has unhealthy fitness: "
                    f"{fp}/{total} false positives "
                    f"({rate:.0%} FP rate)"
                ),
            })
    return issues


def check_cell_conventions(root: Path) -> list[dict]:
    issues = []  # type: List[dict]
    from aegis_core.rule_inventory import CellInventoryError, inventory_rules

    try:
        inventory = inventory_rules(str(root))
    except CellInventoryError as exc:
        path = Path(exc.path)
        issues.append(_failure(
            "cell_conventions", root, path, exc.operation, exc
        ))
        return issues

    from aegis_core.rule_inventory import parse_frontmatter

    for entry in inventory.entries:
        if os.path.basename(entry.relative_path) == "README.md":
            continue
        parts = entry.relative_path.split("/")
        if len(parts) < 4 or parts[:2] != [".aegis", "rules"]:
            continue
        type_dir_name = parts[2]
        allowed_types = DIR_TO_TYPE.get(type_dir_name)
        if allowed_types is None:
            continue
        if isinstance(allowed_types, str):
            allowed_types = (allowed_types,)
        rel = entry.relative_path
        try:
            content = entry.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            issues.append(_failure(
                "cell_conventions", root, Path(entry.absolute_path), "decode", exc
            ))
            continue
        if not content.startswith("---"):
            issues.append({
                "check": "cell_conventions",
                "file": rel,
                "message": f"{rel}: missing YAML frontmatter",
            })
            continue
        lines = content.splitlines()
        closing = next(
            (index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"),
            None,
        )
        if closing is None:
            issues.append({
                "check": "cell_conventions",
                "file": rel,
                "message": f"{rel}: unterminated YAML frontmatter",
            })
            continue
        try:
            meta = parse_frontmatter(content)
        except Exception as exc:
            issues.append(_failure(
                "cell_conventions", root, Path(entry.absolute_path), "parse", exc
            ))
            continue
        if meta is None:
            frontmatter_lines = [line.strip() for line in lines[1:closing] if line.strip()]
            if frontmatter_lines and frontmatter_lines[0].startswith("-"):
                message = f"{rel}: cell frontmatter must be a mapping"
            else:
                message = f"{rel}: malformed YAML frontmatter"
            issues.append({
                "check": "cell_conventions", "file": rel, "message": message,
            })
            continue
        if not isinstance(meta, dict) or not meta:
            issues.append({
                "check": "cell_conventions",
                "file": rel,
                "message": f"{rel}: cell frontmatter must be a non-empty mapping",
            })
            continue

        required = ["id", "domain", "type"]
        if any(t in ("wall", "invariant", "trap") for t in allowed_types):
            required.append("enforcement")
        for field in required:
            if field not in meta:
                issues.append({
                    "check": "cell_conventions",
                    "file": rel,
                    "message": f"{rel}: missing required field '{field}'",
                })
        cell_type = meta.get("type", "")
        if cell_type not in allowed_types:
            issues.append({
                "check": "cell_conventions",
                "file": rel,
                "message": (
                    f"{rel}: type '{cell_type}' doesn't match directory "
                    f"'{type_dir_name}' (expected one of {allowed_types})"
                ),
            })
        if cell_type in ("wall", "invariant") and meta.get("enforcement") != "gate":
            issues.append({
                "check": "cell_conventions",
                "file": rel,
                "message": (
                    f"{rel}: wall/invariant enforcement is '{meta.get('enforcement')}' "
                    "but must use 'gate'"
                ),
            })
        stem = os.path.splitext(os.path.basename(entry.relative_path))[0]
        if meta.get("id") != stem:
            issues.append({
                "check": "cell_conventions",
                "file": rel,
                "message": (
                    f"{rel}: frontmatter id '{meta.get('id')}' "
                    f"doesn't match filename '{stem}'"
                ),
            })
    return issues


def check_paper_walls(root: Path) -> list[dict]:
    """Verify that all wall cells have 'gate' enforcement and valid frontmatter."""
    issues = []
    walls_dir = root / ".aegis" / "rules" / "invariants"
    if not walls_dir.is_dir():
        walls_dir = root / ".aegis" / "rules" / "walls"
    if not walls_dir.is_dir():
        return issues

    for wall_file in sorted(walls_dir.glob("*.md")):
        try:
            content = wall_file.read_text(encoding="utf-8")
            from aegis_core.yaml import parse_frontmatter
            meta = parse_frontmatter(content)
            if not isinstance(meta, dict):
                issues.append({
                    "check": "paper_walls",
                    "file": _relative(root, wall_file),
                    "message": f"Wall cell '{wall_file.name}' has missing or invalid frontmatter.",
                })
                continue
            enforcement = meta.get("enforcement")
            if enforcement != "gate":
                issues.append({
                    "check": "paper_walls",
                    "file": _relative(root, wall_file),
                    "message": f"Wall cell '{wall_file.name}' enforcement is '{enforcement}', but all walls must use 'gate'.",
                })
        except Exception as exc:
            # An unreadable wall cannot be shown to be a gate: report it, never skip it.
            issues.append({
                "check": "paper_walls",
                "file": _relative(root, wall_file),
                "message": (
                    f"Wall cell '{wall_file.name}' cannot be read, so it cannot be shown to use 'gate': "
                    f"{type(exc).__name__}: {exc}"
                ),
            })
    return issues


ALL_CHECKS = [
    check_test_coverage,
    check_hardcoded_paths,
    check_assertion_density,
    check_cell_fitness,
    check_cell_conventions,
    check_paper_walls,
]
CHECK_NAMES = [
    "test_coverage",
    "hardcoded_paths",
    "assertion_density",
    "cell_fitness",
    "cell_conventions",
    "paper_walls",
]


def run_all_checks(root: Path) -> list[dict]:
    """Run every check and convert unexpected check failures into issues."""
    issues = []  # type: List[dict]
    for check_fn in ALL_CHECKS:
        try:
            issues.extend(check_fn(root))
        except Exception as exc:
            check_name = check_fn.__name__.replace("check_", "", 1)
            issues.append(_failure(check_name, root, root, "check", exc))
    return issues

