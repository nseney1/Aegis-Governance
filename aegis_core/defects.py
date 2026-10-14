"""aegis_core.defects — Defect analysis, escaped defect tracking, and cell expiry.

Consolidates:
- Hot zone analysis and diagnostics (formerly aegis_sdk.hot_zones & enzymes/diagnose_hot_zones.py)
- Escaped defect detection and prevention rate tracking (formerly enzymes/cell_escaped_defects.py)
- Cell lifecycle expiry enforcement and pruning (formerly enzymes/cell_expiry.py)
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import fnmatch
import glob
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from aegis_core.workspace import Workspace, resolve_workspace
from aegis_core.yaml import parse_frontmatter, _get_body, dump_frontmatter

# ── Hot Zone Analysis ──────────────────────────────────────────────────────


@dataclass
class BoostConfig:
    """Tunable parameters for hot zone scoring."""
    file_heat_threshold: int = 2
    pattern_heat_threshold: int = 3
    release_window: int = 10
    min_outcomes_for_boost: int = 3
    max_file_boost: float = 0.5
    max_pattern_boost: float = 0.3


@dataclass
class HotZoneReport:
    """Computed boost data from the bug registry."""
    file_heat: dict[str, int] = field(default_factory=dict)
    pattern_heat: dict[str, int] = field(default_factory=dict)
    active_file_zones: list[str] = field(default_factory=list)
    active_pattern_zones: list[str] = field(default_factory=list)
    config: BoostConfig = field(default_factory=BoostConfig)
    total_bugs_analyzed: int = 0


def load_config(registry: dict) -> BoostConfig:
    """Extract boost config from registry, falling back to defaults."""
    raw = registry.get("boost_config", {})
    return BoostConfig(
        file_heat_threshold=raw.get("file_heat_threshold", 2),
        pattern_heat_threshold=raw.get("pattern_heat_threshold", 3),
        release_window=raw.get("release_window", 10),
        min_outcomes_for_boost=raw.get("min_outcomes_for_boost", 3),
        max_file_boost=raw.get("max_file_boost", 0.5),
        max_pattern_boost=raw.get("max_pattern_boost", 0.3),
    )


def compute_hot_zones(registry: dict) -> HotZoneReport:
    """Pure function: registry dict -> HotZoneReport."""
    config = load_config(registry)
    bugs = registry.get("bugs", [])

    file_heat: dict[str, int] = {}
    for bug in bugs:
        for f in bug.get("affected_files", []):
            file_heat[f] = file_heat.get(f, 0) + 1

    pattern_heat: dict[str, int] = {}
    for bug in bugs:
        cat = bug.get("root_cause", "")
        if cat:
            pattern_heat[cat] = pattern_heat.get(cat, 0) + 1

    active_files = sorted(
        [f for f, count in file_heat.items() if count >= config.file_heat_threshold],
        key=lambda f: -file_heat[f],
    )
    active_patterns = sorted(
        [p for p, count in pattern_heat.items() if count >= config.pattern_heat_threshold],
        key=lambda p: -pattern_heat[p],
    )

    return HotZoneReport(
        file_heat=file_heat,
        pattern_heat=pattern_heat,
        active_file_zones=active_files,
        active_pattern_zones=active_patterns,
        config=config,
        total_bugs_analyzed=len(bugs),
    )


def compute_cell_boost(
    cell: dict[str, Any],
    report: HotZoneReport,
    outcome_count: int = 0,
) -> float:
    """Compute the fitness boost multiplier for a single cell."""
    if outcome_count < report.config.min_outcomes_for_boost:
        return 0.0

    file_boost = 0.0
    pattern_boost = 0.0

    target_paths = cell.get("target_paths", [])
    if target_paths and report.active_file_zones:
        for hot_file in report.active_file_zones:
            for pattern in target_paths:
                if fnmatch.fnmatch(hot_file, pattern):
                    heat = report.file_heat.get(hot_file, 0)
                    file_boost += heat * 0.1
                    break

    cell_tags = set(cell.get("tags", []))
    tag_to_category = {
        "data_path": "path_error",
        "path": "path_error",
        "schema": "schema_drift",
        "data_model": "schema_drift",
        "silent": "silent_failure",
        "error_handling": "silent_failure",
        "mapping": "mapping_error",
        "type_coercion": "mapping_error",
        "dead_code": "dead_code",
        "unused": "dead_code",
    }
    for tag in cell_tags:
        category = tag_to_category.get(tag, tag)
        if category in report.active_pattern_zones:
            heat = report.pattern_heat.get(category, 0)
            pattern_boost += heat * 0.1

    file_boost = min(file_boost, report.config.max_file_boost)
    pattern_boost = min(pattern_boost, report.config.max_pattern_boost)

    return file_boost + pattern_boost


def load_registry(workspace: Workspace | Path | str) -> dict | None:
    """Load BUG_REGISTRY.json, returning None if missing."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    path = ws.root / "docs" / "project" / "BUG_REGISTRY.json"
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_report_from_workspace(workspace: Workspace | Path | str) -> HotZoneReport | None:
    """Convenience: load registry from disk and compute report."""
    registry = load_registry(workspace)
    if registry is None:
        return None
    try:
        return compute_hot_zones(registry)
    except Exception:
        return None


def proximity_alerts(report: HotZoneReport) -> list[str]:
    """Report how close each category/file is to activating."""
    alerts = []
    config = report.config

    for cat, count in sorted(report.pattern_heat.items(), key=lambda x: -x[1]):
        remaining = config.pattern_heat_threshold - count
        if remaining <= 0:
            alerts.append(f"  🔥 {cat}: {count}/{config.pattern_heat_threshold} — ACTIVE")
        elif remaining <= 2:
            alerts.append(
                f"  ⚠️  {cat}: {count}/{config.pattern_heat_threshold} "
                f"— {remaining} more bug(s) to activate"
            )
        else:
            alerts.append(f"  ·  {cat}: {count}/{config.pattern_heat_threshold}")

    for f, count in sorted(report.file_heat.items(), key=lambda x: -x[1]):
        remaining = config.file_heat_threshold - count
        if remaining <= 0:
            alerts.append(f"  🔥 {f}: {count}/{config.file_heat_threshold} — ACTIVE")
        elif remaining == 1:
            alerts.append(
                f"  ⚠️  {f}: {count}/{config.file_heat_threshold} "
                f"— 1 more bug to activate"
            )

    return alerts


def threshold_sanity(report: HotZoneReport) -> list[str]:
    """Check if thresholds seem miscalibrated."""
    warnings = []
    total = report.total_bugs_analyzed
    config = report.config
    active_count = len(report.active_file_zones) + len(report.active_pattern_zones)

    if total < 10:
        warnings.append(
            f"ℹ️  Insufficient data ({total} bugs). "
            f"Thresholds untested — revisit after 10+ bugs."
        )
        return warnings

    if total >= 20 and active_count == 0:
        warnings.append(
            f"⚠️  {total} bugs registered but zero hot zones activated. "
            f"Consider lowering thresholds "
            f"(file: {config.file_heat_threshold}, pattern: {config.pattern_heat_threshold})."
        )

    total_files = len(report.file_heat)
    if total_files > 0 and len(report.active_file_zones) > total_files / 3:
        warnings.append(
            f"⚠️  {len(report.active_file_zones)}/{total_files} files are hot zones. "
            f"Thresholds may be too low — consider raising file_heat_threshold "
            f"from {config.file_heat_threshold}."
        )

    total_patterns = len(report.pattern_heat)
    if total_patterns > 0 and len(report.active_pattern_zones) > total_patterns / 2:
        warnings.append(
            f"⚠️  {len(report.active_pattern_zones)}/{total_patterns} categories "
            f"are hot zones. Consider raising pattern_heat_threshold "
            f"from {config.pattern_heat_threshold}."
        )

    return warnings


def run_diagnostic(workspace: str) -> dict:
    """Run full diagnostic and return structured results."""
    registry = load_registry(workspace)
    if registry is None:
        return {"error": "BUG_REGISTRY.json not found"}

    report = compute_hot_zones(registry)

    return {
        "total_bugs": report.total_bugs_analyzed,
        "proximity": proximity_alerts(report),
        "sanity": threshold_sanity(report),
        "active_files": report.active_file_zones,
        "active_patterns": report.active_pattern_zones,
        "file_heat": report.file_heat,
        "pattern_heat": report.pattern_heat,
        "config": {
            "file_heat_threshold": report.config.file_heat_threshold,
            "pattern_heat_threshold": report.config.pattern_heat_threshold,
            "max_file_boost": report.config.max_file_boost,
            "max_pattern_boost": report.config.max_pattern_boost,
        },
    }




# ── Escaped Defects Tracking ──────────────────────────────────────────────


def match_glob(filepath: str, pattern: str) -> bool:
    """Match a filepath against a glob pattern, supporting ** globstar."""
    regex = pattern.replace(".", r"\.")
    regex = regex.replace("?", "[^/]")
    regex = regex.replace("**/", "(?:.+/)?")
    regex = regex.replace("**", ".*")
    regex = regex.replace("*", "[^/]*")
    return bool(re.match(regex + "$", filepath))


def load_cells(cells_dir: str) -> list[dict]:
    """Load all cells with their metadata."""
    cells = []
    for cell_file in glob.glob(os.path.join(cells_dir, "**", "*.md"), recursive=True):
        if os.path.basename(cell_file) == "README.md":
            continue
        try:
            with open(cell_file, "r", encoding="utf-8-sig") as f:
                raw = f.read()
            fm = parse_frontmatter(raw)
            if not fm or not isinstance(fm, dict):
                continue
            body = _get_body(raw)
            fm["_path"] = cell_file
            fm["_name"] = os.path.splitext(os.path.basename(cell_file))[0]
            fm["_body"] = body.strip()
            fm["_raw"] = raw
            cells.append(fm)
        except Exception:
            pass
    return cells


def find_covering_cells(cells: list[dict], files: list[str]) -> list[dict]:
    """Find cells whose target_paths match the given files."""
    covering = []
    for cell in cells:
        target_paths = cell.get("target_paths", [])
        if isinstance(target_paths, str):
            target_paths = [target_paths]
        matched_files = []
        for f in files:
            for pattern in target_paths:
                if match_glob(f, pattern):
                    matched_files.append(f)
                    break
        if matched_files:
            covering.append({
                "cell": cell,
                "matched_files": matched_files,
            })
    return covering


def record_escaped_defect(
    cell: dict,
    event_type: str,
    files: list[str],
    severity: str,
    workspace: Workspace | Path | str,
) -> dict:
    """Record an escaped defect against a cell."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    metrics_dir = ws.metrics_dir
    metrics_dir.mkdir(parents=True, exist_ok=True)

    log_path = metrics_dir / "escaped_defects.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "cell": cell.get("_name") or cell.get("name", ""),
        "cell_type": cell.get("type", ""),
        "enforcement": cell.get("enforcement", "advisory"),
        "event": event_type,
        "files": files,
        "severity": severity,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    return entry


def update_cell_escaped_rate(cell: dict, workspace: Workspace | Path | str) -> float:
    """Recalculate a cell's escaped_defect_rate from the log."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    metrics_dir = ws.metrics_dir
    log_path = metrics_dir / "escaped_defects.jsonl"
    if not log_path.is_file():
        return 0.0

    escaped = 0
    cell_name = cell.get("_name") or cell.get("name", "")
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if entry.get("cell") == cell_name:
                    escaped += 1
            except Exception:
                continue

    tp = cell.get("fitness", {}).get("true_positives", 0)
    total = escaped + tp
    if total == 0:
        return 0.0

    return round(escaped / total, 4)


def compute_enhanced_fitness(cell: dict, escaped_defect_rate: float) -> float:
    """Compute fitness with independent outcome signal."""
    tier_weights = {"advisory": 1.0, "mechanical": 1.2, "gate": 1.5}

    tp = cell.get("fitness", {}).get("true_positives", 0)
    fp = cell.get("fitness", {}).get("false_positives", 0)

    a = tp + 0.5
    b = fp + 0.5
    bayesian_mean = a / (a + b)

    enforcement = cell.get("enforcement", "advisory")
    tier_weight = tier_weights.get(enforcement, 1.0)

    enhanced = bayesian_mean * (1 - escaped_defect_rate) * tier_weight
    return round(enhanced, 4)


def scan_git_for_defects(workspace: str, since: str) -> list[dict]:
    """Scan git history for reverted commits, fix-after-fix patterns."""
    git_args = ["git", "log", "--format=%H %s", f"--since={since}"]
    result = subprocess.run(git_args, capture_output=True, text=True, cwd=workspace)

    defect_commits = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        sha, *msg_parts = line.split(" ")
        msg = " ".join(msg_parts).lower()

        if any(kw in msg for kw in ["revert", "hotfix", "fix:", "bugfix", "patch:", "workaround"]):
            try:
                diff_result = subprocess.run(
                    ["git", "diff", "--name-only", f"{sha}~1", sha],
                    capture_output=True, text=True, cwd=workspace
                )
                if diff_result.returncode != 0:
                    continue
                files = [f for f in diff_result.stdout.strip().split("\n") if f]
            except Exception:
                continue
            if files:
                defect_commits.append({
                    "sha": sha[:8],
                    "message": " ".join(msg_parts),
                    "files": files,
                    "severity": "high" if "revert" in msg else "medium",
                })

    return defect_commits


def generate_report(cells: list[dict], workspace: str) -> tuple[list[dict], int]:
    """Generate escaped defects report."""
    metrics_dir = os.path.join(workspace, ".soma", "metrics")
    log_path = os.path.join(metrics_dir, "escaped_defects.jsonl")

    cell_escapes: dict[str, int] = {}
    total_escapes = 0
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    name = entry.get("cell", "")
                    cell_escapes[name] = cell_escapes.get(name, 0) + 1
                    total_escapes += 1
                except Exception:
                    continue

    report = []
    for cell in cells:
        name = cell.get("_name") or cell.get("name", "")
        escapes = cell_escapes.get(name, 0)
        tp = cell.get("fitness", {}).get("true_positives", 0)
        fp = cell.get("fitness", {}).get("false_positives", 0)
        enforcement = cell.get("enforcement", "advisory")

        escaped_rate = update_cell_escaped_rate(cell, workspace)
        enhanced_fitness = compute_enhanced_fitness(cell, escaped_rate)
        prevention_rate = 1 - escaped_rate

        report.append({
            "cell": name,
            "type": cell.get("type", ""),
            "enforcement": enforcement,
            "tp": tp,
            "fp": fp,
            "escaped": escapes,
            "escaped_defect_rate": escaped_rate,
            "defect_prevention_rate": round(prevention_rate, 4),
            "enhanced_fitness": enhanced_fitness,
        })

    return report, total_escapes




# ── Cell Expiry Enforcement ────────────────────────────────────────────────


def audit_expiry(workspace: Workspace | Path | str, session_count: Optional[int] = None) -> list[dict]:
    """Audit all cells for expiry violations."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells_dir = ws.cells_dir
    if not cells_dir.is_dir():
        return []

    results = []
    now = datetime.now()

    for md_file in sorted(glob.glob(os.path.join(str(cells_dir), "**", "*.md"), recursive=True)):
        if os.path.basename(md_file) == "README.md":
            continue

        try:
            with open(md_file, "r", encoding="utf-8-sig") as f:
                content = f.read()
            metadata = parse_frontmatter(content)
            if not metadata or not isinstance(metadata, dict):
                continue
        except Exception:
            continue

        cell_id = metadata.get("id", os.path.basename(md_file))
        cell_type = metadata.get("type", "unknown")
        is_wall = cell_type == "wall"

        if metadata.get("expired_at"):
            results.append({
                "cell_id": cell_id,
                "filepath": md_file,
                "status": "ALREADY_EXPIRED",
                "reason": "previously_pruned",
                "details": f"Expired at {metadata['expired_at']}",
            })
            continue

        expired = False
        reason = None
        details = None

        expiry_days = metadata.get("expiry_days")
        created_val = metadata.get("created")
        if expiry_days and created_val:
            try:
                expiry_days = int(expiry_days)
                if isinstance(created_val, datetime):
                    created_date = created_val
                elif hasattr(created_val, "isoformat"):
                    created_date = datetime.combine(created_val, datetime.min.time())
                else:
                    created_str = str(created_val).replace("Z", "+00:00")
                    try:
                        created_date = datetime.fromisoformat(created_str)
                        if created_date.tzinfo:
                            created_date = created_date.replace(tzinfo=None)
                    except ValueError:
                        fmt = "%Y-%m-%d"
                        created_date = datetime.strptime(created_str[:10], fmt)
                days_elapsed = (now - created_date).days
                if days_elapsed > expiry_days:
                    expired = True
                    reason = "expiry_days"
                    details = f"{days_elapsed} days elapsed (limit: {expiry_days})"
            except Exception:
                pass

        if not expired and session_count is not None:
            expiry_sessions = metadata.get("expiry_sessions")
            if expiry_sessions:
                try:
                    expiry_sessions = int(expiry_sessions)
                    if session_count > expiry_sessions:
                        expired = True
                        reason = "expiry_sessions"
                        details = f"{session_count} sessions elapsed (limit: {expiry_sessions})"
                except (ValueError, TypeError):
                    pass

        if expired:
            status = "EXPIRY_WARNING" if is_wall else "EXPIRED"
        else:
            status = "OK"

        results.append({
            "cell_id": cell_id,
            "filepath": md_file,
            "status": status,
            "reason": reason,
            "details": details,
        })

    return results


def prune_expired(workspace: Workspace | Path | str, audit_results: list[dict]) -> int:
    """Add expired_at marker to expired cells."""
    pruned = 0
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    for result in audit_results:
        if result["status"] != "EXPIRED":
            continue

        filepath = result["filepath"]
        try:
            with open(filepath, "r", encoding="utf-8-sig") as f:
                content = f.read()
            metadata = parse_frontmatter(content) or {}
            body = _get_body(content)
        except Exception:
            continue

        metadata["expired_at"] = now_str
        metadata["expired_reason"] = result.get("reason", "unknown")

        new_fm = dump_frontmatter(metadata)
        new_content = "---\n" + new_fm + "---\n" + body + ("\n" if not body.endswith("\n") else "")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)

        pruned += 1

    return pruned


__all__ = [
    "BoostConfig",
    "HotZoneReport",
    "load_config",
    "compute_hot_zones",
    "compute_cell_boost",
    "load_registry",
    "load_report_from_workspace",
    "proximity_alerts",
    "threshold_sanity",
    "run_diagnostic",
    "match_glob",
    "load_cells",
    "find_covering_cells",
    "record_escaped_defect",
    "update_cell_escaped_rate",
    "compute_enhanced_fitness",
    "scan_git_for_defects",
    "generate_report",
    "audit_expiry",
    "prune_expired",
]
