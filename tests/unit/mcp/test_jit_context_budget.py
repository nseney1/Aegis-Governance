"""Tests for JIT context token budget clamping (Issue #75)."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aegis_mcp.jit_engine import express, estimate_tokens


class TestJITContextBudgetClamping(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="soma_test_jit_budget_")
        self.ws = Path(self.test_dir)
        self.rules_dir = self.ws / ".aegis" / "rules"
        (self.rules_dir / "vacuoles").mkdir(parents=True, exist_ok=True)
        (self.rules_dir / "walls").mkdir(parents=True, exist_ok=True)

        # Helper to create a cell with custom length
        self._create_cell(
            "walls",
            "wall-security.md",
            frontmatter={
                "type": "wall",
                "enforcement": "gate",
                "target_paths": ["*.py"],
                "hypothesis": "Prevent security vulnerabilities",
                "prediction": "Catch dangerous injection",
            },
            body="Security guidelines detailed instructions " * 15,  # ~60 words -> ~80 tokens
        )
        self._create_cell(
            "vacuoles",
            "vacuole-style.md",
            frontmatter={
                "type": "vacuole",
                "enforcement": "advisory",
                "target_paths": ["*.py"],
                "hypothesis": "Ensure consistent code style",
                "prediction": "Catch formatting drift",
            },
            body="Code style conventions detailed instructions " * 30,  # ~120 words -> ~160 tokens
        )
        self._create_cell(
            "vacuoles",
            "vacuole-perf.md",
            frontmatter={
                "type": "vacuole",
                "enforcement": "advisory",
                "target_paths": ["*.py"],
                "hypothesis": "Optimize hot paths",
                "prediction": "Avoid quadratic loops",
            },
            body="Performance optimization guidelines detailed instructions " * 40,  # ~160 words -> ~216 tokens
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_cell(self, subtype: str, filename: str, frontmatter: dict, body: str):
        path = self.rules_dir / subtype / filename
        fm_lines = ["---"]
        for k, v in frontmatter.items():
            if isinstance(v, list):
                fm_lines.append(f"{k}:")
                for item in v:
                    fm_lines.append(f'  - "{item}"')
            else:
                fm_lines.append(f'{k}: "{v}"')
        fm_lines.append("---")
        content = "\n".join(fm_lines) + "\n\n" + body
        path.write_text(content, encoding="utf-8")

    def test_estimate_tokens_utility(self):
        """estimate_tokens should return ~1.35x word count for English text."""
        text = "one two three four five six seven eight nine ten"
        tokens = estimate_tokens(text)
        self.assertGreaterEqual(tokens, 13)
        self.assertLessEqual(tokens, 15)
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens(None), 0)

    def test_default_token_budget_is_2000(self):
        """When not specified, max_tokens_budget should default to 2000."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AEGIS_MAX_JIT_TOKENS", None)
            res = express(str(self.ws), changed_files=["main.py"], budget=10)
            stats = res["stats"]
            self.assertEqual(stats.get("max_tokens_budget"), 2000)
            self.assertFalse(stats.get("clamped", True))
            self.assertGreater(stats.get("estimated_tokens", 0), 0)

    def test_explicit_max_tokens_argument(self):
        """express() must respect an explicitly provided max_tokens parameter."""
        res = express(str(self.ws), changed_files=["main.py"], max_tokens=150)
        stats = res["stats"]
        self.assertEqual(stats.get("max_tokens_budget"), 150)
        self.assertLessEqual(stats.get("estimated_tokens", 999), 150)
        self.assertTrue(stats.get("clamped"))

    def test_env_var_overrides_token_budget(self):
        """AEGIS_MAX_JIT_TOKENS environment variable should set default budget."""
        with patch.dict(os.environ, {"AEGIS_MAX_JIT_TOKENS": "120"}):
            res = express(str(self.ws), changed_files=["main.py"])
            stats = res["stats"]
            self.assertEqual(stats.get("max_tokens_budget"), 120)
            self.assertLessEqual(stats.get("estimated_tokens", 999), 120)
            self.assertTrue(stats.get("clamped"))

    def test_config_file_sets_token_budget(self):
        """jit.max_tokens in .aegis/config.json sets the budget (D10)."""
        conf_path = self.ws / ".aegis" / "config.json"
        conf_path.parent.mkdir(parents=True, exist_ok=True)
        conf_path.write_text('{"v": 1, "jit": {"max_tokens": 180}}', encoding="utf-8")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AEGIS_MAX_JIT_TOKENS", None)
            res = express(str(self.ws), changed_files=["main.py"])
            stats = res["stats"]
            self.assertEqual(stats.get("max_tokens_budget"), 180)
            self.assertLessEqual(stats.get("estimated_tokens", 999), 180)

    def test_legacy_aegis_conf_is_not_read(self):
        """D10: aegis.conf is gone; `aegis migrate` converts it."""
        (self.ws / "aegis.conf").write_text("max_jit_tokens=180\n", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AEGIS_MAX_JIT_TOKENS", None)
            res = express(str(self.ws), changed_files=["main.py"])
            self.assertNotEqual(res["stats"].get("max_tokens_budget"), 180)

    def test_mandatory_cells_prioritized_under_tight_budget(self):
        """Mandatory wall/gate cells must be included first before advisory cells under a tight budget."""
        wall_only = express(str(self.ws), changed_files=["main.py"], budget=0, max_tokens=10_000)
        self.assertEqual([c["name"] for c in wall_only["relevant_rules"]], ["wall-security"])

        # Enough for the wall and the "2 more rules omitted" notice (~17 tokens as sent),
        # far short of any advisory cell: every advisory cell is omitted, never swapped in.
        res = express(str(self.ws), changed_files=["main.py"], max_tokens=wall_only["stats"]["estimated_tokens"] + 30)
        relevant_names = [c["name"] for c in res["relevant_rules"]]
        self.assertEqual(relevant_names, ["wall-security"])
        self.assertTrue(res["stats"]["clamped"])
        self.assertEqual(res["stats"]["omitted"], 2)

    def test_a_gate_that_does_not_fit_is_never_displaced_by_an_advisory_cell(self):
        """Under a budget too small for the wall, a smaller advisory cell is not staged in its place."""
        res = express(str(self.ws), changed_files=["main.py"], max_tokens=140)
        self.assertEqual(res["relevant_rules"], [])
        self.assertEqual(res["stats"]["omitted"], 3)
