"""`aegis benchmark`: latency, payload size and Layer 1 throughput, never efficacy (v4.2 #4).

The measurements are tested in tests/unit/core/test_benchmark.py. Here: the arguments and
exit codes (0 done, 1 a measurement that could not be taken honestly, 2 usage or no workspace), the
machine-readable envelope, the notice that this is not an efficacy measure in every
output, the one event it writes, and that nothing else in the workspace or the home
directory changes.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List

import pytest

from aegis_cli.cli import main
from aegis_core import benchmark, events

TS = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")

CANNED: Dict[str, Any] = {
    "runs": 5,
    "python": "3.12.3",
    "platform": "linux",
    "corpus": {"name": "aegis-benchmark-corpus", "sha256": "87b60f1de624fdfbbb2ac2047845ec36d32ebb3f8c18636dbf56bc6ca55fc908",
               "files": 25, "python_files": 24, "rules": 10},
    "scan": {"runs": 5, "files": ["a.py"], "rules_served": 3, "first_run_ms": 40.0,
             "latency_ms": {"p50": 1.5, "p95": 2.5, "min": 1.0, "max": 3.0}, "payload_bytes": 4300,
             "approx_tokens": 1080, "approx_tokens_method": "heuristic"},
    "hook_run": {"runs": 5, "exit_code": 0, "mode": "a fresh isolated Python process per run",
                 "latency_ms": {"p50": 90.0, "p95": 120.0, "min": 80.0, "max": 130.0}},
    "layer1": {"runs": 5, "files": 24, "checks": 48, "findings": 0,
               "pass_ms": {"p50": 96.0, "p95": 110.0, "min": 90.0, "max": 111.0}, "files_per_second": 250.0},
}


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / ".aegis" / "rules").mkdir(parents=True)
    return root.resolve()


@pytest.fixture
def canned(monkeypatch):
    """benchmark.run_benchmark answers with CANNED and remembers how it was called."""
    calls: List[Dict[str, Any]] = []

    def fake(runs=benchmark.DEFAULT_RUNS, **kwargs):
        calls.append({"runs": runs, **kwargs})
        result = copy.deepcopy(CANNED)
        result["runs"] = runs
        return result

    monkeypatch.setattr(benchmark, "run_benchmark", fake)
    return calls


def _tree(root: Path) -> List[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames:
            found.append(os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/") + "/")
        for name in filenames:
            found.append(os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/"))
    return sorted(found)


def _run(capsys, ws: Path, *argv: str):
    rc = main(["benchmark", "--workspace", str(ws), *argv])
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_the_text_report_names_each_measurement_and_says_it_is_not_efficacy(ws, canned, capsys):
    rc, out, err = _run(capsys, ws, "--runs", "5")
    assert (rc, err) == (0, "")
    assert "built-in fixture corpus (25 files, 10 rules, sha256 87b60f1de624), 5 runs" in out
    scan_line = next(line for line in out.splitlines() if "aegis_scan" in line)
    for part in ("p50 1.5 ms", "p95 2.5 ms", "first run 40.0 ms", "payload 4300 bytes (~1080 tokens)"):
        assert part in scan_line
    hook_line = next(line for line in out.splitlines() if line.lstrip().startswith("hook run"))
    assert "p50 90.0 ms" in hook_line and "p95 120.0 ms" in hook_line and "fresh Python process" in hook_line
    layer1_line = next(line for line in out.splitlines() if line.lstrip().startswith("Layer 1"))
    assert "250.0 files/s" in layer1_line and "24 files" in layer1_line and "48 checks" in layer1_line
    assert "0 findings" in layer1_line
    assert benchmark.NOTICE in out
    assert out.rstrip().endswith("Recorded a benchmark event.")


def test_the_json_report_carries_the_envelope_the_numbers_and_the_notice(ws, canned, capsys):
    from aegis_core._version import __version__

    rc, out, err = _run(capsys, ws, "--runs", "5", "--json")
    doc = json.loads(out)
    assert (rc, err) == (0, "")
    assert doc["source"] == "aegis benchmark" and doc["aegis_version"] == __version__
    assert TS.match(doc["checked_at"])
    assert doc["scope"] == {"workspace": str(ws), "runs": 5, "corpus": "built-in fixture corpus"}
    assert doc["status"] == "ok" and doc["recorded"] is True and doc["warnings"] == []
    assert doc["notice"] == benchmark.NOTICE
    assert doc["not_measured"] == ["efficacy: whether Aegis makes an agent's code better"]
    assert len(doc["measures"]) == 3
    for key in ("runs", "python", "platform", "corpus", "scan", "hook_run", "layer1"):
        assert doc[key] == CANNED[key]


def test_the_default_run_count_and_a_given_one_reach_the_benchmark(ws, canned, capsys):
    assert _run(capsys, ws)[0] == 0
    assert _run(capsys, ws, "--runs", "7")[0] == 0
    assert [call["runs"] for call in canned] == [benchmark.DEFAULT_RUNS, 7]


@pytest.mark.parametrize("value", ["0", "-3", "1001", "x", "2.5", ""])
def test_a_run_count_outside_one_to_the_maximum_is_a_usage_error(ws, canned, capsys, value):
    with pytest.raises(SystemExit) as info:
        main(["benchmark", "--workspace", str(ws), "--runs", value])
    assert info.value.code == 2
    assert f"a whole number from 1 to {benchmark.MAX_RUNS}" in capsys.readouterr().err
    assert canned == []


def test_a_real_run_count_at_each_limit_is_accepted(ws, canned, capsys):
    assert _run(capsys, ws, "--runs", "1")[0] == 0 and _run(capsys, ws, "--runs", str(benchmark.MAX_RUNS))[0] == 0


def test_one_benchmark_event_records_the_numbers(ws, canned, capsys):
    _run(capsys, ws, "--runs", "5")
    (row,) = events.read(ws, "benchmark").rows
    assert row["result"] == "ok" and row["detail"] == benchmark.event_detail(CANNED)


def test_a_measurement_that_cannot_be_taken_honestly_is_exit_1_and_records_nothing(ws, monkeypatch, capsys):
    def refuse(*args, **kwargs):
        raise benchmark.BenchmarkError("the hook did not reach the scan gate on the fixture payload")

    monkeypatch.setattr(benchmark, "run_benchmark", refuse)
    rc, out, err = _run(capsys, ws)
    assert (rc, out) == (1, "")
    assert err == "Error: the hook did not reach the scan gate on the fixture payload\n"
    assert events.read(ws).rows == []


def test_the_json_report_of_a_refused_benchmark_is_an_enveloped_error(ws, monkeypatch, capsys):
    def refuse(*args, **kwargs):
        raise benchmark.BenchmarkError("hook run exited 2 on the fixture payload")

    monkeypatch.setattr(benchmark, "run_benchmark", refuse)
    rc, out, err = _run(capsys, ws, "--json")
    doc = json.loads(out)
    assert (rc, err) == (1, "")
    assert doc["source"] == "aegis benchmark" and doc["status"] == "error"
    assert doc["error"] == "hook run exited 2 on the fixture payload" and TS.match(doc["checked_at"])


def test_an_event_that_cannot_be_recorded_is_a_warning_not_a_failure(ws, canned, monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(events, "append", broken)
    rc, out, err = _run(capsys, ws)
    assert rc == 0 and "Recorded a benchmark event." not in out
    assert err == "Warning: the benchmark event could not be recorded (OSError: disk full)\n"
    rc, out, err = _run(capsys, ws, "--json")
    doc = json.loads(out)
    assert rc == 0 and doc["recorded"] is False
    assert doc["warnings"] == ["the benchmark event could not be recorded (OSError: disk full)"]


def test_outside_a_workspace_it_is_refused(tmp_path, canned, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    rc, out, err = _run(capsys, plain)
    assert (rc, out) == (2, "")
    assert err == f"Error: not an Aegis workspace (no .aegis/ in {plain.resolve()}); run aegis init\n"
    assert canned == []
    assert not (plain / ".aegis").exists()  # the event would have created .aegis/state


def test_the_help_says_it_measures_latency_and_size_and_not_efficacy(capsys):
    with pytest.raises(SystemExit) as info:
        main(["benchmark", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert info.value.code == 0
    assert "not an efficacy measure" in out and "fixture" in out and "nothing in your repository" in out


def test_a_real_run_writes_only_the_event_and_touches_neither_the_ledger_nor_the_home(ws, capsys):
    home = Path(os.environ["HOME"])
    before_home = _tree(home)
    before = _tree(ws)
    rc, out, err = _run(capsys, ws, "--runs", "2", "--json")
    doc = json.loads(out)
    assert (rc, err) == (0, "")
    assert doc["scan"]["payload_bytes"] > 1000 and doc["hook_run"]["exit_code"] == 0
    assert doc["layer1"]["files"] == 24 and doc["layer1"]["findings"] == 0
    added = sorted(set(_tree(ws)) - set(before))
    assert set(added) <= {".aegis/state/", ".aegis/state/.gitignore", ".aegis/state/events.jsonl",
                          ".aegis/state/events.lock"}
    assert ".aegis/state/events.jsonl" in added
    assert not (ws / ".aegis/state/ledger.jsonl").exists() and not (ws / ".aegis/state/activity.jsonl").exists()
    assert set(before) <= set(_tree(ws))
    assert _tree(home) == before_home
    (row,) = events.read(ws).rows
    assert row["event"] == "benchmark"
