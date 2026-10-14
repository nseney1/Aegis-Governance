"""Shared test helpers for rule lifecycle tests.

Provides factory functions for creating rule files and JSONL evidence
used by lifecycle, fitness, and checkpoint tests.
"""
import json
import os
from datetime import datetime, timedelta

import pytest
from aegis_core.yaml import dump_frontmatter

__all__ = [
    "make_cell",
    "make_rule",
    "write_cell_with_fitness",
    "write_rule_with_fitness",
    "make_cell_dict",
    "make_rule_dict",
    "soma_workspace",
    "aegis_workspace",
    "write_evidence",
]


def make_rule(cells_dir, name, cell_type="trap", created_days_ago=10,
              expiry_days=365, expiry_sessions=100):
    """Create a minimal rule markdown file with YAML frontmatter."""
    created = (datetime.now() - timedelta(days=created_days_ago)).strftime("%Y-%m-%d")
    fm = {
        'id': name,
        'type': cell_type,
        'enforcement': 'advisory',
        'hypothesis': f'Test cell {name}',
        'prediction': 'test',
        'falsification': 'test',
        'target_paths': ['*.py'],
        'expiry_sessions': expiry_sessions,
        'expiry_days': expiry_days,
        'created': created,
    }
    cell_file = os.path.join(str(cells_dir), f"{name}.md")
    with open(cell_file, 'w') as f:
        f.write("---\n")
        f.write(dump_frontmatter(fm))
        f.write("---\n")
        f.write(f"# {name}\nTest cell.\n")
    return cell_file


make_cell = make_rule


def write_rule_with_fitness(cells_dir, name, enforcement="advisory",
                            triggers=0, tp=0, fp=0, cell_type="trap",
                            hypothesis=None):
    """Write a rule markdown file with fitness data in YAML frontmatter."""
    score = tp / max(triggers, 1)
    hyp = hypothesis or f"Test cell {name}"
    content = (
        f"---\n"
        f"type: {cell_type}\n"
        f"hypothesis: {hyp}\n"
        f"enforcement: {enforcement}\n"
        f"target_paths:\n  - \"*.py\"\n"
        f"fitness:\n"
        f"  triggers: {triggers}\n"
        f"  true_positives: {tp}\n"
        f"  false_positives: {fp}\n"
        f"  score: {score:.4f}\n"
        f"---\n# {name}\nContent\n"
    )
    cell_path = os.path.join(str(cells_dir), f"{name}.md")
    with open(cell_path, 'w') as f:
        f.write(content)
    return cell_path


write_cell_with_fitness = write_rule_with_fitness


def make_rule_dict(tp=0, triggers=0, fp=0, impact_weight=1.0, score=None):
    """Build a minimal in-memory rule dict matching the frontmatter structure."""
    fitness = {'true_positives': tp, 'triggers': triggers, 'false_positives': fp}
    if score is not None:
        fitness['score'] = score
    return {'fitness': fitness, 'impact_weight': impact_weight}


make_cell_dict = make_rule_dict


@pytest.fixture
def aegis_workspace(tmp_path):
    """Create a minimal Aegis workspace with rules and metrics directories."""
    workspace = tmp_path / "project"
    rules_dir = workspace / ".aegis" / "rules"
    rules_dir.mkdir(parents=True)
    metrics_dir = workspace / ".aegis" / "metrics"
    metrics_dir.mkdir(parents=True)
    (workspace / "aegis.conf").write_text("TOTAL_SESSIONS=100\n")
    return workspace


@pytest.fixture
def soma_workspace(tmp_path):
    """Create a minimal workspace with rules and metrics directories."""
    workspace = tmp_path / "project"
    rules_dir = workspace / ".aegis" / "rules"
    rules_dir.mkdir(parents=True)
    metrics_dir = workspace / ".aegis" / "metrics"
    metrics_dir.mkdir(parents=True)
    (workspace / "aegis.conf").write_text("TOTAL_SESSIONS=100\n")
    return workspace


def write_evidence(evidence_dir, cell_id, triggers=0, tp=0, fp=0):
    """Write canonical trigger and outcome signals for one rule."""
    evidence_dir = str(evidence_dir)
    signals_file = os.path.join(evidence_dir, "signals.jsonl")

    with open(signals_file, "a", encoding="utf-8") as f:
        for _ in range(triggers):
            f.write(json.dumps({
                "cell": cell_id,
                "signal": "trigger",
                "source": "manual",
                "timestamp": datetime.now().isoformat(),
                "metadata": {"matched_files": ["test.py"]},
            }) + "\n")
        for _ in range(tp):
            f.write(json.dumps({
                "cell": cell_id, "signal": "tp", "source": "manual",
            }) + "\n")
        for _ in range(fp):
            f.write(json.dumps({
                "cell": cell_id, "signal": "fp", "source": "manual",
            }) + "\n")

