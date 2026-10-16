"""Behavioral tests for the aegis_core.workspace helpers."""
from __future__ import annotations



class TestWorkspacePackageArchitecture:
    """The resolve/confine helpers."""

    def test_resolve_and_confine_helpers(self, tmp_path):
        from aegis_core.workspace import resolve_workspace, confine_path
        from aegis_core.workspace.base import Workspace

        repo = tmp_path / "project"
        repo.mkdir()
        (repo / ".aegis" / "rules").mkdir(parents=True)
        (repo / "file.py").write_text("print('test')", encoding="utf-8")

        resolved_str = resolve_workspace(repo)
        assert resolved_str == str(repo.resolve())

        confined_str = str(Workspace.confine(repo).root)
        assert confined_str == str(repo.resolve())

        abs_p, rel_p = confine_path("file.py", repo)
        assert abs_p == str((repo / "file.py").resolve())
        assert rel_p == "file.py"
