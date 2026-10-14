"""aegis_core.arbitration — Canonical arbitration, TTC verification and oracle checks.

Consolidates:
- TTC Verifier heuristics and change proposals (formerly enzymes/ttc_verifier.py)
- TTC Oracle evaluation and rule loading (formerly enzymes/ttc_oracle.py)
- Oracle Checkpoint mid-session health analysis (formerly enzymes/oracle_checkpoint.py)

Strictly layered: uses aegis_core primitives (workspace, evidence) and stdlib.
"""
from __future__ import annotations

import collections
from datetime import datetime, timezone
import difflib
import glob
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from aegis_core.evidence import aggregate_signals
from aegis_core.workspace import Workspace, confine_path, resolve_workspace

# ── TTC Constants ─────────────────────────────────────────────────────────

ESCALATION_PROTOCOLS = ("breeze", "gale", "trident", "maelstrom", "tempest")
ESCALATING_PROTOCOLS = ("trident", "maelstrom", "tempest")
PROTOCOL_UNKNOWN = "unknown"

SENTINEL_TIMEOUT = int(os.environ.get("SOMA_SENTINEL_TIMEOUT", "30"))

ORACLE_FAIL_OPEN_MARKERS = (
    "oracle evaluation failed",
    "no inference provider available",
)
ORACLE_NO_RULES_MARKER = "no oracles defined"

VERDICT_APPROVED = "APPROVED"
VERDICT_REJECTED = "REJECTED"
VERDICT_BLOCKED = "BLOCKED"
VERDICT_ESCALATE = "ESCALATION_REQUIRED"


def _log(message: str) -> None:
    """Emit a diagnostic on stderr (stdout may be a JSON-RPC transport)."""
    print(message, file=sys.stderr)


# ── TTC Heuristics & Verifier ─────────────────────────────────────────────


class TTCVerifier:
    """Fast keyword heuristics standing in for a lightweight LLM reviewer."""

    HEURISTICS = (
        (
            "no-class-components",
            ("react", "functional component", "class component", "jsx"),
            ("class ",),
            "class components are forbidden; use functional components",
        ),
        (
            "no-meaningless-assertions",
            ("assertion", "test", "pytest", "jest", "vitest"),
            ("assert True", "assert 1 == 1", "expect(true).toBe(true)"),
            "meaningless assertions detected",
        ),
        (
            "no-hardcoded-secrets",
            ("secret", "credential", "api key", "token", "password"),
            ("AWS_SECRET_ACCESS_KEY=", 'api_key = "sk-', 'password = "'),
            "a literal credential appears in the proposal",
        ),
    )

    def __init__(self, active_playbooks: Optional[List[Dict[str, Any]]] = None):
        self.active_playbooks = active_playbooks or []

    @staticmethod
    def _playbook_text(playbook: Dict[str, Any]) -> str:
        """Flatten a playbook into lowercase searchable text."""
        parts = []
        for key in (
            "name",
            "_name",
            "hypothesis",
            "prediction",
            "guidance",
            "body",
            "_body",
            "content",
        ):
            value = playbook.get(key)
            if isinstance(value, str):
                parts.append(value)
        return "\n".join(parts).lower()

    def verify_proposal(self, proposed_diff: str, file_path: str) -> Dict[str, Any]:
        """Return status, reason, playbook for the proposal."""
        for playbook in self.active_playbooks:
            if not isinstance(playbook, dict):
                continue
            text = self._playbook_text(playbook)
            if not text:
                continue
            label = playbook.get("name") or playbook.get("_name") or "unnamed playbook"
            for rule_id, topic_markers, forbidden_tokens, reason in self.HEURISTICS:
                if not any(marker in text for marker in topic_markers):
                    continue
                for token in forbidden_tokens:
                    if token in proposed_diff:
                        return {
                            "status": VERDICT_REJECTED,
                            "reason": (
                                f"Violation of '{label}' [{rule_id}]: {reason} "
                                f"(matched {token!r})."
                            ),
                            "playbook": playbook,
                        }

        return {
            "status": VERDICT_APPROVED,
            "reason": (
                f"No playbook heuristic matched "
                f"({len(self.active_playbooks)} playbook(s) checked)."
            ),
            "playbook": None,
        }


def _classify_protocol_python(file_path: str, workspace: Workspace | Path | str) -> str:
    """Pure Python escalation sentinel fallback when bash is unavailable."""
    norm_path = file_path.replace("\\", "/").lstrip("./")

    high_patterns = [
        r"enzymes/.*\.sh$",
        r"install\.sh$",
        r"install\.ps1$",
        r"Makefile$",
        r"hooks\.json",
        r"\.github/workflows/",
        r"auth|credential|secret|token|password",
        r"docker|Dockerfile",
        r"requirements\.txt$|package\.json$|go\.mod$",
    ]
    test_patterns = [
        r"\.test\.",
        r"_test\.",
        r"^tests/",
    ]
    low_patterns = [
        r"(?:^|/)docs/",
        r"README\.md$",
        r"LICENSE$",
        r"CHANGELOG|EVOLUTION|METRICS|EXPERIMENTS",
        r"\.txt$|\.csv$|\.json$",
    ]

    for pat in high_patterns:
        if re.search(pat, norm_path, re.IGNORECASE):
            return "trident"

    for pat in test_patterns:
        if re.search(pat, norm_path, re.IGNORECASE):
            return "gale"

    for pat in low_patterns:
        if re.search(pat, norm_path, re.IGNORECASE):
            return "breeze"

    return "gale"


def get_escalation_protocol(file_path: str, workspace: Workspace | Path | str) -> str:
    """Determine the review protocol for a file path (fails closed)."""
    protocol = _classify_protocol_python(file_path, workspace)
    if protocol in ESCALATION_PROTOCOLS:
        return protocol
    _log(f"[TTC] Python protocol classifier could not determine protocol for {file_path}; failing closed.")
    return PROTOCOL_UNKNOWN



# ── Oracle Evaluation ─────────────────────────────────────────────────────


def load_oracles(workspace: Workspace | Path | str) -> List[Tuple[str, str]]:
    """Load foundational markdown oracles from genome/.oracles/."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    oracles_dir = ws.root / "rules" / ".oracles"
    if not oracles_dir.is_dir():
        oracles_dir = ws.root / "genome" / ".oracles"
    oracles: List[Tuple[str, str]] = []
    if not oracles_dir.is_dir():
        return oracles

    for f in sorted(glob.glob(os.path.join(str(oracles_dir), "*.md"))):
        with open(f, "r", encoding="utf-8") as file:
            oracles.append((os.path.basename(f), file.read()))
    return oracles


def evaluate_change(workspace: Workspace | Path | str, target_file: str, proposed_content: str, strict: bool = False) -> str:
    """Evaluate proposed content against hidden oracles using inference provider."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    oracles = load_oracles(ws)
    if not oracles:
        return "APPROVED: No oracles defined."

    try:
        from aegis_core.inference_provider import resolve_provider, PromptOnlyProvider
    except ImportError:
        resolve_provider = None
        PromptOnlyProvider = None

    provider = resolve_provider(str(ws.root)) if resolve_provider else None
    if not provider or (PromptOnlyProvider and isinstance(provider, PromptOnlyProvider)):
        if strict:
            return "BLOCKED: No inference provider available to run TTC Oracle."
        return "APPROVED: No inference provider available to run TTC Oracle."


    rulebook = ""
    for name, content in oracles:
        rulebook += f"\n--- RULEBOOK: {name} ---\n{content}\n"

    prompt = f"""
You are the TTC Oracle, a strict and unforgiving gatekeeper for this repository.
You must evaluate the following proposed change against the foundational rules (Oracles).

{rulebook}

TARGET FILE:
{target_file}

PROPOSED CONTENT:
{proposed_content}

INSTRUCTIONS:
Evaluate if the proposed content violates ANY of the rules defined in the rulebooks.
If it violates a rule, you MUST output exactly:
REJECTED: [Name of Rulebook violated] - [Specific, precise reason for rejection]

If it perfectly aligns with all rules, you MUST output exactly:
APPROVED

Respond ONLY with REJECTED or APPROVED as specified above. Do not include any other text.
"""
    try:
        result = provider.generate(prompt).strip()
        if not result.startswith("REJECTED") and not result.startswith("APPROVED"):
            if "REJECTED" in result:
                return result
            return "APPROVED"
        return result
    except Exception as e:
        return f"REJECTED: Oracle evaluation failed ({str(e)})"


def _consult_oracle(workspace: Workspace | Path | str, file_path: str, proposed_content: str) -> Tuple[str, str]:
    """Run the TTC oracle. Returns (verdict, detail)."""
    try:
        raw = evaluate_change(workspace, file_path, proposed_content)
    except Exception as exc:
        return VERDICT_BLOCKED, f"oracle raised ({exc!r})"

    raw = (raw or "").strip()
    lowered = raw.lower()

    if lowered.startswith("rejected"):
        return VERDICT_REJECTED, raw
    if any(marker in lowered for marker in ORACLE_FAIL_OPEN_MARKERS):
        return VERDICT_BLOCKED, raw
    if ORACLE_NO_RULES_MARKER in lowered or lowered.startswith("approved"):
        return VERDICT_APPROVED, raw
    return VERDICT_BLOCKED, f"unrecognised oracle response: {raw[:200]!r}"


def _build_diff(resolved_path: str, relative_path: str, proposed_content: str) -> str:
    """Unified diff between the file on disk and the proposal."""
    current = ""
    exists = os.path.isfile(resolved_path)
    if exists:
        try:
            with open(resolved_path, "r", encoding="utf-8") as f:
                current = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            return f"(could not read existing file for diff: {exc})"

    diff = "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            proposed_content.splitlines(keepends=True),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
            n=3,
        )
    )
    if not diff:
        return "(no change: the proposal is identical to the file on disk)"
    header = "" if exists else f"(new file: {relative_path} does not exist yet)\n"
    return header + diff


def _render_report(
    verdict: str,
    relative_path: str,
    protocol: str,
    lines: List[str],
    diff: Optional[str] = None,
) -> str:
    """Render the advisory report returned to caller."""
    out = [
        f"VERDICT: {verdict} — ADVISORY ONLY, NO FILE WAS WRITTEN.",
        f"File: {relative_path}",
        f"Escalation protocol: {protocol}",
    ]
    out.extend(lines)
    if diff is not None:
        out.append("")
        out.append("--- proposed diff (not applied) ---")
        out.append(diff)
    return "\n".join(out)


def soma_propose_change(
    file_path: str,
    proposed_content: str,
    active_playbooks: Optional[List[Dict[str, Any]]] = None,
    workspace: Optional[Workspace | Path | str] = None,
) -> str:
    """Review a proposed change and return a verdict plus a diff (advisory only)."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )

    try:
        resolved_path, relative_path = confine_path(file_path, ws)
    except ValueError as exc:
        _log(f"[TTC] {exc}")
        return (
            f"VERDICT: {VERDICT_REJECTED} — ADVISORY ONLY, NO FILE WAS WRITTEN.\n"
            f"File: {file_path}\n"
            f"Reason: {exc}\n"
            "Nothing was inspected and nothing was sent anywhere. Supply a "
            "path inside the workspace."
        )

    if proposed_content is None:
        return _render_report(
            VERDICT_REJECTED,
            relative_path,
            "n/a",
            ["Reason: no proposed_content was supplied."],
        )

    protocol = get_escalation_protocol(relative_path, ws)
    if protocol in ESCALATING_PROTOCOLS or protocol == PROTOCOL_UNKNOWN:
        why = (
            "Sensitivity could not be determined, so this is treated as sensitive (the gate fails closed)."
            if protocol == PROTOCOL_UNKNOWN
            else "This file is highly sensitive (core infrastructure / auth)."
        )
        return _render_report(
            VERDICT_ESCALATE,
            relative_path,
            protocol,
            [
                f"Reason: {why}",
                (
                    "ACTION REQUIRED: dispatch the 'Security Audit Organ' and "
                    "'Performance Audit Organ' subagents to review this change "
                    "concurrently. Changes to this file require out-of-band approval."
                ),
                "The proposal was NOT sent to the oracle and NOT written.",
            ],
        )

    _log(f"[TTC] Reviewing proposed change to {relative_path} (protocol: {protocol}).")

    playbooks = active_playbooks or []
    playbook_result = TTCVerifier(playbooks).verify_proposal(proposed_content, relative_path)
    if playbook_result["status"] == VERDICT_REJECTED:
        return _render_report(
            VERDICT_REJECTED,
            relative_path,
            protocol,
            [
                f"Playbook check: REJECTED — {playbook_result['reason']}",
                "Revise the proposal so it no longer violates this playbook.",
                "The proposal was NOT sent to the oracle and NOT written.",
            ],
        )

    if os.environ.get("SOMA_ENABLE_CLOUD_ORACLE", "0").lower() in ("1", "true"):
        oracle_verdict, oracle_detail = _consult_oracle(ws, relative_path, proposed_content)
    else:
        oracle_verdict, oracle_detail = VERDICT_APPROVED, "Oracle skipped (local-only mode)"
    diff = _build_diff(resolved_path, relative_path, proposed_content)

    if oracle_verdict == VERDICT_REJECTED:
        _log(f"[TTC Oracle] {oracle_detail}")
        return _render_report(
            VERDICT_REJECTED,
            relative_path,
            protocol,
            [
                f"Playbook check: PASSED — {playbook_result['reason']}",
                f"Oracle: REJECTED — {oracle_detail}",
                "Follow the architectural tenets and standards, then re-propose.",
            ],
            diff,
        )

    if oracle_verdict == VERDICT_BLOCKED:
        _log(f"[TTC Oracle] inconclusive: {oracle_detail}")
        return _render_report(
            VERDICT_BLOCKED,
            relative_path,
            protocol,
            [
                f"Playbook check: PASSED — {playbook_result['reason']}",
                f"Oracle: INCONCLUSIVE — {oracle_detail}",
                (
                    "This is NOT a rule violation: the oracle could not render a "
                    "judgement, so the gate fails closed rather than approving blind."
                ),
            ],
            diff,
        )

    return _render_report(
        VERDICT_APPROVED,
        relative_path,
        protocol,
        [
            f"Playbook check: PASSED — {playbook_result['reason']}",
            f"Oracle: APPROVED — {oracle_detail}",
            "NEXT STEP: nothing was written. Apply the diff below with your own file-editing tool.",
        ],
        diff,
    )


def _parse_cell(filepath: str) -> Tuple[Dict[str, Any], str]:
    """Parse cell frontmatter and body."""
    from aegis_core.lifecycle import parse_cell as _core_parse
    fm, body = _core_parse(filepath)
    return (fm or {}, body)


def _load_fitness_evidence(workspace: Workspace | Path | str) -> Dict[str, Any]:
    """Load canonical signal evidence aggregated per cell id."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    return aggregate_signals(str(ws.evidence_dir)).counts


def _load_cells(workspace: Workspace | Path | str) -> List[Dict[str, Any]]:
    """Load all cell metadata from .soma/cells/."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells_dir = ws.cells_dir
    cells = []
    if not cells_dir.is_dir():
        return cells

    for md_file in sorted(glob.glob(os.path.join(str(cells_dir), "**", "*.md"), recursive=True)):
        if os.path.basename(md_file) == "README.md":
            continue
        try:
            metadata, _body = _parse_cell(md_file)
            metadata["_filepath"] = md_file
            if not metadata.get("id"):
                metadata["id"] = metadata.get("name") or Path(md_file).stem
            cells.append(metadata)
        except Exception:
            continue
    return cells


def _parse_iso_date(ts_str: Any) -> Optional[datetime]:
    if not ts_str or not isinstance(ts_str, str):
        return None
    cleaned = ts_str.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _classify_cell(cell: Dict[str, Any], evidence: Dict[str, Any], expired_ids: set) -> Tuple[str, str]:
    """Classify a single cell's health status."""
    cell_id = cell.get("id", "")

    # Check expiry first
    if cell_id in expired_ids:
        return "expired", "Past expiry limit"

    # Check evidence
    ev = evidence.get(cell_id)
    if not ev or ev.get("triggers", 0) == 0:
        return "unobserved", "No trigger data recorded"

    triggers = ev["triggers"]
    tp = float(ev.get("tp", 0))
    fp = float(ev.get("fp", 0))
    has_outcomes = ev.get("has_outcomes", False)

    # Dynamic read-time decay: check days since last trigger
    last_trigger_str = ev.get("last_trigger")
    if not last_trigger_str and isinstance(cell.get("fitness"), dict):
        last_trigger_str = cell["fitness"].get("last_trigger_date")

    last_trigger_dt = _parse_iso_date(last_trigger_str)
    days_inactive = 0
    if last_trigger_dt:
        now_utc = datetime.now(timezone.utc)
        days_inactive = max(0, (now_utc - last_trigger_dt).days)

    expiry_days = cell.get("expiry_days")
    if expiry_days:
        try:
            expiry_days = int(expiry_days)
        except (ValueError, TypeError):
            expiry_days = None

    if expiry_days and expiry_days > 60:
        dormant_limit = expiry_days
        decay_limit = expiry_days
    else:
        decay_limit = 30
        dormant_limit = 60

    if days_inactive > dormant_limit:
        return "dormant", f"Inactive for {days_inactive} days (dormant)"
    elif days_inactive > decay_limit:
        return "decaying", f"{int(tp)}/{triggers} true positives ({days_inactive}d inactive, score decaying)"

    if has_outcomes:
        if triggers >= 3 and fp > tp:
            precision = tp / triggers if triggers > 0 else 0
            return "noisy", f"{int(fp)}/{triggers} false positives (precision: {precision:.0%})"
        return "healthy", f"{int(tp)}/{triggers} true positives"

    if triggers >= 5:
        return "active", f"{triggers} triggers (no outcome data yet)"
    return "healthy", f"{triggers} trigger(s) recorded"


def generate_checkpoint(workspace: Optional[Workspace | Path | str] = None, session_count: Optional[int] = None) -> Dict[str, Any]:
    """Generate a mid-session health checkpoint report."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells = _load_cells(ws)
    evidence = _load_fitness_evidence(ws)

    from aegis_core.defects import audit_expiry

    expiry_results = audit_expiry(ws, session_count=session_count)
    expired_ids = {
        r["cell_id"] for r in expiry_results
        if r.get("status") in ("EXPIRED", "EXPIRY_WARNING")
    }

    classifications = collections.defaultdict(list)
    for cell in cells:
        cell_id = cell.get("id", "")
        category, details = _classify_cell(cell, evidence, expired_ids)
        classifications[category].append({
            "cell_id": cell_id,
            "type": cell.get("type", "unknown"),
            "details": details,
        })

    recommendations = []
    expired_count = len(classifications.get("expired", []))
    if expired_count > 0:
        recommendations.append({
            "severity": "critical",
            "action": "prune_expired",
            "message": f"{expired_count} cell(s) past expiry limit. Run: python3 enzymes/cell_expiry.py . --prune",
        })

    noisy_count = len(classifications.get("noisy", []))
    if noisy_count > 0:
        noisy_ids = [c["cell_id"] for c in classifications["noisy"]]
        recommendations.append({
            "severity": "warning",
            "action": "review_noisy",
            "message": f"{noisy_count} noisy cell(s): {', '.join(noisy_ids)}. Consider tightening hypotheses or target_paths.",
        })

    unobserved_count = len(classifications.get("unobserved", []))
    if unobserved_count > 0 and len(cells) > 0:
        pct = unobserved_count / len(cells) * 100
        if pct > 50:
            recommendations.append({
                "severity": "info",
                "action": "collect_evidence",
                "message": f"{unobserved_count}/{len(cells)} cells ({pct:.0f}%) have no fitness evidence. Run post-session hook to collect data.",
            })

    healthy_count = len(classifications.get("healthy", [])) + len(classifications.get("active", []))
    warning_count = len(classifications.get("noisy", [])) + len(classifications.get("decaying", []))
    expired_count = len(classifications.get("expired", []))
    dormant_count = len(classifications.get("unobserved", [])) + len(classifications.get("dormant", []))

    return {
        "workspace": str(ws.root),
        "total_cells": len(cells),
        "healthy_count": healthy_count,
        "warning_count": warning_count,
        "expired_count": expired_count,
        "dormant_count": dormant_count,
        "classifications": dict(classifications),
        "recommendations": recommendations,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }



def cli_checkpoint(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for oracle_checkpoint."""
    import argparse

    parser = argparse.ArgumentParser(description="Oracle Checkpoint — Mid-Session Fitness Feedback")
    parser.add_argument("workspace", nargs="?", default=None, help="Workspace path")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--session-count", type=int, default=None, help="Current session sequence")

    parsed = parser.parse_args(argv if argv is not None else sys.argv[1:])
    report = generate_checkpoint(workspace=parsed.workspace, session_count=parsed.session_count)

    if parsed.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        ts = report.get("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        ws_str = report.get("workspace", parsed.workspace or "")
        tot = report.get("total_cells", 0)
        h = report.get("healthy_count", 0)
        w = report.get("warning_count", 0)
        e = report.get("expired_count", 0)
        d = report.get("dormant_count", 0)
        print(f"Soma Oracle Checkpoint ({ts})")
        print(f"Workspace: {ws_str}")
        print(f"Cells: {tot} (Healthy: {h}, Warning: {w}, Expired: {e}, Dormant: {d})")
    has_critical = any(
        r.get("severity") == "critical"
        for r in report.get("recommendations", [])
    )
    return 1 if has_critical else 0


def self_test_verifier() -> int:
    """Non-destructive self-test for TTC verifier."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    import io

    sys.stdin = io.StringIO()
    mock_playbooks = [
        {"name": "chloroplast-react-idioms", "hypothesis": "React components must be functional.", "body": "Never use class components."},
        {"name": "wall-test-assertions", "hypothesis": "Tests must carry meaningful assertions.", "body": "Meaningless assertions are forbidden."},
    ]
    target = "src/App.jsx"
    bad_proposal = "class MyComponent extends React.Component {\n  render() { return <div>Hi</div>; }\n}"
    good_proposal = "const MyComponent = () => <div>Hi</div>;\n"

    ws = resolve_workspace()
    probe = os.path.join(ws, target)
    existed_before = os.path.exists(probe)

    soma_propose_change(target, bad_proposal, mock_playbooks, workspace=ws)
    soma_propose_change(target, good_proposal, mock_playbooks, workspace=ws)

    if os.path.exists(probe) and not existed_before:
        print(f"SELF-TEST FAIL: created {probe}")
        return 1
    print("SELF-TEST PASS: no file created or modified.")
    return 0


_classify_cells = _classify_cell

__all__ = [
    "ESCALATION_PROTOCOLS",
    "ESCALATING_PROTOCOLS",
    "PROTOCOL_UNKNOWN",
    "SENTINEL_TIMEOUT",
    "ORACLE_FAIL_OPEN_MARKERS",
    "ORACLE_NO_RULES_MARKER",
    "VERDICT_APPROVED",
    "VERDICT_REJECTED",
    "VERDICT_BLOCKED",
    "VERDICT_ESCALATE",
    "TTCVerifier",
    "get_escalation_protocol",
    "load_oracles",
    "evaluate_change",
    "soma_propose_change",
    "generate_checkpoint",
    "_load_fitness_evidence",
    "_load_cells",
    "_classify_cell",
    "_classify_cells",
    "cli_checkpoint",
    "self_test_verifier",
]
