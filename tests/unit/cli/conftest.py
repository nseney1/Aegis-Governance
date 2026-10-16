"""Hermetic defaults for every CLI unit test.

`aegis init` and `aegis uninstall` write the user plane (``~/.aegis/workspaces.json``,
host MCP configs) and call host CLIs (``codex``, ``claude``). The developer's real home
and the agent hosts installed on the machine must never be touched by a test, so every
test here gets an empty HOME (USERPROFILE on Windows) and a host-CLI runner that fails
loudly. A test that exercises registration installs its own fake runner.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_user_plane(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


@pytest.fixture(autouse=True)
def _no_real_host_cli(monkeypatch):
    import aegis_cli.install_hosts as install_hosts

    def refuse(argv):
        raise AssertionError(f"a test tried to run a real host CLI: {argv!r}")

    monkeypatch.setattr(install_hosts, "_run_cli", refuse)
