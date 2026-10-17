"""The credit state machine (v4.3 spec §3 T1, T4): what a ``check`` row is worth, derived on read."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json, re, sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from aegis_core import gitsafe, human_gate
from aegis_core.errors import AegisError, PathTraversalError
from aegis_core.storage import ledger_locked, read_jsonl
from aegis_core.telemetry_engine import ledger

__all__ = [
    "EVENTS", "MAX_REPORT_ROWS_PER_SESSION", "CIUnavailable", "Credit", "GhRestClient",
    "ReportConflict", "check_ci_divergence", "claimed_summary", "confirm",
    "confirmed_outcome_rows", "derive", "exposed_rules", "format_trailer", "landed_lookup",
    "parse_trailer", "passing_check", "read_rows", "record_adjudication", "record_detection",
    "record_exposure", "record_override", "record_void", "select_ci_run", "submit_report",
]
EVENTS = ("check", "claimed", "report", "ci", "void", "exposure", "detection", "adjudication", "override")
MAX_REPORT_ROWS_PER_SESSION = 200
CI_EVENTS = ("push", "workflow_dispatch", "release")
CI_FAILED = ("failure", "timed_out", "startup_failure")
_RESULT = {"success": "tp", "tp": "tp", "pass": "tp", "failure": "fp", "fp": "fp", "fail": "fp", "partial": "trigger"}
_TRAILER = re.compile(r"\s*Aegis-Check:\s*tree=([0-9a-f]{40,64})\s+exit=(-?\d+)\s*")
_REV_LIMIT = 5000


class CIUnavailable(AegisError):
    """CI cannot be read right now (no gh, no network, a refusal): the credit stays where it is."""


class ReportConflict(ValueError):
    """An idempotency key was already used by this server session for a different report."""


def _normalize_event_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    if "for_rule" in item and "rule" not in item:
        item["rule"] = item["for_rule"]
    elif "rule" in item and "for_rule" not in item:
        item["for_rule"] = item["rule"]
    return item


def read_rows(root: Any) -> List[Dict[str, Any]]:
    try:
        raw = read_jsonl(ledger.ledger_path(root)).rows
    except (PathTraversalError, OSError):
        return []
    return [_normalize_event_row(r) for r in raw if isinstance(r, dict) and r.get("v") == ledger.LEDGER_VERSION and r.get("event") in EVENTS]


def _of(rows: Iterable[Mapping[str, Any]], event: str) -> List[Mapping[str, Any]]:
    return [r for r in rows if r.get("event") == event]


def flaky_keys(rows: Iterable[Mapping[str, Any]]) -> Set[Tuple[Any, Any, Any]]:
    seen: Dict[Tuple[Any, Any, Any], Set[bool]] = {}
    for row in _of(rows, "check"):
        seen.setdefault((row.get("tree"), row.get("cmd_digest"), row.get("env_class")), set()).add(bool(row.get("passed")))
    return {key for key, outcomes in seen.items() if len(outcomes) == 2}


def passing_check(rows: Iterable[Mapping[str, Any]], tree: Optional[str]) -> Optional[Mapping[str, Any]]:
    if not tree:
        return None
    best = None
    for row in _of(rows, "check"):
        if row.get("tree") == tree and row.get("witness") == "aegis" and row.get("passed") is True and not row.get("partial") and isinstance(row.get("id"), str):
            best = row
    return best


def _workflow_path(run: Mapping[str, Any]) -> str:
    return str(run.get("path") or "").split("@", 1)[0]


def select_ci_run(runs: Iterable[Mapping[str, Any]], commit: str, workflow: str) -> Optional[Mapping[str, Any]]:
    wanted = f".github/workflows/{workflow}"
    best, best_key = None, None
    for run in runs:
        if not isinstance(run, Mapping):
            continue
        head = (run.get("head_repository") or {}).get("full_name") if isinstance(run.get("head_repository"), Mapping) else None
        home = (run.get("repository") or {}).get("full_name") if isinstance(run.get("repository"), Mapping) else None
        if (_workflow_path(run) != wanted or run.get("head_sha") != commit or run.get("event") not in CI_EVENTS
                or not head or head != home or run.get("conclusion") == "cancelled"):
            continue
        key = (str(run.get("created_at") or ""), int(run.get("run_attempt") or 0), int(run.get("id") or 0))
        if best_key is None or key > best_key:
            best, best_key = run, key
    return best


def ci_conclusion(run: Optional[Mapping[str, Any]]) -> str:
    if run is None:
        return "none"
    if run.get("status") != "completed":
        return "pending"
    conclusion = run.get("conclusion")
    return conclusion if conclusion == "success" or conclusion in CI_FAILED else "pending"


class GhRestClient:
    def __init__(self, repo: Optional[str] = None, runner: Optional[Callable[..., Any]] = None, cwd: Any = None) -> None:
        self.repo, self.runner, self.cwd = repo, runner or human_gate.default_gh_runner, cwd

    def runs_for(self, commit: str) -> List[Dict[str, Any]]:
        if not re.fullmatch(r"[0-9a-f]{40,64}", commit or ""):
            raise CIUnavailable("not a full commit id")
        result = self.runner(["api", f"repos/{self.repo or '{owner}/{repo}'}/actions/runs?head_sha={commit}&per_page=100"], cwd=self.cwd)
        if result is None:
            raise CIUnavailable("gh is not installed")
        if result.returncode != 0:
            raise CIUnavailable(f"gh api failed (exit {result.returncode})")
        try:
            body = json.loads(result.stdout)
        except ValueError as exc:
            raise CIUnavailable("gh printed something that is not JSON") from exc
        runs = body.get("workflow_runs") if isinstance(body, dict) else None
        if not isinstance(runs, list):
            raise CIUnavailable("gh printed no workflow_runs")
        return [r for r in runs if isinstance(r, dict)]


def landed_lookup(root: Any, refs: Sequence[str] = ("HEAD",), limit: int = _REV_LIMIT) -> Callable[[str], Optional[str]]:
    top = gitsafe.toplevel(Path(str(root)))
    table: Optional[Dict[str, str]] = None

    def load() -> Dict[str, str]:
        found: Dict[str, str] = {}
        resolved = [r for r in refs if top is not None and gitsafe.resolve_commit(top, r)]
        if top is None or not resolved:
            return found
        res = gitsafe.run(["rev-list", f"--max-count={limit}", "--format=%T", *resolved], top)
        if res.returncode != 0:
            return found
        commit = None
        for line in res.stdout.decode("ascii", "replace").splitlines():
            if line.startswith("commit "):
                commit = line.split()[1]
            elif commit and line.strip():
                found[line.strip()], commit = commit, None
        return found

    def lookup(tree: str) -> Optional[str]:
        nonlocal table
        if table is None:
            table = load()
        return table.get(tree)

    return lookup


_EXPOSED: Dict[Tuple[str, str, str], Set[str]] = {}
_MAX_EXPOSED_SESSIONS = 256


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_exposure(
    root: Any, host: Optional[str], session: Optional[str], rules: Iterable[str], *,
    paths: Optional[Iterable[str]] = None, rev: Optional[str] = None, scope_basis: Optional[str] = None,
    heartbeat: Optional[bool] = None, ts: Optional[str] = None, persist: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    rule_list = [r for r in dict.fromkeys(rules) if isinstance(r, str) and r]
    key = (str(root), host or "", session or "")
    if key not in _EXPOSED and len(_EXPOSED) >= _MAX_EXPOSED_SESSIONS:
        _EXPOSED.pop(next(iter(_EXPOSED)))
    _EXPOSED.setdefault(key, set()).update(rule_list)
    if persist is None:
        if any(v is not None for v in (paths, rev, scope_basis, heartbeat, ts)):
            should_persist = True
        else:
            should_persist = (sys._getframe(1).f_code.co_name if hasattr(sys, "_getframe") else "") != "_record_exposure"
    else:
        should_persist = bool(persist)
    if not should_persist or not rule_list:
        return []
    stamp, s_id, h_id = ts or _now(), session or "", host or ""
    path_list = [str(p) for p in (paths or ()) if isinstance(p, str)]
    try:
        with ledger_locked(root):
            seen = {(str(r.get("session") or ""), str(r.get("rule") or r.get("for_rule") or ""), r.get("scope_basis")) for r in _of(read_rows(root), "exposure")}
            to_append: List[Dict[str, Any]] = []
            for rule_id in rule_list:
                if (s_id, rule_id, scope_basis) in seen:
                    continue
                seen.add((s_id, rule_id, scope_basis))
                row: Dict[str, Any] = {"v": ledger.LEDGER_VERSION, "ts": stamp, "event": "exposure", "for_rule": rule_id, "session": s_id, "host": h_id, "paths": path_list, "rev": rev}
                if scope_basis is not None:
                    row["scope_basis"] = str(scope_basis)
                if heartbeat is not None:
                    row["heartbeat"] = bool(heartbeat)
                to_append.append(row)
            return [_normalize_event_row(r) for r in ledger.append_rows(root, to_append)] if to_append else []
    except (PathTraversalError, OSError):
        return []


def exposed_rules(root: Any, host: Optional[str], session: Optional[str]) -> Set[str]:
    return set(_EXPOSED.get((str(root), host or "", session or ""), ()))


def record_detection(
    root: Any, rule: str, file: str, pattern: str, *, disposition: str,
    rev: Optional[str] = None, branch: str = "main", fix_rev: Optional[str] = None,
    weight: Optional[float] = None, ts: Optional[str] = None,
) -> Dict[str, Any]:
    if disposition not in ("caught", "leaked"):
        raise ValueError(f"disposition must be 'caught' or 'leaked', got {disposition!r}")
    eff_weight = float(weight) if weight is not None else (0.5 if disposition == "caught" else 1.0)
    with ledger_locked(root):
        for ex in _of(read_rows(root), "detection"):
            if (ex.get("rule") or ex.get("for_rule")) == rule and ex.get("file") == file and ex.get("pattern") == pattern and (ex.get("branch") or "main") == (branch or "main"):
                return _normalize_event_row(ex)
        row = {"v": ledger.LEDGER_VERSION, "ts": ts or _now(), "event": "detection", "for_rule": rule, "file": file, "pattern": pattern, "disposition": disposition, "branch": branch or "main", "rev": rev, "fix_rev": fix_rev, "weight": eff_weight}
        return _normalize_event_row(ledger.append_rows(root, [row])[0])


def record_adjudication(
    root: Any, rule: str, verdict: str, *, adjudicator: str = "human", ref: Optional[str] = None,
    summary: Optional[str] = None, file: Optional[str] = None, line: Optional[int] = None,
    snippet: Optional[str] = None, session: Optional[str] = None, repo: Optional[str] = None, ts: Optional[str] = None,
) -> Dict[str, Any]:
    norm_verdict = _RESULT.get(verdict, verdict)
    if norm_verdict not in ("tp", "fp"):
        raise ValueError(f"adjudication verdict must be 'tp' or 'fp', got {verdict!r}")
    if adjudicator not in ("human", "automated", "ci", "pr", "revert"):
        raise ValueError(f"adjudicator must be 'human', 'automated', 'ci', 'pr', or 'revert', got {adjudicator!r}")
    with ledger_locked(root):
        if ref is not None:
            for ex in _of(read_rows(root), "adjudication"):
                if (ex.get("rule") or ex.get("for_rule")) == rule and ex.get("ref") == ref:
                    return _normalize_event_row(ex)
        row: Dict[str, Any] = {"v": ledger.LEDGER_VERSION, "ts": ts or _now(), "event": "adjudication", "for_rule": rule, "verdict": norm_verdict, "adjudicator": adjudicator}
        for k, v in (("ref", ref), ("summary", summary), ("file", file), ("snippet", snippet), ("session", session), ("repo", repo)):
            if v is not None:
                row[k] = str(v)
        if line is not None:
            row["line"] = int(line)
        return _normalize_event_row(ledger.append_rows(root, [row])[0])


def record_override(
    root: Any, rule: str, file: str, line: int, reason: str = "", *, rev: Optional[str] = None, ts: Optional[str] = None,
) -> Dict[str, Any]:
    with ledger_locked(root):
        for ex in _of(read_rows(root), "override"):
            if (ex.get("rule") or ex.get("for_rule")) == rule and ex.get("file") == file and int(ex.get("line") or 0) == int(line) and ex.get("rev") == rev:
                return _normalize_event_row(ex)
        row: Dict[str, Any] = {"v": ledger.LEDGER_VERSION, "ts": ts or _now(), "event": "override", "for_rule": rule, "file": str(file), "line": int(line), "reason": str(reason or ""), "status": "contested"}
        if rev is not None:
            row["rev"] = str(rev)
        return _normalize_event_row(ledger.append_rows(root, [row])[0])


def record_void(root: Any, check_id: str, reason: str) -> Dict[str, Any]:
    with ledger_locked(root):
        existing = next((r for r in _of(read_rows(root), "void") if r.get("check") == check_id), None)
        if existing is not None:
            return dict(existing)
        return ledger.append_rows(root, [{"v": ledger.LEDGER_VERSION, "ts": _now(), "event": "void", "check": check_id, "reason": reason}])[0]


def confirm(root: Any, *, client: Any, workflow: str, landed: Optional[Callable[[str], Optional[str]]] = None) -> Dict[str, Any]:
    rows, look = read_rows(root), landed or landed_lookup(root)
    voided_checks = {r.get("check") for r in _of(rows, "void")}
    known = {str(r.get("commit")): str(r.get("ci_conclusion")) for r in _of(rows, "ci")}
    by_id = {r["id"]: r for r in _of(rows, "check") if isinstance(r.get("id"), str)}
    summary: Dict[str, Any] = {"asked": 0, "confirmed": 0, "voided": 0, "errors": []}
    commits: Dict[str, List[str]] = {}
    for check_id in sorted({r.get("check") for r in _of(rows, "report")}):
        if check_id not in voided_checks and check_id in by_id:
            commit = look(str(by_id[check_id].get("tree")))
            if commit and known.get(commit) != "success":
                commits.setdefault(commit, []).append(check_id)
    for commit, checks in commits.items():
        try:
            runs = client.runs_for(commit)
        except CIUnavailable as exc:
            summary["errors"].append(str(exc))
            continue
        summary["asked"] += 1
        run = select_ci_run(runs, commit, workflow)
        conclusion = ci_conclusion(run)
        if known.get(commit) != conclusion:
            ledger.append_rows(root, [{"v": ledger.LEDGER_VERSION, "ts": _now(), "event": "ci", "commit": commit, "workflow": workflow, "ci_conclusion": conclusion, "run_id": run.get("id") if run else None, "ci_run_attempt": run.get("run_attempt") if run else None}])
        if conclusion == "success":
            summary["confirmed"] += len(checks)
        elif conclusion in CI_FAILED:
            for check_id in checks:
                record_void(root, check_id, "ci_failed")
            summary["voided"] += len(checks)
    return summary


def _count(rows: Iterable[Mapping[str, Any]], session: Optional[str]) -> int:
    return sum(1 for r in rows if r.get("event") in ("claimed", "report") and r.get("session") == session)


def submit_report(
    root: Any, *, tree: Optional[str], session: Optional[str], host: Optional[str], key: str,
    outcome: str, rules_for: Callable[[Mapping[str, Any]], Sequence[str]],
    cap: Optional[int] = None, source: str = "mcp",
) -> Dict[str, Any]:
    limit = MAX_REPORT_ROWS_PER_SESSION if cap is None else cap
    result, namespaced = _RESULT.get(outcome, "trigger"), (f"{host}/{session}/{key}" if session else key)
    with ledger_locked(root):
        rows = read_rows(root)
        for row in rows:
            if row.get("report_key") == namespaced and row.get("event") in ("claimed", "report") and row.get("result", result) != result:
                raise ReportConflict(namespaced)
        used, check = _count(rows, session), passing_check(rows, tree)
        if check is None:
            if any(r.get("session") == session and r.get("tree") == tree for r in _of(rows, "claimed")):
                return {"status": "claimed", "witness": "self", "credited": [], "tree": tree, "recorded": False}
            if used >= limit:
                return {"status": "rate_limited", "limit": limit, "witness": "self", "credited": []}
            ledger.append_rows(root, [{"v": ledger.LEDGER_VERSION, "ts": _now(), "event": "claimed", "witness": "self", "tree": tree, "source": source, "session": session, "host": host, "key": f"claim:{host}/{session}:{tree}", "report_key": namespaced, "result": result}])
            return {"status": "claimed", "witness": "self", "credited": [], "tree": tree, "recorded": True}
        rules = list(dict.fromkeys(rules_for(check)))
        have = {r.get("for_rule") for r in _of(rows, "report") if r.get("check") == check["id"]}
        fresh = [r for r in rules if r not in have]
        if used + len(fresh) > limit:
            return {"status": "rate_limited", "limit": limit, "witness": "aegis", "credited": []}
        if fresh:
            stamp = _now()
            ledger.append_rows(root, [{"v": ledger.LEDGER_VERSION, "ts": stamp, "event": "report", "witness": "aegis", "check": check["id"], "tree": tree, "for_rule": rule, "result": result, "source": source, "session": session, "host": host, "key": f"credit:{check['id']}:{rule}", "report_key": namespaced} for rule in fresh])
        return {"status": "recorded", "witness": "aegis", "credited": rules, "check": check["id"], "tree": tree}


@dataclass(frozen=True)
class Credit:
    check: str
    rule: str
    tree: str
    state: str
    result: str
    commit: Optional[str] = None
    reason: str = ""
    flaky: bool = False
    counts: bool = False
    ts: str = ""
    protected: Tuple[str, ...] = ()


def derive(
    rows: Sequence[Mapping[str, Any]], *, landed: Callable[[str], Optional[str]],
    approved: Optional[Callable[[str, Sequence[str]], bool]] = None,
) -> List[Credit]:
    checks = {r["id"]: r for r in _of(rows, "check") if isinstance(r.get("id"), str)}
    voids = {str(r.get("check")): str(r.get("reason") or "voided") for r in _of(rows, "void")}
    ci = {str(r.get("commit")): str(r.get("ci_conclusion")) for r in _of(rows, "ci")}
    flaky, credits, seen = flaky_keys(rows), [], set()
    for report in _of(rows, "report"):
        identity = (str(report.get("check")), str(report.get("for_rule")))
        check = checks.get(identity[0])
        if check is None or identity in seen:
            continue
        seen.add(identity)
        tree = str(check.get("tree"))
        commit = landed(tree)
        conclusion = ci.get(commit) if commit else None
        reason = ""
        if identity[0] in voids:
            state, reason = "voided", voids[identity[0]]
        elif commit and conclusion in CI_FAILED:
            state, reason = "voided", "ci_failed"
        elif commit and conclusion == "success":
            state = "confirmed"
        else:
            state = "landed" if commit else "witnessed"
        is_flaky = (check.get("tree"), check.get("cmd_digest"), check.get("env_class")) in flaky
        categories = tuple(check.get("protected") or ())
        counts = state == "confirmed" and not is_flaky
        if counts and check.get("protected_changed") and not (approved and approved(identity[0], categories)):
            counts, reason = False, "protected_changed"
        elif is_flaky and not reason:
            reason = "flaky"
        credits.append(Credit(check=identity[0], rule=identity[1], tree=tree, state=state, result=str(report.get("result") or "trigger"), commit=commit, reason=reason, flaky=is_flaky, counts=counts, ts=str(report.get("ts") or ""), protected=categories))
    return credits


def confirmed_outcome_rows(credits: Iterable[Credit]) -> List[Dict[str, Any]]:
    return [{"v": ledger.LEDGER_VERSION, "ts": c.ts, "rule": c.rule, "outcome": c.result, "source": "ci", "key": f"credit:{c.check}", "host": None, "session": None} for c in credits if c.counts]


def claimed_summary(root: Any) -> Dict[str, Any]:
    claims = _of(read_rows(root), "claimed")
    return {"label": "claimed (unwitnessed)", "claimed": len(claims), "sessions": len({(c.get("host"), c.get("session")) for c in claims})}


def format_trailer(tree: str, exit_code: int) -> str:
    return f"Aegis-Check: tree={tree} exit={exit_code}"


def parse_trailer(line: str) -> Optional[Dict[str, Any]]:
    found = _TRAILER.fullmatch(line.strip("\r\n")) if isinstance(line, str) else None
    return {"tree": found.group(1), "exit": int(found.group(2))} if found else None


def check_ci_divergence(trailer: Any, rerun: Mapping[str, Any], second: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    given = parse_trailer(trailer) if isinstance(trailer, str) else (dict(trailer) if isinstance(trailer, Mapping) else None)
    if not given or not given.get("tree") or "exit" not in given:
        return {"result": "unbound", "failed": False, "reason": "no usable Aegis-Check trailer"}
    first = dict(rerun) if isinstance(rerun, Mapping) else {}
    if first.get("tree") != given["tree"]:
        return {"result": "unbound", "failed": False, "reason": "CI ran a different tree"}
    claimed_pass = given["exit"] == 0
    if (first.get("exit") == 0) == claimed_pass:
        return {"result": "agree", "failed": False, "reason": ""}
    if second is None:
        return {"result": "rerun", "failed": False, "reason": "outcomes diverge on the same tree"}
    again = dict(second)
    if again.get("tree") == given["tree"] and (again.get("exit") == 0) == claimed_pass:
        return {"result": "agree", "failed": False, "reason": "flaky: the re-run agrees with the trailer"}
    return {"result": "void", "failed": True, "reason": "outcomes still diverge on the same tree after a re-run"}
