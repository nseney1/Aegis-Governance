"""aegis_core.sync — Protocol escalation, liveness sentinels, team sync, HGT ribosome, and hooks.

Consolidates:
- Subagent liveness & deadlock sentinel (formerly enzymes/liveness_sentinel.py)
- Protocol escalation recommender & last-gasp sentinel (formerly enzymes/escalation_sentinel.py)
- Team cell & metrics synchronization (formerly enzymes/team_sync.py)
- Horizontal Gene Transfer ribosome translation (formerly enzymes/hgt_ribosome.py)
- Periodic governance sweep (formerly enzymes/immune_sweep.py)
- Post-session transcript fitness and evidence hook (formerly enzymes/post_session_hook.py)
"""
from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import glob
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

from aegis_core.workspace import Workspace, as_workspace, resolve_workspace
from aegis_core.yaml import parse_frontmatter, _get_body, dump_frontmatter


# ── Sentinels & Protocol Escalation Re-exports ─────────────────────────────
from aegis_core.sentinels import (
    HIGH_PATTERNS,
    MEDIUM_PATTERNS,
    LOW_PATTERNS,
    TEST_PATTERNS,
    PROTOCOL_RANKS,
    check_liveness,
    classify_file,
    is_test_file,
    gather_files,
    get_diff_size,
    detect_branch_ops,
    check_membrane_overrides,
    recommend_protocol,
    set_review_mode,
    write_frontmatter,
    run_last_gasp,
)


# ── Team Sync ──────────────────────────────────────────────────────────────


def load_soma_config(repo_dir: Path | str | Workspace) -> dict[str, str]:
    ws = as_workspace(repo_dir)
    conf_path = ws.root / "soma.conf"
    cfg = {}
    if conf_path.is_file():
        with open(conf_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def run_push(repo_dir: Path | str | Workspace, team_repo: Path | str, org_repo: Path | str | None, member_id: str) -> int:
    clean_id = re.sub(r"[^a-zA-Z0-9._-]", "_", str(member_id)).lstrip("-")
    if not clean_id or ".." in str(member_id):
        raise ValueError(f"Invalid member_id: {member_id}")

    ws = as_workspace(repo_dir)
    root_path = ws.root
    team_repo = Path(team_repo)
    org_repo = Path(org_repo) if org_repo else None

    print(f"Syncing local promoted cells to team repo ({team_repo})...")
    promoted_dir = team_repo / "cells" / "promoted"
    promoted_dir.mkdir(parents=True, exist_ok=True)
    snap_dir = team_repo / "snapshots" / clean_id
    snap_dir.mkdir(parents=True, exist_ok=True)

    cells_dir = ws.cells_dir

    try:
        from aegis_core.lifecycle import compute_cells_fitness
        data = compute_cells_fitness(workspace=ws)
        for item in data:
            if item.get("score") is not None and item.get("score") > 0.85:
                cell_name = item["cell"]
                src = cells_dir / cell_name
                if not src.is_file():
                    for match in cells_dir.rglob(cell_name):
                        if match.is_file():
                            src = match
                            break
                if src.is_file():
                    shutil.copy2(str(src), str(promoted_dir / cell_name))
                    print(f"Promoted: {cell_name}")
                    if org_repo:
                        org_promoted_dir = org_repo / "cells" / "promoted"
                        org_promoted_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(src), str(org_promoted_dir / cell_name))
    except Exception as e:
        print(f"Error syncing cells: {e}", file=sys.stderr)

    print("Syncing metrics snapshot...")
    try:
        from aegis_core.telemetry import take_snapshot
        take_snapshot(save=True, workspace=ws)
    except Exception as e:
        print(f"Error syncing metrics snapshot: {e}", file=sys.stderr)

    metrics_repo = root_path / "docs" / "snapshots"
    snapshots = sorted(metrics_repo.glob("*.json"), key=os.path.getmtime, reverse=True)
    if snapshots:
        shutil.copy2(str(snapshots[0]), str(snap_dir / snapshots[0].name))

    if (team_repo / ".git").exists():
        subprocess.run(["git", "add", "--", "cells/promoted", f"snapshots/{clean_id}"], cwd=str(team_repo))
        subprocess.run(
            ["git", "commit", "-m", f"chore(sync): update promoted cells and metrics for {clean_id}"],
            cwd=str(team_repo),
            capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=str(team_repo), capture_output=True)

    if org_repo and (org_repo / ".git").exists():
        subprocess.run(["git", "add", "--", "cells/promoted"], cwd=str(org_repo))
        subprocess.run(
            ["git", "commit", "-m", f"chore(sync): update org promoted cells from {member_id}"],
            cwd=str(org_repo),
            capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=str(org_repo), capture_output=True)

    print("Push complete.")
    return 0


def run_pull(repo_dir: Path | str | Workspace, team_repo: Path | str, org_repo: Path | str | None) -> int:
    ws = as_workspace(repo_dir)
    team_repo = Path(team_repo)
    org_repo = Path(org_repo) if org_repo else None

    print(f"Pulling promoted cells from team repo ({team_repo})...")
    if (team_repo / ".git").exists():
        subprocess.run(["git", "pull", "--rebase"], cwd=str(team_repo), capture_output=True)

    if org_repo and (org_repo / ".git").exists():
        print(f"Pulling from org repo ({org_repo})...")
        subprocess.run(["git", "pull", "--rebase"], cwd=str(org_repo), capture_output=True)

    local_cells = ws.cells_dir
    ribosomes_dir = local_cells / "ribosomes"
    ribosomes_dir.mkdir(parents=True, exist_ok=True)

    team_promoted = team_repo / "cells" / "promoted"
    if team_promoted.is_dir():
        for f in team_promoted.glob("*.md"):
            dest = ribosomes_dir / f.name
            if not dest.exists():
                shutil.copy2(str(f), str(dest))
                print(f"Imported from team: {f.name} -> ribosomes/")

    if org_repo:
        org_promoted = org_repo / "cells" / "promoted"
        if org_promoted.is_dir():
            for f in org_promoted.glob("*.md"):
                dest = ribosomes_dir / f.name
                if not dest.exists():
                    shutil.copy2(str(f), str(dest))
                    print(f"Imported from org: {f.name} -> ribosomes/")

    print("Pull complete.")
    return 0


def run_status(repo_dir: Path, team_repo: Path, org_repo: Path | None) -> int:
    print("=== Team Sync Status ===")
    print(f"Local repo:  {repo_dir}")
    print(f"Team repo:   {team_repo} (exists: {team_repo.is_dir()})")
    if org_repo:
        print(f"Org repo:    {org_repo} (exists: {org_repo.is_dir()})")

    team_promoted = team_repo / "cells" / "promoted"
    team_count = len(list(team_promoted.glob("*.md"))) if team_promoted.is_dir() else 0
    print(f"Team promoted cells: {team_count}")

    if org_repo:
        org_promoted = org_repo / "cells" / "promoted"
        org_count = len(list(org_promoted.glob("*.md"))) if org_promoted.is_dir() else 0
        print(f"Org promoted cells:  {org_count}")

    return 0



# ── Horizontal Gene Transfer (Ribosome) ────────────────────────────────────


def prompt_llm_translation(cell_content: str, mock: bool = False) -> str:
    """Translate domain-specific strategy into universal engineering law."""
    if mock:
        if "draft all combat-capable pawns" in cell_content:
            return """# Resource Consolidation (HGT)
- When a catastrophic event is detected (e.g., massive production outage), immediately consolidate resources to a defensible position.
- Halt all exploratory or non-essential feature work until the primary threat is neutralized.
- Do not engage in risky ad-hoc fixes unless core stability is breached."""
        else:
            return "# Generalized Strategy\n- Apply caution and verify inputs."

    return "# Generalized Strategy\n- Apply caution and verify inputs."



# ── Immune Sweep ───────────────────────────────────────────────────────────


def resolve_home() -> Path:
    home_str = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if home_str:
        return Path(home_str)
    return Path.home()


def run_sweep(active_only: bool = False, soma_data_dir: Path | None = None) -> int:
    """Run periodic governance sweep."""
    from collections import Counter
    import time
    try:
        from aegis_core.sweep_session import scan_transcript, to_session_metrics
    except ImportError:
        scan_transcript = None
        to_session_metrics = None


    resolved_home = resolve_home()

    if soma_data_dir is None:
        env_data = os.environ.get("SOMA_DATA_DIR")
        soma_data_dir = Path(env_data) if env_data else resolved_home / ".gemini" / "antigravity"

    governance_dir = soma_data_dir / "scratch" / "ai-conversation-logs" / "governance"
    brain_dir = soma_data_dir / "brain"
    metrics_dir = governance_dir / "session_metrics"
    sweep_log = governance_dir / "sweep_log.jsonl"
    proposals = governance_dir / "pending_proposals.md"
    audit_log = governance_dir / "auto_applied_log.jsonl"
    gate_log = governance_dir / "gate_events.jsonl"

    metrics_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    sessions_scanned = 0
    metrics_generated = 0
    warnings_tallied = 0
    active_flagged = 0

    print(f"🔄 Governance Sweep — {timestamp}\n")

    # ── Check 1: Unreviewed Sessions ──────────────────────────────────────────
    if not active_only:
        print("📋 Check 1: Scanning for unreviewed sessions (>100 steps)...")
        if brain_dir.is_dir():
            for child in brain_dir.iterdir():
                if not child.is_dir():
                    continue

                session_id = child.name
                short_id = session_id[:8]
                transcript = child / ".system_generated" / "logs" / "transcript.jsonl"
                metrics_file = metrics_dir / f"{short_id}.json"

                if not transcript.is_file():
                    continue
                if metrics_file.is_file():
                    continue

                try:
                    with open(transcript, "r", encoding="utf-8", errors="replace") as fh:
                        step_count = sum(1 for _ in fh)
                except OSError:
                    step_count = 0

                if step_count > 100:
                    print(f"  🔍 {short_id} ({step_count} steps) — generating metrics...")
                    if scan_transcript and to_session_metrics:
                        try:
                            result = scan_transcript(str(transcript))
                            if result:
                                metrics = to_session_metrics(short_id, result)
                                with open(metrics_file, "w", encoding="utf-8") as out_f:
                                    json.dump(metrics, out_f, indent=2)
                                metrics_generated += 1
                                print(f"  ✅ {short_id}: metrics generated")
                            else:
                                print(f"  ⚠️  {short_id}: scan failed")
                        except Exception:
                            print(f"  ⚠️  {short_id}: scan failed")
                            if metrics_file.exists():
                                metrics_file.unlink(missing_ok=True)
                    sessions_scanned += 1

        print(f"  Done: {sessions_scanned} scanned, {metrics_generated} metrics generated\n")

    # ── Check 2: Warning Trends ──────────────────────────────────────────────
    warning_report = ""
    if not active_only:
        print("📋 Check 2: Tallying warning-level findings...")
        if audit_log.is_file() and audit_log.stat().st_size > 0:
            counts: Counter[str] = Counter()
            try:
                with open(audit_log, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            if entry.get("severity") == "warning":
                                counts[entry.get("rule", "unknown")] += 1
                        except json.JSONDecodeError:
                            continue

                hardening_candidates = []
                for rule, count in counts.most_common():
                    flag = "⚠️  CONSIDER HARDENING" if count >= 3 else ""
                    line_str = f"  {count}x {rule} {flag}".rstrip()
                    print(line_str)
                    warnings_tallied += 1
                    if count >= 3:
                        hardening_candidates.append(line_str)

                if hardening_candidates:
                    warning_report = "\n".join(hardening_candidates)
            except OSError:
                print("  (parse error)")
        else:
            print("  (no audit log entries)")
        print()

    # ── Check 3: Metrics Recomputation ───────────────────────────────────────
    if not active_only:
        print("📋 Check 3: Recomputing aggregate metrics...")
        total_steps = 0
        total_waste = 0
        session_count = 0
        deep_sessions = 0
        sweep_sessions = 0

        if metrics_dir.is_dir():
            for f in sorted(metrics_dir.glob("*.json")):
                try:
                    with open(f, "r", encoding="utf-8", errors="replace") as fh:
                        m = json.load(fh)
                    if "total_steps" not in m:
                        continue
                    steps = int(m.get("total_steps", 0))
                    flat_waste = m.get("wasted_steps")
                    nested_waste = None
                    if isinstance(m.get("waste"), dict):
                        nested_waste = m["waste"].get("total_wasted_steps")

                    if nested_waste is not None and (flat_waste is None or flat_waste == 0):
                        waste = int(nested_waste)
                    elif flat_waste is not None:
                        waste = int(flat_waste)
                    else:
                        waste = 0

                    is_sweep = m.get("scan_type") == "lightweight_sweep" or m.get("review_tier") == "heuristic_sweep"
                    if is_sweep:
                        sweep_sessions += 1
                    else:
                        deep_sessions += 1

                    total_steps += steps
                    total_waste += waste
                    session_count += 1
                except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError):
                    continue

        rate = round(total_waste / total_steps * 100, 1) if total_steps > 0 else 0
        print(f"  Sessions: {session_count} (deep: {deep_sessions}, sweep: {sweep_sessions})")
        print(f"  Total steps: {total_steps:,}")
        print(f"  Total waste: {total_waste:,} ({rate}%)\n")

    # ── Check 4: Active Session Monitoring ───────────────────────────────────
    print("📋 Check 4: Checking active sessions (modified in last 2 hours)...")
    active_report_lines: list[str] = []
    now_ts = time.time()
    two_hours_ago = now_ts - (120 * 60)

    if brain_dir.is_dir():
        for transcript_path in brain_dir.glob("*/.system_generated/logs/transcript.jsonl"):
            try:
                st = transcript_path.stat()
                if st.st_mtime < two_hours_ago:
                    continue
            except OSError:
                continue

            try:
                with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
                    step_count = sum(1 for _ in f)
            except OSError:
                step_count = 0

            if step_count > 50:
                session_id = transcript_path.parent.parent.parent.name
                short_id = session_id[:8]

                waste_pct = 0
                top_pattern = "unknown"
                if scan_transcript:
                    try:
                        res = scan_transcript(str(transcript_path))
                        if res:
                            waste_pct = int(float(res.get("estimated_waste_rate", 0)) * 100)
                            top_patterns = res.get("top_patterns", [])
                            top_pattern = top_patterns[0]["pattern"] if top_patterns else "clean"
                    except Exception:
                        pass

                if waste_pct > 15:
                    print(f"  ⚠️  {short_id}: {step_count} steps, ~{waste_pct}% waste, top: {top_pattern}")
                    active_flagged += 1
                    active_report_lines.append(f"  ⚠️  {short_id}: {waste_pct}% waste ({top_pattern})")
                else:
                    print(f"  ✅ {short_id}: {step_count} steps, ~{waste_pct}% waste")

    if active_flagged == 0:
        print("  All active sessions clean.")
    print()

    # ── Check 5: Gate Event Summary ──────────────────────────────────────────
    if gate_log.is_file() and not active_only:
        print("📋 Check 5: Gate event summary...")
        try:
            with open(gate_log, "r", encoding="utf-8", errors="replace") as gf:
                lines = gf.readlines()
            gate_count = len(lines)
            blocked = sum(1 for l in lines if '"BLOCKED"' in l)
            print(f"  Total events: {gate_count}")
            print(f"  Blocked: {blocked}\n")
        except OSError:
            pass

    # ── Generate Sweep Report ────────────────────────────────────────────────
    has_actionable = metrics_generated > 0 or bool(warning_report) or active_flagged > 0

    if has_actionable:
        proposals_content = [
            "",
            f"## Governance Sweep — {timestamp}",
            "",
        ]
        if metrics_generated > 0:
            proposals_content.extend([
                f"### New Session Metrics ({metrics_generated} generated)",
                "Run `staff-review` post-mortem for deep analysis on high-waste sessions.",
                "",
            ])
        if warning_report:
            proposals_content.extend([
                "### Warning Trends — Hardening Candidates",
                warning_report,
                "",
            ])
        if active_flagged > 0:
            proposals_content.extend([
                "### Active Session Alerts",
                "\n".join(active_report_lines),
                "",
            ])

        try:
            with open(proposals, "a", encoding="utf-8") as pf:
                pf.write("\n".join(proposals_content) + "\n")
            print("📝 Sweep report appended to pending_proposals.md")
        except OSError:
            pass

    # ── Log Sweep ────────────────────────────────────────────────────────────
    sweep_entry = {
        "timestamp": timestamp,
        "sessions_scanned": sessions_scanned,
        "metrics_generated": metrics_generated,
        "warnings_tallied": warnings_tallied,
        "active_flagged": active_flagged,
        "has_actionable": has_actionable,
    }
    try:
        with open(sweep_log, "a", encoding="utf-8") as sf:
            sf.write(json.dumps(sweep_entry) + "\n")
    except OSError:
        pass

    print()
    print("✅ Governance sweep complete.")
    print(
        f"   Scanned: {sessions_scanned} | Generated: {metrics_generated} | "
        f"Warnings: {warnings_tallied} | Active flags: {active_flagged}"
    )
    return 0



# ── Evidence Aggregation & Frontmatter Sync ───────────────────────────────


def aggregate_evidence(evidence_dir: str) -> dict[str, dict]:
    """Preserve the established counts-only return shape for callers."""
    from aegis_core.evidence import aggregate_signals
    return aggregate_signals(evidence_dir).counts


def _atomic_write_cell(path: str, content: str) -> None:
    """Atomically replace path using a durable same-directory temp file."""
    from aegis_core.storage import atomic_write_text
    atomic_write_text(path, content)


def sync_frontmatter(
    cells_dir: str,
    counts: dict[str, dict],
    dry_run: bool = False,
    errors: Optional[list[dict]] = None,
) -> list[dict]:
    """Update cell frontmatter from aggregated evidence without PyYAML requirement."""
    changes = []
    error_sink = errors if errors is not None else []

    for cell_file in glob.glob(
        os.path.join(cells_dir, "**", "*.md"), recursive=True
    ):
        if os.path.basename(cell_file) == "README.md":
            continue

        cid = os.path.splitext(os.path.basename(cell_file))[0]
        try:
            content = Path(cell_file).read_text(encoding="utf-8")
            fm = parse_frontmatter(content) or {}
            body = _get_body(content)
            cid = fm.get("id", cid)
            if cid not in counts:
                continue

            evidence = counts[cid]
            fitness = fm.get("fitness", {})
            if not isinstance(fitness, dict):
                fitness = {"score": None, "impact_weight": 1.0}

            old_triggers = fitness.get("triggers", 0)
            old_tp = fitness.get("true_positives", 0)
            old_fp = fitness.get("false_positives", 0)
            old_score = fitness.get("score")
            old_last_trigger = fitness.get("last_trigger_date")

            has_triggers = evidence.get("has_triggers", "triggers" in evidence)
            has_outcomes = evidence.get("has_outcomes")
            has_tp = (
                False if has_outcomes is False else evidence.get("has_tp", "tp" in evidence)
            )
            has_fp = (
                False if has_outcomes is False else evidence.get("has_fp", "fp" in evidence)
            )
            triggers = evidence.get("triggers", 0) if has_triggers else old_triggers
            tp = evidence.get("tp", 0) if has_tp else old_tp
            fp = evidence.get("fp", 0) if has_fp else old_fp

            score = old_score
            if tp + fp > 0:
                score = round(tp / triggers, 4) if triggers > 0 else None
            elif triggers == 0:
                score = None

            last_trigger = old_last_trigger
            if has_triggers and evidence.get("last_trigger") is not None:
                last_trigger = str(evidence["last_trigger"])

            updated = dict(fitness)
            updated["triggers"] = triggers
            updated["true_positives"] = tp
            updated["false_positives"] = fp
            updated["score"] = score
            if last_trigger is not None:
                updated["last_trigger_date"] = last_trigger

            compared_keys = (
                "triggers", "true_positives", "false_positives", "score",
                "last_trigger_date",
            )
            if all(fitness.get(key) == updated.get(key) for key in compared_keys):
                continue

            change = {
                "cell_id": cid,
                "triggers": f"{old_triggers} → {triggers}",
                "tp": f"{old_tp} → {tp}",
                "fp": f"{old_fp} → {fp}",
                "score": score,
            }

            if dry_run:
                changes.append(change)
                continue

            fm["fitness"] = updated
            new_fm = dump_frontmatter(fm)
            new_content = f"---\n{new_fm}---\n{body}"

            _atomic_write_cell(cell_file, new_content)
            changes.append(change)
        except Exception as exc:  # noqa: BLE001
            error_sink.append({
                "cell_id": cid,
                "file": cell_file,
                "error": str(exc),
            })

    return changes


# ── Post-Session Hook ──────────────────────────────────────────────────────


def run_post_session_hook(
    transcript_path: Path,
    platform: str | None = None,
    cells_dir: Path | None = None,
    evidence_dir: Path | None = None,
    repo_root: Path | str | Workspace | None = None,
    use_json: bool = False,
) -> int:
    """Run post-session transcript fitness and evidence collection."""
    if not transcript_path.is_file():
        print(f"Error: transcript not found: {transcript_path}", file=sys.stderr)
        return 1

    ws = as_workspace(repo_root)
    root = ws.root
    cells_dir = cells_dir or ws.cells_dir
    evidence_dir = evidence_dir or ws.evidence_dir

    from aegis_core.telemetry import (
        detect_platform,
        extract_modified_files,
        match_cells,
        resolve_transcript_id,
        update_fitness,
    )
    try:
        from aegis_core.evidence_collector import (
            aggregate_evidence as collector_aggregate,
            build_observation,
            check_compliance,
        )
    except ImportError:
        collector_aggregate = build_observation = check_compliance = None


    resolved_platform = platform or detect_platform(transcript_path)
    transcript_id = resolve_transcript_id(transcript_path, resolved_platform)

    info_file = sys.stderr if use_json else sys.stdout

    print(f"Processing transcript: {transcript_path}", file=info_file)
    print(f"  Platform: {resolved_platform}", file=info_file)
    modified = extract_modified_files(transcript_path, platform=resolved_platform)
    print(f"  Modified files: {len(modified)}", file=info_file)

    triggered = match_cells(modified, cells_dir, repo_root=str(root))
    print(f"  Cells triggered: {len(triggered)}", file=info_file)
    for t in triggered:
        print(f"    - {t['cell_id']} ({len(t['matched_files'])} files)", file=info_file)

    update_fitness(triggered, transcript_id, evidence_dir)
    print(f"  Fitness updated: {evidence_dir / 'signals.jsonl'}", file=info_file)

    counts = aggregate_evidence(str(evidence_dir))
    if counts:
        changes = sync_frontmatter(str(cells_dir), counts)
        if changes:
            print(f"  Frontmatter synced: {len(changes)} cells updated", file=info_file)

    rules = ["read-before-write", "test-before-implementation", "no-hardcoded-paths"]
    observations = []
    for rule_id in rules:
        result = check_compliance(transcript_path, rule_id)
        obs = build_observation(result, transcript_path, rule_id)
        if obs is not None:
            observations.append(obs)

    if observations and collector_aggregate is not None:
        summary = collector_aggregate(observations)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        outfile = evidence_dir / "compliance.jsonl"
        try:
            with open(outfile, "a", encoding="utf-8") as f:
                f.write(json.dumps(summary) + "\n")
        except OSError as exc:
            print(f"Warning: could not write compliance evidence: {exc}", file=sys.stderr)

    if use_json:
        result = {
            "status": "ok",
            "transcript_id": transcript_id,
            "platform": resolved_platform,
            "modified_files": sorted(list(modified)),
            "triggered_cells": [t.get("cell_id") for t in triggered],
        }
        print(json.dumps(result))

    return 0


__all__ = [
    "HIGH_PATTERNS",
    "MEDIUM_PATTERNS",
    "LOW_PATTERNS",
    "TEST_PATTERNS",
    "PROTOCOL_RANKS",
    "check_liveness",
    "classify_file",
    "is_test_file",
    "gather_files",
    "get_diff_size",
    "detect_branch_ops",
    "check_membrane_overrides",
    "recommend_protocol",
    "set_review_mode",
    "write_frontmatter",
    "run_last_gasp",
    "load_soma_config",
    "run_push",
    "run_pull",
    "run_status",
    "prompt_llm_translation",
    "resolve_home",
    "run_sweep",
    "run_post_session_hook",
    "aggregate_evidence",
    "sync_frontmatter",
]
