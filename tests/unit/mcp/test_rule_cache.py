from pathlib import Path
"""Tests for aegis_mcp.cell_cache — mtime-based in-memory cell cache.

v0.83 'Fast Path': eliminates redundant disk I/O in MCP hot path.
"""
import json
import os
import sys
import time

import pytest
from aegis_core.yaml import dump_frontmatter

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from aegis_mcp.cell_cache import CellCache


def _make_cell(cells_dir, subdir, name, target_paths=None):
    """Create a minimal cell .md file."""
    path = os.path.join(cells_dir, subdir, f'{name}.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fm = {
        'id': name,
        'type': 'wall',
        'target_paths': target_paths or ['src/*.py'],
    }
    content = dump_frontmatter(fm, body=f"# {name}\nBody text.\n")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


class TestCellCacheBasic:
    """Core cache behavior."""

    def test_returns_cells_from_disk(self, tmp_path):
        """First call reads cells from disk."""
        cells_dir = str(tmp_path / '.soma' / 'cells')
        _make_cell(cells_dir, 'walls', 'trap-test')
        cache = CellCache()
        cells = cache.get_cells(str(tmp_path))
        assert len(cells) == 1
        assert cells[0]['id'] == 'trap-test'

    def test_second_call_returns_cached(self, tmp_path):
        """Second call with same mtime returns cached list (no re-parse)."""
        cells_dir = str(tmp_path / '.soma' / 'cells')
        _make_cell(cells_dir, 'walls', 'trap-test')
        cache = CellCache()
        cells1 = cache.get_cells(str(tmp_path))
        cells2 = cache.get_cells(str(tmp_path))
        # Same list object means cache hit
        assert cells1 is cells2

    def test_invalidates_on_new_file(self, tmp_path):
        """Adding a cell file triggers re-parse."""
        cells_dir = str(tmp_path / '.soma' / 'cells')
        _make_cell(cells_dir, 'walls', 'trap-a')
        cache = CellCache()
        cells1 = cache.get_cells(str(tmp_path))
        assert len(cells1) == 1

        # Touch the directory to update mtime
        time.sleep(0.05)
        _make_cell(cells_dir, 'walls', 'trap-b')

        cells2 = cache.get_cells(str(tmp_path))
        assert len(cells2) == 2
        assert cells2 is not cells1

    def test_invalidates_on_modified_file(self, tmp_path):
        """Modifying a cell file triggers re-parse."""
        cells_dir = str(tmp_path / '.soma' / 'cells')
        cell_path = _make_cell(cells_dir, 'walls', 'trap-test')
        cache = CellCache()
        cells1 = cache.get_cells(str(tmp_path))
        assert cells1[0]['id'] == 'trap-test'

        # Modify the file — touch to update mtime
        time.sleep(0.05)
        with open(cell_path, 'a', encoding='utf-8') as f:
            f.write('\nAppended.\n')
        # Touch parent dir to update dir mtime
        os.utime(os.path.dirname(cell_path))

        cells2 = cache.get_cells(str(tmp_path))
        assert cells2 is not cells1

    def test_empty_dir_returns_empty(self, tmp_path):
        """No cells directory → empty list."""
        cache = CellCache()
        cells = cache.get_cells(str(tmp_path))
        assert cells == []

    def test_deleted_cell_removed(self, tmp_path):
        """Removing a cell file updates cache."""
        cells_dir = str(tmp_path / '.soma' / 'cells')
        cell_path = _make_cell(cells_dir, 'walls', 'trap-a')
        _make_cell(cells_dir, 'walls', 'trap-b')
        cache = CellCache()
        cells1 = cache.get_cells(str(tmp_path))
        assert len(cells1) == 2

        time.sleep(0.05)
        os.remove(cell_path)
        # Touch dir to update mtime
        os.utime(os.path.dirname(cell_path))

        cells2 = cache.get_cells(str(tmp_path))
        assert len(cells2) == 1

    def test_skips_readme(self, tmp_path):
        """README.md files are not treated as cells."""
        cells_dir = str(tmp_path / '.soma' / 'cells')
        _make_cell(cells_dir, 'walls', 'trap-test')
        readme = os.path.join(cells_dir, 'README.md')
        with open(readme, 'w') as f:
            f.write('# Cell Directory\n')
        cache = CellCache()
        cells = cache.get_cells(str(tmp_path))
        assert len(cells) == 1

    def test_skips_expired_cells(self, tmp_path):
        """Cells with expired_at are excluded."""
        cells_dir = str(tmp_path / '.soma' / 'cells')
        path = os.path.join(cells_dir, 'walls', 'trap-expired.md')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fm = {'id': 'trap-expired', 'type': 'wall', 'expired_at': '2026-01-01'}
        content = dump_frontmatter(fm, body="Expired.\n")
        with open(path, 'w') as f:
            f.write(content)
        cache = CellCache()
        cells = cache.get_cells(str(tmp_path))
        assert len(cells) == 0


class TestCellCacheIntegration:
    """Integration with existing load_all_cells output format."""

    def test_output_matches_load_all_cells_schema(self, tmp_path):
        """Cache output has same keys as load_all_cells."""
        cells_dir = str(tmp_path / '.soma' / 'cells')
        _make_cell(cells_dir, 'walls', 'trap-schema')
        cache = CellCache()
        cells = cache.get_cells(str(tmp_path))
        cell = cells[0]
        # Must have internal keys set by load_all_cells
        assert '_name' in cell
        assert '_path' in cell
        assert '_body' in cell
        assert '_full' in cell
        assert cell['_name'] == 'trap-schema'


class TestCellCacheContentFingerprint:
    """Cache invalidation and I/O failures are content-correct and fail closed."""

    def test_same_size_edit_with_restored_mtime_invalidates(self, tmp_path):
        cells_dir = str(tmp_path / '.soma' / 'cells')
        cell_path = _make_cell(cells_dir, 'walls', 'trap-one')
        cache = CellCache()
        cells1 = cache.get_cells(str(tmp_path))
        original_stat = os.stat(cell_path)
        original = open(cell_path, encoding='utf-8').read()
        changed = original.replace('trap-one', 'trap-two')
        assert len(changed.encode('utf-8')) == len(original.encode('utf-8'))
        with open(cell_path, 'w', encoding='utf-8') as f:
            f.write(changed)
        os.utime(cell_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

        cells2 = cache.get_cells(str(tmp_path))
        assert cells2 is not cells1
        assert cells2[0]['id'] == 'trap-two'

    def test_stat_failure_after_warm_cache_raises(self, tmp_path, monkeypatch):
        import aegis_core.cell_inventory as inventory
        from aegis_mcp.cell_cache import CellCacheError

        cells_dir = str(tmp_path / '.soma' / 'cells')
        cell_path = _make_cell(cells_dir, 'walls', 'trap-test')
        cache = CellCache()
        warmed = cache.get_cells(str(tmp_path))
        real_stat = inventory.os.stat

        def failing_stat(path, *args, **kwargs):
            if os.fspath(path) == cell_path:
                raise PermissionError('simulated stat denial')
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(inventory.os, 'stat', failing_stat)
        with pytest.raises(CellCacheError, match='stat'):
            cache.get_cells(str(tmp_path))
        assert warmed[0]['id'] == 'trap-test'

    def test_open_failure_after_warm_cache_raises(self, tmp_path, monkeypatch):
        import aegis_core.cell_inventory as inventory
        from aegis_mcp.cell_cache import CellCacheError

        cells_dir = str(tmp_path / '.soma' / 'cells')
        cell_path = _make_cell(cells_dir, 'walls', 'trap-test')
        cache = CellCache()
        cache.get_cells(str(tmp_path))
        real_open = inventory.os.open

        def failing_open(path, *args, **kwargs):
            if os.fspath(path) == cell_path:
                raise PermissionError('simulated open denial')
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(inventory.os, 'open', failing_open)
        with pytest.raises(CellCacheError, match='open'):
            cache.get_cells(str(tmp_path))

    def test_load_uses_inventory_bytes_without_second_open(self, tmp_path, monkeypatch):
        import aegis_core.cell_inventory as inventory

        cells_dir = str(tmp_path / '.soma' / 'cells')
        _make_cell(cells_dir, 'walls', 'trap-test')
        inventory_result = inventory.inventory_cells(str(tmp_path))
        monkeypatch.setattr(
            inventory, 'inventory_cells', lambda workspace: inventory_result
        )

        def forbidden_open(*args, **kwargs):
            raise AssertionError('cache reopened a cell after inventory')

        monkeypatch.setattr('builtins.open', forbidden_open)
        cells = CellCache().get_cells(str(tmp_path))
        assert cells[0]['id'] == 'trap-test'

    def test_manifest_tampering_invalidates_cache_and_raises(self, tmp_path):
        from aegis_mcp.integrity import generate_key, generate_manifest, save_manifest
        from aegis_mcp.cell_cache import CellCacheError

        cells_dir = str(tmp_path / '.soma' / 'cells')
        _make_cell(cells_dir, 'walls', 'trap-test')

        # Generate key and signed manifest
        generate_key(str(tmp_path))
        manifest = generate_manifest(cells_dir)
        save_manifest(str(tmp_path), manifest)

        cache = CellCache()
        warmed = cache.get_cells(str(tmp_path))
        assert len(warmed) == 1

        # Tamper with manifest.json
        manifest_path = os.path.join(cells_dir, 'manifest.json')
        with open(manifest_path, 'w', encoding='utf-8') as f:
            f.write('{"cells": {}, "signature": "bogus"}')

        # get_cells must not serve stale cache and must fail integrity check
        with pytest.raises(CellCacheError, match="integrity"):
            cache.get_cells(str(tmp_path))

