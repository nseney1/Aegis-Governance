"""Verifiable outcome reflection: test/build runner execution, MCP outcomes, and ambient telemetry."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from typing import Any, Optional

from aegis_core.workspace import Workspace, as_workspace, resolve_workspace

__all__ = [
    "VERIFY_TIMEOUT",
    "detect_test_runner",
    "capture_test_outcome",
    "capture_build_outcome",
    "capture_mcp_outcomes",
    "record_verification_telemetry",
]

VERIFY_TIMEOUT = int(os.environ.get("SOMA_VERIFY_TIMEOUT", "60"))


def _run_verify(cmd: str, cwd: str, timeout: Optional[int] = None) -> Optional[dict]:
    """Run a verification command, return (exit_code, stdout_snippet)."""
    if timeout is None:
        timeout = VERIFY_TIMEOUT
    try:
        result = subprocess.run(
            cmd, cwd=cwd, shell=True, timeout=timeout,
            capture_output=True, text=True
        )
        stdout_tail = "\n".join(result.stdout.strip().split("\n")[-10:])
        stderr_tail = "\n".join(result.stderr.strip().split("\n")[-5:])
        if result.returncode == 127:
            return {
                "exit_code": 127,
                "passed": None,
                "error": f"command not found: {cmd}",
                "stdout_tail": stdout_tail[:500],
                "stderr_tail": stderr_tail[:300],
            }
        return {
            "exit_code": result.returncode,
            "passed": result.returncode == 0,
            "stdout_tail": stdout_tail[:500],
            "stderr_tail": stderr_tail[:300],
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "passed": None, "error": "timeout"}
    except FileNotFoundError:
        return None
    except Exception as e:
        return {"exit_code": -1, "passed": None, "error": str(e)[:200]}


def detect_test_runner(workspace: str) -> tuple[Optional[str], Optional[str]]:
    """Detect which test framework this project uses. Returns (command, framework_name)."""
    checks = [
        ("pyproject.toml", "pytest", "python3 -m pytest --tb=short -q --no-header 2>&1", 'python3 -c "import pytest" 2>/dev/null'),
        ("setup.cfg", "pytest", "python3 -m pytest --tb=short -q --no-header 2>&1", 'python3 -c "import pytest" 2>/dev/null'),
        ("pytest.ini", "pytest", "python3 -m pytest --tb=short -q --no-header 2>&1", 'python3 -c "import pytest" 2>/dev/null'),
        ("jest.config.js", "jest", "npx jest --silent --no-coverage 2>&1", "npx jest --version 2>/dev/null"),
        ("jest.config.ts", "jest", "npx jest --silent --no-coverage 2>&1", "npx jest --version 2>/dev/null"),
        ("vitest.config.ts", "vitest", "npx vitest run --reporter=dot 2>&1", "npx vitest --version 2>/dev/null"),
        ("package.json", "npm test", "npm test 2>&1", None),
        ("go.mod", "go test", "go test ./... -count=1 -short 2>&1", "go version 2>/dev/null"),
        ("Cargo.toml", "cargo test", "cargo test --quiet 2>&1", "cargo --version 2>/dev/null"),
    ]

    for config_file, name, test_cmd, check_cmd in checks:
        if os.path.exists(os.path.join(workspace, config_file)):
            if check_cmd is None or subprocess.run(check_cmd, shell=True, cwd=workspace, capture_output=True).returncode == 0:
                return test_cmd, name

    # Fallback to Makefile test target (only if make binary is installed)
    makefile = os.path.join(workspace, "Makefile")
    if os.path.exists(makefile) and shutil.which("make") is not None:
        try:
            with open(makefile, "r", encoding="utf-8") as f:
                if re.search(r"^test\s*:", f.read(), re.MULTILINE):
                    return "make test", "Makefile"
        except Exception:
            pass

    return None, None


def capture_test_outcome(workspace: str) -> dict:
    """Ground truth: run tests and capture exit code."""
    test_cmd, framework = detect_test_runner(workspace)
    if not test_cmd:
        return {"verified": False, "reason": "no test runner detected", "passed": None}

    outcome = _run_verify(test_cmd, cwd=workspace)
    if not outcome or outcome.get("passed") is None:
        return {"verified": False, "reason": outcome.get("error", "test execution failed") if outcome else "failed to run", "passed": None, "framework": framework}

    return {
        "verified": True,
        "passed": outcome["passed"],
        "exit_code": outcome["exit_code"],
        "framework": framework,
        "snippet": outcome["stdout_tail"] if not outcome["passed"] else "",
    }


def capture_build_outcome(workspace: str) -> dict:
    """Strong signal: did the build succeed?"""
    build_checks = [
        ("Cargo.toml", "cargo check --quiet 2>&1"),
        ("package.json", "npm run build --if-present 2>&1"),
        ("go.mod", "go vet ./... 2>&1"),
    ]
    for config_file, cmd in build_checks:
        if os.path.exists(os.path.join(workspace, config_file)):
            outcome = _run_verify(cmd, cwd=workspace)
            if outcome and outcome.get("passed") is not None:
                return {
                    "verified": True,
                    "passed": outcome["passed"],
                    "exit_code": outcome["exit_code"],
                    "command": cmd.split()[0],
                }
    return {"verified": False, "reason": "no build system detected", "passed": None}


def capture_mcp_outcomes(workspace: Workspace | Path | str) -> list[dict]:
    """Read any soma_report_outcome calls from this session from .soma/evidence/signals.jsonl."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    signals_file = str(ws.signals_file)
    outcomes = []
    if not os.path.isfile(signals_file):
        return outcomes
    try:
        with open(signals_file, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    record = json.loads(line_str)
                except Exception:
                    continue

                sig_type = record.get("signal_type") or record.get("signal") or record.get("outcome")
                if not sig_type:
                    continue

                outcome = record.get("outcome")
                if not outcome:
                    if sig_type in ("tp", "success"):
                        outcome = "success"
                    elif sig_type in ("fp", "failure"):
                        outcome = "failure"
                    elif sig_type in ("trigger", "partial"):
                        outcome = "partial"
                    else:
                        outcome = str(sig_type)
                record["outcome"] = outcome

                cell_id = record.get("cell_id") or record.get("cell_name") or record.get("cell")
                if cell_id and "cell_id" not in record:
                    record["cell_id"] = cell_id
                if cell_id and "cells_used" not in record:
                    record["cells_used"] = [cell_id]

                outcomes.append(record)
    except Exception as exc:
        print(f"    ! failed to read signals file: {exc}", file=sys.stderr)
    return outcomes


def record_verification_telemetry(
    workspace: str,
    target_files: list[str],
    passed: bool,
    verdict: Any = None,
    layer1_evidence: Any = None,
    source: str = "session",
    run_id: Optional[str] = None,
) -> bool:
    """Record ambient verification evidence (triggers and outcomes) for matched cells."""
    if not workspace or not target_files:
        return False

    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells_dir = ws.cells_dir
    if not cells_dir.is_dir():
        return False

    from aegis_core.outcomes.engine import match_cells_to_changes
    from aegis_core.outcomes.fitness import compute_credit_weights, update_cell_fitness

    matched = match_cells_to_changes(ws, target_files)
    if not matched:
        return False

    from aegis_core.telemetry import append_signals

    if run_id is None:
        run_id = secrets.token_hex(16)

    credit_weights = compute_credit_weights(matched, target_files)
    events = []
    fitness_signals = []
    sig_type = "tp" if passed else "fp"
    signal_val = 1.0 if passed else -1.0

    for cell in matched:
        cell_id = cell.get("_name") or cell.get("id")
        if not cell_id:
            continue
        weight = float(credit_weights.get(cell_id, 1.0))
        weight = max(0.0, min(1.0, weight))

        # 1. Trigger event
        events.append({
            "cell_name": cell_id,
            "signal_type": "trigger",
            "source": source,
            "metadata": {
                "credit_weight": 1.0,
                "verdict": str(verdict) if verdict is not None else ("PASS" if passed else "FAIL"),
                "target_files": target_files[:20],
            },
            "principal": "verification",
            "idempotency_scope": "run",
            "idempotency_key": f"{run_id}:trig:{cell_id}",
        })

        # 2. Outcome event
        events.append({
            "cell_name": cell_id,
            "signal_type": sig_type,
            "source": source,
            "metadata": {
                "credit_weight": weight,
                "verdict": str(verdict) if verdict is not None else ("PASS" if passed else "FAIL"),
                "passed": passed,
                "evidence_checks": len(layer1_evidence) if layer1_evidence else 0,
            },
            "principal": "verification",
            "idempotency_scope": "run",
            "idempotency_key": f"{run_id}:out:{cell_id}",
        })

        fitness_signals.append({
            "cell": cell_id,
            "_path": cell.get("_path"),
            "signal": signal_val,
            "credit_weight": weight,
        })

    try:
        append_signals(workspace, events)
        if fitness_signals:
            update_cell_fitness(workspace, fitness_signals)
        return True
    except Exception as exc:
        print(f"    ! failed to record ambient verification telemetry: {exc}", file=sys.stderr)
        return False
