"""Unit tests for the Workspace value object, exceptions, and confinement (Layer 0 Core)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from aegis_core.errors import (
    PathTraversalError,
    SomaError,
    SomaValidationError,
    WorkspaceError,
    WorkspaceNotFoundError,
)
from aegis_core.workspace import (
    Workspace,
    confine_path,
    confine_workspace,
    resolve_workspace,
    resolve_workspace_path,
    validate_cell_names,
)


@pytest.fixture
def soma_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "valid_project"
    (ws / ".soma" / "cells" / "walls").mkdir(parents=True)
    (ws / ".soma" / "evidence").mkdir(parents=True)
    (ws / ".soma" / "metrics").mkdir(parents=True)
    (ws / ".soma" / "cells" / "walls" / "wall-test.md").write_text(
        "---\ntype: wall\nenforcement: gate\n---\nTest rule.\n"
    )
    return ws


class TestWorkspaceExceptions:
    def test_exception_inheritance_and_codes(self):
        assert issubclass(WorkspaceError, SomaValidationError)
        assert issubclass(WorkspaceError, ValueError)
        assert issubclass(WorkspaceError, SomaError)

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

    def test_workspace_resolve_env(self, soma_ws: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SOMA_WORKSPACE", str(soma_ws))
        ws = Workspace.resolve()
        assert isinstance(ws, Workspace)
        assert ws.root == soma_ws.resolve()
        assert str(ws) == str(soma_ws.resolve())
        assert os.fspath(ws) == str(soma_ws.resolve())
        assert Path(ws) == soma_ws.resolve()

    def test_workspace_resolve_strict_env_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SOMA_WORKSPACE", str(tmp_path / "nonexistent"))
        with pytest.raises(WorkspaceNotFoundError, match="no .soma/cells found"):
            Workspace.resolve(strict_env=True)

    def test_workspace_resolve_walkup(self, soma_ws: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SOMA_WORKSPACE", raising=False)
        monkeypatch.delenv("SOMA_ROOT", raising=False)

        sub = soma_ws / "deep" / "nested" / "dir"
        sub.mkdir(parents=True)

        ws = Workspace.resolve(start=sub)
        assert isinstance(ws, Workspace)
        assert ws.root == soma_ws.resolve()

    def test_workspace_confine_factory(self, soma_ws: Path, tmp_path: Path):
        ws = Workspace.confine(soma_ws)
        assert isinstance(ws, Workspace)
        assert ws.root == soma_ws.resolve()

        with pytest.raises(WorkspaceError, match="must not be empty"):
            Workspace.confine("")

        with pytest.raises(WorkspaceNotFoundError, match="does not exist"):
            Workspace.confine(tmp_path / "missing")

        with pytest.raises(WorkspaceError, match="missing .soma/cells"):
            Workspace.confine(tmp_path)

    def test_workspace_properties(self, soma_ws: Path):
        ws = Workspace.resolve(soma_ws)
        assert ws.soma_dir == ws.root / ".soma"
        assert ws.cells_dir == ws.root / ".soma" / "cells"
        assert ws.metrics_dir == ws.root / ".soma" / "metrics"
        assert ws.evidence_dir == ws.root / ".soma" / "evidence"
        assert ws.signals_file == ws.root / ".soma" / "evidence" / "signals.jsonl"
        assert ws / "subdir" == ws.root / "subdir"

    def test_workspace_pathlike_and_immutability(self, soma_ws: Path):
        ws = Workspace.resolve(soma_ws)
        assert isinstance(ws, os.PathLike)

        # Immutability
        with pytest.raises((AttributeError, TypeError)):
            ws.root = Path("/tmp")  # type: ignore[misc]

        # os.path and Path interoperability
        joined = os.path.join(ws, "sub", "file.txt")
        assert joined == str(soma_ws.resolve() / "sub" / "file.txt")

    def test_workspace_confine_path_success(self, soma_ws: Path):
        ws = Workspace.resolve(soma_ws)
        target = soma_ws / "src" / "main.py"
        target.parent.mkdir(parents=True)
        target.write_text("print('hello')")

        abs_p, rel_p = ws.confine_path("src/main.py")
        assert abs_p == str(target.resolve())
        assert rel_p == os.path.join("src", "main.py")

    def test_workspace_confine_path_failures(self, soma_ws: Path):
        ws = Workspace.resolve(soma_ws)

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

    def test_workspace_validate_cell_names(self, soma_ws: Path):
        ws = Workspace.resolve(soma_ws)
        assert ws.validate_cell_names(["wall-test"]) == []
        assert ws.validate_cell_names(["wall-test", "wall-nonexistent"]) == ["wall-nonexistent"]


class TestWorkspaceBackwardCompatibilityFacades:
    def test_standalone_functions_wrap_workspace(self, soma_ws: Path):
        root_str = resolve_workspace(soma_ws)
        assert isinstance(root_str, str)
        assert root_str == str(soma_ws.resolve())

        root_path = resolve_workspace_path(soma_ws)
        assert isinstance(root_path, Path)
        assert root_path == soma_ws.resolve()

        confined = confine_workspace(str(soma_ws))
        assert confined == str(soma_ws.resolve())

        missing = validate_cell_names(["wall-test", "ghost"], soma_ws)
        assert missing == ["ghost"]

        # confine_path backward compatibility accepts str or Workspace
        abs_p, rel_p = confine_path("src", soma_ws)
        assert isinstance(abs_p, str)
        assert isinstance(rel_p, str)

        ws_obj = Workspace.resolve(soma_ws)
        abs_p2, rel_p2 = confine_path("src", ws_obj)
        assert abs_p2 == abs_p
        assert rel_p2 == rel_p
