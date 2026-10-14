import os
import sys
import pytest
from conftest import REPO_ROOT, run

def _env(tmp_path, **extra):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"HOME": str(home), "USERPROFILE": str(home), "SOMA_PYTHON": sys.executable,
           "SOMA_PYTHON_RESOLVED": "", "PYTHONPATH": REPO_ROOT}
    env.update(extra)
    return env

def test_cell_create_in_process(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".aegis" / "rules").mkdir(parents=True)
    proc = run([sys.executable, "-c", "import sys; from aegis_core.lifecycle import cli_cell_create; sys.exit(cli_cell_create(sys.argv[1:]))",
                "--type", "trap", "--hypothesis", "linked", "--id", "trap-linked"],
               cwd=str(proj), env=_env(tmp_path))
    assert "No such file" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert list((proj / ".aegis" / "rules").rglob("*trap-linked*"))
