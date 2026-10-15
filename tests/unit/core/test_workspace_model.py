"""Unit tests for the Workspace value object, exceptions, and confinement (Layer 0 Core)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from aegis_core.errors import (
    AegisError,
    AegisValidationError,
    PathTraversalError,
    WorkspaceError,
    WorkspaceNotFoundError,
)
from aegis_core.workspace.base import Workspace
from aegis_core.rules import validate_rule_names
from aegis_core.workspace import (
    confine_path,
    resolve_workspace,
)


@pytest.fixture
def aegis_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "valid_project"
    (ws / ".aegis" / "rules" / "invariants").mkdir(parents=True)
    (ws / ".aegis" / "evidence").mkdir(parents=True)
    (ws / ".aegis" / "metrics").mkdir(parents=True)
    (ws / ".aegis" / "rules" / "invariants" / "invariant-test.md").write_text(
        "---\ntype: invariant\nenforcement: gate\n---\nTest rule.\n"
    )
    return ws


class TestWorkspaceExceptions:
    def test_exception_inheritance_and_codes(self):
        assert issubclass(WorkspaceError, AegisValidationError)
        assert issubclass(WorkspaceError, ValueError)
        assert issubclass(WorkspaceError, AegisError)

        assert issubclass(WorkspaceNotFoundError, WorkspaceError)
        assert issubclass(WorkspaceNotFoundError, ValueError)

        assert issubclass(PathTraversalError, WorkspaceError)
        assert issubclass(PathTraversalError, ValueError)

        err_ws = WorkspaceError("workspace error")
        assert err_ws.code == "ERR_WORKSPACE"
        assert str(err_ws) == "workspace error"

        err_not_found = WorkspaceNotFoundError("not found")
        assert err_not_found.code == "ERR_WORKSPACE_NOT_FOUND"

        err_traversal = PathTraversalError("traversal blocked")
        assert err_traversal.code == "ERR_PATH_TRAVERSAL"


class TestWorkspaceModel:

    def test_workspace_resolve_env(self, aegis_ws: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AEGIS_WORKSPACE", str(aegis_ws))
        ws = Workspace.resolve()
        assert isinstance(ws, Workspace)
        assert ws.root == aegis_ws.resolve()
        assert str(ws) == str(aegis_ws.resolve())
        assert os.fspath(ws) == str(aegis_ws.resolve())
        assert Path(ws) == aegis_ws.resolve()

    def test_workspace_resolve_strict_env_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AEGIS_WORKSPACE", str(tmp_path / "nonexistent"))
        with pytest.raises(WorkspaceNotFoundError, match="no .aegis/rules found"):
            Workspace.resolve(strict_env=True)

    def test_workspace_resolve_walkup(self, aegis_ws: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("AEGIS_WORKSPACE", raising=False)
        monkeypatch.delenv("AEGIS_ROOT", raising=False)

        sub = aegis_ws / "deep" / "nested" / "dir"
        sub.mkdir(parents=True)

        ws = Workspace.resolve(start=sub)
        assert isinstance(ws, Workspace)
        assert ws.root == aegis_ws.resolve()

    def test_workspace_confine_factory(self, aegis_ws: Path, tmp_path: Path):
        ws = Workspace.confine(aegis_ws)
        assert isinstance(ws, Workspace)
        assert ws.root == aegis_ws.resolve()

        with pytest.raises(WorkspaceError, match="must not be empty"):
            Workspace.confine("")

        with pytest.raises(WorkspaceNotFoundError, match="does not exist"):
            Workspace.confine(tmp_path / "missing")

        with pytest.raises(WorkspaceError, match="missing .aegis/rules"):
            Workspace.confine(tmp_path)

    def test_workspace_properties(self, aegis_ws: Path):
        ws = Workspace.resolve(aegis_ws)
        assert ws.aegis_dir == ws.root / ".aegis"
        assert ws.rules_dir == ws.root / ".aegis" / "rules"
        assert ws.layout.state_dir == ws.root / ".aegis" / "state"
        assert ws.layout.ledger_file == ws.root / ".aegis" / "state" / "ledger.jsonl"
        assert ws / "subdir" == ws.root / "subdir"

    def test_workspace_pathlike_and_immutability(self, aegis_ws: Path):
        ws = Workspace.resolve(aegis_ws)
        assert isinstance(ws, os.PathLike)

        # Immutability
        with pytest.raises((AttributeError, TypeError)):
            ws.root = Path("/tmp")  # type: ignore[misc]

        # os.path and Path interoperability
        joined = os.path.join(ws, "sub", "file.txt")
        assert joined == str(aegis_ws.resolve() / "sub" / "file.txt")

    def test_workspace_confine_path_success(self, aegis_ws: Path):
        ws = Workspace.resolve(aegis_ws)
        target = aegis_ws / "src" / "main.py"
        target.parent.mkdir(parents=True)
        target.write_text("print('hello')")

        abs_p, rel_p = ws.confine_path("src/main.py")
        assert abs_p == str(target.resolve())
        assert rel_p == os.path.join("src", "main.py")

    def test_workspace_confine_path_failures(self, aegis_ws: Path):
        ws = Workspace.resolve(aegis_ws)

        # Empty
        with pytest.raises(PathTraversalError, match="must not be empty"):
            ws.confine_path("")

        # Null byte
        with pytest.raises(PathTraversalError, match="null bytes"):
            ws.confine_path("path\x00escape")

        # Relative traversal
        with pytest.raises(PathTraversalError, match="path traversal blocked"):
            ws.confine_path("../outside.txt")

        # Root itself
        with pytest.raises(PathTraversalError, match="workspace root as a file"):
            ws.confine_path(".")

        # Extended namespace
        with pytest.raises(PathTraversalError, match="extended device namespace"):
            ws.confine_path("\\\\?\\C:\\Windows")

        # Alternate data streams
        with pytest.raises(PathTraversalError, match="alternate data stream"):
            ws.confine_path("secret.txt:hidden")

        # Windows device names
        with pytest.raises(PathTraversalError, match="reserved Windows device name"):
            ws.confine_path("CON.txt")

    def test_validate_rule_names_takes_a_workspace(self, aegis_ws: Path):
        ws = Workspace.resolve(aegis_ws)
        assert validate_rule_names(["invariant-test"], ws) == []
        assert validate_rule_names(["invariant-test", "invariant-nonexistent"], ws) == ["invariant-nonexistent"]


class TestWorkspaceBackwardCompatibilityFacades:
    def test_standalone_functions_wrap_workspace(self, aegis_ws: Path):
        root_str = resolve_workspace(aegis_ws)
        assert isinstance(root_str, str)
        assert root_str == str(aegis_ws.resolve())

        root_path = Workspace.resolve(aegis_ws).root
        assert isinstance(root_path, Path)
        assert root_path == aegis_ws.resolve()

        confined = str(Workspace.confine(str(aegis_ws)).root)
        assert confined == str(aegis_ws.resolve())

        missing = validate_rule_names(["invariant-test", "ghost"], aegis_ws)
        assert missing == ["ghost"]

        # confine_path backward compatibility accepts str or Workspace
        abs_p, rel_p = confine_path("src", aegis_ws)
        assert isinstance(abs_p, str)
        assert isinstance(rel_p, str)

        ws_obj = Workspace.resolve(aegis_ws)
        abs_p2, rel_p2 = confine_path("src", ws_obj)
        assert abs_p2 == abs_p
        assert rel_p2 == rel_p
