"""Tests for signature-based global rules cleanse and quarantine.

Verifies:
1. Safe preview default (dry_run=True); --force required to execute changes.
2. Whitelist retention: universal tenets and custom user rules are strictly preserved.
3. Purge targeting: leaked HGT rules (hgt-*.md) and internal Soma rules are quarantined and removed.
4. Delimiter-targeted cleanup of ~/.claude/CLAUDE.md preserving user content.
5. Mandatory backup creation in ~/.soma/quarantine/global_rules_backup_{TIMESTAMP}/.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import pytest

from aegis_cli.rule import (
    UNIVERSAL_TENETS,
    clean_global_rules,
    run_clean_rules,
)
from aegis_core.somayaml import dump_frontmatter


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()

    # Gemini rules
    gemini_rules = home / ".gemini" / "config" / "rules"
    gemini_rules.mkdir(parents=True)

    # 1. Universal tenet (must retain)
    (gemini_rules / "providence.md").write_text("# Providence\nGrounding over guesswork.\n", encoding="utf-8")
    (gemini_rules / "cost-optimization.md").write_text("# Cost Optimization\n", encoding="utf-8")

    # 2. Custom user rule (must retain!)
    (gemini_rules / "my-custom-pipeline.md").write_text("# My Custom Pipeline\nCompany rule.\n", encoding="utf-8")

    # 3. Leaked HGT rule (must purge)
    (gemini_rules / "hgt-resource-consolidation-hgt001.md").write_text("# RimWorld Raid Defense\n", encoding="utf-8")

    # 4. Leaked Soma internal rule (must purge)
    (gemini_rules / "core-change-protocol.md").write_text("# Core Change Protocol\n", encoding="utf-8")
    (gemini_rules / "optional-import-guard.md").write_text("# Optional Import Guard\n", encoding="utf-8")

    # Claude CLAUDE.md
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    claude_content = (
        "# Claude User Instructions\n\n"
        "Custom instructions for Claude.\n\n"
        "<!-- SOMA:START -->\n"
        "## Providence\nUniversal providence rule.\n\n"
        "## Core Change Protocol\nInternal Soma protocol leaked here.\n\n"
        "## HGT Resource Consolidation\nLeaked RimWorld raid defense.\n"
        "<!-- SOMA:END -->\n\n"
        "## User Custom Section\nDo not delete this section!\n"
    )
    (claude_dir / "CLAUDE.md").write_text(claude_content, encoding="utf-8")
    return home


def test_dry_run_does_not_modify_files(fake_home: Path):
    """By default, clean_global_rules runs in dry-run mode and modifies nothing."""
    res = clean_global_rules(home_dir=fake_home, dry_run=True, force=False)
    assert res["dry_run"] is True
    assert "hgt-resource-consolidation-hgt001.md" in res["purged_rules"]
    assert "core-change-protocol.md" in res["purged_rules"]
    assert "optional-import-guard.md" in res["purged_rules"]
    assert "providence.md" in res["retained_rules"]
    assert "my-custom-pipeline.md" in res["retained_rules"]

    # Files must still exist on disk
    gemini_rules = fake_home / ".gemini" / "config" / "rules"
    assert (gemini_rules / "hgt-resource-consolidation-hgt001.md").exists()
    assert (gemini_rules / "core-change-protocol.md").exists()
    assert (gemini_rules / "providence.md").exists()
    assert (gemini_rules / "my-custom-pipeline.md").exists()


def test_force_cleans_rules_with_quarantine_backup(fake_home: Path):
    """When force=True and dry_run=False, leaked files are moved to quarantine and removed from config."""
    q_dir = fake_home / ".soma" / "quarantine"
    res = clean_global_rules(home_dir=fake_home, dry_run=False, force=True, quarantine_dir=q_dir)
    assert res["dry_run"] is False

    gemini_rules = fake_home / ".gemini" / "config" / "rules"
    # Leaked rules deleted from rules dir
    assert not (gemini_rules / "hgt-resource-consolidation-hgt001.md").exists()
    assert not (gemini_rules / "core-change-protocol.md").exists()
    assert not (gemini_rules / "optional-import-guard.md").exists()

    # Universal and custom rules preserved
    assert (gemini_rules / "providence.md").exists()
    assert (gemini_rules / "cost-optimization.md").exists()
    assert (gemini_rules / "my-custom-pipeline.md").exists()

    # Quarantine directory created with backups
    assert q_dir.exists()
    backup_dirs = list(q_dir.glob("global_rules_backup_*"))
    assert len(backup_dirs) == 1
    bdir = backup_dirs[0]
    assert (bdir / "hgt-resource-consolidation-hgt001.md").exists()
    assert (bdir / "core-change-protocol.md").exists()
    assert (bdir / "CLAUDE.md").exists()

    # CLAUDE.md was cleaned and user custom content was preserved
    claude_md = fake_home / ".claude" / "CLAUDE.md"
    assert claude_md.exists()
    content = claude_md.read_text(encoding="utf-8")
    assert "Custom instructions for Claude." in content
    assert "## User Custom Section" in content
    assert "Do not delete this section!" in content
    assert "## Providence" in content
    assert "## Core Change Protocol" not in content
    assert "## HGT Resource Consolidation" not in content


def test_cli_clean_global_rules_command(fake_home: Path, monkeypatch):
    """CLI dispatcher executes soma clean-global-rules."""
    monkeypatch.setenv("HOME", str(fake_home))

    # Dry-run
    args_dry = argparse.Namespace(dry_run=True, force=False, quarantine_dir="")
    rc = run_clean_rules(args_dry)
    assert rc == 0
    assert (fake_home / ".gemini" / "config" / "rules" / "core-change-protocol.md").exists()

    # Force run
    args_force = argparse.Namespace(dry_run=False, force=True, quarantine_dir="")
    rc = run_clean_rules(args_force)
    assert rc == 0
    assert not (fake_home / ".gemini" / "config" / "rules" / "core-change-protocol.md").exists()
