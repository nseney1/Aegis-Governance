"""Regression tests for the canonical governance-cell inventory."""
import os
import time

import pytest


def _write_cell(path, cell_id="cell-a"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"id: {cell_id}\n"
        "domain: testing\n"
        "type: wall\n"
        "enforcement: gate\n"
        "target_paths: ['src/*.py']\n"
        "---\n"
        "# Rule\n",
        encoding="utf-8",
    )


def test_inventory_is_stable_and_captures_exact_bytes(tmp_path):
    from aegis_core.cell_inventory import inventory_cells

    first_path = tmp_path / ".aegis" / "rules" / "walls" / "b.md"
    second_path = tmp_path / ".aegis" / "rules" / "vacuoles" / "a.md"
    _write_cell(first_path, "b")
    _write_cell(second_path, "a")

    first = inventory_cells(str(tmp_path))
    second = inventory_cells(str(tmp_path))

    assert [entry.relative_path for entry in first.entries] == [
        ".aegis/rules/vacuoles/a.md",
        ".aegis/rules/walls/b.md",
    ]
    assert first.fingerprint == second.fingerprint
    assert first.entries == second.entries
    for entry in first.entries:
        assert os.path.isabs(entry.absolute_path)
        assert entry.size == len(entry.content)
        assert len(entry.digest) == 64
        assert entry.content == open(entry.absolute_path, "rb").read()


def test_cell_edited_after_creation_is_inventoried(tmp_path):
    """BUG-035: on Windows os.stat reports st_ctime as creation time but
    os.fstat reports it as last-change time, so any cell edited after it was
    created was rejected as 'changed before it was opened'."""
    from aegis_core.cell_inventory import inventory_cells

    cell = tmp_path / ".aegis" / "rules" / "walls" / "edited.md"
    _write_cell(cell, "edited")
    time.sleep(0.05)
    with open(cell, "a", encoding="utf-8") as f:
        f.write("Edited after creation.\n")

    inventory = inventory_cells(str(tmp_path))
    assert [entry.relative_path for entry in inventory.entries] == [
        ".aegis/rules/walls/edited.md"
    ]
    assert inventory.entries[0].content == cell.read_bytes()
    assert b"Edited after creation." in inventory.entries[0].content


def test_missing_cells_directory_has_stable_empty_inventory(tmp_path):
    from aegis_core.cell_inventory import inventory_cells

    inventory = inventory_cells(str(tmp_path))
    assert inventory.entries == ()
    assert len(inventory.fingerprint) == 64


def test_symlinked_cell_is_rejected(tmp_path):
    from aegis_core.cell_inventory import CellInventoryError, inventory_cells

    outside = tmp_path / "outside.md"
    _write_cell(outside, "outside")
    link = tmp_path / ".aegis" / "rules" / "walls" / "linked.md"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")

    with pytest.raises(CellInventoryError, match="symlink"):
        inventory_cells(str(tmp_path))


def test_symlinked_directory_that_would_feed_jit_is_rejected(tmp_path):
    from aegis_mcp.cell_cache import CellCacheError
    from aegis_mcp.jit_engine import CellCache, express
    import aegis_mcp.jit_engine as jit_engine

    outside = tmp_path / "outside" / "walls"
    _write_cell(outside / "external.md", "external")
    cells_dir = tmp_path / "workspace" / ".aegis" / "rules"
    cells_dir.mkdir(parents=True)
    link = cells_dir / "external-rules"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")

    previous = jit_engine._cell_cache
    jit_engine._cell_cache = CellCache()
    try:
        with pytest.raises(CellCacheError, match="symlink"):
            express(str(tmp_path / "workspace"), changed_files=["src/app.py"])
    finally:
        jit_engine._cell_cache = previous


def test_find_matching_cells(tmp_path):
    from aegis_core.cell_inventory import find_matching_cells
    cells_dir = tmp_path / ".aegis" / "rules"
    _write_cell(cells_dir / "walls" / "test_wall.md", "test-wall")

    matches = find_matching_cells(cells_dir, ["src/index.py"])
    assert len(matches) == 1
    assert matches[0].cell_id == "test-wall"

    # Non-matching path
    assert find_matching_cells(cells_dir, ["other/file.txt"]) == []

    # Non-existent dir or empty files
    assert find_matching_cells(tmp_path / "nonexistent", ["src/index.py"]) == []
    assert find_matching_cells(cells_dir, []) == []


def test_inventory_aegis_rules_and_soma_rules(tmp_path):
    from aegis_core.cell_inventory import inventory_cells, inventory_rules

    # Test .aegis/rules
    ws_aegis = tmp_path / "ws_aegis"
    rule_aegis = ws_aegis / ".aegis" / "rules" / "invariants" / "inv1.md"
    _write_cell(rule_aegis, "inv1")
    inv = inventory_rules(str(ws_aegis))
    assert [e.relative_path for e in inv.entries] == [".aegis/rules/invariants/inv1.md"]

    # Test .aegis/rules
    ws_soma_rules = tmp_path / "ws_soma_rules"
    rule_soma = ws_soma_rules / ".aegis" / "rules" / "invariants" / "inv2.md"
    _write_cell(rule_soma, "inv2")
    inv2 = inventory_cells(str(ws_soma_rules))
    assert [e.relative_path for e in inv2.entries] == [".aegis/rules/invariants/inv2.md"]
