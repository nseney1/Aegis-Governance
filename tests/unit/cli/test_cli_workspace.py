"""Behavioral tests for CLI root workspace resolution and subcommand migration (Phase 18)."""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aegis_cli.cli import _build_parser, main
from aegis_core.workspace import Workspace


@pytest.fixture
def initialized_ws(tmp_path: Path) -> Workspace:
    ws_dir = tmp_path / "init_project"
    (ws_dir / ".soma" / "cells" / "walls").mkdir(parents=True)
    (ws_dir / ".soma" / "evidence").mkdir(parents=True)
    (ws_dir / ".soma" / "cells" / "walls" / "test.md").write_text("---\ntype: wall\n---\n")
    return Workspace(root=ws_dir)


class TestCliWorkspaceRootResolution:
    def test_root_resolution_attaches_workspace_object(self, initialized_ws: Workspace):
        """main() resolves target path into strongly-typed args.ws Workspace object."""
        with patch("aegis_cli.cli.cmd_status", return_value=0) as mock_status:
            exit_code = main(["status", "--workspace", str(initialized_ws.root)])
            assert exit_code == 0
            mock_status.assert_called_once()
            args = mock_status.call_args[0][0]
            assert hasattr(args, "ws")
            assert isinstance(args.ws, Workspace)
            assert args.ws == initialized_ws
            assert args._project_root == initialized_ws.root
            assert args.workspace == str(initialized_ws.root)

    def test_root_resolution_exempts_completion(self):
        """soma completion command is exempted from workspace resolution."""
        with patch("aegis_cli.cli.cmd_completion", return_value=0) as mock_comp:
            exit_code = main(["completion", "bash"])
            assert exit_code == 0
            mock_comp.assert_called_once()
            args = mock_comp.call_args[0][0]
            assert getattr(args, "ws", None) is None

    def test_root_resolution_for_init_uninitialized_directory(self, tmp_path: Path):
        """soma init resolves via Workspace.for_init without requiring .soma/cells/."""
        blank_dir = tmp_path / "blank_repo"
        blank_dir.mkdir()

        with patch("aegis_cli.cli.cmd_init", return_value=0) as mock_init:
            exit_code = main(["init", "--workspace", str(blank_dir), "--dry-run"])
            assert exit_code == 0
            mock_init.assert_called_once()
            args = mock_init.call_args[0][0]
            assert isinstance(args.ws, Workspace)
            assert args.ws.root == blank_dir.resolve()
            assert not (args.ws.root / ".soma" / "cells").exists()

    def test_root_resolution_argument_precedence(self, tmp_path: Path, initialized_ws: Workspace):
        """Workspace is resolved canonical via --workspace, and legacy --repo-root is rejected."""
        with patch("aegis_cli.cli.cmd_verify", return_value=0) as mock_verify:
            exit_code = main([
                "verify",
                "--workspace", str(initialized_ws.root),
                "--dry-run"
            ])
            assert exit_code == 0
            args = mock_verify.call_args[0][0]
            assert args.ws == initialized_ws

        # Legacy --repo-root is purged and rejected
        with pytest.raises(SystemExit):
            main(["verify", "--repo-root", str(tmp_path)])


class TestSubcommandDirectInvocationFallback:
    def test_handler_fallback_when_bypassing_main(self, initialized_ws: Workspace):
        """Direct invocation of subcommand handlers without args.ws falls back to Workspace.resolve()."""
        from aegis_cli.status import run_status

        # Create a raw Namespace with no ws attribute
        raw_args = argparse.Namespace(
            workspace=str(initialized_ws.root),
            plumbing=False,
            format="json",
            json=True,
            verbose=False,
            quiet=False,
            plain=False,
        )
        exit_code = run_status(raw_args)
        assert exit_code == 0


class TestLocalHelperDecoupling:
    def test_no_duplicate_resolve_workspace_in_quarantine_and_transfer(self):
        """quarantine.py and transfer.py must not define local duplicate resolve_workspace functions."""
        for filename in ["aegis_cli/quarantine.py", "aegis_cli/transfer.py", "aegis_cli/quarantine.py", "aegis_cli/transfer.py"]:
            p = Path(filename)
            if not p.is_file():
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            local_defs = [
                node.name
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "resolve_workspace"
            ]
            assert not local_defs, f"Found duplicate local resolve_workspace() in {filename}"
