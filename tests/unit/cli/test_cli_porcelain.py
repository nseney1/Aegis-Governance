"""Behavioral tests for Soma porcelain aliases, output ergonomics, and plumbing decoupling.

Phase 10 (v0.107.0):
- soma check (alias for soma verify)
- soma rules (alias for soma status)
- soma audit (porcelain alias for system/policy health audit)
- --plain and --no-emoji output sanitization
- Decoupling default output from raw biological terms unless --plumbing is set
"""
import io
import re
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch, MagicMock

from aegis_cli.cli import main, _build_parser


class TestCliPorcelainAliases(unittest.TestCase):
    def test_parser_recognizes_check_alias(self):
        """soma check should be recognized by the parser as an alias for verify."""
        parser = _build_parser()
        args = parser.parse_args(["check", "--dry-run"])
        self.assertEqual(args.command, "check")
        self.assertTrue(args.dry_run)

    def test_parser_recognizes_rules_alias(self):
        """soma rules should be recognized by the parser as an alias for status."""
        parser = _build_parser()
        args = parser.parse_args(["rules"])
        self.assertEqual(args.command, "rules")
    def test_check_alias_dispatches_to_verify(self):
        """Executing 'soma check' should dispatch to cmd_check handler."""
        with patch("aegis_cli.cli.cmd_check", return_value=0) as mock_check:
            exit_code = main(["check", "--dry-run"])
            self.assertEqual(exit_code, 0)
            mock_check.assert_called_once()
            args = mock_check.call_args[0][0]
            self.assertEqual(args.command, "check")
            self.assertTrue(args.dry_run)

    def test_common_parser_supports_plain_and_no_emoji_flags(self):
        """The CLI parser must support global --plain and --no-emoji flags."""
        parser = _build_parser()
        args1 = parser.parse_args(["--plain", "check"])
        self.assertTrue(getattr(args1, "plain", False))

        args2 = parser.parse_args(["--no-emoji", "check"])
        self.assertTrue(getattr(args2, "no_emoji", False))


class TestOutputErgonomicsAndPlumbing(unittest.TestCase):
    def test_plain_flag_strips_emojis_from_output(self):
        """When --plain or --no-emoji is active, output must not contain Unicode emojis."""
        from aegis_cli import format_plain

        sample_text = "🧱 [WALL] Invariant Check ✅ Passed ❌ Failed ⚠️ Warning 🧫 Trap"
        plain_text = format_plain(sample_text)
        # Should convert or strip emojis
        self.assertNotIn("🧱", plain_text)
        self.assertNotIn("✅", plain_text)
        self.assertNotIn("❌", plain_text)
        self.assertNotIn("⚠️", plain_text)
        self.assertNotIn("🧫", plain_text)
        self.assertIn("[WALL]", plain_text)
        self.assertIn("[PASS]", plain_text)
        self.assertIn("[FAIL]", plain_text)
        self.assertIn("[WARN]", plain_text)

    def test_status_porcelain_output_has_no_raw_biological_terms(self):
        """Default 'soma status' / 'soma rules' output should not expose internal biological terms."""
        from aegis_cli.status import format_status_summary

        mock_data = {
            "active_rules": 5,
            "wall_count": 2,
            "trap_count": 1,
            "archived_count": 0,
            "fitness_avg": 0.95,
        }
        output = format_status_summary(mock_data, plumbing=False)
        lowered = output.lower()
        self.assertNotIn("mitosis", lowered)
        self.assertNotIn("apoptosis", lowered)
        self.assertNotIn("plasmodesmata", lowered)
        self.assertNotIn("vacuole", lowered)
