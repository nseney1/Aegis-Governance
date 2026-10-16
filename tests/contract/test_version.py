"""One version (ADR 0005 D18, defense #44).

The version is written once, in aegis_core/_version.py. The build reads it from there
(pyproject's dynamic version), and every runtime surface reports it: `aegis --version`,
the MCP initialize serverInfo, and the packages' ``__version__`` (aegis_sdk's is used by
external callers). Nothing reads a VERSION file: it is not shipped in the wheel, and
``./aegis`` runs from a checkout with no install, so neither it nor installed package
metadata can be the source.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from aegis_core import _version

REPO = Path(__file__).resolve().parents[2]
# PEP 440 public versions of the forms Aegis uses: 4.0.0, 4.0.0rc1, 4.0.0.dev0, 4.0.1.post1.
_PEP440 = re.compile(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.post\d+)?(?:\.dev\d+)?")


def test_the_version_is_a_pep440_version():
    assert _PEP440.fullmatch(_version.__version__), _version.__version__


def test_aegis_version_flag_reports_it(capsys):
    from aegis_cli.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"aegis {_version.__version__}"


def test_mcp_initialize_reports_it(monkeypatch):
    import aegis_mcp.server as server

    monkeypatch.setattr(server, "_session_id", None)
    response = server.handle_request({"jsonrpc": "2.0", "id": 0, "method": "initialize"})
    assert response["result"]["serverInfo"] == {"name": "aegis-mcp", "version": _version.__version__}


def test_every_package_version_attribute_reports_it():
    import aegis_cli
    import aegis_core
    import aegis_mcp
    import aegis_sdk

    for package in (aegis_core, aegis_cli, aegis_mcp, aegis_sdk):
        assert package.__version__ == _version.__version__, package.__name__


def test_a_checkout_without_an_install_reports_it(tmp_path):
    """What `./aegis` and an MCP host run: the package from a path entry, in another cwd."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(REPO), env.get("PYTHONPATH", "")) if p)
    cli = subprocess.run(
        [sys.executable, "-m", "aegis_cli", "--version"],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=120,
    )
    assert (cli.returncode, cli.stdout.strip()) == (0, f"aegis {_version.__version__}"), cli.stderr
    init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
    mcp = subprocess.run(
        [sys.executable, "-m", "aegis_mcp"],
        cwd=str(tmp_path), env=env, input=init, capture_output=True, text=True, timeout=120,
    )
    assert mcp.returncode == 0, mcp.stderr
    assert json.loads(mcp.stdout.splitlines()[0])["result"]["serverInfo"]["version"] == _version.__version__


def test_no_version_file_is_left_to_drift():
    assert not (REPO / "VERSION").exists()


def test_the_build_takes_its_version_from_the_module():
    """setuptools resolves pyproject's dynamic version by reading the attribute statically."""
    pyprojecttoml = pytest.importorskip("setuptools.config.pyprojecttoml")
    config = pyprojecttoml.read_configuration(str(REPO / "pyproject.toml"), expand=False)
    assert "version" not in config["project"]
    assert config["project"]["dynamic"] == ["version"]
    assert config["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "aegis_core._version.__version__"}
    expanded = pyprojecttoml.read_configuration(str(REPO / "pyproject.toml"), expand=True)
    assert expanded["project"]["version"] == _version.__version__
