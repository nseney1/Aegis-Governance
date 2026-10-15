"""Behavioral tests for CLI root workspace resolution and subcommand migration (Phase 18)."""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from aegis_cli.cli import main
from aegis_core.workspace.base import Workspace


@pytest.fixture
def initialized_ws(tmp_path: Path) -> Workspace:
    ws_dir = tmp_path / "init_project"
    (ws_dir / ".aegis" / "rules" / "invariants").mkdir(parents=True)
    (ws_dir / ".aegis" / "state").mkdir(parents=True)
    (ws_dir / ".aegis" / "rules" / "invariants" / "test.md").write_text("---\ntype: invariant\n---\n")
    return Workspace(root=ws_dir)


def _capture_execute(monkeypatch, command_cls):
    """Replace a command's execute with a recorder; return the list of received args."""
    calls = []

    def fake_execute(self, args):
        calls.append(args)
        return 0

    monkeypatch.setattr(command_cls, "execute", fake_execute)
    return calls


class TestCliWorkspaceRootResolution:
    def test_root_resolution_attaches_workspace_object(self, initialized_ws: Workspace, monkeypatch):
        """main() resolves target path into strongly-typed args.ws Workspace object."""
        from aegis_cli.status import StatusCommand

        calls = _capture_execute(monkeypatch, StatusCommand)
        assert main(["status", "--workspace", str(initialized_ws.root)]) == 0
        assert len(calls) == 1
        args = calls[0]
        assert isinstance(args.ws, Workspace)
        assert args.ws == initialized_ws
        assert args._project_root == initialized_ws.root
        assert args.workspace == str(initialized_ws.root)

    def test_root_resolution_for_init_uninitialized_directory(self, tmp_path: Path, monkeypatch):
        """aegis init resolves via Workspace.for_init without requiring .aegis/rules/."""
        from aegis_cli.init import InitCommand

        blank_dir = tmp_path / "blank_repo"
        blank_dir.mkdir()
        calls = _capture_execute(monkeypatch, InitCommand)
        assert main(["init", "--workspace", str(blank_dir), "--dry-run"]) == 0
        args = calls[0]
        assert isinstance(args.ws, Workspace)
        assert args.ws.root == blank_dir.resolve()
        assert not (args.ws.root / ".aegis" / "rules").exists()

    def test_root_resolution_argument_precedence(self, tmp_path: Path, initialized_ws: Workspace, monkeypatch):
        """Workspace is resolved canonical via --workspace, and legacy --repo-root is rejected."""
        from aegis_cli.check import CheckCommand

        calls = _capture_execute(monkeypatch, CheckCommand)
        assert main(["check", "--workspace", str(initialized_ws.root), "--dry-run"]) == 0
        assert calls[0].ws == initialized_ws

        # Legacy --repo-root is purged and rejected
        with pytest.raises(SystemExit):
            main(["check", "--repo-root", str(tmp_path)])


class TestSubcommandDirectInvocationFallback:
    def test_handler_fallback_when_bypassing_main(self, initialized_ws: Workspace):
        """Direct invocation of subcommand handlers without args.ws falls back to Workspace.resolve()."""
        from aegis_cli.status import run_status

        # Create a raw Namespace with no ws attribute
        raw_args = argparse.Namespace(
            workspace=str(initialized_ws.root),
            json=True,
            plain=False,
        )
        exit_code = run_status(raw_args)
        assert exit_code == 0
