"""Governance: read-only governance reports over a workspace, as thin wrappers over aegis_core."""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Optional

from aegis_core.lifecycle.decay import compute_cells_fitness
from aegis_core.metrics import calculate_coverage, calculate_governance_grade
from aegis_core.outcomes.engine import _get_changed_files, match_cells_to_changes
from aegis_core.rule_inventory import RuleInventoryError, inventory_rules
from aegis_core.workspace.base import Workspace
from aegis_core.yaml_engine.frontmatter import parse_frontmatter

# Legacy (v1/v2) rule type names accepted by list_rules(rule_type=...).
TYPE_TRANSLATION_MAP: dict[str, str] = {
    "safety-guard": "invariant",
    "learned-trap": "trap",
    "agent-persona": "persona",
    "escalation-boundary": "boundary",
    "contract-bridge": "contract",
    "invariant": "invariant",
    "trap": "trap",
    "persona": "persona",
    "boundary": "boundary",
    "contract": "contract",
    "wall": "invariant",
    "membrane": "boundary",
}

__all__ = ["Governance", "TYPE_TRANSLATION_MAP"]


class Governance:
    """Aegis governance reports for one workspace.

    Usage:
        from aegis_sdk import Governance
        gov = Governance(project_root='.')
        grade = gov.grade()
        coverage = gov.coverage_report()
    """

    def __init__(self, project_root: str | Path | os.PathLike[str] | Workspace = '.') -> None:
        self.workspace: Workspace = (
            project_root if isinstance(project_root, Workspace) else Workspace.resolve(project_root)
        )
        self.root: Path = self.workspace.root
        self.rules_dir: Path = self.workspace.rules_dir

    def list_rules(self, rule_type: Optional[str] = None) -> list[dict[str, Any]]:
        """List rules (frontmatter plus ``_name``/``_path``), optionally filtered by type.

        Invalid rule contents stay visible as ``_error`` records. Unsafe or
        unreadable inventory trees fail closed because callers cannot safely
        distinguish an empty tree from an incomplete one.
        """
        try:
            inventory = inventory_rules(str(self.root))
        except RuleInventoryError as exc:
            raise RuntimeError(str(exc)) from exc

        canonical_filter = TYPE_TRANSLATION_MAP.get(rule_type, rule_type) if rule_type else None

        rules = []
        for entry in inventory.entries:
            relative_path = entry.relative_path
            rule_name = Path(relative_path).stem
            if Path(relative_path).name == 'README.md':
                continue

            if canonical_filter:
                parent_name = Path(relative_path).parent.name
                path_matches = (
                    parent_name in (canonical_filter, canonical_filter + 's')
                    or f"/{canonical_filter}/" in relative_path
                    or f"/{canonical_filter}s/" in relative_path
                )
            else:
                path_matches = True

            try:
                content = entry.content.decode('utf-8')
            except UnicodeDecodeError as exc:
                if path_matches:
                    rules.append({'_name': rule_name, '_path': relative_path, '_error': f'invalid UTF-8: {exc}'})
                continue

            frontmatter = parse_frontmatter(content)
            if frontmatter is None:
                if path_matches:
                    rules.append({'_name': rule_name, '_path': relative_path, '_error': 'malformed YAML frontmatter'})
                continue
            if not frontmatter:
                if path_matches:
                    rules.append({'_name': rule_name, '_path': relative_path, '_error': 'no frontmatter metadata'})
                continue

            if canonical_filter and frontmatter.get('type') != canonical_filter and not path_matches:
                continue

            frontmatter['_name'] = rule_name
            frontmatter['_path'] = relative_path
            rules.append(frontmatter)
        return rules

    def fitness_landscape(self, bayesian: bool = False) -> list[dict[str, Any]]:
        """Fitness scores for every rule (with the Bayesian posterior when ``bayesian``)."""
        return compute_cells_fitness(workspace=str(self.root), bayesian=bayesian)

    def coverage_report(self, exclude: Optional[str] = None) -> dict[str, Any]:
        """Which workspace files the rules' target_paths cover, overall and per directory."""
        return calculate_coverage(workspace=str(self.root), exclude=[exclude] if exclude else None)

    def grade(self) -> dict[str, Any]:
        """Governance report card; a fixed all-F report when there are no rules."""
        report = calculate_governance_grade(workspace=str(self.root))
        if report is None:
            return {
                "coverage": {"pct": 0.0, "grade": "F"},
                "avg_fitness": {"pct": 0.0, "grade": "F", "score": 0.0},
                "diversity": {"pct": 0.0, "grade": "F"},
                "staleness": {"pct": 0.0, "grade": "F"},
                "wall_integrity": {"pct": 0.0, "grade": "F"},
                "tiers": {},
                "overall": {"pct": 0.0, "grade": "F"},
                "status": "PASS",
                "note": "No cells found to grade",
            }
        return report

    def scan(self, files: Optional[list[str]] = None) -> list[dict[str, Any]]:
        """Rules whose target_paths match ``files`` (default: the files git reports changed)."""
        changed = files if files is not None else _get_changed_files(str(self.root))
        return match_cells_to_changes(str(self.root), changed)

    def entropy(self) -> dict[str, Any]:
        """Rule population and the Shannon entropy (bits) of its type distribution."""
        rules = self.list_rules()
        if not rules:
            return {"population": {"total": 0, "active": 0, "dormant": 0}, "type_entropy": 0.0}
        type_counts: dict[str, int] = {}
        for r in rules:
            rt = str(r.get('type', 'unknown'))
            type_counts[rt] = type_counts.get(rt, 0) + 1
        total = len(rules)
        type_entropy = 0.0
        if len(type_counts) > 1:
            type_entropy = -sum((n / total) * math.log2(n / total) for n in type_counts.values() if n > 0)
        return {
            "population": {"total": total},
            "type_entropy": {"value": round(type_entropy, 4), "distribution": type_counts},
        }
