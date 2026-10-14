"""Tests for aegis migrate command and migrate_workspace utility."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aegis_cli.cli import main
from aegis_cli.migrate import migrate_workspace, run_migrate


def test_migrate_already_migrated(tmp_path: Path):
    (tmp_path / ".aegis" / "rules").mkdir(parents=True)
    res = migrate_workspace(tmp_path)
    assert res["status"] == "already_migrated"


def test_migrate_not_found(tmp_path: Path):
    res = migrate_workspace(tmp_path)
    assert res["status"] == "not_found"


def test_migrate_dry_run(tmp_path: Path):
    soma_cells = tmp_path / ".soma" / "cells"
    soma_cells.mkdir(parents=True)
    res = migrate_workspace(tmp_path, dry_run=True)
    assert res["status"] == "legacy_detected"
    assert "aegis migrate" in res["message"]
    assert "v2.1" in res["message"]
    assert (tmp_path / ".soma").is_dir()
    assert not (tmp_path / ".aegis").exists()


def test_migrate_full_cutover(tmp_path: Path):
    """In v3.0.0+, unmigrated .soma workspaces trigger the Upgrade Sentinel directing users to v2.1.x."""
    soma_dir = tmp_path / ".soma" / "cells"
    soma_dir.mkdir(parents=True)

    res = migrate_workspace(tmp_path, dry_run=False)
    assert res["status"] == "legacy_detected"
    assert "aegis migrate" in res["message"]
    assert "v2.1" in res["message"]


def test_cli_migrate_invocation(tmp_path: Path, capsys):
    soma_dir = tmp_path / ".soma" / "cells"
    soma_dir.mkdir(parents=True)

    code = main(["migrate", "--workspace", str(tmp_path)])
    assert code == 1
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "aegis migrate" in combined
    assert "v2.1" in combined
