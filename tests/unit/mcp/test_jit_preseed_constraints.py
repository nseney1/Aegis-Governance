"""Tests for GitHub Issue #77: Pre-seed Active File Constraints to Prevent Post-Generation Rejection Waste.

Ensures soma_scan and jit_engine.express() extract target file constraints
prior to code generation, formatting an early-warning constraint summary at
the top of JIT prompt context and returning structured target_constraints.
"""
import os
import tempfile
import unittest

from aegis_mcp import jit_engine
from aegis_mcp.tools import _handle_scan


class TestJitPreseedConstraints(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = self.temp_dir.name
        self.cells_dir = os.path.join(self.workspace, ".soma", "cells")
        os.makedirs(self.cells_dir, exist_ok=True)

        # Create a sample wall cell (security invariant)
        wall_cell = (
            "---\n"
            "name: auth-token-invariants\n"
            "type: wall\n"
            "enforcement: wall\n"
            "target_paths:\n"
            '  - "soma_core/*.py"\n'
            "hypothesis: Never store secrets in plain-text or bypass auth token validation\n"
            "prediction: Token validation bypass will allow unauthorized access\n"
            "fitness: 0.98\n"
            "---\n"
            "# Auth Token Invariants\n"
            "All authentication handlers must validate tokens before processing requests.\n"
        )
        with open(os.path.join(self.cells_dir, "auth-token-invariants.md"), "w", encoding="utf-8") as f:
            f.write(wall_cell)

        # Create a sample vacuole cell (anti-pattern trap)
        trap_cell = (
            "---\n"
            "name: no-broad-exceptions\n"
            "type: vacuole\n"
            "enforcement: vacuole\n"
            "target_paths:\n"
            '  - "soma_core/*.py"\n'
            "hypothesis: Broad except Exception blocks swallow critical system faults\n"
            "prediction: Silent failure during runtime\n"
            "fitness: 0.85\n"
            "---\n"
            "# No Broad Exceptions\n"
            "Catch specific exceptions rather than broad Exception.\n"
        )
        with open(os.path.join(self.cells_dir, "no-broad-exceptions.md"), "w", encoding="utf-8") as f:
            f.write(trap_cell)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_express_returns_structured_target_constraints(self):
        """express() should extract structured target_constraints for candidate files."""
        result = jit_engine.express(
            self.workspace,
            changed_files=["soma_core/auth.py"],
        )
        self.assertIn("target_constraints", result)
        constraints = result["target_constraints"]
        self.assertIsInstance(constraints, list)
        self.assertGreaterEqual(len(constraints), 1)

        # Check constraint fields
        wall_constraints = [c for c in constraints if c.get("tier") == "wall" or c.get("type") == "wall"]
        self.assertTrue(len(wall_constraints) >= 1)
        wall = wall_constraints[0]
        self.assertIn("name", wall)
        self.assertIn("hypothesis", wall)
        self.assertIn("Never store secrets", wall["hypothesis"])

    def test_early_warning_summary_at_top_of_context(self):
        """express() should format an early-warning constraint section at the top of context."""
        result = jit_engine.express(
            self.workspace,
            changed_files=["soma_core/auth.py"],
        )
        context = result.get("context", "")
        # Must contain an early-warning constraint header
        self.assertIn("## Pre-Edit Invariants & Constraints", context)

        # Early-warning section must appear before general active cells
        early_warning_pos = context.find("## Pre-Edit Invariants & Constraints")
        active_cells_pos = context.find("## Active Governance Cells")
        if active_cells_pos != -1:
            self.assertLess(
                early_warning_pos,
                active_cells_pos,
                "Early-warning constraints must appear before active cells to anchor LLM attention",
            )

        # The warning must cite the invariant
        self.assertIn("Never store secrets in plain-text", context)

    def test_soma_scan_handler_exposes_target_constraints(self):
        """MCP _handle_scan should return target_constraints in its result."""
        args = {
            "workspace": self.workspace,
            "files": ["soma_core/auth.py"],
        }
        res = _handle_scan(args, None)
        self.assertNotIn("error", res)
        self.assertIn("target_constraints", res)
        self.assertIn("context", res)
        self.assertIn("## Pre-Edit Invariants & Constraints", res["context"])

    def test_preseed_inspection_with_unmodified_target_file(self):
        """Agent should be able to inspect constraints for a target file before editing it."""
        # Note: soma_core/auth.py does NOT need to exist or be dirty in git
        result = jit_engine.express(
            self.workspace,
            changed_files=["soma_core/new_handler.py"],
        )
        self.assertIn("target_constraints", result)
        self.assertGreaterEqual(len(result["target_constraints"]), 1)
        self.assertIn("Never store secrets", result["context"])
