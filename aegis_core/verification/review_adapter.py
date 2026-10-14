from __future__ import annotations

"""Review adapter: converts Prosecutor/Defender findings to arbiter inputs.

Maps Supercell review findings (JSON) into Prediction/Claim objects that the
deterministic arbiter can process. This is the bridge between prose-based
review and set-algebra arbitration.

Usage:
    from aegis_core.verification.review_adapter import (
        findings_to_predictions, findings_to_claims, run_review_arbitration,
    )
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from . import (
    ArbitrationResult, Claim, Prediction, RiskCategory,
    Severity, ToolEvidence,
)
from .arbiter import arbitrate, format_report


# Mapping from review severity strings to Severity enum
_SEVERITY_MAP = {
    "block": Severity.CRITICAL,
    "BLOCK": Severity.CRITICAL,
    "warn": Severity.HIGH,
    "WARN": Severity.HIGH,
    "info": Severity.LOW,
    "INFO": Severity.LOW,
}

# Mapping from review domain/keywords to RiskCategory
_KEYWORD_TO_CATEGORY: dict[str, RiskCategory] = {
    # Security
    "code_injection": RiskCategory.CODE_INJECTION,
    "injection": RiskCategory.CODE_INJECTION,
    "format string attack": RiskCategory.CODE_INJECTION,
    "f-string injection": RiskCategory.CODE_INJECTION,
    "path_traversal": RiskCategory.PATH_TRAVERSAL,
    "traversal": RiskCategory.PATH_TRAVERSAL,
    "containment": RiskCategory.PATH_TRAVERSAL,
    "shell injection": RiskCategory.SHELL_INJECTION,
    "shell command": RiskCategory.SHELL_INJECTION,
    "shell=true": RiskCategory.SHELL_INJECTION,
    # Structural
    "dead_code": RiskCategory.DEAD_CODE,
    "dead code": RiskCategory.DEAD_CODE,
    "orphan": RiskCategory.MISSING_WIRE,
    "missing_wire": RiskCategory.MISSING_WIRE,
    "unused": RiskCategory.DEAD_CODE,
    # Contracts
    "contract_drift": RiskCategory.CONTRACT_DRIFT,
    "signature": RiskCategory.CONTRACT_DRIFT,
    "schema": RiskCategory.CONTRACT_DRIFT,
    "type_mismatch": RiskCategory.TYPE_MISMATCH,
    "timezone": RiskCategory.TYPE_MISMATCH,
    # Testing
    "missing_coverage": RiskCategory.MISSING_COVERAGE,
    "untested": RiskCategory.MISSING_COVERAGE,
    "missing test": RiskCategory.MISSING_COVERAGE,
    "tautological": RiskCategory.TAUTOLOGICAL_TEST,
    # Quality
    "dry": RiskCategory.DRY_VIOLATION,
    "duplicate": RiskCategory.DRY_VIOLATION,
    "copy-paste": RiskCategory.DRY_VIOLATION,
    "doc_drift": RiskCategory.DOC_DRIFT,
    "documentation": RiskCategory.DOC_DRIFT,
    "readme": RiskCategory.DOC_DRIFT,
    "changelog": RiskCategory.DOC_DRIFT,
    "convention": RiskCategory.CONVENTION_VIOLATION,
    "enforcement": RiskCategory.CONVENTION_VIOLATION,
    # State
    "state_corruption": RiskCategory.STATE_CORRUPTION,
    "boundary": RiskCategory.BOUNDARY_VIOLATION,
    "threshold": RiskCategory.BOUNDARY_VIOLATION,
    # Portability
    "portability": RiskCategory.PLATFORM_INCOMPATIBLE,
    "windows": RiskCategory.PLATFORM_INCOMPATIBLE,
    "encoding": RiskCategory.PLATFORM_INCOMPATIBLE,
}


def _classify_finding(text: str) -> RiskCategory:
    """Map a finding description to a RiskCategory via keyword matching.

    Falls back to CONTRACT_DRIFT if no keyword matches.
    """
    lower = text.lower()
    for keyword, category in _KEYWORD_TO_CATEGORY.items():
        if keyword in lower:
            return category
    return RiskCategory.CONTRACT_DRIFT


def findings_to_predictions(findings: list[dict]) -> list[Prediction]:
    """Convert Prosecutor findings (JSON dicts) to Prediction objects.

    Each finding dict must have:
      - severity: "BLOCK" | "WARN" | "INFO"
      - issue: str description
      - file: str (optional)
      - function: str (optional)
    """
    predictions = []
    for f in findings:
        severity = _SEVERITY_MAP.get(f.get("severity", "INFO"), Severity.LOW)
        issue = f.get("issue", "")
        category = _classify_finding(issue)
        predictions.append(Prediction(
            category=category,
            severity=severity,
            risk=issue,
            mechanism=f.get("mechanism", issue),
            affected_function=f.get("function", f.get("file", "unknown")),
        ))
    return predictions


def findings_to_claims(verifications: list[dict]) -> list[Claim]:
    """Convert Defender verifications (JSON dicts) to Claim objects.

    Each verification dict must have:
      - verdict: "CONFIRMED" | "CONCERN"
      - claim: str description
      - file: str
      - line: int (optional)
      - tests: list[str] (optional)
    """
    claims = []
    for v in verifications:
        if v.get("verdict") != "CONFIRMED":
            continue  # Only confirmed claims go to the arbiter
        claim_text = v.get("claim", "")
        category = _classify_finding(claim_text)
        claims.append(Claim(
            category=category,
            claim=claim_text,
            evidence_file=v.get("file", "unknown"),
            evidence_line=v.get("line", 0),
            tests_covering=v.get("tests", []),
        ))
    return claims


def run_review_arbitration(
    prosecutor_findings: list[dict],
    defender_verifications: list[dict],
    layer1_evidence: list[ToolEvidence] | None = None,
) -> ArbitrationResult:
    """Run deterministic arbitration on review findings.

    This is the un-bypassable entry point. Converts prose findings to
    structured objects and feeds them through the arbiter.

    Returns ArbitrationResult with deterministic SHIP/BLOCK/REVISE verdict.
    """
    predictions = findings_to_predictions(prosecutor_findings)
    claims = findings_to_claims(defender_verifications)
    evidence = layer1_evidence or []

    return arbitrate(predictions, claims, evidence)


def _scan_highest_cycle(evidence_dir: Path) -> int:
    """Fallback scanner finding the highest cycle number on disk."""
    max_cycle = 0
    pattern = re.compile(r"^arbitration_cycle_(\d+)\.json$")
    try:
        if evidence_dir.is_dir():
            for entry in evidence_dir.iterdir():
                if entry.is_file():
                    m = pattern.match(entry.name)
                    if m:
                        c = int(m.group(1))
                        if c > max_cycle:
                            max_cycle = c
    except OSError:
        pass
    return max_cycle


def _resolve_evidence_dir(workspace: str | os.PathLike) -> Path:
    ws_path = Path(workspace)
    aegis_ev = ws_path / ".aegis" / "evidence"
    if aegis_ev.is_dir():
        return aegis_ev
    soma_ev = ws_path / ".soma" / "evidence"
    if soma_ev.is_dir():
        return soma_ev
    if (ws_path / ".aegis").is_dir():
        return aegis_ev
    if (ws_path / ".soma").is_dir():
        return soma_ev
    if os.environ.get("AEGIS_WORKSPACE"):
        return aegis_ev
    return soma_ev


def get_next_cycle_number(workspace: str | os.PathLike) -> int:
    """Find the next arbitration cycle number atomically under file lock.

    Maintains `.aegis/evidence/.cycle_counter` to avoid O(N) filesystem sweeps,
    with fallback recovery scanning existing cycles if the counter file is absent or corrupt.
    """
    evidence_dir = _resolve_evidence_dir(workspace)
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
    except OSError:  # pragma: no cover
        pass

    counter_file = evidence_dir / ".cycle_counter"
    lock_file = evidence_dir / ".evidence.lock"

    lock_fd = None
    try:
        import fcntl
        lock_fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
    except Exception:  # pragma: no cover
        lock_fd = None

    try:
        highest = _scan_highest_cycle(evidence_dir)
        current_counter = 0
        if counter_file.is_file():
            try:
                current_counter = int(counter_file.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                current_counter = 0

        next_cycle = max(current_counter, highest) + 1
        try:
            counter_file.write_text(f"{next_cycle}\n", encoding="utf-8")
        except OSError:  # pragma: no cover
            pass
        return next_cycle
    finally:
        if lock_fd is not None:
            try:
                import fcntl
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except Exception:  # pragma: no cover
                pass
            try:
                os.close(lock_fd)
            except Exception:  # pragma: no cover
                pass


def get_latest_arbitration_evidence(workspace: str | os.PathLike) -> tuple[int, dict | None]:
    """Retrieve the latest arbitration cycle record and cycle number."""
    evidence_dir = _resolve_evidence_dir(workspace)
    if not evidence_dir.is_dir():
        return 0, None

    max_cycle = 0
    latest_file = None
    pattern = re.compile(r"^arbitration_cycle_(\d+)\.json$")
    try:
        for entry in evidence_dir.iterdir():
            if entry.is_file():
                m = pattern.match(entry.name)
                if m:
                    cycle_num = int(m.group(1))
                    if cycle_num > max_cycle:
                        max_cycle = cycle_num
                        latest_file = entry
    except OSError:
        return 0, None

    if latest_file is None:
        return 0, None

    try:
        data = json.loads(latest_file.read_text(encoding="utf-8"))
        return max_cycle, data
    except Exception:
        return max_cycle, None


def save_arbitration_evidence(
    result: ArbitrationResult,
    workspace: str | os.PathLike,
    cycle: int | None = None,
    target_files: list[str] | None = None,
) -> str:
    """Persist arbitration result to .aegis/evidence/ for checkpoint verification.

    The checkpoint gate checks for this file to prevent bypassing the arbiter.
    Uses atomic write (tempfile + rename) to prevent corruption on crash.

    Returns the path to the saved evidence file.
    """
    if cycle is None:
        cycle = get_next_cycle_number(workspace)
    else:
        # Sanitize cycle to prevent path traversal
        cycle = int(cycle)
        if cycle < 1:
            raise ValueError(f"cycle must be a positive integer, got {cycle}")

    evidence_dir = _resolve_evidence_dir(workspace)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    target = evidence_dir / f"arbitration_cycle_{cycle}.json"

    record = {
        "cycle": cycle,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "verdict": result.verdict.value,
        "divergence_count": len(result.divergences),
        "convergence_count": len(result.convergences),
        "prediction_count": len(result.predictions),
        "claim_count": len(result.claims),
        "convergences": [c.value for c in result.convergences],
        "divergences": [
            {
                "type": d.divergence_type,
                "category": d.category.value,
                "resolution": d.resolution,
            }
            for d in result.divergences
        ],
    }
    if target_files:
        record["target_files"] = list(target_files)

    try:
        git_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(workspace), capture_output=True, text=True, timeout=3,
        )
        if git_sha.returncode == 0:
            record["commit_sha"] = git_sha.stdout.strip()
        git_tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=str(workspace), capture_output=True, text=True, timeout=3,
        )
        if git_tree.returncode == 0:
            record["tree_hash"] = git_tree.stdout.strip()
    except Exception:
        pass

    # Atomic write: write to temp file, then rename
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(evidence_dir), suffix='.json')
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(record, f, indent=2)
        os.replace(tmp_path, str(target))
        try:
            counter_file = evidence_dir / ".cycle_counter"
            current = 0
            if counter_file.is_file():
                current = int(counter_file.read_text(encoding="utf-8").strip())
            if cycle > current:
                counter_file.write_text(f"{cycle}\n", encoding="utf-8")
        except Exception:  # pragma: no cover
            pass
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return str(target)
