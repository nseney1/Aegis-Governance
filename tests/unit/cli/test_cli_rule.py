"""Unit tests for aegis rule command (aegis_cli/rule.py) and BUG-067."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aegis_cli.rule import (
    RuleCommand,
    _force_demote,
    _force_promote,
    run_demote,
    run_promote,
    run_rule,
)


def test_demote_core_rule_fails(tmp_path, capsys):
    """BUG-067: demoting a protected core rule must fail closed."""
    args = argparse.Namespace(
        rule_action="demote",
        rule_id="cost-optimization",
        workspace=str(tmp_path),
        dry_run=False,
        json=False,
    )
    rc = run_rule(args)
    assert rc == 1
    out = capsys.readouterr().out
    assert "Cannot demote core rule" in out or "error" in out.lower()


def test_rule_list_empty(tmp_path, capsys):
    args = argparse.Namespace(
        rule_action="list",
        workspace=str(tmp_path),
        json=False,
        type=None,
        min_fitness=None,
    )
    rc = run_rule(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "No rules directory found" in out


def test_rule_list_with_rules(tmp_path, capsys):
    rules_dir = tmp_path / ".aegis" / "rules" / "invariants"
    rules_dir.mkdir(parents=True)
    rule_file = rules_dir / "inv-test.md"
    rule_file.write_text(
        "---\nid: inv-test\ntype: invariant\nenforcement: strict\nfitness:\n  score: 0.95\n---\nRule body\n",
        encoding="utf-8",
    )

    args = argparse.Namespace(
        rule_action="list",
        workspace=str(tmp_path),
        json=False,
        type="invariant",
        min_fitness=0.9,
    )
    rc = run_rule(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "inv-test" in out


def test_rule_promote_and_force_promote(tmp_path, capsys):
    with patch("aegis_cli.rule.promote_cell", return_value={"status": "already_terminal", "current_type": "invariant"}):
        args = argparse.Namespace(
            rule_action="promote",
            rule_id="inv-test",
            workspace=str(tmp_path),
            dry_run=False,
            json=False,
        )
        rc = run_rule(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "already at terminal" in out

        # Test _force_promote helper
        rc2 = _force_promote(tmp_path, "inv-test")
        assert rc2 == 0


def test_rule_demote_and_force_demote(tmp_path, capsys):
    with patch("aegis_cli.rule.demote_cell", return_value={"status": "already_base", "current_type": "trap"}):
        args = argparse.Namespace(
            rule_action="demote",
            rule_id="trap-test",
            workspace=str(tmp_path),
            dry_run=False,
            json=False,
        )
        rc = run_rule(args)
        assert rc == 1
        out = capsys.readouterr().out
        assert "already at base" in out

        # Test _force_demote helper
        rc2 = _force_demote(tmp_path, "trap-test")
        assert rc2 == 1


def test_rule_archive(tmp_path):
    with patch("aegis_cli.rule.prune_cells", return_value=0) as mock_prune:
        args = argparse.Namespace(
            rule_action="archive",
            workspace=str(tmp_path),
            dry_run=False,
        )
        rc = run_rule(args)
        assert rc == 0
        mock_prune.assert_called_once_with(workspace=tmp_path, execute=True)


def test_rule_list_long_id_not_truncated_and_colored(tmp_path, capsys):
    """v3.0.0: long rule IDs (>36 chars) are never truncated and Table uses OutputContext."""
    from aegis_cli.ui.theme import OutputContext

    rules_dir = tmp_path / ".aegis" / "rules" / "invariants"
    rules_dir.mkdir(parents=True)
    long_id = "invariant-very-long-identifier-exceeding-thirty-six-characters-limit"
    (rules_dir / f"{long_id}.md").write_text(
        f"---\nid: {long_id}\ntype: invariant\nenforcement: gate\nfitness:\n  score: 0.91\n---\nBody\n",
        encoding="utf-8",
    )

    tty_ui = OutputContext(color_enabled=True, emoji_enabled=True, plain=False)
    args_tty = argparse.Namespace(
        rule_action="list",
        workspace=str(tmp_path),
        json=False,
        type=None,
        min_fitness=None,
        ui=tty_ui,
    )
    assert run_rule(args_tty) == 0
    out_tty = capsys.readouterr().out
    assert long_id in out_tty
    assert "\x1b[" in out_tty

    plain_ui = OutputContext(color_enabled=False, emoji_enabled=False, plain=True)
    args_plain = argparse.Namespace(
        rule_action="list",
        workspace=str(tmp_path),
        json=False,
        type=None,
        min_fitness=None,
        plain=True,
        ui=plain_ui,
    )
    assert run_rule(args_plain) == 0
    out_plain = capsys.readouterr().out
    assert long_id in out_plain
    assert "\x1b[" not in out_plain


def test_rule_parser_rejects_legacy_cell_flag():
    """v3.0.0: --cell flag is removed from aegis rule subcommands."""
    cmd = RuleCommand()
    parser = argparse.ArgumentParser()
    cmd.configure_parser(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(["promote", "--cell", "old-id"])
    with pytest.raises(SystemExit):
        parser.parse_args(["demote", "--cell", "old-id"])

