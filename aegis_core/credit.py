"""The credit state machine (v4.3 spec §3 T1): what a ``check`` row is worth, derived on read.

Nothing local witnesses anything against a same-uid agent, so what Aegis records is a **label**
and a rule is credited only when CI on the landing commit says so. The ledger holds five kinds
of event rows (they carry neither ``rule`` nor ``outcome``, so fitness readers never see them):

- ``check``: one verified run of a tree (``aegis_core.checkrun``);
- ``report``: ``aegis_report_outcome`` with a passing ``check`` row for the current tree, one
  row per credited rule (credit identity is ``(check, rule)``);
- ``claimed``: the same call with no such row, at most one per (server session, tree);
- ``ci``: the required workflow's conclusion for one commit (``ci_conclusion``), an observation;
- ``void``: a check that CI or a gate falsified.

``derive`` folds them, and a landing lookup, into one ``Credit`` per ``(check, rule)``; it never
writes. States, strongest first:

==========  ==================================================================================
voided      terminal: CI failed on the landing commit, a gate or CI divergence voided the check
confirmed   the required workflow concluded ``success`` on a commit whose tree is the check's
landed      a commit C has the check's tree, CI has not (yet) said success
witnessed   a ``check`` row for the tree exists
==========  ==================================================================================

Only ``confirmed`` counts, and even then not when the run is ``flaky`` (the same tree, command
and environment class both passed and failed: excluded, no penalty) or when it changed the
governance set (``protected_changed``) without an approval.

CI is read over REST through an injectable client; the run selected is the newest attempt of the
required workflow whose head is the commit, from this repository, on a push, dispatch or release
event, cancelled runs ignored. Its conclusion is stored per head SHA so later consumers can reuse
it without their own request.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from aegis_core import gitsafe, human_gate
from aegis_core.errors import AegisError, PathTraversalError
from aegis_core.storage import ledger_locked, read_jsonl
from aegis_core.telemetry_engine import ledger

__all__ = [
    "EVENTS",
    "MAX_REPORT_ROWS_PER_SESSION",
    "CIUnavailable",
    "Credit",
    "GhRestClient",
    "ReportConflict",
    "check_ci_divergence",
    "claimed_summary",
    "confirm",
    "confirmed_outcome_rows",
    "derive",
    "exposed_rules",
    "format_trailer",
    "landed_lookup",
    "parse_trailer",
    "passing_check",
    "read_rows",
    "record_exposure",
    "record_void",
    "select_ci_run",
    "submit_report",
]

EVENTS = ("check", "claimed", "report", "ci", "void")
#: The most ``claimed`` and ``report`` rows one server session may write: a prompt-injected agent
#: that calls the tool in a loop fills this and no more.
MAX_REPORT_ROWS_PER_SESSION = 200
CI_EVENTS = ("push", "workflow_dispatch", "release")
#: Conclusions that falsify a check; any other unfinished or inconclusive state leaves it landed.
CI_FAILED = ("failure", "timed_out", "startup_failure")
_RESULT = {"success": "tp", "tp": "tp", "pass": "tp", "failure": "fp", "fp": "fp", "fail": "fp", "partial": "trigger"}
_TRAILER = re.compile(r"\s*Aegis-Check:\s*tree=([0-9a-f]{40,64})\s+exit=(-?\d+)\s*")
_REV_LIMIT = 5000


class CIUnavailable(AegisError):
    """CI cannot be read right now (no gh, no network, a refusal): the credit stays where it is."""


class ReportConflict(ValueError):
    """An idempotency key was already used by this server session for a different report."""


# ── Reading ──────────────────────────────────────────────────────────────────

def read_rows(root: Any) -> List[Dict[str, Any]]:
    """Every event row of this module in the ledger, oldest first. Never raises: a ledger that
    cannot be read yields nothing (its health is ``ledger.read``'s to report)."""
    try:
        raw = read_jsonl(ledger.ledger_path(root)).rows
    except (PathTraversalError, OSError):
        return []
    return [r for r in raw if r.get("v") == ledger.LEDGER_VERSION and r.get("event") in EVENTS]


def _of(rows: Iterable[Mapping[str, Any]], event: str) -> List[Mapping[str, Any]]:
    return [r for r in rows if r.get("event") == event]


def flaky_keys(rows: Iterable[Mapping[str, Any]]) -> Set[Tuple[Any, Any, Any]]:
    """The ``(tree, cmd_digest, env_class)`` keys that have both a passing and a failing check."""
    seen: Dict[Tuple[Any, Any, Any], Set[bool]] = {}
    for row in _of(rows, "check"):
        seen.setdefault((row.get("tree"), row.get("cmd_digest"), row.get("env_class")), set()).add(bool(row.get("passed")))
    return {key for key, outcomes in seen.items() if len(outcomes) == 2}


def passing_check(rows: Iterable[Mapping[str, Any]], tree: Optional[str]) -> Optional[Mapping[str, Any]]:
    """The newest ``check`` row that is a usable witness for ``tree``: ``witness: aegis``, passed,
    bound completely (not ``partial``). None when there is none."""
    if not tree:
        return None
    best = None
    for row in _of(rows, "check"):
        if (row.get("tree") == tree and row.get("witness") == "aegis" and row.get("passed") is True
                and not row.get("partial") and isinstance(row.get("id"), str)):
            best = row
    return best


# ── CI ───────────────────────────────────────────────────────────────────────

def _workflow_path(run: Mapping[str, Any]) -> str:
    return str(run.get("path") or "").split("@", 1)[0]


def select_ci_run(runs: Iterable[Mapping[str, Any]], commit: str, workflow: str) -> Optional[Mapping[str, Any]]:
    """The run that speaks for ``commit``: the required ``workflow``'s newest attempt on that exact
    SHA, from this repository's own branch, on a push, dispatch or release; cancelled runs are ignored."""
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
    """``success``, a failing conclusion, ``pending`` (not finished or inconclusive) or ``none`` (no run)."""
    if run is None:
        return "none"
    if run.get("status") != "completed":
        return "pending"
    conclusion = run.get("conclusion")
    return conclusion if conclusion == "success" or conclusion in CI_FAILED else "pending"


class GhRestClient:
    """CI runs of a commit through the user's own ``gh`` (``runs_for``); the runner is injectable."""

    def __init__(self, repo: Optional[str] = None, runner: Optional[Callable[..., Any]] = None,
                 cwd: Any = None) -> None:
        self.repo = repo
        self.runner = runner or human_gate.default_gh_runner
        self.cwd = cwd

    def runs_for(self, commit: str) -> List[Dict[str, Any]]:
        if not re.fullmatch(r"[0-9a-f]{40,64}", commit or ""):
            raise CIUnavailable("not a full commit id")
        slug = self.repo or "{owner}/{repo}"
        result = self.runner(["api", f"repos/{slug}/actions/runs?head_sha={commit}&per_page=100"], cwd=self.cwd)
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
    """A function mapping a tree id to the oldest commit with that tree among the last ``limit``
    commits reachable from ``refs`` (the landing commit of a squash or a fast-forward), or None."""
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
                found[line.strip()] = commit  # newest first, so the last write is the oldest commit
                commit = None
        return found

    def lookup(tree: str) -> Optional[str]:
        nonlocal table
        if table is None:
            table = load()
        return table.get(tree)

    return lookup


# ── What this server session showed ──────────────────────────────────────────

# (workspace root, host, server session) -> the rules its scans served. Held in the server
# process on purpose: it is the server's own witness of what the agent was shown, so it is
# neither a file the agent can write nor something the agent's report can extend.
_EXPOSED: Dict[Tuple[str, str, str], Set[str]] = {}
_MAX_EXPOSED_SESSIONS = 256


def record_exposure(root: Any, host: str, session: str, rules: Iterable[str]) -> None:
    key = (str(root), host, session)
    if key not in _EXPOSED and len(_EXPOSED) >= _MAX_EXPOSED_SESSIONS:
        _EXPOSED.pop(next(iter(_EXPOSED)))
    _EXPOSED.setdefault(key, set()).update(r for r in rules if isinstance(r, str))


def exposed_rules(root: Any, host: str, session: str) -> Set[str]:
    return set(_EXPOSED.get((str(root), host, session), ()))


# ── Writing ──────────────────────────────────────────────────────────────────

def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_void(root: Any, check_id: str, reason: str) -> Dict[str, Any]:
    """Void a check for good (CI divergence, a failed gate, a revert). Idempotent per check."""
    with ledger_locked(root):
        if any(r.get("check") == check_id for r in _of(read_rows(root), "void")):
            return next(r for r in _of(read_rows(root), "void") if r.get("check") == check_id)  # type: ignore[return-value]
        row = {"v": ledger.LEDGER_VERSION, "ts": _now(), "event": "void", "check": check_id, "reason": reason}
        return ledger.append_rows(root, [row])[0]


def confirm(root: Any, *, client: Any, workflow: str, landed: Optional[Callable[[str], Optional[str]]] = None,
            ) -> Dict[str, Any]:
    """Ask CI about every landed, not yet decided check and record what it says (a ``ci`` row per
    commit; a failing conclusion also voids the check). Returns counts and the errors met."""
    rows = read_rows(root)
    look = landed or landed_lookup(root)
    voided_checks = {r.get("check") for r in _of(rows, "void")}
    known: Dict[str, str] = {}
    for row in _of(rows, "ci"):
        known[str(row.get("commit"))] = str(row.get("ci_conclusion"))
    reported = {r.get("check") for r in _of(rows, "report")}
    by_id = {r["id"]: r for r in _of(rows, "check") if isinstance(r.get("id"), str)}
    summary: Dict[str, Any] = {"asked": 0, "confirmed": 0, "voided": 0, "errors": []}
    commits: Dict[str, List[str]] = {}
    for check_id in sorted(reported):
        if check_id in voided_checks or check_id not in by_id:
            continue
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
            observation = {"v": ledger.LEDGER_VERSION, "ts": _now(), "event": "ci", "commit": commit,
                           "workflow": workflow, "ci_conclusion": conclusion,
                           "run_id": run.get("id") if run else None,
                           "ci_run_attempt": run.get("run_attempt") if run else None}
            ledger.append_rows(root, [observation])
        if conclusion == "success":
            summary["confirmed"] += len(checks)
        elif conclusion in CI_FAILED:
            for check_id in checks:
                record_void(root, check_id, "ci_failed")
            summary["voided"] += len(checks)
    return summary


def _count(rows: Iterable[Mapping[str, Any]], session: str) -> int:
    return sum(1 for r in rows if r.get("event") in ("claimed", "report") and r.get("session") == session)


def submit_report(root: Any, *, tree: Optional[str], session: str, host: str, key: str, outcome: str,
                  rules_for: Callable[[Mapping[str, Any]], Sequence[str]],
                  cap: Optional[int] = None) -> Dict[str, Any]:
    """Record one ``aegis_report_outcome`` call and say what it earned.

    ``tree`` is the tree the server computed now. With a passing ``check`` row for it, one
    ``report`` row per credited rule (``rules_for(check_row)``, the server's choice, never the
    agent's); without one, a single ``claimed`` row per (session, tree) that earns nothing. A
    session at its cap gets ``rate_limited`` and nothing is written. Raises ReportConflict when
    the session's key was used for a different outcome.
    """
    limit = MAX_REPORT_ROWS_PER_SESSION if cap is None else cap
    result = _RESULT.get(outcome, "trigger")
    namespaced = f"{host}/{session}/{key}"
    # The ledger dedupes on (key, rule) and these rows carry no 'rule', so 'key' is each row's own
    # identity: (check, rule) for a credit, (session, tree) for a claim. The caller's key, namespaced
    # by server session, is 'report_key'.
    with ledger_locked(root):
        rows = read_rows(root)
        for row in rows:
            if (row.get("report_key") == namespaced and row.get("event") in ("claimed", "report")
                    and row.get("result", result) != result):
                raise ReportConflict(namespaced)
        used = _count(rows, session)
        check = passing_check(rows, tree)
        if check is None:
            existing = next((r for r in _of(rows, "claimed") if r.get("session") == session and r.get("tree") == tree), None)
            if existing is not None:
                return {"status": "claimed", "witness": "self", "credited": [], "tree": tree, "recorded": False}
            if used >= limit:
                return {"status": "rate_limited", "limit": limit, "witness": "self", "credited": []}
            ledger.append_rows(root, [{"v": ledger.LEDGER_VERSION, "ts": _now(), "event": "claimed", "witness": "self",
                                       "tree": tree, "session": session, "host": host,
                                       "key": f"claim:{host}/{session}:{tree}", "report_key": namespaced,
                                       "result": result}])
            return {"status": "claimed", "witness": "self", "credited": [], "tree": tree, "recorded": True}
        rules = [r for r in dict.fromkeys(rules_for(check))]
        have = {r.get("for_rule") for r in _of(rows, "report") if r.get("check") == check["id"]}
        fresh = [r for r in rules if r not in have]
        if used + len(fresh) > limit:
            return {"status": "rate_limited", "limit": limit, "witness": "aegis", "credited": []}
        if fresh:
            stamp = _now()
            ledger.append_rows(root, [
                {"v": ledger.LEDGER_VERSION, "ts": stamp, "event": "report", "witness": "aegis", "check": check["id"],
                 "tree": tree, "for_rule": rule, "result": result, "session": session, "host": host,
                 "key": f"credit:{check['id']}:{rule}", "report_key": namespaced}
                for rule in fresh])
        return {"status": "recorded", "witness": "aegis", "credited": rules, "check": check["id"], "tree": tree}


# ── Deriving ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Credit:
    """One ``(check, rule)`` and what it is worth now."""

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


def derive(rows: Sequence[Mapping[str, Any]], *, landed: Callable[[str], Optional[str]],
           approved: Optional[Callable[[str, Sequence[str]], bool]] = None) -> List[Credit]:
    """Fold event rows into one ``Credit`` per ``(check, rule)``. Pure: it reads ``rows`` and asks
    ``landed`` where a tree landed; ``approved(check_id, categories)`` says whether a human approved
    a protected change (default: never)."""
    checks = {r["id"]: r for r in _of(rows, "check") if isinstance(r.get("id"), str)}
    voids = {str(r.get("check")): str(r.get("reason") or "voided") for r in _of(rows, "void")}
    ci: Dict[str, str] = {}
    for row in _of(rows, "ci"):
        ci[str(row.get("commit"))] = str(row.get("ci_conclusion"))
    flaky = flaky_keys(rows)
    credits: List[Credit] = []
    seen: Set[Tuple[str, str]] = set()
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
        elif commit:
            state = "landed"
        else:
            state = "witnessed"
        is_flaky = (check.get("tree"), check.get("cmd_digest"), check.get("env_class")) in flaky
        categories = tuple(check.get("protected") or ())
        counts = state == "confirmed" and not is_flaky
        if counts and check.get("protected_changed") and not (approved and approved(identity[0], categories)):
            counts, reason = False, "protected_changed"
        elif is_flaky and not reason:
            reason = "flaky"
        credits.append(Credit(check=identity[0], rule=identity[1], tree=tree, state=state,
                              result=str(report.get("result") or "trigger"), commit=commit, reason=reason,
                              flaky=is_flaky, counts=counts, ts=str(report.get("ts") or ""), protected=categories))
    return credits


def confirmed_outcome_rows(credits: Iterable[Credit]) -> List[Dict[str, Any]]:
    """The outcome rows (the shape ``ledger.normalize_rows`` yields) of the credits that count,
    the only ones a fitness or promotion decision may use."""
    return [{"v": ledger.LEDGER_VERSION, "ts": c.ts, "rule": c.rule, "outcome": c.result, "source": "ci",
             "key": f"credit:{c.check}", "host": None, "session": None}
            for c in credits if c.counts]


def claimed_summary(root: Any) -> Dict[str, Any]:
    """The unwitnessed reports, counted apart from every rule's evidence."""
    claims = _of(read_rows(root), "claimed")
    return {"label": "claimed (unwitnessed)", "claimed": len(claims),
            "sessions": len({(c.get("host"), c.get("session")) for c in claims})}


# ── The trailer and CI falsification ─────────────────────────────────────────

def format_trailer(tree: str, exit_code: int) -> str:
    return f"Aegis-Check: tree={tree} exit={exit_code}"


def parse_trailer(line: str) -> Optional[Dict[str, Any]]:
    """``{"tree", "exit"}`` of an ``Aegis-Check:`` trailer line, or None for anything else."""
    found = _TRAILER.fullmatch(line.strip("\r\n")) if isinstance(line, str) else None
    return {"tree": found.group(1), "exit": int(found.group(2))} if found else None


def check_ci_divergence(trailer: Any, rerun: Mapping[str, Any], second: Optional[Mapping[str, Any]] = None
                        ) -> Dict[str, Any]:
    """Compare a head commit's ``Aegis-Check`` trailer with CI's own run of the same code.

    ``trailer`` is the trailer line (or its parsed dict); ``rerun`` and ``second`` are
    ``{"tree", "exit"}`` of CI's first run and, when the first diverged, its one re-run. Results:

    - ``unbound``: no usable trailer, or CI ran a different tree (a rebase or a squash). Never a failure.
    - ``agree``: the same tree and the same outcome (a re-run that agrees after a first miss is a flake).
    - ``rerun``: the same tree, diverging outcome, no re-run yet: run once more.
    - ``void``: the same tree still diverges on the re-run: the job fails and the check is voided.
    """
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
