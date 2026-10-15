"""Integration test: `aegis rule promote --tier-check` decays fitness before re-tiering.

The tier check applies exponential decay to a rule's counts before it evaluates
promotion/demotion, so frozen champions can be displaced over time. Without
--dry-run the decayed counts and the new tier are written back (an explicit
`aegis rule` command, AD-1); with --dry-run nothing on disk changes.
"""
from __future__ import annotations

import pytest

from aegis_cli.cli import main
from aegis_core.yaml import parse_frontmatter
from tests.helpers_rule import soma_workspace, write_cell_with_fitness  # noqa: F401  (fixture)


def _tier_check(workspace, *extra: str) -> int:
    return main(["rule", "promote", "--tier-check", "--workspace", str(workspace), *extra])


def _read_meta(cell_path):
    return parse_frontmatter(cell_path.read_text(encoding="utf-8")) or {}


@pytest.fixture(autouse=True)
def _no_workspace_pin(monkeypatch):
    monkeypatch.delenv("AEGIS_WORKSPACE", raising=False)


class TestDecayIntegration:
    def test_tier_check_decays_counts_on_disk(self, soma_workspace, capsys):
        cells_dir = soma_workspace / ".aegis" / "rules"
        write_cell_with_fitness(cells_dir, "high-count", "advisory", 100, 90, 10)

        assert _tier_check(soma_workspace) == 0

        fitness = _read_meta(cells_dir / "high-count.md")["fitness"]
        assert fitness["triggers"] < 100
        assert fitness["true_positives"] < 90

    def test_gate_rule_with_high_fp_rate_demotes_to_mechanical(self, soma_workspace, capsys):
        """A gate whose FP rate exceeds 0.30 after decay drops to mechanical."""
        cells_dir = soma_workspace / ".aegis" / "rules"
        write_cell_with_fitness(cells_dir, "stale-gate", "gate", 100, 60, 40)

        assert _tier_check(soma_workspace, "--json") == 0

        assert "stale-gate.md" in capsys.readouterr().out
        assert _read_meta(cells_dir / "stale-gate.md")["enforcement"] == "mechanical"

    def test_gate_rule_with_low_fp_rate_keeps_its_tier(self, soma_workspace, capsys):
        cells_dir = soma_workspace / ".aegis" / "rules"
        write_cell_with_fitness(cells_dir, "solid-gate", "gate", 100, 95, 5)

        assert _tier_check(soma_workspace) == 0

        assert _read_meta(cells_dir / "solid-gate.md")["enforcement"] == "gate"

    def test_tier_check_dry_run_does_not_decay(self, soma_workspace, capsys):
        cells_dir = soma_workspace / ".aegis" / "rules"
        write_cell_with_fitness(cells_dir, "dry-run-cell", "advisory", 100, 90, 10)
        before = (cells_dir / "dry-run-cell.md").read_bytes()

        assert _tier_check(soma_workspace, "--dry-run") == 0

        assert (cells_dir / "dry-run-cell.md").read_bytes() == before

    def test_tier_check_execute_idempotent_consecutive_runs(self, soma_workspace, capsys):
        """The second run reads last_decay_epoch from disk and skips decay."""
        cells_dir = soma_workspace / ".aegis" / "rules"
        write_cell_with_fitness(cells_dir, "idempotent-cell", "advisory", 100, 90, 10)

        assert _tier_check(soma_workspace) == 0
        first = _read_meta(cells_dir / "idempotent-cell.md")["fitness"]["triggers"]
        assert first < 100

        assert _tier_check(soma_workspace) == 0
        assert _read_meta(cells_dir / "idempotent-cell.md")["fitness"]["triggers"] == first
