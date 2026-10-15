"""Behavioral tests for the aegis_core.workspace helpers and Workspace.is_aegis_repo."""
from __future__ import annotations



class TestWorkspacePackageArchitecture:
    """Workspace fingerprinting and the resolve/confine helpers."""

    def test_is_aegis_repo_compound_fingerprint(self, tmp_path):
        from aegis_core.workspace.base import Workspace

        # Dummy foreign repository
        foreign = tmp_path / "foreign"
        foreign.mkdir()
        (foreign / ".aegis" / "rules").mkdir(parents=True)
        (foreign / "pyproject.toml").write_text('[project]\nname = "my-awesome-tool"\n', encoding="utf-8")
        ws_foreign = Workspace.resolve(foreign)
        assert not ws_foreign.is_aegis_repo

        # Fake repo with only pyproject.toml name but missing aegis_core/aegis_cli
        fake = tmp_path / "fake"
        fake.mkdir()
        (fake / ".aegis" / "rules").mkdir(parents=True)
        (fake / "pyproject.toml").write_text('[project]\nname = "aegis-guardrails"\n', encoding="utf-8")
        ws_fake = Workspace.resolve(fake)
        assert not ws_fake.is_aegis_repo

        # Valid Aegis repository
        aegis_mock = tmp_path / "aegis_mock"
        aegis_mock.mkdir()
        (aegis_mock / ".aegis" / "rules").mkdir(parents=True)
        (aegis_mock / "pyproject.toml").write_text('[project]\nname = "aegis-guardrails"\n', encoding="utf-8")
        (aegis_mock / "aegis_core").mkdir()
        (aegis_mock / "aegis_cli").mkdir()
        ws_aegis = Workspace.resolve(aegis_mock)
        assert ws_aegis.is_aegis_repo

    def test_backward_compatibility_facades_work_unchanged(self, tmp_path):
        from aegis_core.workspace import resolve_workspace, confine_workspace, confine_path

        repo = tmp_path / "project"
        repo.mkdir()
        (repo / ".aegis" / "rules").mkdir(parents=True)
        (repo / "file.py").write_text("print('test')", encoding="utf-8")

        # Facades
        resolved_str = resolve_workspace(repo)
        assert resolved_str == str(repo.resolve())

        confined_str = confine_workspace(repo)
        assert confined_str == str(repo.resolve())

        abs_p, rel_p = confine_path("file.py", repo)
        assert abs_p == str((repo / "file.py").resolve())
        assert rel_p == "file.py"
