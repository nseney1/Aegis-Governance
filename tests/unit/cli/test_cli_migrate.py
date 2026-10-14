"""Tests for aegis migrate command and migrate_workspace utility."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aegis_cli.cli import main
from aegis_cli.migrate import migrate_workspace, run_migrate, ORGANELLE_MAPPING


def test_migrate_already_migrated(tmp_path: Path):
    (tmp_path / ".aegis" / "rules").mkdir(parents=True)
    res = migrate_workspace(tmp_path)
    assert res["status"] == "already_migrated"


def test_migrate_not_found(tmp_path: Path):
    res = migrate_workspace(tmp_path)
    assert res["status"] == "not_found"


def test_migrate_dry_run(tmp_path: Path):
    soma_cells = tmp_path / ".soma" / "cells" / "walls"
    soma_cells.mkdir(parents=True)
    (soma_cells / "wall-test.md").write_text("# Test wall", encoding="utf-8")
    (tmp_path / "soma.conf").write_text("max_jit_tokens=4000\n", encoding="utf-8")

    res = migrate_workspace(tmp_path, dry_run=True)
    assert res["status"] == "preview"
    assert (tmp_path / ".soma").is_dir()
    assert not (tmp_path / ".aegis").exists()


def test_migrate_full_cutover(tmp_path: Path):
    soma_dir = tmp_path / ".soma"
    (soma_dir / "cells" / "walls").mkdir(parents=True)
    (soma_dir / "cells" / "vacuoles").mkdir(parents=True)
    (soma_dir / "cells" / "membranes").mkdir(parents=True)
    (soma_dir / "locks").mkdir(parents=True)

    (soma_dir / "cells" / "walls" / "wall-test.md").write_text(
        "---\nid: wall-test\ntype: wall\nenforcement: strict\n---\n# Wall\n",
        encoding="utf-8",
    )
    (soma_dir / "cells" / "vacuoles" / "trap-test.md").write_text(
        "---\nid: trap-test\ntype: vacuole\nenforcement: advisory\n---\n# Trap\n",
        encoding="utf-8",
    )
    (soma_dir / "locks" / "stale.lock").write_text("pid: 123", encoding="utf-8")
    (tmp_path / "soma.conf").write_text("max_jit_tokens=3000\n", encoding="utf-8")

    res = migrate_workspace(tmp_path, dry_run=False)
    assert res["status"] == "success"

    # Verify .soma is gone
    assert not (tmp_path / ".soma").exists()

    # Verify modern .aegis/rules layout
    aegis_dir = tmp_path / ".aegis"
    assert aegis_dir.is_dir()
    assert (aegis_dir / "rules" / "invariants" / "wall-test.md").is_file()
    assert (aegis_dir / "rules" / "traps" / "trap-test.md").is_file()

    # Verify locks cleaned
    assert not (aegis_dir / "locks" / "stale.lock").exists()

    # Verify manifest generated
    assert (aegis_dir / "rules" / "manifest.json").is_file()

    # Verify soma.conf -> aegis.conf
    assert not (tmp_path / "soma.conf").exists()
    assert (tmp_path / "aegis.conf").is_file()


def test_cli_migrate_invocation(tmp_path: Path, capsys):
    soma_dir = tmp_path / ".soma" / "cells" / "walls"
    soma_dir.mkdir(parents=True)
    (soma_dir / "wall-x.md").write_text("---\nid: wall-x\ntype: wall\n---\n# X", encoding="utf-8")

    code = main(["migrate", "--workspace", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Aegis Workspace Migration" in out
    assert "Migration complete" in out
    assert (tmp_path / ".aegis" / "rules" / "invariants" / "wall-x.md").is_file()
