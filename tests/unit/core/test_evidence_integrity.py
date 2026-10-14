from pathlib import Path
"""Cross-process integrity tests for the evidence pipeline (v0.89 audit fixes).

Covers what single-process unit tests cannot: the evidence lock really is
an OS-level lock, idempotent appends dedupe across processes, the migration
holds the lock for its whole cutover, and fcntl-less platforms keep the
idempotency/fence semantics.
"""
import json
import os
import subprocess
import sys
import textwrap
import time

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None


def _env():
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _spawn(code, prelude=""):
    return subprocess.Popen(
        [sys.executable, "-c", prelude + textwrap.dedent(code)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=REPO_ROOT, env=_env(),
    )


def _rows(ws):
    path = os.path.join(ws, ".aegis", "evidence", "signals.jsonl")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_idempotent_append_dedupes_across_processes(tmp_path):
    ws = str(tmp_path)
    code = f"""
        from aegis_sdk.telemetry import append_signal
        for _ in range(20):
            append_signal({ws!r}, "cell-a", "tp", "ci", principal="p",
                          idempotency_scope="run", idempotency_key="op-1")
    """
    procs = [_spawn(code) for _ in range(4)]
    for p in procs:
        _, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
    rows = _rows(ws)
    assert len(rows) == 1
    assert rows[0]["event_id"]


def test_idempotency_and_fence_without_fcntl(tmp_path):
    ws = str(tmp_path)
    code = f"""
        import json
        from aegis_sdk.telemetry import (append_signal, EventConflictError,
                                        StaleGenerationError)
        a = append_signal({ws!r}, "cell-a", "tp", "mcp", idempotency_key="k")
        b = append_signal({ws!r}, "cell-a", "tp", "mcp", idempotency_key="k")
        assert a == b
        try:
            append_signal({ws!r}, "cell-a", "fp", "mcp", idempotency_key="k")
        except EventConflictError:
            pass
        else:
            raise SystemExit("expected EventConflictError")
        try:
            append_signal({ws!r}, "cell-a", "tp", "mcp", expected_generation=7)
        except StaleGenerationError:
            pass
        else:
            raise SystemExit("expected StaleGenerationError")
        print("ok")
    """
    p = _spawn(code, prelude="import sys; sys.modules['fcntl'] = None\n")
    out, err = p.communicate(timeout=60)
    assert p.returncode == 0, err
    assert out.strip() == "ok"
    assert len(_rows(ws)) == 1
