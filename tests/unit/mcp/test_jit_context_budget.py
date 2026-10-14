"""Tests for JIT context token budget clamping (Issue #75) and Gate 4.5 workflow integration."""
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
        self.cells_dir = self.ws / ".soma" / "cells"
        (self.cells_dir / "vacuoles").mkdir(parents=True, exist_ok=True)
        (self.cells_dir / "walls").mkdir(parents=True, exist_ok=True)

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
        path = self.cells_dir / subtype / filename
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
            os.environ.pop("SOMA_MAX_JIT_TOKENS", None)
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
        """SOMA_MAX_JIT_TOKENS environment variable should set default budget."""
        with patch.dict(os.environ, {"SOMA_MAX_JIT_TOKENS": "120"}):
            res = express(str(self.ws), changed_files=["main.py"])
            stats = res["stats"]
            self.assertEqual(stats.get("max_tokens_budget"), 120)
            self.assertLessEqual(stats.get("estimated_tokens", 999), 120)
            self.assertTrue(stats.get("clamped"))

    def test_config_file_sets_token_budget(self):
        """max_jit_tokens setting in soma.conf should be respected."""
        conf_path = self.ws / "soma.conf"
        conf_path.write_text("max_jit_tokens=180\n", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SOMA_MAX_JIT_TOKENS", None)
            res = express(str(self.ws), changed_files=["main.py"])
            stats = res["stats"]
            self.assertEqual(stats.get("max_tokens_budget"), 180)
            self.assertLessEqual(stats.get("estimated_tokens", 999), 180)

    def test_mandatory_cells_prioritized_under_tight_budget(self):
        """Mandatory wall/gate cells must be included first before advisory cells under a tight budget."""
        # Set budget just enough for wall (~80 tokens) but not all cells (~450 tokens)
        res = express(str(self.ws), changed_files=["main.py"], max_tokens=140)
        relevant_names = [c["name"] for c in res["relevant_cells"]]
        self.assertIn("wall-security", relevant_names)
        self.assertTrue(res["stats"]["clamped"])
        # Should not include all 3 cells
        self.assertLess(len(res["relevant_cells"]), 3)

    def test_release_workflow_contains_gate_4_5(self):
        """RELEASE_WORKFLOW.md must document Gate 4.5 2-Layer verification."""
        repo_root = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
        workflow_doc = repo_root / "docs" / "project" / "RELEASE_WORKFLOW.md"
        content = workflow_doc.read_text(encoding="utf-8")
        self.assertIn("Gate 4.5", content)
        self.assertIn("soma verify", content)
