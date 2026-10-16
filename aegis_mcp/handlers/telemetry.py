"""aegis_report_outcome: advisory self-reports appended to the outcome ledger."""
from __future__ import annotations

from pathlib import PurePath
import sys
from typing import List, Optional, Set, Tuple

from aegis_core.rule_inventory import RuleInventoryError
from aegis_core.telemetry_engine import ledger
from aegis_mcp.registry import _STATUS_FAIL, _VALID_OUTCOMES, _get_workspace

# (workspace root, session, idempotency key) whose edit event is recorded.
_RECORDED: Set[Tuple[str, str, str]] = set()

_LEDGER_OUTCOME = {
    "success": "tp",
    "tp": "tp",
    "pass": "tp",
    "failure": "fp",
    "fp": "fp",
    "fail": "fp",
    "partial": "trigger",
}

_KEY_REQUIRED = (
    "'idempotency_key' is required: send a unique key per report so a retry is never recorded twice."
)
_RULES_REQUIRED = (
    "'rules_used' must name at least one rule from aegis_scan: "
    "an outcome with no rule has nothing to credit."
)


def _fail(message: str) -> dict:
    return {"status": _STATUS_FAIL, "error": message}


def handle_report_outcome(args: dict) -> dict:
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return _fail(str(exc))

    raw_outcome = args.get("outcome")
    outcome = raw_outcome.strip().lower() if isinstance(raw_outcome, str) else None
    if outcome not in _VALID_OUTCOMES:
        return _fail(f"Invalid 'outcome': {raw_outcome!r}. Expected one of {list(_VALID_OUTCOMES)}.")

    # A generated key would make every retry a new event, so the caller must supply one.
    idempotency_key = args.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        return _fail(_KEY_REQUIRED)

    rules_used = args.get("rules_used")
    if rules_used is None or (isinstance(rules_used, (list, tuple)) and not rules_used):
        return _fail(_RULES_REQUIRED)
    if not isinstance(rules_used, (list, tuple)) or not all(isinstance(r, str) for r in rules_used):
        return _fail("'rules_used' must be a list of rule names.")
    rules_used = list(rules_used)
    try:
        invalid = workspace.validate_rule_names(rules_used)
    except RuleInventoryError as exc:
        return _fail(f"Cannot check 'rules_used' against the rules: {exc}")
    if invalid:
        return _fail(f"Unknown rule(s): {invalid}. Only existing rules can be reported.")
    files = args.get("files")
    edited: Optional[List[str]] = None
    if files is not None:
        if not isinstance(files, (list, tuple)) or not all(isinstance(f, str) for f in files):
            return _fail("'files' must be a list of file paths")
        try:
            edited = sorted({PurePath(workspace.confine_path(f)[1]).as_posix() for f in files})
        except ValueError as exc:
            return _fail(str(exc))

    meta = {
        "notes": args.get("notes", ""),
        "tests_passed": args.get("tests_passed"),
        "rework_count": args.get("rework_count", 0),
    }
    # Attribution comes from the server (clientInfo and its session), never the caller.
    # The key is scoped by host and session (host-matrix §3.8): two sessions that pick
    # the same key ("report-1") are two reports. The cost: a retry after a reconnect,
    # which starts a new session, records again.
    host, session = args.get("_host"), args.get("_session")
    ledger_key = f"{host}/{session}/{idempotency_key}" if session else idempotency_key
    events = [
        {
            "rule": rule,
            "outcome": _LEDGER_OUTCOME[outcome],
            "source": "mcp",
            "host": host,
            "session": session,
            "key": ledger_key,
            "meta": meta,
        }
        for rule in rules_used
    ]
    try:
        records = ledger.append(workspace.root, events)
    except ledger.EventConflictError:
        return _fail(
            f"'idempotency_key' {idempotency_key!r} was already used for a different report: "
            "send a new key for each new report."
        )
    except Exception as exc:
        return _fail(f"Failed to record outcome: {exc}")
    if edited:
        _record_edit(workspace, args, idempotency_key, edited)
    return {"status": "recorded", "records": records}


def _record_edit(workspace, args: dict, idempotency_key: str, files: List[str]) -> None:
    """One ``edit`` activity event per report, for aegis status --compliance."""
    from aegis_core import scan_compliance

    session = args.get("_session")
    if not session:
        return
    key = (str(workspace.root), str(session), idempotency_key)
    if key in _RECORDED:
        return
    try:
        scan_compliance.record(
            workspace, "edit", host=str(args.get("_host") or "generic"), session=str(session), files=files,
            client={"name": args.get("_client_name") or "", "version": args.get("_client_version") or ""},
            binding=args.get("_binding"), basis="report", key=idempotency_key,
        )
    except Exception as exc:  # telemetry only: the outcome is recorded
        print(f"aegis-mcp: edit event not recorded: {exc}", file=sys.stderr)
        return
    _RECORDED.add(key)
