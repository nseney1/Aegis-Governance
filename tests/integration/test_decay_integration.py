from pathlib import Path
"""Integration test: verify apply_decay is wired into the tier-check path.

This tests that running `cell_promote.py --tier-check` actually applies
exponential decay to fitness data before evaluating promotion/demotion,
so that frozen champions can be displaced over time.
"""
import os
import sys
import subprocess
import pytest

from aegis_core.yaml import parse_frontmatter
from tests.helpers_rule import soma_workspace, write_cell_with_fitness

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)


class TestDecayIntegration:
    """Verify decay is called during tier-check evaluation."""

    def _read_cell_fitness(self, cell_path):
        """Read fitness data back from a cell file."""
        content = cell_path.read_text()
        meta = parse_frontmatter(content)
        return meta.get('fitness', {})

    def test_tier_check_decays_counts_on_disk(self, soma_workspace):
        """After --tier-check --execute, the cell file should have decayed counts."""
        cells_dir = soma_workspace / ".soma" / "cells"
        write_cell_with_fitness(cells_dir, "high-count", "advisory", 100, 90, 10)

        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; from aegis_core.lifecycle import cli_cell_promote; sys.exit(cli_cell_promote(sys.argv[1:]))",
             "--tier-check", "--execute"],
            cwd=str(soma_workspace),
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONPATH": REPO_ROOT}
        )

        fitness = self._read_cell_fitness(cells_dir / "high-count.md")
        # After decay: 100 * 0.95 = 95, 90 * 0.95 = 85, 10 * 0.95 = 9
        assert fitness['triggers'] < 100, \
            f"Triggers should be decayed below 100, got {fitness['triggers']}"
        assert fitness['true_positives'] < 90, \
            f"TPs should be decayed below 90, got {fitness['true_positives']}"

    def test_frozen_champion_eventually_demotes(self, soma_workspace):
        """A gate-tier cell that stops being useful should eventually demote
        after enough tier-check cycles apply decay + see no new TPs."""
        cells_dir = soma_workspace / ".soma" / "cells"

        # Start with a cell that has a massive history but is now getting FPs
        # After decay, the FP rate will dominate
        write_cell_with_fitness(cells_dir, "stale-gate", "gate", 100, 95, 5)

        escaped_log = soma_workspace / ".soma" / "metrics" / "escaped_defects.jsonl"
        import json
        escaped_log.write_text(
            json.dumps({"cell": "stale-gate", "defect": "test"}) + "\n"
        )

        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; from aegis_core.lifecycle import cli_cell_promote; sys.exit(cli_cell_promote(sys.argv[1:]))",
             "--tier-check", "--execute"],
            cwd=str(soma_workspace),
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONPATH": REPO_ROOT}
        )

        # Should demote because of escaped defect
        content = (cells_dir / "stale-gate.md").read_text()
        meta = parse_frontmatter(content)
        assert meta['enforcement'] == 'mechanical', \
            f"Gate cell with escaped defects should demote, got {meta['enforcement']}"

    def test_tier_check_dry_run_does_not_decay(self, soma_workspace):
        """Dry run (no --execute) should NOT write decayed values to disk."""
        cells_dir = soma_workspace / ".soma" / "cells"
        write_cell_with_fitness(cells_dir, "dry-run-cell", "advisory", 100, 90, 10)

        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; from aegis_core.lifecycle import cli_cell_promote; sys.exit(cli_cell_promote(sys.argv[1:]))",
             "--tier-check"],  # No --execute
            cwd=str(soma_workspace),
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONPATH": REPO_ROOT}
        )

        fitness = self._read_cell_fitness(cells_dir / "dry-run-cell.md")
        assert fitness['triggers'] == 100, \
            f"Dry run should not modify file, triggers should be 100, got {fitness['triggers']}"

    def test_tier_check_execute_idempotent_consecutive_runs(self, soma_workspace):
        """Running --tier-check --execute twice in a row should only decay once.
        The second run must read last_decay_epoch from disk and skip decay."""
        cells_dir = soma_workspace / ".soma" / "cells"
        write_cell_with_fitness(cells_dir, "idempotent-cell", "advisory", 100, 90, 10)

        cmd = [sys.executable, "-c",
               "import sys; from aegis_core.lifecycle import cli_cell_promote; sys.exit(cli_cell_promote(sys.argv[1:]))",
               "--tier-check", "--execute"]
        env = {**os.environ, "PYTHONPATH": REPO_ROOT}

        # First run: should decay
        subprocess.run(cmd, cwd=str(soma_workspace), capture_output=True, text=True,
                       timeout=30, env=env)
        fitness_after_first = self._read_cell_fitness(cells_dir / "idempotent-cell.md")
        assert fitness_after_first['triggers'] < 100, \
            f"First run should decay, got triggers={fitness_after_first['triggers']}"

        # Second run immediately: should NOT decay again
        subprocess.run(cmd, cwd=str(soma_workspace), capture_output=True, text=True,
                       timeout=30, env=env)
        fitness_after_second = self._read_cell_fitness(cells_dir / "idempotent-cell.md")
        assert fitness_after_second['triggers'] == fitness_after_first['triggers'], \
            f"Second run should be idempotent. First: {fitness_after_first['triggers']}, " \
            f"Second: {fitness_after_second['triggers']}"
