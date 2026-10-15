"""aegis_report_outcome: advisory self-reports appended to the outcome ledger."""
from __future__ import annotations

from aegis_core.rule_inventory import RuleInventoryError
from aegis_core.rules import validate_rule_names
from aegis_core.telemetry_engine import ledger
from aegis_mcp.registry import _STATUS_FAIL, _VALID_OUTCOMES, _get_workspace

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
        invalid = validate_rule_names(rules_used, workspace)
    except RuleInventoryError as exc:
        return _fail(f"Cannot check 'rules_used' against the rules: {exc}")
    if invalid:
        return _fail(f"Unknown rule(s): {invalid}. Only existing rules can be reported.")

    meta = {
        "notes": args.get("notes", ""),
        "tests_passed": args.get("tests_passed"),
        "rework_count": args.get("rework_count", 0),
    }
    # Attribution comes from the server (clientInfo and its session), never the caller.
    # A retry from a new session (after a reconnect) returns the row stored under the
    # original session: the ledger identity is (key, rule) and attribution is not payload.
    events = [
        {
            "rule": rule,
            "outcome": _LEDGER_OUTCOME[outcome],
            "source": "mcp",
            "host": args.get("_host"),
            "session": args.get("_session"),
            "key": idempotency_key,
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
    return {"status": "recorded", "records": records}
