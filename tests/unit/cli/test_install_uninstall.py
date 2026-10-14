"""Tests for soma install and soma uninstall commands."""
import argparse
from pathlib import Path
import pytest

from aegis_cli.install import run_install, run_uninstall, InstallCommand, UninstallCommand
from aegis_cli.hooks.management import generate_hook_block


def test_uninstall_command_contract():
    cmd = UninstallCommand()
    parser = argparse.ArgumentParser()
    cmd.configure_parser(parser)
    parsed = parser.parse_args(["--platform", "claude", "--local", "--dry-run", "--purge"])
    assert parsed.platform == "claude"
    assert parsed.local is True
    assert parsed.dry_run is True
    assert parsed.purge is True


def test_install_command_contract():
    cmd = InstallCommand()
    parser = argparse.ArgumentParser()
    cmd.configure_parser(parser)
    parsed = parser.parse_args(["--platform", "claude", "--local", "--dry-run"])
    assert parsed.platform == "claude"
    assert parsed.local is True
    assert parsed.dry_run is True


def test_uninstall_removes_pre_commit_hook(tmp_path, capsys):
    """soma uninstall removes the soma hook block from .git/hooks/pre-commit."""
    git_dir = tmp_path / ".git" / "hooks"
    git_dir.mkdir(parents=True)
    hook_file = git_dir / "pre-commit"
    user_script = "#!/bin/sh\n# custom user hook\necho 'hello'\n"
    soma_block = generate_hook_block("python3")
    hook_file.write_text(user_script + "\n" + soma_block, encoding="utf-8")

    args = argparse.Namespace(
        platform="claude",
        local=True,
        dry_run=False,
        purge=False,
        _project_root=tmp_path,
    )
    rc = run_uninstall(args)
    assert rc == 0
    assert hook_file.is_file()
    remaining = hook_file.read_text(encoding="utf-8")
    assert "custom user hook" in remaining
    assert "SOMA_HOOK_START" not in remaining


def test_uninstall_purge_removes_soma_dir(tmp_path, capsys):
    """soma uninstall --purge removes .soma/ while non-purge preserves it."""
    soma_dir = tmp_path / ".soma"
    soma_dir.mkdir()
    (soma_dir / "slots.yaml").write_text("dummy: 1\n", encoding="utf-8")

    # 1. Non-purge preserves .soma
    args = argparse.Namespace(
        platform="claude",
        local=True,
        dry_run=False,
        purge=False,
        _project_root=tmp_path,
    )
    rc = run_uninstall(args)
    assert rc == 0
    assert soma_dir.is_dir()

    # 2. Purge deletes .soma
    args.purge = True
    rc = run_uninstall(args)
    assert rc == 0
    assert not soma_dir.exists()


def test_uninstall_dry_run_leaves_files(tmp_path, capsys):
    """soma uninstall --dry-run prints would remove and leaves files untouched."""
    soma_dir = tmp_path / ".soma"
    soma_dir.mkdir()
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("<!-- SOMA:START -->\n# Soma\n<!-- SOMA:END -->\n", encoding="utf-8")

    args = argparse.Namespace(
        platform="claude",
        local=True,
        dry_run=True,
        purge=True,
        _project_root=tmp_path,
    )
    rc = run_uninstall(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "[dry-run] Would uninstall" in captured.out
    assert "[dry-run] Would remove" in captured.out
    assert soma_dir.is_dir()
    assert claude_md.is_file()
