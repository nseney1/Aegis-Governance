"""Scan-before-edit compliance per host (ADR 0005 AD-9, H2's falsification metric).

The MCP server appends one row per event to ``.aegis/state/activity.jsonl`` (the
activity log; the outcome ledger and fitness never read it)::

    {"v": 1, "ts": "2026-10-15T12:00:00Z", "event": "scan" | "edit", "host": "claude-code",
     "session": "<server instance id>", "files": ["src/a.py"], "client": {"name", "version"},
     "binding": "pin", "basis": "files" | "git_diff" | "report"}

``scan``: an aegis_scan, once per (session, files). ``edit``: the ``files`` an
aegis_report_outcome named. ``report()`` reads the log (and, when the workspace is a git
repository, the commits on HEAD) and computes, per session and per host:

    rate = edited files the same session scanned no later than its first recorded edit
           / edited files observed

The heuristic and its limits (stated in ``HEURISTIC`` and ``LIMITS`` and in the output):

- Edits are the files a session named in aegis_report_outcome ``files``, plus files of
  commits whose commit time falls inside exactly one session's window (its first event
  to its last event plus ``GRACE_SECONDS``).
- An edit's time is an upper bound (the report or commit time), so the rate can
  overstate compliance; uncommitted edits that were never reported are not seen.
- Commits inside overlapping sessions cannot be attributed: they are counted as
  ambiguous, never as misses. Only commits reachable from HEAD are read.
- A session with no observed edit has rate ``unknown`` (null), never 0. A host rate is
  an aggregate over sessions, not a per-attempt verdict.

Reading never writes, syncs or touches the network: git is asked through gitsafe.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path, PurePath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from aegis_core.storage import append_jsonl, locked, read_jsonl
from aegis_core.workspace.layout import WorkspaceLayout

__all__ = [
    "ACTIVITY_VERSION",
    "EVENTS",
    "GRACE_SECONDS",
    "HEURISTIC",
    "LIMITS",
    "SCHEMA",
    "activity_path",
    "record",
    "report",
]

ACTIVITY_VERSION = 1
EVENTS = ("scan", "edit")
SCHEMA = "aegis.compliance/v1"
GRACE_SECONDS = 15 * 60
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

HEURISTIC = (
    "Each aegis-mcp session (one server process) records the files it scanned. Edits are the "
    "files a session named in aegis_report_outcome 'files', plus files of commits whose commit "
    "time falls inside exactly one session's window (first to last event plus 15 minutes). A "
    "file counts as scanned before edit when the same session scanned it no later than its first "
    "recorded edit."
)
LIMITS = (
    "edit times are upper bounds (report or commit time), so the rate can overstate compliance",
    "uncommitted edits that were never reported are not seen",
    "commits inside overlapping sessions are counted as ambiguous, not as misses",
    "only commits reachable from HEAD are read",
    "a session with no observed edit has rate unknown, never 0",
    "a host rate is an aggregate over sessions, not a per-attempt verdict",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(_TS_FORMAT)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, _TS_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def activity_path(workspace: Any) -> Path:
    return WorkspaceLayout(Path(os.fspath(workspace)).resolve()).activity_file


# ── recording (the MCP server) ───────────────────────────────────────────────

def record(
    workspace: Any,
    event: str,
    *,
    host: str,
    session: str,
    files: Sequence[str],
    client: Optional[Mapping[str, str]] = None,
    binding: Optional[str] = None,
    basis: Optional[str] = None,
    key: Optional[str] = None,
) -> Dict[str, Any]:
    """Append one activity row under the workspace lock; return it.

    ``files`` are workspace-relative; they are stored as sorted, unique POSIX paths.
    Raises what the append raises (a symlinked state dir, a lock timeout): callers
    that must not fail on telemetry catch it.
    """
    if event not in EVENTS:
        raise ValueError(f"event must be one of {list(EVENTS)}, got {event!r}")
    if not isinstance(session, str) or not session or not isinstance(host, str) or not host:
        raise ValueError("host and session must be non-empty strings")
    row: Dict[str, Any] = {
        "v": ACTIVITY_VERSION,
        "ts": _stamp(_utc_now()),
        "event": event,
        "host": host,
        "session": session,
        "files": sorted({PurePath(f).as_posix() for f in files}),
    }
    if client is not None:
        row["client"] = {"name": str(client.get("name") or ""), "version": str(client.get("version") or "")}
    for name, value in (("binding", binding), ("basis", basis), ("key", key)):
        if value is not None:
            row[name] = value
    with locked(workspace):
        append_jsonl(activity_path(workspace), [row])
    return row


# ── reading ──────────────────────────────────────────────────────────────────

class _Session:
    def __init__(self, session: str, host: str, client: Optional[Dict[str, str]], first: datetime) -> None:
        self.session = session
        self.host = host
        self.client = client
        self.first = first
        self.last = first
        self.scan_events = 0
        self.scanned: Dict[str, datetime] = {}
        self.edited: Dict[str, datetime] = {}
        self.sources: Dict[str, set] = {"report": set(), "git": set()}

    def see(self, moment: datetime) -> None:
        self.first = min(self.first, moment)
        self.last = max(self.last, moment)

    def edit(self, path: str, moment: datetime, origin: str) -> None:
        if path not in self.edited or moment < self.edited[path]:
            self.edited[path] = moment
        self.sources[origin].add(path)


def _usable(row: Dict[str, Any]) -> bool:
    files = row.get("files")
    return (
        row.get("v") == ACTIVITY_VERSION
        and row.get("event") in EVENTS
        and isinstance(row.get("session"), str) and bool(row["session"])
        and isinstance(row.get("host"), str) and bool(row["host"])
        and isinstance(files, list) and all(isinstance(f, str) for f in files)
        and _parse_ts(row.get("ts")) is not None
    )


def _sessions(rows: Iterable[Dict[str, Any]]) -> Dict[str, _Session]:
    sessions: Dict[str, _Session] = {}
    for row in rows:
        moment = _parse_ts(row["ts"])
        assert moment is not None
        session = sessions.get(row["session"])
        if session is None:
            client = row.get("client") if isinstance(row.get("client"), dict) else None
            session = sessions[row["session"]] = _Session(row["session"], row["host"], client, moment)
        session.see(moment)
        for path in row["files"]:
            if row["event"] == "scan":
                if path not in session.scanned or moment < session.scanned[path]:
                    session.scanned[path] = moment
            else:
                session.edit(path, moment, "report")
        if row["event"] == "scan":
            session.scan_events += 1
    return sessions


def _commits(root: Path, since: datetime, until: datetime) -> Optional[List[Tuple[datetime, List[str]]]]:
    """(commit time, workspace-relative files) of the commits on HEAD in [since, until],
    or None when git cannot answer (no repository, git missing)."""
    from aegis_core import gitsafe

    top = gitsafe.toplevel(root)
    if top is None:
        return None
    try:
        prefix = root.resolve().relative_to(top.resolve()).as_posix()
    except (ValueError, OSError):
        return None
    try:
        listed = gitsafe.run(
            ["rev-list", "--timestamp", f"--since={_stamp(since - timedelta(seconds=1))}",
             f"--until={_stamp(until + timedelta(seconds=1))}", "HEAD"],
            root,
        )
    except gitsafe.GitError:
        return None
    if listed.returncode != 0:
        # An unborn HEAD has no commits to read.
        return [] if gitsafe.head_commit(root) is None else None
    stamped = []
    for line in os.fsdecode(listed.stdout).splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit():
            stamped.append((datetime.fromtimestamp(int(parts[0]), timezone.utc), parts[1]))
    out = []
    for moment, commit in stamped:
        try:
            tree = gitsafe.run(
                ["diff-tree", "-r", "-z", "--name-only", "--no-renames", "--no-commit-id", "--root",
                 "--diff-filter=ACMR", commit],
                root,
            )
        except gitsafe.GitError:
            return None
        if tree.returncode != 0:
            return None
        files = []
        for raw in tree.stdout.split(b"\0"):
            path = os.fsdecode(raw)
            if not path:
                continue
            if prefix not in ("", "."):
                if not path.startswith(prefix + "/"):
                    continue
                path = path[len(prefix) + 1:]
            files.append(path)
        out.append((moment, files))
    return out


def _rate(scanned: int, edited: int) -> Optional[float]:
    return round(scanned / edited, 4) if edited else None


def report(workspace: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The compliance report of ``workspace`` (see the module docstring). Reads only."""
    root = Path(os.fspath(workspace)).resolve()
    read = read_jsonl(activity_path(root))
    usable = [row for row in read.rows if _usable(row)]
    skipped = len(read.skipped_lines) + (len(read.rows) - len(usable))
    sessions = _sessions(usable)

    git: Dict[str, Any] = {"status": "unavailable", "ambiguous_edits": None, "grace_seconds": GRACE_SECONDS}
    if sessions:
        grace = timedelta(seconds=GRACE_SECONDS)
        since = min(s.first for s in sessions.values())
        until = max(s.last for s in sessions.values()) + grace
        commits = _commits(root, since, until)
        if commits is not None:
            ambiguous = 0
            for moment, files in commits:
                owners = [s for s in sessions.values() if s.first <= moment <= s.last + grace]
                if len(owners) == 1:
                    for path in files:
                        owners[0].edit(path, moment, "git")
                elif len(owners) > 1:
                    ambiguous += len(files)
            git = {"status": "used", "ambiguous_edits": ambiguous, "grace_seconds": GRACE_SECONDS}

    ordered = sorted(sessions.values(), key=lambda s: (s.first, s.session))
    session_rows = []
    per_host: Dict[str, Dict[str, Any]] = {}
    for s in ordered:
        before = sum(1 for path, moment in s.edited.items() if path in s.scanned and s.scanned[path] <= moment)
        edited = len(s.edited)
        rate = _rate(before, edited)
        entry: Dict[str, Any] = {
            "scope": "session",
            "session": s.session,
            "host": s.host,
            "client": s.client,
            "first_event": _stamp(s.first),
            "last_event": _stamp(s.last),
            "scans": s.scan_events,
            "edits_observed": edited,
            "scanned_before_edit": before if edited else None,
            "rate": rate,
            "rate_status": "measured" if edited else "unknown",
            "edit_sources": {origin: len(paths) for origin, paths in s.sources.items()},
        }
        if not edited:
            entry["unknown_reason"] = "no edits observed in this session"
        session_rows.append(entry)
        host = per_host.setdefault(s.host, {"sessions": 0, "measured": 0, "edited": 0, "before": 0})
        host["sessions"] += 1
        if edited:
            host["measured"] += 1
            host["edited"] += edited
            host["before"] += before

    host_rows = [
        {
            "scope": "host_aggregate",
            "host": name,
            "sessions": totals["sessions"],
            "sessions_measured": totals["measured"],
            "edits_observed": totals["edited"],
            "scanned_before_edit": totals["before"] if totals["edited"] else None,
            "rate": _rate(totals["before"], totals["edited"]),
            "rate_status": "measured" if totals["edited"] else "unknown",
        }
        for name, totals in sorted(per_host.items())
    ]
    return {
        "schema": SCHEMA,
        "source": "aegis status --compliance",
        "checked_at": _stamp(now or _utc_now()),
        "scope": {
            "workspace": str(root),
            "hosts": sorted(per_host),
            "sessions": [s.session for s in ordered],
            "since": _stamp(ordered[0].first) if ordered else None,
            "until": _stamp(max(s.last for s in ordered)) if ordered else None,
        },
        "stale": False,
        "metric": "scan_before_edit",
        "heuristic": {"edits": HEURISTIC, "limits": list(LIMITS)},
        "git": git,
        "activity": {"path": activity_path(root).relative_to(root).as_posix(), "rows": len(usable), "skipped": skipped},
        "hosts": host_rows,
        "sessions": session_rows,
    }
