"""`aegis migrate` from the command line: dry run by default, --apply, --json, exit codes."""
from __future__ import annotations

import json
from pathlib import Path

from aegis_cli.cli import main
from aegis_core.workspace.discovery import LEGACY_SOMA_UPGRADE_MSG


def _soma_workspace(root: Path) -> Path:
    cell = root / ".soma" / "cells" / "vacuoles" / "trap-x.md"
    cell.parent.mkdir(parents=True)
    cell.write_text("---\ntype: vacuole\nfitness:\n  triggers: 2\n---\nBody\n", encoding="utf-8")
    odd = root / ".soma" / "cells" / "ribosomes" / "ribosome-y.md"
    odd.parent.mkdir(parents=True)
    odd.write_text("---\ntype: ribosome\n---\nBody\n", encoding="utf-8")
    return root


def _tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_dry_run_is_the_default_and_writes_nothing(tmp_path: Path, capsys):
    root = _soma_workspace(tmp_path)
    before = _tree(root)

    assert main(["migrate", "--workspace", str(root)]) == 0

    out = capsys.readouterr().out
    assert "dry run: nothing written; rerun with --apply" in out
    assert "rule: .soma/cells/vacuoles/trap-x.md -> .aegis/rules/traps/trap-x.md (type trap)" in out
    assert "unmapped type 'ribosome': .soma/cells/ribosomes/ribosome-y.md left in place" in out
    assert _tree(root) == before
    assert main(["migrate", "--workspace", str(root), "--dry-run"]) == 0


def test_apply_converts_and_exits_1_when_something_was_left_behind(tmp_path: Path, capsys):
    root = _soma_workspace(tmp_path)

    assert main(["migrate", "--workspace", str(root), "--apply"]) == 1

    out = capsys.readouterr().out
    assert "migrated" in out and "backup:" in out
    assert (root / ".aegis" / "rules" / "traps" / "trap-x.md").read_text(encoding="utf-8") == "---\ntype: trap\n---\nBody\n"
    assert (root / ".soma" / "cells" / "ribosomes" / "ribosome-y.md").is_file()


def test_json_report_and_idempotent_second_apply(tmp_path: Path, capsys):
    root = tmp_path / "ws"
    cell = root / ".soma" / "cells" / "walls" / "wall-a.md"
    cell.parent.mkdir(parents=True)
    cell.write_text("---\ntype: wall\n---\nBody\n", encoding="utf-8")

    assert main(["--json", "migrate", "--workspace", str(root), "--apply"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "applied"
    assert first["rules"] == [{"from": ".soma/cells/walls/wall-a.md", "to": ".aegis/rules/invariants/wall-a.md",
                               "type": "invariant"}]
    assert first["backup"].endswith(first["backup"].split("/")[-1]) and "migrate-backup-" in first["backup"]

    assert main(["--json", "migrate", "--workspace", str(root), "--apply"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["status"] == "up_to_date" and second["backup"] is None


def test_apply_and_dry_run_together_is_a_usage_error(tmp_path: Path, capsys):
    assert main(["migrate", "--workspace", str(tmp_path), "--apply", "--dry-run"]) == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_the_legacy_sentinel_points_at_migrate(tmp_path: Path):
    assert "aegis migrate --apply" in LEGACY_SOMA_UPGRADE_MSG
