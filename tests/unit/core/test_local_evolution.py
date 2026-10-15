"""The one promotion ladder (trap -> invariant -> gate) in every repository.

v3 promoted invariants into a top-level genome/ in the Aegis repository itself; v4
has one ladder and never reads or writes rules outside .aegis/rules/<type>/.
"""
from __future__ import annotations

from pathlib import Path

from aegis_core.yaml_engine.serializer import dump_frontmatter
from aegis_core.yaml_engine.frontmatter import parse_frontmatter
from aegis_core.lifecycle.parsers import find_cell_file
from aegis_core.rules import load_rules
from aegis_core.lifecycle.promotion import promote_cell, demote_cell
from aegis_core.workspace.base import Workspace


def test_the_aegis_repository_promotes_on_the_same_ladder(tmp_path: Path):
    """v3 sent invariants of the Aegis repository to genome/; v4 has one ladder."""
    soma_repo = tmp_path / "aegis"
    (soma_repo / "aegis_core").mkdir(parents=True)
    (soma_repo / "aegis_cli").mkdir()
    (soma_repo / "pyproject.toml").write_text('name = "aegis-governance"\nversion = "0.120.0"\n', encoding="utf-8")
    (soma_repo / "rules").mkdir()
    inv_dir = soma_repo / ".aegis" / "rules" / "invariants"
    inv_dir.mkdir(parents=True)
    (inv_dir / "law.md").write_text(dump_frontmatter({"id": "law", "type": "invariant", "enforcement": "gate"}, body="Law\n"), encoding="utf-8")
    ws = Workspace(root=soma_repo)

    res = promote_cell(ws, "law", force=True)

    assert res["status"] == "promoted" and res["to_type"] == "gate"
    assert (soma_repo / ".aegis" / "rules" / "gates" / "law.md").is_file()
    assert list((soma_repo / "rules").iterdir()) == []


def test_foreign_repo_local_promotion(tmp_path: Path):
    """Foreign repositories promote trap -> invariant -> gate without touching genome/."""
    repo = tmp_path / "app"
    repo.mkdir()
    traps_dir = repo / ".aegis" / "rules" / "traps"
    traps_dir.mkdir(parents=True)

    cell_file = traps_dir / "safety-check.md"
    cell_meta = {
        "id": "safety-check",
        "type": "trap",
        "enforcement": "advisory",
        "fitness": {"triggers": 25, "true_positives": 24, "false_positives": 1},
    }
    cell_file.write_text(dump_frontmatter(cell_meta, body="# Safety Rule\nMust be safe.\n"), encoding="utf-8")

    ws = Workspace(root=repo)

    # Step 1: Promote trap -> invariant
    res1 = promote_cell(ws, "safety-check", force=True)
    assert res1["status"] == "promoted"
    assert res1["from_type"] == "trap"
    assert res1["to_type"] == "invariant"
    assert not cell_file.exists()
    inv_file = repo / ".aegis" / "rules" / "invariants" / "safety-check.md"
    assert inv_file.exists()
    assert not (repo / "genome").exists()

    inv_meta = parse_frontmatter(inv_file.read_text(encoding="utf-8"))
    assert inv_meta["type"] == "invariant"
    assert inv_meta["enforcement"] == "gate"

    # Step 2: Promote invariant -> gate
    res2 = promote_cell(ws, "safety-check", force=True)
    assert res2["status"] == "promoted"
    assert res2["from_type"] == "invariant"
    assert res2["to_type"] == "gate"
    assert not inv_file.exists()
    gate_file = repo / ".aegis" / "rules" / "gates" / "safety-check.md"
    assert gate_file.exists()
    assert not (repo / "genome").exists()

    gate_meta = parse_frontmatter(gate_file.read_text(encoding="utf-8"))
    assert gate_meta["type"] == "gate"
    assert gate_meta["enforcement"] == "gate"

    # Step 3: Terminal check
    res3 = promote_cell(ws, "safety-check", force=True)
    assert res3["status"] == "already_terminal"
    assert not (repo / "genome").exists()


def test_foreign_repo_local_demotion(tmp_path: Path):
    """Foreign repositories demote gate -> invariant -> trap."""
    repo = tmp_path / "app"
    repo.mkdir()
    gates_dir = repo / ".aegis" / "rules" / "gates"
    gates_dir.mkdir(parents=True)

    cell_file = gates_dir / "strict-check.md"
    cell_meta = {
        "id": "strict-check",
        "type": "gate",
        "enforcement": "gate",
        "fitness": {"triggers": 30, "true_positives": 5, "false_positives": 25},
    }
    cell_file.write_text(dump_frontmatter(cell_meta, body="# Strict Check\n"), encoding="utf-8")

    ws = Workspace(root=repo)

    # Demote gate -> invariant
    res1 = demote_cell(ws, "strict-check")
    assert res1["status"] == "demoted"
    assert res1["from_type"] == "gate"
    assert res1["to_type"] == "invariant"
    inv_file = repo / ".aegis" / "rules" / "invariants" / "strict-check.md"
    assert inv_file.exists()
    assert not cell_file.exists()

    # Demote invariant -> trap
    res2 = demote_cell(ws, "strict-check")
    assert res2["status"] == "demoted"
    assert res2["from_type"] == "invariant"
    assert res2["to_type"] == "trap"
    trap_file = repo / ".aegis" / "rules" / "traps" / "strict-check.md"
    assert trap_file.exists()
    assert not inv_file.exists()


def test_parsers_ignore_a_genome_directory(tmp_path: Path):
    """Markdown in a project's genome/ (or any directory outside .aegis/rules) is never a rule."""
    repo = tmp_path / "bioinformatics_project"
    repo.mkdir()
    (repo / ".aegis" / "rules" / "invariants").mkdir(parents=True)

    # Foreign project happens to have a genome/ folder with markdown files
    foreign_genome = repo / "genome"
    foreign_genome.mkdir()
    foreign_rule = foreign_genome / "chromosome1.md"
    foreign_rule.write_text("---\nid: chromosome1\nnon_standard: true\n---\nDNA sequence data\n", encoding="utf-8")

    ws = Workspace(root=repo)

    # 1. find_cell_file should NOT return chromosome1
    found_path, cell_type = find_cell_file(ws, "chromosome1")
    assert found_path is None
    assert cell_type is None

    # 2. The loader never reads it
    assert load_rules(ws).rules == ()

