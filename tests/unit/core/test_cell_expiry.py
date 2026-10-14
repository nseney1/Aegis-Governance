from pathlib import Path
"""Tests for cell expiry enforcement.

Verifies that:
1. Cells past expiry_days are flagged as expired
2. Cells past expiry_sessions are flagged as expired
3. Cells within limits are not flagged
4. Walls (mandatory) get warnings, not expiry
5. --prune mode adds expired_at marker to cell frontmatter
"""
import os
import sys
import tempfile
import shutil
from datetime import datetime, timedelta

import pytest
from aegis_core.yaml import dump_frontmatter, parse_frontmatter

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)


def make_cell(cells_dir, name, cell_type="vacuole", created_days_ago=10,
              expiry_days=30, expiry_sessions=20, enforcement="advisory"):
    """Helper: create a cell file with given metadata."""
    created = (datetime.now() - timedelta(days=created_days_ago)).strftime("%Y-%m-%d")
    frontmatter = {
        'id': name,
        'type': cell_type,
        'enforcement': enforcement,
        'hypothesis': f'Test cell {name}',
        'prediction': 'test',
        'falsification': 'test',
        'target_paths': ['*.py'],
        'expiry_sessions': expiry_sessions,
        'expiry_days': expiry_days,
        'created': created,
    }
    content = dump_frontmatter(frontmatter, body=f"# {name}\nTest content\n")
    subdir = os.path.join(cells_dir, f"{cell_type}s")
    os.makedirs(subdir, exist_ok=True)
    filepath = os.path.join(subdir, f"{name}.md")
    with open(filepath, 'w') as f:
        f.write(content)
    return filepath


@pytest.fixture
def workspace(tmp_path):
    """Create a temp workspace with .soma/cells/ structure."""
    cells_dir = tmp_path / ".soma" / "cells"
    cells_dir.mkdir(parents=True)
    evidence_dir = tmp_path / ".soma" / "evidence"
    evidence_dir.mkdir(parents=True)
    return tmp_path


class TestExpiryByDays:
    """Verify day-based expiry enforcement."""

    def test_fresh_cell_not_expired(self, workspace):
        from aegis_core.defects import audit_expiry
        cells_dir = str(workspace / ".soma" / "cells")
        make_cell(cells_dir, "fresh-cell", created_days_ago=5, expiry_days=30)
        results = audit_expiry(str(workspace))
        expired = [r for r in results if r['status'] == 'EXPIRED']
        assert len(expired) == 0

    def test_old_cell_is_expired(self, workspace):
        from aegis_core.defects import audit_expiry
        cells_dir = str(workspace / ".soma" / "cells")
        make_cell(cells_dir, "stale-cell", created_days_ago=45, expiry_days=30)
        results = audit_expiry(str(workspace))
        expired = [r for r in results if r['status'] == 'EXPIRED']
        assert len(expired) == 1
        assert expired[0]['cell_id'] == 'stale-cell'
        assert expired[0]['reason'] == 'expiry_days'

    def test_cell_at_exact_expiry_not_expired(self, workspace):
        from aegis_core.defects import audit_expiry
        cells_dir = str(workspace / ".soma" / "cells")
        make_cell(cells_dir, "edge-cell", created_days_ago=30, expiry_days=30)
        results = audit_expiry(str(workspace))
        expired = [r for r in results if r['status'] == 'EXPIRED']
        assert len(expired) == 0, "Cell at exact expiry boundary should NOT be expired"


class TestExpiryBySessions:
    """Verify session-based expiry enforcement."""

    def test_cell_with_no_sessions_not_expired(self, workspace):
        from aegis_core.defects import audit_expiry
        cells_dir = str(workspace / ".soma" / "cells")
        make_cell(cells_dir, "no-sessions", expiry_sessions=10)
        results = audit_expiry(str(workspace), session_count=0)
        expired = [r for r in results if r['status'] == 'EXPIRED']
        assert len(expired) == 0

    def test_cell_past_session_limit_is_expired(self, workspace):
        from aegis_core.defects import audit_expiry
        cells_dir = str(workspace / ".soma" / "cells")
        make_cell(cells_dir, "overdue-cell", expiry_sessions=10)
        results = audit_expiry(str(workspace), session_count=15)
        expired = [r for r in results if r['status'] == 'EXPIRED']
        assert len(expired) == 1
        assert expired[0]['reason'] == 'expiry_sessions'


class TestWallProtection:
    """Walls are mandatory — they get warnings, not expiry."""

    def test_expired_wall_gets_warning_not_expiry(self, workspace):
        from aegis_core.defects import audit_expiry
        cells_dir = str(workspace / ".soma" / "cells")
        make_cell(cells_dir, "wall-auth", cell_type="wall",
                  created_days_ago=100, expiry_days=30)
        results = audit_expiry(str(workspace))
        wall = [r for r in results if r['cell_id'] == 'wall-auth']
        assert len(wall) == 1
        assert wall[0]['status'] == 'EXPIRY_WARNING', \
            f"Walls should get EXPIRY_WARNING, got {wall[0]['status']}"


class TestPruneMode:
    """Verify --prune adds expired_at to cell frontmatter."""

    def test_prune_adds_expired_at_marker(self, workspace):
        from aegis_core.defects import audit_expiry, prune_expired
        cells_dir = str(workspace / ".soma" / "cells")
        filepath = make_cell(cells_dir, "to-prune",
                             created_days_ago=60, expiry_days=30)
        results = audit_expiry(str(workspace))
        expired = [r for r in results if r['status'] == 'EXPIRED']
        assert len(expired) == 1

        pruned = prune_expired(str(workspace), results)
        assert pruned == 1

        # Verify the file was updated
        with open(filepath) as f:
            content = f.read()
        fm = parse_frontmatter(content)
        assert 'expired_at' in fm, "Pruned cell should have expired_at marker"

    def test_prune_skips_non_expired(self, workspace):
        from aegis_core.defects import audit_expiry, prune_expired
        cells_dir = str(workspace / ".soma" / "cells")
        make_cell(cells_dir, "healthy-cell", created_days_ago=5, expiry_days=30)
        results = audit_expiry(str(workspace))
        pruned = prune_expired(str(workspace), results)
        assert pruned == 0
