"""Unit tests for aegis_core.sync."""
import json
import pytest
from aegis_core.sync import (
    check_liveness,
    classify_file,
    is_test_file,
    prompt_llm_translation,
)


def test_sync_liveness_check():
    payload = json.dumps({
        "agents": [
            {
                "name": "worker",
                "dispatched": "2026-10-05T12:00:00Z",
                "timeout_seconds": 3600,
            }
        ]
    })
    rc = check_liveness(payload)
    assert rc == 0


def test_sync_classification():
    assert classify_file("enzymes/cell_create.sh") == "HIGH"
    assert classify_file("genome/testing.md") == "MEDIUM"
    assert classify_file("docs/README.md") == "LOW"
    assert is_test_file("tests/test_sync.py")
    assert not is_test_file("soma_core/sync.py")


def test_sync_hgt_mock_translation():
    res = prompt_llm_translation("draft all combat-capable pawns", mock=True)
    assert "Resource Consolidation" in res


def test_run_push_member_id_traversal_rejected(tmp_path):
    from aegis_core.sync import run_push

    team_repo = tmp_path / "team"
    repo = tmp_path / "repo"
    team_repo.mkdir()
    repo.mkdir()

    with pytest.raises(ValueError, match="Invalid member_id"):
        run_push(repo, team_repo, None, "../../traversal")

    with pytest.raises(ValueError, match="Invalid member_id"):
        run_push(repo, team_repo, None, "")


def test_sync_sentinel_exports(tmp_path):
    from pathlib import Path
    from aegis_core.sync import set_review_mode, write_frontmatter, resolve_home
    from aegis_core.yaml import parse_frontmatter
    # Test set_review_mode
    conf = tmp_path / "steering.conf"
    conf.write_text("REVIEW_MODE=breeze\nOTHER=true\n", encoding="utf-8")
    set_review_mode(str(tmp_path), "maelstrom")
    assert "REVIEW_MODE=maelstrom\n" in conf.read_text(encoding="utf-8")

    # Test write_frontmatter
    out_cell = tmp_path / "cell.md"
    write_frontmatter(str(out_cell), {"id": "test-cell", "type": "gene"}, "Cell body text\n")
    assert out_cell.exists()
    parsed = parse_frontmatter(out_cell.read_text(encoding="utf-8"))
    assert parsed.get("id") == "test-cell"

    # Test resolve_home
    home = resolve_home()
    assert isinstance(home, Path)
    assert home.exists()


def test_sync_liveness_check_naive_datetime():
    # W-07: Ensure offset-naive datetime string does not raise TypeError
    payload = json.dumps({
        "agents": [
            {
                "name": "worker-naive",
                "dispatched": "2026-10-05T12:00:00",
                "timeout_seconds": 3600,
            }
        ]
    })
    rc = check_liveness(payload)
    assert rc == 0


def test_sync_command_contract():
    import argparse
    from unittest.mock import patch
    from aegis_cli.sync import SyncCommand
    cmd = SyncCommand()
    parser = argparse.ArgumentParser()
    cmd.configure_parser(parser)
    parsed = parser.parse_args(["--dry-run"])
    assert parsed.dry_run is True

    with patch("aegis_cli.sync.run_sync", return_value=0) as mock_run:
        assert cmd.execute(parsed) == 0
        mock_run.assert_called_once_with(parsed)


