"""Tests for soma status — Phase C test gate.

All tests use tmp_path to avoid touching the real filesystem.
"""
import argparse
from datetime import date, timedelta
import json


from aegis_cli.status import run_status


class TestStatus:
    """Test suite for the soma status subcommand."""

    def test_status_no_rules(self, tmp_path, capsys):
        """Empty dirs → '0 active' and helpful message."""
        (tmp_path / "genome").mkdir()
        (tmp_path / ".aegis" / "rules").mkdir(parents=True)
        args = argparse.Namespace(_root=tmp_path)
        ret = run_status(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "0 active" in captured.out
        assert "No rules found" in captured.out

    def test_status_counts_core_rules(self, tmp_path, capsys):
        """Create 3 .md files in mock genome/ dir → '3 active'."""
        genome = tmp_path / "genome"
        genome.mkdir()
        (genome / "rule1.md").write_text("# Rule 1 content\n")
        (genome / "rule2.md").write_text("# Rule 2 content\n")
        (genome / "rule3.md").write_text("# Rule 3 content\n")
        # README should be excluded
        (genome / "README.md").write_text("# Readme info\n")

        args = argparse.Namespace(_root=tmp_path)
        ret = run_status(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "3 active" in captured.out

    def test_status_counts_adaptive_rules(self, tmp_path, capsys):
        """Create 2 .md files in mock .aegis/rules/ → counts them."""
        cells = tmp_path / ".aegis" / "rules"
        cells.mkdir(parents=True)
        (cells / "rule1.md").write_text("# Rule 1\n")
        sub = cells / "patterns"
        sub.mkdir()
        (sub / "rule2.md").write_text("# Rule 2\n")
        # README should be excluded
        (cells / "README.md").write_text("# Ignore me\n")

        args = argparse.Namespace(_root=tmp_path)
        ret = run_status(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "Adaptive rules: 2 (traps/patterns)" in captured.out

    def test_status_reads_trigger_counts(self, tmp_path, capsys):
        """Ledger rows win over contradictory legacy evidence."""
        genome = tmp_path / "genome"
        genome.mkdir()
        (genome / "rule-a.md").write_text("# Rule A\n")
        (genome / "rule-b.md").write_text("# Rule B\n")

        evidence = tmp_path / ".aegis" / "evidence"
        evidence.mkdir(parents=True)
        records = [
            {"cell": "rule-a", "signal": "trigger", "timestamp": "2026-09-30T12:00:00Z"},
            {"cell": "rule-a", "signal": "trigger", "timestamp": "2026-09-30T12:01:00Z"},
            {"cell": "rule-a", "signal": "trigger", "timestamp": "2026-09-30T12:02:00Z"},
            {"cell": "rule-b", "signal": "trigger", "timestamp": "2026-09-30T12:03:00Z"},
        ]
        state = tmp_path / ".aegis" / "state"
        state.mkdir(parents=True)
        (state / "ledger.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n"
        )
        legacy_records = [
            {"cell_id": "rule-a"},
            {"cell_id": "rule-b"},
            {"cell_id": "rule-b"},
            {"cell_id": "rule-b"},
        ]
        (evidence / "fitness.jsonl").write_text(
            "\n".join(json.dumps(r) for r in legacy_records) + "\n"
        )

        args = argparse.Namespace(_root=tmp_path)
        ret = run_status(args)
        assert ret == 0
        captured = capsys.readouterr()

        lines = captured.out.splitlines()
        rule_a_line = next((line for line in lines if "rule-a" in line), None)
        rule_b_line = next((line for line in lines if "rule-b" in line), None)
        assert rule_a_line is not None
        assert rule_b_line is not None

        # Verify exact counts associated with the rules
        cols_a = rule_a_line.split()
        cols_b = rule_b_line.split()
        assert cols_a[0] == "rule-a"
        assert cols_a[1] == "3"
        assert cols_b[0] == "rule-b"
        assert cols_b[1] == "1"

    def test_status_output_no_biology_terms(self, tmp_path, capsys):
        """Capture output, assert no 'enzyme', 'vacuole', 'genome', 'cell' in output."""
        genome = tmp_path / "genome"
        genome.mkdir()
        (genome / "rule-a.md").write_text("# Rule A\n")

        cells = tmp_path / ".aegis" / "rules"
        cells.mkdir(parents=True)
        (cells / "rule-b.md").write_text(
            "---\ncreated: 2026-09-01\nexpiry_days: 30\n---\n# Rule B\n"
        )

        state = tmp_path / ".aegis" / "state"
        state.mkdir(parents=True)
        (state / "ledger.jsonl").write_text(
            json.dumps(
                {
                    "cell": "rule-a",
                    "signal": "trigger",
                    "timestamp": "2026-09-30T12:00:00Z",
                }
            ) + "\n"
        )

        args = argparse.Namespace(_root=tmp_path)
        ret = run_status(args)
        assert ret == 0
        captured = capsys.readouterr()

        out_lower = captured.out.lower()
        for term in ["enzyme", "vacuole", "genome", "cell"]:
            assert term not in out_lower, (
                f"Biology term '{term}' found in user output:\n{captured.out}"
            )

    def test_status_returns_zero(self, tmp_path):
        """run_status returns 0."""
        args = argparse.Namespace(_root=tmp_path)
        assert run_status(args) == 0

    def test_status_oracle_rules_counted(self, tmp_path, capsys):
        """Core rules include .md files in genome/.oracles/."""
        genome = tmp_path / "genome"
        oracles = genome / ".oracles"
        oracles.mkdir(parents=True)
        (genome / "base.md").write_text("# Base\n")
        (oracles / "oracle1.md").write_text("# Oracle 1\n")
        (oracles / "README.md").write_text("# Ignore\n")

        args = argparse.Namespace(_root=tmp_path)
        ret = run_status(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "2 active" in captured.out
        assert "base" in captured.out
        assert "oracle1" in captured.out

    def test_status_context_load_calculation(self, tmp_path, capsys):
        """Approximate context overhead divides total chars by 4."""
        genome = tmp_path / "genome"
        genome.mkdir()
        content = "x" * 400
        (genome / "rule1.md").write_text(content)

        args = argparse.Namespace(_root=tmp_path)
        ret = run_status(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "~100 tokens (pre-JIT max)" in captured.out

    def test_status_adaptive_rule_expiry_active(self, tmp_path, capsys):
        """Active adaptive rules show remaining days."""
        cells = tmp_path / ".aegis" / "rules"
        cells.mkdir(parents=True)
        created = (date.today() - timedelta(days=10)).isoformat()
        (cells / "pattern.md").write_text(
            f"---\ncreated: {created}\nexpiry_days: 30\n---\n# Pattern\n"
        )

        args = argparse.Namespace(_root=tmp_path)
        ret = run_status(args)
        assert ret == 0
        captured = capsys.readouterr()
        # 30 - 10 = 20 days remaining
        assert "20d" in captured.out

    def test_status_adaptive_rule_expiry_expired(self, tmp_path, capsys):
        """Expired adaptive rules show 'expired'."""
        cells = tmp_path / ".aegis" / "rules"
        cells.mkdir(parents=True)
        created = (date.today() - timedelta(days=40)).isoformat()
        (cells / "stale.md").write_text(
            f"---\ncreated: {created}\nexpiry_days: 30\n---\n# Stale\n"
        )

        args = argparse.Namespace(_root=tmp_path)
        ret = run_status(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "expired" in captured.out

    def test_status_command_contract(self):
        from unittest.mock import patch
        from aegis_cli.status import StatusCommand
        cmd = StatusCommand()
        parser = argparse.ArgumentParser()
        cmd.configure_parser(parser)
        parsed = parser.parse_args([])

        with patch("aegis_cli.status.run_status", return_value=0) as mock_run:
            assert cmd.execute(parsed) == 0
            mock_run.assert_called_once_with(parsed)

    def test_status_with_project_root_counts_platform_rules(self, tmp_path, capsys):
        """Regression test for BUG-090: _project_root set by cli.py must not skip rule counting."""
        proj = tmp_path / "project"
        proj.mkdir()
        home = tmp_path / "home"
        claude_dir = home / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "rule1.md").write_text("# Rule 1\n")
        (claude_dir / "rule2.md").write_text("# Rule 2\n")

        args = argparse.Namespace(_project_root=proj, _home=home)
        ret = run_status(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "2 active" in captured.out

    def test_genome_heading_map_coverage(self, tmp_path):
        from aegis_cli.status import _genome_heading_map
        # Test fallback to genome
        g_dir = tmp_path / "fallback" / "genome"
        g_dir.mkdir(parents=True)
        (g_dir / "r1.md").write_text("# R1 Heading\nBody", encoding="utf-8")
        mapping = _genome_heading_map(tmp_path / "fallback")
        assert mapping.get("R1 Heading") == "r1"

        # Test rules dir
        r_dir = tmp_path / "primary" / "rules"
        r_dir.mkdir(parents=True)
        (r_dir / "r2.md").write_text("# R2 Heading\nBody", encoding="utf-8")
        mapping2 = _genome_heading_map(tmp_path / "primary")
        assert mapping2.get("R2 Heading") == "r2"

    def test_status_branded_aegis_header_and_no_soma(self, tmp_path, capsys):
        """v3.0.0: status prints Aegis Workspace Status, token budget bar, and zero 'Soma' references."""
        (tmp_path / "rules").mkdir()
        (tmp_path / ".aegis" / "rules").mkdir(parents=True)
        args = argparse.Namespace(_root=tmp_path)
        ret = run_status(args)
        assert ret == 0
        out = capsys.readouterr().out
        assert "Aegis Workspace Status" in out
        assert "Token budget:" in out
        assert "soma" not in out.lower()
        assert "aegis init" in out

    def test_status_groups_rules_by_type_and_colors_fitness(self, tmp_path, capsys):
        """v3.0.0: rules are grouped by modern rule type with colored fitness in TTY and zero ANSI in plain mode."""
        from aegis_cli.ui.theme import OutputContext

        rules_dir = tmp_path / ".aegis" / "rules"
        (rules_dir / "invariants").mkdir(parents=True)
        (rules_dir / "traps").mkdir(parents=True)
        (rules_dir / "invariants" / "inv-auth.md").write_text(
            "---\nid: inv-auth\ntype: wall\nfitness:\n  score: 0.92\n---\n# Auth Invariant\n",
            encoding="utf-8",
        )
        (rules_dir / "traps" / "trap-retry.md").write_text(
            "---\nid: trap-retry\ntype: trap\nfitness:\n  score: 0.42\n---\n# Retry Trap\n",
            encoding="utf-8",
        )

        tty_ui = OutputContext(color_enabled=True, emoji_enabled=True, plain=False)
        args_tty = argparse.Namespace(_root=tmp_path, ui=tty_ui)
        assert run_status(args_tty) == 0
        out_tty = capsys.readouterr().out
        assert "🛡️ Aegis Workspace Status" in out_tty
        assert "\x1b[" in out_tty
        assert "0.92" in out_tty
        assert "0.42" in out_tty
        assert "wall" not in out_tty.lower()
        assert "vacuole" not in out_tty.lower()

        plain_ui = OutputContext(color_enabled=False, emoji_enabled=False, plain=True)
        args_plain = argparse.Namespace(_root=tmp_path, plain=True, ui=plain_ui)
        assert run_status(args_plain) == 0
        out_plain = capsys.readouterr().out
        assert "\x1b[" not in out_plain
        assert "soma" not in out_plain.lower()


