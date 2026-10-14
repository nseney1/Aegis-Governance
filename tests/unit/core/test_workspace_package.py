"""Behavioral tests verifying the modular soma_core/workspace/ package architecture.

Validates:
1. aegis_core.workspace is a proper package with __init__.py.
2. Direct submodule imports: base, git, discovery, confinement, scaffold, hooks.
3. Canonical symbols re-exported at package root.
4. Workspace.is_soma_repo compound property.
5. Zero circular imports across submodules.
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest


class TestWorkspacePackageArchitecture:
    """Verifies that soma_core/workspace is a clean modular package."""

    def test_workspace_is_a_package(self):
        import aegis_core.workspace
        assert aegis_core.workspace.__file__ is not None
        assert aegis_core.workspace.__file__.endswith("__init__.py")

    def test_direct_submodule_imports(self):
        import aegis_core.workspace.base
        import aegis_core.workspace.git
        import aegis_core.workspace.discovery
        import aegis_core.workspace.confinement
        import aegis_core.workspace.scaffold
        import aegis_core.workspace.hooks

        assert hasattr(aegis_core.workspace.base, "Workspace")
        assert hasattr(aegis_core.workspace.git, "GitWorkspace")
        assert hasattr(aegis_core.workspace.discovery, "is_soma_repo")
        assert hasattr(aegis_core.workspace.confinement, "confine_path_internal")
        assert hasattr(aegis_core.workspace.scaffold, "scaffold_workspace")
        assert hasattr(aegis_core.workspace.hooks, "resolve_git_hooks_dir")

    def test_package_re_exports_canonical_symbols(self):
        from aegis_core.workspace import (
            GitWorkspace,
            Workspace,
            as_workspace,
            confine_path,
            confine_workspace,
            resolve_git_hooks_dir,
            resolve_workspace,
            resolve_workspace_path,
            validate_cell_names,
        )

        assert issubclass(GitWorkspace, Workspace)
        assert callable(as_workspace)
        assert callable(confine_path)
        assert callable(confine_workspace)
        assert callable(resolve_git_hooks_dir)
        assert callable(resolve_workspace)

    def test_is_soma_repo_compound_fingerprint(self, tmp_path):
        from aegis_core.workspace import Workspace

        # Dummy foreign repository
        foreign = tmp_path / "foreign"
        foreign.mkdir()
        (foreign / ".soma" / "cells").mkdir(parents=True)
        (foreign / "pyproject.toml").write_text('[project]\nname = "my-awesome-tool"\n', encoding="utf-8")
        ws_foreign = Workspace.resolve(foreign)
        assert not ws_foreign.is_soma_repo

        # Fake repo with only pyproject.toml name but missing soma_core/soma_cli
        fake = tmp_path / "fake"
        fake.mkdir()
        (fake / ".soma" / "cells").mkdir(parents=True)
        (fake / "pyproject.toml").write_text('[project]\nname = "soma-governance"\n', encoding="utf-8")
        ws_fake = Workspace.resolve(fake)
        assert not ws_fake.is_soma_repo

        # Valid Soma repository
        soma_mock = tmp_path / "soma_mock"
        soma_mock.mkdir()
        (soma_mock / ".soma" / "cells").mkdir(parents=True)
        (soma_mock / "pyproject.toml").write_text('[project]\nname = "soma-governance"\n', encoding="utf-8")
        (soma_mock / "soma_core").mkdir()
        (soma_mock / "soma_cli").mkdir()
        ws_soma = Workspace.resolve(soma_mock)
        assert ws_soma.is_soma_repo

    def test_backward_compatibility_facades_work_unchanged(self, tmp_path):
        from aegis_core.workspace import (
            Workspace,
            resolve_workspace,
            confine_workspace,
            confine_path,
        )

        repo = tmp_path / "project"
        repo.mkdir()
        (repo / ".soma" / "cells").mkdir(parents=True)
        (repo / "file.py").write_text("print('test')", encoding="utf-8")

        # Facades
        resolved_str = resolve_workspace(repo)
        assert resolved_str == str(repo.resolve())

        confined_str = confine_workspace(repo)
        assert confined_str == str(repo.resolve())

        abs_p, rel_p = confine_path("file.py", repo)
        assert abs_p == str((repo / "file.py").resolve())
        assert rel_p == "file.py"
