"""Core Governance API."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import re
import warnings
from pathlib import Path
from typing import Any, Optional

from aegis_core.cell_inventory import CellInventoryError, inventory_cells
from aegis_core.yaml import parse_frontmatter
from aegis_core.telemetry import EventConflictError, StaleGenerationError
from aegis_core.workspace import Workspace

TYPE_TRANSLATION_MAP: dict[str, str] = {
    "safety-guard": "wall",
    "learned-trap": "vacuole",
    "agent-persona": "chloroplast",
    "escalation-boundary": "membrane",
    "contract-bridge": "plasmodesmata",
    "wall": "wall",
    "vacuole": "vacuole",
    "chloroplast": "chloroplast",
    "membrane": "membrane",
    "plasmodesmata": "plasmodesmata",
}

__all__ = ["Governance", "TYPE_TRANSLATION_MAP"]

VALID_SOURCES = ('ci', 'manual', 'mcp', 'session')


class Governance:
    """Soma governance interface.
    
    Usage:
        from aegis_sdk import Governance
        gov = Governance(project_root='.')
        
        landscape = gov.fitness_landscape(bayesian=True)
        coverage = gov.coverage_report()
        grade = gov.grade()
    """
    
    def __init__(self, project_root: str | Path | os.PathLike[str] | Workspace = '.') -> None:
        self.workspace: Workspace = (
            project_root if isinstance(project_root, Workspace) else Workspace.resolve(project_root)
        )
        self.root: Path = self.workspace.root
        self.cells_dir: Path = self.workspace.cells_dir
        self.metrics_dir: Path = self.workspace.metrics_dir
    
    # === Cell & Rule Management ===
    
    def list_cells(self, cell_type: Optional[str] = None) -> list[dict[str, Any]]:
        """List immune cells, optionally filtered by cell_type or porcelain alias.

        Invalid cell contents remain visible as diagnostic records. Unsafe or
        unreadable inventory trees fail closed because callers cannot safely
        distinguish an empty tree from an incomplete one.
        """
        try:
            inventory = inventory_cells(str(self.root))
        except CellInventoryError as exc:
            raise RuntimeError(str(exc)) from exc

        canonical_filter = TYPE_TRANSLATION_MAP.get(cell_type, cell_type) if cell_type else None

        cells = []
        for entry in inventory.entries:
            relative_path = entry.relative_path
            cell_name = Path(relative_path).stem
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
                if not path_matches:
                    continue
                cells.append({
                    '_name': cell_name,
                    '_path': relative_path,
                    '_error': f'invalid UTF-8: {exc}',
                })
                continue

            frontmatter = parse_frontmatter(content)
            if frontmatter is None:
                if not path_matches:
                    continue
                cells.append({
                    '_name': cell_name,
                    '_path': relative_path,
                    '_error': 'malformed YAML frontmatter',
                })
                continue
            if not frontmatter:
                if not path_matches:
                    continue
                cells.append({
                    '_name': cell_name,
                    '_path': relative_path,
                    '_error': 'no frontmatter metadata',
                })
                continue

            if canonical_filter:
                entry_type = frontmatter.get('type')
                type_matches = (entry_type == canonical_filter) or path_matches
                if not type_matches:
                    continue

            frontmatter['_name'] = cell_name
            frontmatter['_path'] = relative_path
            cells.append(frontmatter)
        return cells

    def list_rules(self, rule_type: Optional[str] = None) -> list[dict[str, Any]]:
        """List active rules (porcelain alias for list_cells)."""
        return self.list_cells(cell_type=rule_type)

    def record_outcome(
        self,
        rule_id: str,
        success: bool,
        metric: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Record an empirical rule outcome (tp/fp) in-process via atomic evidence telemetry.
        
        Underlying data updates Wilson confidence scores and Bayesian fitness.
        """
        # I-03: Validate rule_id against active inventory (advisory warning)
        try:
            inventory = inventory_cells(str(self.root))
            known_cells = {
                Path(entry.relative_path).stem
                for entry in inventory.entries
                if Path(entry.relative_path).name != 'README.md'
            }
            if known_cells and rule_id not in known_cells:
                warnings.warn(f"Cell '{rule_id}' not found in active inventory", UserWarning, stacklevel=2)
        except Exception:
            pass

        if isinstance(success, str):
            norm = success.strip().lower()
            if norm in ("tp", "pass", "true", "1", "success"):
                signal_type = "tp"
            elif norm in ("fp", "fail", "false", "0", "failure"):
                signal_type = "fp"
            else:
                raise ValueError(f"Invalid outcome string: {success!r}")
        elif isinstance(success, (bool, int)):
            signal_type = "tp" if bool(success) else "fp"
        else:
            raise TypeError(f"success must be a bool or string, got {type(success).__name__}")

        merged_metric = dict(metric or {})
        session_id = kwargs.pop("session_id", None)
        source = kwargs.pop("source", "manual")
        principal = kwargs.pop("principal", "unknown")
        idempotency_scope = kwargs.pop("idempotency_scope", None)
        if idempotency_scope is None:
            idempotency_scope = session_id if session_id else "global"
        idempotency_key = kwargs.pop("idempotency_key", "")
        expected_generation = kwargs.pop("expected_generation", None)

        if source not in VALID_SOURCES:
            raise ValueError(f"Invalid telemetry source '{source}'. Must be one of: {', '.join(VALID_SOURCES)}")
        merged_metric.update(kwargs)
        if session_id:
            merged_metric["session_id"] = session_id
        try:
            from aegis_core.telemetry import append_signal
            return append_signal(
                workspace=str(self.root),
                cell_name=rule_id,
                signal_type=signal_type,
                source=source,
                metadata={"metric": merged_metric} if merged_metric else {},
                principal=principal,
                idempotency_scope=idempotency_scope,
                idempotency_key=idempotency_key,
                expected_generation=expected_generation,
            )
        except (EventConflictError, StaleGenerationError, ValueError):
            raise
        except Exception:
            raw_output = self.signal(rule_id, signal_type, metric=merged_metric)
            return {
                "cell": rule_id,
                "signal": signal_type,
                "source": source,
                "status": "fallback_recorded",
                "raw": str(raw_output),
            }
    
    def create_cell(
        self,
        hypothesis: str,
        type: str = 'vacuole',
        target_paths: Optional[list[str]] = None,
        minimum_mode: str = 'breeze',
        tags: Optional[list[str]] = None,
        cell_id: Optional[str] = None,
    ) -> dict[str, Any] | str:
        """Create a new immune cell."""
        from aegis_core.lifecycle import create_cell as core_create_cell
        raw_slug = cell_id or hypothesis[:40]
        safe_slug = re.sub(r'[^a-zA-Z0-9_.-]', '-', raw_slug).strip('-')
        canonical_type = TYPE_TRANSLATION_MAP.get(type, type)
        created_path = core_create_cell(
            cell_type=canonical_type,
            hypothesis=hypothesis,
            minimum_mode=minimum_mode,
            tags=tags,
            target_paths=target_paths,
            id_override=safe_slug,
            workspace=self.root,
        )
        return str(created_path)

    def create_rule(
        self,
        hypothesis: str,
        type: str = 'vacuole',
        target_paths: Optional[list[str]] = None,
        minimum_mode: str = 'breeze',
        tags: Optional[list[str]] = None,
        cell_id: Optional[str] = None,
        rule_id: Optional[str] = None,
    ) -> dict[str, Any] | str:
        """Create a new immune rule (porcelain alias for create_cell)."""
        return self.create_cell(
            hypothesis=hypothesis,
            type=type,
            target_paths=target_paths,
            minimum_mode=minimum_mode,
            tags=tags,
            cell_id=rule_id or cell_id,
        )

    def parse_cell_file(self, filepath: str) -> tuple[dict, str]:
        """Parse a cell markdown file into (frontmatter_dict, body_text)."""
        from aegis_sdk.cells import parse_cell_file
        return parse_cell_file(filepath)
    
    def create_cell_from_description(
        self, description: str, domain: Optional[str] = None, cell_type: Optional[str] = None,
    ) -> dict[str, Any] | str:
        """Create a cell using natural language via configured inference provider."""
        from aegis_core.lifecycle import create_cell_from_description as core_create_cell_nl
        canonical_type = TYPE_TRANSLATION_MAP.get(cell_type, cell_type) if cell_type else None
        return core_create_cell_nl(
            description=description,
            domain_hint=domain,
            cell_type=canonical_type,
            workspace=str(self.root),
        )
    
    def signal(
        self, cell_name: str, signal_type: str, metric: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any] | str:
        """Send a fitness signal to a cell in-process."""
        from aegis_core.telemetry import append_signal
        return append_signal(
            workspace=str(self.root),
            cell_name=cell_name,
            signal_type=signal_type,
            source="manual",
            metadata={"metric": metric} if metric else None,
        )
    
    # === Analysis ===
    
    def fitness_landscape(self, bayesian: bool = False) -> list[dict[str, Any]]:
        """Get fitness scores for all cells."""
        from aegis_core.lifecycle import compute_cells_fitness
        return compute_cells_fitness(workspace=str(self.root), bayesian=bayesian)

    def rule_fitness(self, bayesian: bool = False) -> list[dict[str, Any]]:
        """Get fitness scores for all rules (porcelain alias for fitness_landscape)."""
        return self.fitness_landscape(bayesian=bayesian)
    
    def coverage_report(self, exclude: Optional[str] = None) -> dict[str, Any]:
        """Get cell coverage report."""
        from aegis_core.telemetry import calculate_coverage
        return calculate_coverage(workspace=str(self.root), exclude=[exclude] if exclude else None)
    
    def grade(self) -> dict[str, Any]:
        """Get governance report card."""
        from aegis_core.telemetry import calculate_immune_grade
        report = calculate_immune_grade(workspace=str(self.root))
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
    
    def quorum(self, threshold: int = 3, changed_files: Optional[list[str]] = None) -> dict[str, Any]:
        """Check for quorum (systemic multi-cell triggers)."""
        from aegis_core.telemetry import evaluate_quorum, _get_changed_files
        files = changed_files if changed_files is not None else _get_changed_files(str(self.root))
        return evaluate_quorum(cells_dir=self.cells_dir, changed_files=files, threshold=threshold)
    
    def scan(self, files: Optional[list[str]] = None) -> list[dict[str, Any]]:
        """Scan current diff against cells."""
        from aegis_core.telemetry import match_cells_to_changes, _get_changed_files
        changed = files if files is not None else _get_changed_files(str(self.root))
        return match_cells_to_changes(str(self.root), changed)

    def entropy(self) -> dict[str, Any]:
        """Compute immune entropy across all cells."""
        import math
        cells = self.list_cells()
        if not cells:
            return {"population": {"total": 0, "active": 0, "dormant": 0}, "type_entropy": 0.0}
        type_counts: dict[str, int] = {}
        for c in cells:
            ct = str(c.get('type', 'unknown'))
            type_counts[ct] = type_counts.get(ct, 0) + 1
        total = len(cells)
        type_entropy = 0.0
        if total > 0 and len(type_counts) > 1:
            type_probs = [n / total for n in type_counts.values()]
            type_entropy = -sum(p * math.log2(p) for p in type_probs if p > 0)
        return {
            "population": {"total": total},
            "type_entropy": {"value": round(type_entropy, 4), "distribution": type_counts},
        }
