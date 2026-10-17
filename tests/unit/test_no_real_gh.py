"""The suite's own guard: no test can reach a real `gh`, wherever the machine installs it.

A runner image puts gh beside git (/usr/bin), so a test that builds PATH from git's
directory to model "no gh" would otherwise run the real gh: on GitHub's runners a gh new
enough to go on to verify attestations over the network.
"""
from __future__ import annotations

import os
import shutil
import stat

import pytest

from aegis_core import pathlookup


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_a_path_built_from_gits_directory_finds_no_real_gh(monkeypatch):
    path = os.path.dirname(shutil.which("git"))
    monkeypatch.setenv("PATH", path)
    assert pathlookup.which("gh") is None
    assert pathlookup.which("gh", path=path) is None


@pytest.mark.skipif(os.name == "nt", reason="a POSIX shell stub")
def test_a_fake_gh_a_test_places_is_still_found(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gh"
    stub.write_bytes(b"#!/bin/sh\necho 'gh version 2.99.0'\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    found = pathlookup.which("gh", path=str(bin_dir))
    assert found is not None and os.path.realpath(found) == os.path.realpath(str(stub))
