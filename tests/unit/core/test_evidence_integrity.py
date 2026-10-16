"""Cross-process integrity of the ledger: the one lock is an OS-level lock, idempotent
appends dedupe across processes, and platforms without fcntl keep the semantics."""
from pathlib import Path
import json
import os
import subprocess
import sys
import textwrap


REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))


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
    path = os.path.join(ws, ".aegis", "state", "ledger.jsonl")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_idempotent_append_dedupes_across_processes(tmp_path):
    ws = str(tmp_path)
    code = f"""
        from aegis_core.telemetry_engine import ledger
        for _ in range(20):
            ledger.append({ws!r}, [{{"rule": "rule-a", "outcome": "tp", "source": "ci", "key": "op-1"}}])
    """
    procs = [_spawn(code) for _ in range(4)]
    for p in procs:
        _, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
    rows = _rows(ws)
    assert len(rows) == 1
    assert (rows[0]["key"], rows[0]["seq"]) == ("op-1", 1)


def test_idempotency_without_fcntl(tmp_path):
    ws = str(tmp_path)
    code = f"""
        from aegis_core.telemetry_engine import ledger
        event = {{"rule": "rule-a", "outcome": "tp", "source": "mcp", "key": "k"}}
        a = ledger.append({ws!r}, [event])
        b = ledger.append({ws!r}, [event])
        assert a == b
        try:
            ledger.append({ws!r}, [dict(event, outcome="fp")])
        except ledger.EventConflictError:
            pass
        else:
            raise SystemExit("expected EventConflictError")
        print("ok")
    """
    p = _spawn(code, prelude="import sys; sys.modules['fcntl'] = None\n")
    out, err = p.communicate(timeout=60)
    assert p.returncode == 0, err
    assert out.strip() == "ok"
    assert len(_rows(ws)) == 1
