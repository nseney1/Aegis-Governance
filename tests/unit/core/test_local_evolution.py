"""Tests for localized cell evolution and compound soma repo fingerprinting.

Verifies:
1. Workspace.is_aegis_repo compound check (pyproject.toml + soma_core + soma_cli).
2. Local promotion path in foreign repositories (vacuole -> wall -> gate), never creating/writing to genome/.
3. Global promotion path in Soma repository (vacuole -> wall -> genome).
4. Parsers, JIT engine, and metrics confining genome scanning to Soma repositories only.
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest

from aegis_core.yaml import dump_frontmatter, parse_frontmatter
from aegis_core.lifecycle.constants import (
    GLOBAL_PROMOTION_PATH,
    LOCAL_PROMOTION_PATH,
    GLOBAL_DEMOTION_PATH,
    LOCAL_DEMOTION_PATH,
    get_promotion_path,
    get_demotion_path,
)
from aegis_core.lifecycle.parsers import find_cell_file, _load_cells
from aegis_core.lifecycle.promotion import promote_cell, demote_cell, metamorphose_cell
from aegis_core.metrics import compute_token_census
from aegis_core.workspace import Workspace
from aegis_mcp.jit_engine import load_genome_rules


def test_promotion_paths_definition():
    """Verify promotion and demotion path dictionaries."""
    assert GLOBAL_PROMOTION_PATH == {"trap": "invariant", "invariant": "genome", "wall": "genome"}
    assert LOCAL_PROMOTION_PATH == {"trap": "invariant", "invariant": "gate", "wall": "gate"}
    assert GLOBAL_DEMOTION_PATH == {"genome": "invariant", "invariant": "trap", "wall": "trap"}
    assert LOCAL_DEMOTION_PATH == {"gate": "invariant", "invariant": "trap", "wall": "trap"}


def test_is_aegis_repo_detection(tmp_path: Path):
    """Verify compound detection of soma repo vs foreign repos."""
    foreign_repo = tmp_path / "foreign"
    foreign_repo.mkdir()
    # Has a genome/ dir (e.g. genomics project)
    (foreign_repo / "genome").mkdir()
    ws_foreign = Workspace(root=foreign_repo)
    assert not ws_foreign.is_aegis_repo
    assert get_promotion_path(ws_foreign) == LOCAL_PROMOTION_PATH
    assert get_demotion_path(ws_foreign) == LOCAL_DEMOTION_PATH

    soma_repo = tmp_path / "soma"
    soma_repo.mkdir()
    (soma_repo / "aegis_core").mkdir()
    (soma_repo / "aegis_cli").mkdir()
    (soma_repo / "pyproject.toml").write_text('name = "aegis-governance"\nversion = "0.120.0"\n', encoding="utf-8")
    ws_soma = Workspace(root=soma_repo)
    assert ws_soma.is_aegis_repo
    assert get_promotion_path(ws_soma) == GLOBAL_PROMOTION_PATH
    assert get_demotion_path(ws_soma) == GLOBAL_DEMOTION_PATH


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
    assert not ws.is_aegis_repo

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
    assert not ws.is_aegis_repo

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


def test_foreign_repo_metamorphose_cell(tmp_path: Path):
    """Foreign repositories metamorphose rules to gates instead of genome/."""
    repo = tmp_path / "app"
    repo.mkdir()
    walls_dir = repo / ".aegis" / "rules" / "walls"
    walls_dir.mkdir(parents=True)

    cell_file = walls_dir / "meta-check.md"
    cell_meta = {
        "id": "meta-check",
        "type": "wall",
        "fitness": {"triggers": 30, "true_positives": 28, "false_positives": 2, "score": 0.93},
    }
    cell_file.write_text(dump_frontmatter(cell_meta, body="# Meta Check\n"), encoding="utf-8")

    ws = Workspace(root=repo)
    res = metamorphose_cell(ws, cell_file)
    assert res["status"] == "metamorphosed"
    assert not (repo / "genome").exists()
    gate_file = repo / ".aegis" / "rules" / "gates" / "meta-check.md"
    assert gate_file.exists()


def test_parsers_and_jit_isolate_foreign_genome(tmp_path: Path):
    """Verify parsers, JIT engine, and metrics ignore genome/ in foreign repositories."""
    repo = tmp_path / "bioinformatics_project"
    repo.mkdir()
    (repo / ".aegis" / "rules" / "walls").mkdir(parents=True)

    # Foreign project happens to have a genome/ folder with markdown files
    foreign_genome = repo / "genome"
    foreign_genome.mkdir()
    foreign_rule = foreign_genome / "chromosome1.md"
    foreign_rule.write_text("---\nid: chromosome1\nnon_standard: true\n---\nDNA sequence data\n", encoding="utf-8")

    ws = Workspace(root=repo)
    assert not ws.is_aegis_repo

    # 1. find_cell_file should NOT return chromosome1
    found_path, cell_type = find_cell_file(ws, "chromosome1")
    assert found_path is None
    assert cell_type is None

    # 2. _load_cells should NOT include chromosome1
    cells = _load_cells(ws)
    assert not any(c["id"] == "chromosome1" for c in cells)

    # 3. load_genome_rules should return empty list
    rules = load_genome_rules(str(repo), ["chromosome1.md"])
    assert rules == []

    # 4. compute_token_census should report 0 genome rules
    census = compute_token_census(ws)
    assert not any(item["filename"].startswith("genome/") for item in census["files"])
