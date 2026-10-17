"""`aegis check --record` (lane f-a2) and `--ci` (lane f-a3) are separate modes: neither
takes the other's options, and no combination silently drops one of them."""
from __future__ import annotations

import pytest

from aegis_cli import cli
from tests import helpers_humangate as hg
from tests import helpers_verified as hv

needs_git = pytest.mark.skipif(not hg.git_ok(), reason="needs git")


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path / "home"))


@needs_git
@pytest.mark.parametrize(
    "flags, named",
    [
        (["--record", "--ci"], "--ci"),
        (["--record", "--head", "HEAD"], "--head"),
        (["--record", "--format", "github"], "--format github"),
        (["--ci", "--tests"], "--tests"),
    ],
    ids=["rec-ci", "rec-head", "rec-github", "ci-tests"],
)
def test_the_two_modes_refuse_each_others_options(tmp_path, capsys, flags, named):
    repo = hv.make_project(tmp_path)
    rc = cli.main(["check", "--workspace", str(repo.root), "--base", "main", *flags])
    err = capsys.readouterr().err
    assert rc == 2 and named in err
    assert hv.rows_of(repo.root, "check") == [], "a refused call writes no check row"
