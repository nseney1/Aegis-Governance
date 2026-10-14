"""Phase 4.2b — Enforcement ladder behavioral tests.

Tests verify the three-tier enforcement ladder:
  advisory  → warn, exit 0 (no block)
  mechanical → warn, exit 1 (pre-commit block)
  gate      → warn, exit 1 (CI block)
"""
import os
import pytest
from textwrap import dedent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cell_with_invariant(ws, name, enforcement, invariant_type,
                               invariant_kwargs, target_paths=None):
    """Create a cell with an invariant spec in frontmatter."""
    cells_dir = os.path.join(ws, '.soma', 'cells', 'walls')
    os.makedirs(cells_dir, exist_ok=True)
    tp_yaml = ''
    if target_paths:
        tp_lines = '\n'.join(f'  - "{p}"' for p in target_paths)
        tp_yaml = f'target_paths:\n{tp_lines}'
    inv_items = '\n'.join(f'    {k}: "{v}"' for k, v in invariant_kwargs.items())
    content = dedent(f"""\
        ---
        type: wall
        hypothesis: "Test cell for enforcement ladder"
        enforcement: {enforcement}
        {tp_yaml}
        invariants:
          - type: {invariant_type}
        {inv_items}
        fitness:
          triggers: 10
          true_positives: 8
          false_positives: 2
          score: 0.8
        ---
        Body of {name}.
    """)
    path = os.path.join(cells_dir, f'{name}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


# ---------------------------------------------------------------------------
# Enforcement Ladder Tests
# ---------------------------------------------------------------------------

class TestAdvisory:
    """Advisory tier warns but does NOT block (exit 0)."""

    def test_advisory_warns_no_block(self, tmp_path):
        """Advisory enforcement returns exit 0 even with violations."""
        from aegis_sdk.invariants import evaluate_enforcement
        violations = [type('V', (), {'message': 'test violation', 'file': 'f.py'})()]
        result = evaluate_enforcement(
            violations=violations,
            enforcement='advisory'
        )
        assert result['exit_code'] == 0
        assert result['action'] == 'warn'
        assert len(result['violations']) == 1

    def test_advisory_no_violation_passes(self, tmp_path):
        from aegis_sdk.invariants import evaluate_enforcement
        result = evaluate_enforcement(
            violations=[],
            enforcement='advisory'
        )
        assert result['exit_code'] == 0
        assert result['action'] == 'pass'


class TestGate:
    """Gate tier blocks CI (exit 1) on violations."""

    def test_gate_blocks_ci(self, tmp_path):
        """Gate enforcement returns exit 1 on violations."""
        from aegis_sdk.invariants import evaluate_enforcement
        violations = [type('V', (), {'message': 'banned import', 'file': 'f.py'})()]
        result = evaluate_enforcement(
            violations=violations,
            enforcement='gate'
        )
        assert result['exit_code'] == 1
        assert result['action'] == 'block'

    def test_gate_no_violation_passes(self, tmp_path):
        from aegis_sdk.invariants import evaluate_enforcement
        result = evaluate_enforcement(
            violations=[],
            enforcement='gate'
        )
        assert result['exit_code'] == 0
        assert result['action'] == 'pass'


class TestMechanical:
    """Mechanical tier blocks commits (exit 1) on violations."""

    def test_mechanical_blocks_commit(self, tmp_path):
        from aegis_sdk.invariants import evaluate_enforcement
        violations = [type('V', (), {'message': 'pattern match', 'file': 'f.py'})()]
        result = evaluate_enforcement(
            violations=violations,
            enforcement='mechanical'
        )
        assert result['exit_code'] == 1
        assert result['action'] == 'block'

    def test_mechanical_no_violation_passes(self, tmp_path):
        from aegis_sdk.invariants import evaluate_enforcement
        result = evaluate_enforcement(
            violations=[],
            enforcement='mechanical'
        )
        assert result['exit_code'] == 0
        assert result['action'] == 'pass'


class TestEnforcementEdgeCases:
    """Edge cases in enforcement evaluation."""

    def test_unknown_enforcement_defaults_to_advisory(self):
        """Unknown enforcement tier defaults to advisory behavior."""
        from aegis_sdk.invariants import evaluate_enforcement
        violations = [type('V', (), {'message': 'test', 'file': 'f.py'})()]
        result = evaluate_enforcement(
            violations=violations,
            enforcement='unknown_tier'
        )
        assert result['exit_code'] == 0  # advisory = no block
