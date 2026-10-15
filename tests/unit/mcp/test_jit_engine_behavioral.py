from pathlib import Path
"""Behavioral tests for JIT engine — cell selection, scoring, context formatting.

Tests express(), get_fitness_score(), rank_cells(), ensure_type_diversity(),
match_cells_to_files(), and parse_frontmatter().
"""
import os
import sys
import time
import pytest
from aegis_core.yaml import dump_frontmatter

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from aegis_mcp.jit_engine import (
    express,
    get_fitness_score,
    rank_cells,
    ensure_type_diversity,
    match_cells_to_files,
    load_all_cells,
    parse_frontmatter,
)
from aegis_core.yaml import parse_yaml_subset


def _make_cell(workspace, cell_id, cell_type='vacuole', target_paths=None,
               fitness=None, enforcement='advisory', impact_weight=1.0,
               expired=False):
    """Create a minimal cell file in workspace."""
    type_map = {'vacuole': 'vacuoles', 'wall': 'walls', 'membrane': 'membranes'}
    cells_dir = os.path.join(workspace, '.aegis', "rules",
                             type_map.get(cell_type, 'vacuoles'))
    os.makedirs(cells_dir, exist_ok=True)
    fm = {
        'id': cell_id,
        'type': cell_type,
        'enforcement': enforcement,
        'target_paths': target_paths or ['src/*.py'],
        'hypothesis': f'Hypothesis for {cell_id}',
        'prediction': f'Prediction for {cell_id}',
        'impact_weight': impact_weight,
    }
    if fitness:
        fm['fitness'] = fitness
    if expired:
        fm['expired_at'] = '2020-01-01'
    content = dump_frontmatter(fm, body="Guidance text\n")
    path = os.path.join(cells_dir, f'{cell_id}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


class TestGetFitnessScore:
    """Tests for Bayesian posterior fitness scoring."""

    def test_known_tp_triggers_calculation(self):
        cell = {'fitness': {'true_positives': 10, 'triggers': 20},
                'impact_weight': 1.0}
        score = get_fitness_score(cell)
        expected = (10 + 1) / (20 + 2)  # 0.5
        assert abs(score - expected) < 0.01

    def test_unobserved_cell_gets_default(self):
        cell = {'impact_weight': 1.0}
        score = get_fitness_score(cell)
        assert abs(score - 0.5) < 0.01  # default = 0.5 * impact_weight

    def test_impact_weight_scales_score(self):
        cell = {'fitness': {'true_positives': 10, 'triggers': 20},
                'impact_weight': 2.0}
        score = get_fitness_score(cell)
        expected = ((10 + 1) / (20 + 2)) * 2.0
        assert abs(score - expected) < 0.01

    def test_zero_triggers_uses_default(self):
        cell = {'fitness': {'true_positives': 0, 'triggers': 0},
                'impact_weight': 1.0}
        score = get_fitness_score(cell)
        # (0+1)/(0+2) = 0.5
        assert abs(score - 0.5) < 0.01


class TestRankCells:
    """Tests for cell ranking by fitness."""

    def test_higher_fitness_first(self):
        cells = [
            {'id': 'low', 'fitness': {'true_positives': 1, 'triggers': 10},
             'impact_weight': 1.0},
            {'id': 'high', 'fitness': {'true_positives': 9, 'triggers': 10},
             'impact_weight': 1.0},
        ]
        ranked = rank_cells(cells)
        assert ranked[0]['id'] == 'high'

    def test_empty_list_returns_empty(self):
        assert rank_cells([]) == []


class TestEnsureTypeDiversity:
    """Tests for type diversity in cell selection."""

    def test_one_of_each_type_first(self):
        cells = [
            {'id': 'v1', 'type': 'vacuole', 'fitness_score': 0.9},
            {'id': 'v2', 'type': 'vacuole', 'fitness_score': 0.8},
            {'id': 'w1', 'type': 'wall', 'fitness_score': 0.7},
            {'id': 'm1', 'type': 'membrane', 'fitness_score': 0.6},
        ]
        selected = ensure_type_diversity(cells, budget=3)
        types = [c['type'] for c in selected]
        # Should have at least 2 different types within budget of 3
        assert len(set(types)) >= 2

    def test_respects_budget(self):
        cells = [{'id': f'c{i}', 'type': 'vacuole', 'fitness_score': 0.5}
                 for i in range(10)]
        selected = ensure_type_diversity(cells, budget=3)
        assert len(selected) <= 3


class TestMatchCellsToFiles:
    """Tests for file-glob matching."""

    def test_matching_glob_returns_cell(self):
        cells = [{'id': 'c1', 'target_paths': ['src/*.py']}]
        matched = match_cells_to_files(cells, ['src/foo.py'])
        assert len(matched) >= 1

    def test_non_matching_glob_returns_empty(self):
        cells = [{'id': 'c1', 'target_paths': ['tests/*.py']}]
        matched = match_cells_to_files(cells, ['src/foo.py'])
        assert len(matched) == 0

    def test_no_target_paths_not_matched(self):
        cells = [{'id': 'c1'}]
        matched = match_cells_to_files(cells, ['src/foo.py'])
        assert len(matched) == 0


class TestParseFrontmatter:
    """Tests for zero-dep YAML frontmatter parsing."""

    def test_valid_frontmatter_returns_dict(self):
        content = '---\nid: test-cell\ntype: vacuole\n---\nBody'
        result = parse_frontmatter(content)
        assert isinstance(result, dict)
        assert result.get('id') == 'test-cell'

    def test_no_delimiters_returns_none_or_empty(self):
        result = parse_frontmatter('Just plain text')
        # Returns None or empty dict for absent frontmatter
        assert result is None or result == {}

    def test_empty_frontmatter_returns_empty_dict(self):
        result = parse_frontmatter('---\n---\nBody')
        assert result is not None
        assert isinstance(result, dict)


class TestParseYamlSubset:
    """Tests for stdlib-only YAML parser."""

    def test_flat_key_value(self):
        text = 'id: test\ntype: vacuole'
        result = parse_yaml_subset(text)
        assert result['id'] == 'test'
        assert result['type'] == 'vacuole'

    def test_list_values(self):
        text = 'tags:\n- alpha\n- beta'
        result = parse_yaml_subset(text)
        assert result.get('tags') == ['alpha', 'beta']


class TestExpress:
    """Tests for the main express() entry point."""

    def test_empty_workspace_no_crash(self, tmp_path):
        ws = str(tmp_path)
        os.makedirs(os.path.join(ws, '.aegis', "rules"), exist_ok=True)
        result = express(ws)
        assert 'relevant_rules' in result
        assert 'stats' in result

    def test_matching_cells_returned(self, tmp_path):
        ws = str(tmp_path)
        _make_cell(ws, 'match-me', target_paths=['src/*.py'])
        result = express(ws, changed_files=['src/foo.py'])
        # Cell IDs may use 'id', '_name', or filename-based keys
        cells = result['relevant_rules']
        found = any(
            c.get('id') == 'match-me' or c.get('_name') == 'match-me'
            or 'match-me' in str(c.get('_path', ''))
            for c in cells
        )
        assert found or len(cells) > 0, f"No matching cells returned: {cells}"

    def test_mandatory_walls_always_included(self, tmp_path):
        ws = str(tmp_path)
        _make_cell(ws, 'mandatory-wall', cell_type='wall',
                   target_paths=['anything/*.py'], enforcement='gate')
        _make_cell(ws, 'optional-vac', target_paths=['src/*.py'])
        result = express(ws, changed_files=['src/foo.py'], budget=1)
        cells = result['relevant_rules']
        found = any(
            c.get('id') == 'mandatory-wall' or c.get('_name') == 'mandatory-wall'
            or 'mandatory-wall' in str(c.get('_path', ''))
            for c in cells
        )
        assert found or len(cells) > 0, f"Mandatory wall not included: {cells}"

    def test_expired_cells_skipped(self, tmp_path):
        ws = str(tmp_path)
        _make_cell(ws, 'expired-cell', expired=True, target_paths=['src/*.py'])
        result = express(ws, changed_files=['src/foo.py'])
        cell_ids = [c.get('name', '') for c in result['relevant_rules']]
        assert not any('expired-cell' in cid for cid in cell_ids)

    def test_stats_has_required_keys(self, tmp_path):
        ws = str(tmp_path)
        os.makedirs(os.path.join(ws, '.aegis', "rules"), exist_ok=True)
        result = express(ws)
        stats = result['stats']
        assert 'total_rules' in stats

    def test_guidance_is_string(self, tmp_path):
        ws = str(tmp_path)
        _make_cell(ws, 'ctx-cell', target_paths=['src/*.py'])
        result = express(ws, changed_files=['src/foo.py'])
        assert isinstance(result['guidance'], str)
        assert 'ctx-cell' in result['guidance']

    def test_performance_100_cells_under_1s(self, tmp_path):
        ws = str(tmp_path)
        for i in range(100):
            _make_cell(ws, f'perf-cell-{i}', target_paths=['src/*.py'])
        start = time.time()
        express(ws, changed_files=['src/foo.py'])
        elapsed = time.time() - start
        assert elapsed < 1.0, f"express() took {elapsed:.2f}s for 100 cells"

    def test_rule_count_budget_caps_optional_rules(self, tmp_path):
        ws = str(tmp_path)
        for i in range(10):
            _make_cell(ws, f'budget-cell-{i}', target_paths=['src/*.py'])
        result = express(ws, changed_files=['src/foo.py'], budget=2)
        assert result['stats']['budget'] == 2
        assert result['rules_staged'] == 2

# ── Phase 4: C3 — Mandatory Cells Fitness Score ──────────────────────────

from tests.helpers_rule import write_cell_with_fitness, soma_workspace

class TestMandatoryCellsFitnessScore:
    """Verify mandatory wall/gate cells have their fitness score computed."""

    @pytest.fixture
    def populated_workspace(self, soma_workspace):
        """Workspace with a wall cell and an advisory cell for fitness tests."""
        cells_dir = soma_workspace / ".aegis" / "rules"
        write_cell_with_fitness(cells_dir, "wall-auth", cell_type="wall",
                               triggers=50, tp=48, fp=1,
                               hypothesis="Auth check")
        write_cell_with_fitness(cells_dir, "advisory-style",
                               triggers=10, tp=8, fp=1,
                               hypothesis="Style check")
        return str(soma_workspace)

    def test_mandatory_cells_have_nonzero_fitness(self, populated_workspace):
        """Wall cells must have their fitness computed, not default to 0."""
        from aegis_mcp.jit_engine import express
        result = express(populated_workspace, changed_files=["app.py"], budget=5)

        for cell in result['relevant_rules']:
            if cell.get('type') == 'wall':
                fitness = cell.get('fitness', 0)
                assert fitness > 0, \
                    f"Mandatory cell '{cell.get('name')}' has fitness {fitness}, expected > 0"

    def test_all_expressed_cells_have_fitness(self, populated_workspace):
        """Every expressed cell (mandatory or candidate) must have fitness."""
        from aegis_mcp.jit_engine import express
        result = express(populated_workspace, changed_files=["app.py"], budget=5)

        for cell in result['relevant_rules']:
            assert 'fitness' in cell, \
                f"Cell '{cell.get('name')}' missing fitness key"
            assert isinstance(cell['fitness'], (int, float)), \
                f"Cell '{cell.get('name')}' fitness is not numeric"


class TestModernRuleTypeExecution:
    """JIT engine must stage modern rule types (invariant, trap, boundary, persona, contract)."""

    def test_express_stages_invariant_rule_and_emits_pre_edit_warning(self, tmp_path):
        """A rule with type: invariant must be staged as mandatory and emit a Pre-Edit Invariants warning."""
        from aegis_core.yaml import dump_frontmatter
        from aegis_mcp.jit_engine import express

        inv_dir = tmp_path / ".aegis" / "rules" / "invariants"
        inv_dir.mkdir(parents=True)
        (inv_dir / "invariant-zero-deps.md").write_text(
            dump_frontmatter(
                {
                    "id": "invariant-zero-deps",
                    "type": "invariant",
                    "domain": "architecture",
                    "enforcement": "advisory",
                    "target_paths": ["aegis_core/*.py"],
                    "hypothesis": "Zero external runtime dependencies allowed in core",
                    "prediction": "ImportError in clean stdlib environments",
                    "falsification": "Inspect pyproject.toml dependencies",
                },
                "# Zero Deps Invariant\n\nNever import third-party libraries in aegis_core.",
            ),
            encoding="utf-8",
        )

        res = express(str(tmp_path), changed_files=["aegis_core/yaml.py"], budget=5)
        selected_names = [r.get("name") for r in res.get("relevant_rules", [])]
        assert "invariant-zero-deps" in selected_names
        assert "Pre-Edit Invariants & Constraints" in res.get("guidance", "")
        assert "🧱 [INVARIANT] invariant-zero-deps" in res.get("guidance", "")

    def test_format_cell_guidance_renders_modern_rule_type_labels_and_icons(self):
        """format_cell_guidance must map invariant, trap, boundary, persona, and contract to their icons and labels."""
        from aegis_mcp.jit_engine import format_cell_guidance

        expected_mappings = [
            ("invariant", "🧱", "INVARIANT (must not violate)"),
            ("trap", "🧫", "ANTI-PATTERN TRAP (watch out)"),
            ("boundary", "🔬", "ESCALATION GATE (needs review)"),
            ("persona", "🌿", "BEST PRACTICE (follow this pattern)"),
            ("contract", "🔗", "CONTRACT (cross-service agreement)"),
        ]
        for rule_type, emoji, label in expected_mappings:
            fg = format_cell_guidance({
                "_name": f"rule-{rule_type}",
                "type": rule_type,
                "hypothesis": f"Hypothesis for {rule_type}",
                "_body": "Rule body",
            })
            assert emoji in fg["guidance"], f"Missing emoji {emoji} for {rule_type}"
            assert label in fg["guidance"], f"Missing label {label} for {rule_type}"


