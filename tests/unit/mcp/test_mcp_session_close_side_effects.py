"""aegis-mcp shutdown has no side effects (ADR 0005 AD-1; host-matrix §3.8 "No reflection on close").

On every stdin EOF, even with zero tool calls, the server used to run the outcome engine:
it executed the project's test target, appended ledger rows and rewrote rule frontmatter.
With N servers on one repo that recorded one change N times.
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import aegis_mcp.server as server
from aegis_core.yaml_engine.serializer import dump_frontmatter

_INIT = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"clientInfo": {"name": "pytest"}}})
_LIST = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=repo, check=True, capture_output=True,
    )


def _tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def server_state(monkeypatch):
    """run_stdio_server sets module globals; restore them after the test."""
    monkeypatch.setattr(server, "_canonical_workspace", None)
    monkeypatch.setattr(server, "_session_id", None)
    monkeypatch.setattr(server, "_workspace_error", None)


@pytest.fixture
def governed_repo(tmp_path: Path, monkeypatch) -> Path:
    """A governed git repo whose last commit touches a ruled file and whose `make test` leaves a marker."""
    repo = tmp_path / "repo"
    rules = repo / ".aegis" / "rules" / "traps"
    rules.mkdir(parents=True)
    fm = {"id": "guard-src", "type": "trap", "target_paths": ["src/*.py"],
          "hypothesis": "h", "prediction": "p"}
    (rules / "guard-src.md").write_text(dump_frontmatter(fm, body="Body\n"), encoding="utf-8")
    (repo / "Makefile").write_text("test:\n\ttouch MAKE_TEST_RAN\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "one")
    (repo / "src" / "app.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "two")

    monkeypatch.setenv("AEGIS_WORKSPACE", str(repo))
    # The removed opt-out defaulted to "1" (reflect); setting it must change nothing.
    monkeypatch.setenv("AEGIS_REFLECT_ON_CLOSE", "1")
    return repo


@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
@pytest.mark.parametrize(
    "stdin_text",
    ["", f"{_INIT}\n{_LIST}\n"],
    ids=["zero-tool-calls", "after-initialize-and-tools-list"],
)
def test_shutdown_runs_no_project_commands_and_writes_nothing(
    governed_repo: Path, stdin_text: str, monkeypatch, server_state, capsys
) -> None:
    aegis_before = _tree(governed_repo / ".aegis")
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_text))

    rc = server.run_stdio_server()

    assert rc == 0
    assert not (governed_repo / "MAKE_TEST_RAN").exists()
    # No ledger rows, no rule rewrite: nothing under .aegis/ changed.
    assert _tree(governed_repo / ".aegis") == aegis_before
    for line in capsys.readouterr().out.splitlines():
        json.loads(line)  # stdout carries only JSON-RPC frames
