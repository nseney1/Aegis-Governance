"""Tests for soma report — Session report card.

All tests use tmp_path for filesystem operations.
Verifies session boundary detection, bar chart scaling, formatting,
and ensures no speculative metrics or biological terms in user-facing output.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from soma_cli.report import run_report


def _create_event(cell: str, triggered_at: datetime) -> dict:
    """Helper to create a canonical signals.jsonl trigger record."""
    return {
        "cell": cell,
        "signal": "trigger",
        "timestamp": triggered_at.isoformat(),
    }


def _write_ledger(tmp_path, events: list[dict]) -> None:
    """Helper to write events into <tmp_path>/.soma/evidence/signals.jsonl."""
    ledger = tmp_path / ".soma" / "evidence" / "signals.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(ev) + "\n" for ev in events)


class TestReportEmpty:
    """Verify handling of missing or empty evidence ledger."""

    def test_report_empty_ledger(self, tmp_path, capsys):
        """No file → prints 'No session data' message, returns 0."""
        args = argparse.Namespace(session=-1, _root=tmp_path)
        ret = run_report(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "No session data yet. Run a governed session first." in captured.out

    def test_report_empty_file(self, tmp_path, capsys):
        """Empty file → prints 'No session data', returns 0."""
        ledger = tmp_path / ".soma" / "evidence" / "signals.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text("")

        args = argparse.Namespace(session=-1, _root=tmp_path)
        ret = run_report(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "No session data yet. Run a governed session first." in captured.out


class TestReportSingleSession:
    """Verify single session parsing, counting, and box display."""

    def test_report_single_session(self, tmp_path, capsys):
        """Write 5 events (3 unique cells) → verify trigger counts in output."""
        base_time = datetime(2026, 9, 30, 14, 0, 0, tzinfo=timezone.utc)
        events = [
            _create_event("providence", base_time),
            _create_event("providence", base_time + timedelta(minutes=1)),
            _create_event("providence", base_time + timedelta(minutes=2)),
            _create_event("testing", base_time + timedelta(minutes=3)),
            _create_event("destructive-ops", base_time + timedelta(minutes=4)),
        ]
        _write_ledger(tmp_path, events)

        args = argparse.Namespace(session=-1, _root=tmp_path)
        ret = run_report(args)
        assert ret == 0

        captured = capsys.readouterr()
        out = captured.out

        # Verify summary statistics
        assert "Rules triggered:    3 of 5" in out
        assert "Total events:       5" in out

        # Verify trigger counts for active rules
        assert "providence" in out
        assert "3 fires" in out
        assert "testing" in out
        assert "1 fire" in out
        assert "destructive-ops" in out
        # Inactive rules show 0 fires
        assert "cost-optimization" in out
        assert "0 fires" in out
        assert "git-workflow" in out


class TestReportSessionBoundary:
    """Verify grouping of events across session gaps."""

    def test_report_session_boundary_detection(self, tmp_path, capsys):
        """Write events with >30 min gap → verify they split into 2 sessions.

        First 3 events within 5 minutes, then a 45-minute gap, then 2 more events.
        Verify report defaults to latest session (2 events).
        """
        t0 = datetime(2026, 9, 30, 10, 0, 0, tzinfo=timezone.utc)
        events = [
            # Session 1: 3 events within 5 min
            _create_event("providence", t0),
            _create_event("testing", t0 + timedelta(minutes=2)),
            _create_event("providence", t0 + timedelta(minutes=4)),
            # 45-minute gap: 10:04 to 10:49 (>30 min)
            # Session 2: 2 events
            _create_event("destructive-ops", t0 + timedelta(minutes=49)),
            _create_event("destructive-ops", t0 + timedelta(minutes=51)),
        ]
        _write_ledger(tmp_path, events)

        # Default: latest session
        args = argparse.Namespace(session=-1, _root=tmp_path)
        ret = run_report(args)
        assert ret == 0

        captured = capsys.readouterr()
        assert "Total events:       2" in captured.out
        assert "destructive-ops" in captured.out
        assert "2 fires" in captured.out

        # Explicit index 0: first session (3 events)
        args_first = argparse.Namespace(session=0, _root=tmp_path)
        ret_first = run_report(args_first)
        assert ret_first == 0

        captured_first = capsys.readouterr()
        assert "Total events:       3" in captured_first.out
        assert "providence" in captured_first.out
        assert "2 fires" in captured_first.out


class TestReportBarChartScaling:
    """Verify ASCII bar chart scaling proportional to max fires."""

    def test_report_bar_chart_scaling(self, tmp_path, capsys):
        """8 fires max, 4 fires → should get 4 blocks filled."""
        base_time = datetime(2026, 9, 30, 16, 0, 0, tzinfo=timezone.utc)
        events = []
        # 8 fires for providence (max)
        for i in range(8):
            events.append(_create_event("providence", base_time + timedelta(seconds=i * 10)))
        # 4 fires for testing (half of max)
        for i in range(4):
            events.append(_create_event("testing", base_time + timedelta(seconds=100 + i * 10)))

        _write_ledger(tmp_path, events)

        args = argparse.Namespace(session=-1, _root=tmp_path)
        ret = run_report(args)
        assert ret == 0

        captured = capsys.readouterr()
        out = captured.out

        # 8 fires is max -> full bar (8 filled blocks)
        assert "████████" in out
        # 4 fires -> 4 blocks filled, 4 empty
        assert "████░░░░" in out


class TestReportConstraints:
    """Verify no speculative metrics, no biology terms, and clean exit codes."""

    def test_report_no_speculative_metrics(self, tmp_path, capsys):
        """Output contains none of: 'estimated', 'avoided', 'saved', 'waste'."""
        base_time = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
        events = [
            _create_event("providence", base_time),
            _create_event("testing", base_time + timedelta(minutes=1)),
        ]
        _write_ledger(tmp_path, events)

        args = argparse.Namespace(session=-1, _root=tmp_path)
        run_report(args)

        captured = capsys.readouterr()
        out_lower = captured.out.lower()

        # No speculative metrics
        for forbidden in ["estimated", "avoided", "saved", "waste"]:
            assert forbidden not in out_lower, f"Found speculative metric '{forbidden}' in output"

        # No biology terms in user-facing output
        for bio in ["genome", "enzyme", "cell", "organ", "dna", "fitness"]:
            assert bio not in out_lower, f"Found biological term '{bio}' in user-facing output"

    def test_report_returns_zero(self, tmp_path):
        """returns 0 on success."""
        base_time = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
        events = [_create_event("providence", base_time)]
        _write_ledger(tmp_path, events)

        args = argparse.Namespace(session=-1, _root=tmp_path)
        assert run_report(args) == 0


class TestReportEdgeCases:
    """Additional edge cases for robustness."""

    def test_report_invalid_session_index(self, tmp_path, capsys):
        """Invalid session index prints error and returns 1."""
        base_time = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
        _write_ledger(tmp_path, [_create_event("providence", base_time)])

        args = argparse.Namespace(session=10, _root=tmp_path)
        ret = run_report(args)
        assert ret == 1
        captured = capsys.readouterr()
        assert "Session index 10 not found" in captured.out

    def test_report_corrupted_lines_skipped(self, tmp_path, capsys):
        """Corrupted or malformed lines are safely skipped."""
        ledger = tmp_path / ".soma" / "evidence" / "signals.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(
            "\n"
            "not-valid-json\n"
            '{"incomplete": true}\n'
            '{"cell": "providence", "signal": "trigger", "timestamp": "2026-09-30T12:00:00Z"}\n'
        )

        args = argparse.Namespace(session=-1, _root=tmp_path)
        ret = run_report(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "Total events:       1" in captured.out

    def test_report_custom_rules(self, tmp_path, capsys):
        """Custom rules without starter rules format cleanly."""
        base_time = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
        events = [
            _create_event("custom-rule-a", base_time),
            _create_event("custom-rule-b", base_time + timedelta(minutes=1)),
        ]
        _write_ledger(tmp_path, events)

        args = argparse.Namespace(session=-1, _root=tmp_path)
        ret = run_report(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "Rules triggered:    2 of 2" in captured.out
        assert "custom-rule-a" in captured.out
        assert "custom-rule-b" in captured.out

    def test_report_command_contract(self):
        from unittest.mock import patch
        from soma_cli.report import ReportCommand
        cmd = ReportCommand()
        parser = argparse.ArgumentParser()
        cmd.configure_parser(parser)
        parsed = parser.parse_args(["--session", "2"])
        assert parsed.session == 2

        with patch("soma_cli.report.run_report", return_value=0) as mock_run:
            assert cmd.execute(parsed) == 0
            mock_run.assert_called_once_with(parsed)

    def test_report_json_and_plain_modes(self, tmp_path, capsys):
        """v3.0.0: report supports --json and --plain without leaking ANSI or Unicode emojis."""
        base_time = datetime(2026, 9, 30, 14, 0, 0, tzinfo=timezone.utc)
        _write_ledger(
            tmp_path,
            [
                _create_event("providence", base_time),
                _create_event("providence", base_time + timedelta(minutes=1)),
            ],
        )

        # JSON mode
        assert run_report(argparse.Namespace(session=-1, _root=tmp_path, json=True)) == 0
        raw_json = capsys.readouterr().out
        assert "\x1b[" not in raw_json
        payload = json.loads(raw_json)
        assert payload["total_events"] == 2
        assert payload["rules_triggered"] == 1
        assert any(r["rule"] == "providence" and r["fires"] == 2 for r in payload["rules"])

        # Plain mode
        assert run_report(argparse.Namespace(session=-1, _root=tmp_path, plain=True)) == 0
        out_plain = capsys.readouterr().out
        assert "\x1b[" not in out_plain
        assert "📊" not in out_plain
        assert "🛡️" not in out_plain
        assert "Rules triggered:    1 of 5" in out_plain

