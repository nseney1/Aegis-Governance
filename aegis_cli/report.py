"""soma report — Session report card.

Displays a session summary box with triggered rules, event counts,
and an ASCII bar chart proportional to max fires.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from aegis_cli import resolve_root, sanitize_display
from aegis_cli.base import CommandCategory, AegisCommand
from aegis_cli.init import STARTER_RULES
from aegis_core.evidence import aggregate_signals

__all__ = ["run_report", "ReportCommand"]

BASE_RULES = list(STARTER_RULES)

MAX_EVENTS = 50_000

CONTEXTUAL_EMOJIS = {
    "providence": "🛡️",
    "testing": "📋",
    "destructive-ops": "🔒",
    "cost-optimization": "💰",
    "git-workflow": "🌿",
}


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO timestamp string into a timezone-aware datetime."""
    s = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def run_report(args: argparse.Namespace) -> int:
    """Session report card."""
    root = resolve_root(args)

    evidence_dir = root / ".aegis" / "evidence"
    aggregation = aggregate_signals(str(evidence_dir))
    events: list[dict] = []
    for event in aggregation.trigger_events:
        if not isinstance(event, dict):
            continue
        cell = event.get("cell")
        timestamp = event.get("timestamp")
        if not isinstance(cell, str) or not cell or not isinstance(timestamp, str):
            continue
        try:
            _parse_timestamp(timestamp)
        except (ValueError, AttributeError, TypeError):
            continue
        events.append({"cell": cell, "timestamp": timestamp})

    if len(events) > MAX_EVENTS:
        print(f"Warning: truncating to last {MAX_EVENTS:,} of {len(events):,} events")
        events = events[-MAX_EVENTS:]

    if not events:
        print("No session data yet. Run a governed session first.")
        return 0

    # Sort events chronologically
    events.sort(key=lambda e: _parse_timestamp(e["timestamp"]))

    # Group into sessions: >30 min gap starts a new session
    sessions: list[list[dict]] = []
    current_session: list[dict] = []
    prev_time: datetime | None = None

    for event in events:
        event_time = _parse_timestamp(event["timestamp"])
        if prev_time is not None and (event_time - prev_time) > timedelta(minutes=30):
            sessions.append(current_session)
            current_session = []
        current_session.append(event)
        prev_time = event_time

    if current_session:
        sessions.append(current_session)

    if not sessions:
        print("No session data yet. Run a governed session first.")
        return 0

    session_idx = getattr(args, "session", -1)
    if session_idx < -len(sessions) or session_idx >= len(sessions):
        print(f"Session index {session_idx} not found. Available sessions: 0 to {len(sessions) - 1}.")
        return 1

    selected_session = sessions[session_idx]

    # Count trigger events in selected session
    session_counts: dict[str, int] = {}
    for event in selected_session:
        cid = sanitize_display(event["cell"])
        session_counts[cid] = session_counts.get(cid, 0) + 1

    base_set = set(BASE_RULES)
    if set(session_counts.keys()) & base_set:
        rule_keys = list(BASE_RULES)
        for cid in session_counts:
            if cid not in rule_keys:
                rule_keys.append(cid)
    else:
        rule_keys = list(session_counts.keys())

    rule_stats = [(r, session_counts.get(r, 0)) for r in rule_keys]
    # Sort by fire count descending, tie-breaker alphabetical
    rule_stats.sort(key=lambda x: (-x[1], x[0]))

    max_fires = max((count for _, count in rule_stats), default=0)
    name_width = max(20, max((len(r[0]) for r in rule_stats), default=20))
    fires_num_width = max(2, max((len(str(r[1])) for r in rule_stats), default=2))
    fires_col_width = 2 + fires_num_width + 1 + 5 + 2
    inner_width = 2 + 2 + 2 + name_width + 8 + fires_col_width

    trig_count = sum(1 for _, c in rule_stats if c > 0)
    total_rules = len(rule_stats)
    total_events = len(selected_session)

    if getattr(args, "json", False) or getattr(args, "format", None) == "json":
        import json
        payload = {
            "rules_triggered": trig_count,
            "total_rules": total_rules,
            "total_events": total_events,
            "session": session_idx,
            "rules": [{"rule": name, "fires": count} for name, count in rule_stats],
        }
        print(json.dumps(payload, indent=2))
        return 0

    lines = []
    lines.append(f"╭{'─' * inner_width}╮")

    title = "📊 Session Report"
    if inner_width == 46:
        lines.append("│           📊 Session Report                  │")
    else:
        pad_left = (inner_width - 17) // 2
        pad_right = inner_width - 17 - pad_left
        lines.append(f"│{' ' * pad_left}{title}{' ' * pad_right}│")

    lines.append(f"├{'─' * inner_width}┤")

    trig_line = f"  Rules triggered:    {trig_count} of {total_rules}"
    lines.append(f"│{trig_line:<{inner_width}}│")

    ev_line = f"  Total events:       {total_events}"
    lines.append(f"│{ev_line:<{inner_width}}│")

    lines.append(f"│{' ' * inner_width}│")

    for name, c in rule_stats:
        if c == 0:
            emoji = "😴"
            bar = "░" * 8
        else:
            emoji = CONTEXTUAL_EMOJIS.get(name, "📌")
            filled = round(c / max_fires * 8) if max_fires > 0 else 0
            filled = max(1, min(8, filled))
            bar = "█" * filled + "░" * (8 - filled)

        unit = "fire" if c == 1 else "fires"
        fires_str = f"  {c:>{fires_num_width}} {unit:<5}  "
        line = f"│  {emoji}  {name:<{name_width}}{bar}{fires_str}│"
        lines.append(line)

    lines.append(f"╰{'─' * inner_width}╯")
    output = "\n".join(lines)
    if getattr(args, "plain", False) or getattr(args, "no_emoji", False):
        from aegis_cli import format_plain
        for em in ("📊", "🛡️", "📋", "🔒", "💰", "🌿", "📌", "😴"):
            output = output.replace(em, "  ")
        output = format_plain(output)
    print(output)
    return 0



class ReportCommand(AegisCommand):
    """Command to show session report card."""

    name = "report"
    category = CommandCategory.WORKFLOW
    help = "Session report card"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--session",
            type=int,
            default=-1,
            help="Session index (default: latest)",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_report(args)
