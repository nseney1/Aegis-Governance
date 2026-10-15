"""aegis-mcp stdio contract: ungoverned startup.

- With no governed workspace (no AEGIS_WORKSPACE and a cwd without .aegis/, or $HOME),
  the server used to either exit 1 or mkdir ~/.aegis/rules and govern $HOME with zero
  rules. It must stay up, create nothing, and answer every tools/call with an error.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

import aegis_mcp.server as server
from aegis_core.yaml import dump_frontmatter

NOT_GOVERNED = 'not an Aegis workspace: run "aegis init" in your repository'


def _frame(req_id, method, params=None) -> str:
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)


_INIT = _frame(1, "initialize", {"clientInfo": {"name": "pytest"}})
_LIST = _frame(2, "tools/list")
_CALLS = {
    3: _frame(3, "tools/call", {"name": "aegis_list_rules", "arguments": {}}),
    4: _frame(4, "tools/call", {"name": "aegis_scan", "arguments": {"files": ["a.py"]}}),
    5: _frame(5, "tools/call", {"name": "aegis_report_outcome",
                                "arguments": {"rule_id": "x", "tests_passed": True}}),
}


def _tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


@pytest.fixture
def server_state(monkeypatch):
    """run_stdio_server sets module globals; restore them after the test."""
    monkeypatch.setattr(server, "_canonical_workspace", None)
    monkeypatch.setattr(server, "_execution_enabled", False)
    monkeypatch.setattr(server, "_workspace_error", None, raising=False)


def _serve(monkeypatch, capsys, lines: list[str]) -> tuple[int, dict]:
    monkeypatch.setattr("sys.stdin", io.StringIO("".join(f"{line}\n" for line in lines)))
    try:
        rc = server.run_stdio_server()
    except Exception as exc:  # the defect under test: a frame that kills the server
        pytest.fail(f"server died instead of answering: {exc!r}")
    frames = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    return rc, frames


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AEGIS_WORKSPACE", raising=False)
    return home


def _cwd_is_home(home: Path, tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(home)
    return home


def _cwd_is_home_with_v33_user_rules(home: Path, tmp_path: Path, monkeypatch) -> Path:
    # v3.3 auto-created ~/.aegis/rules; its presence must not make $HOME a workspace.
    (home / ".aegis" / "rules").mkdir(parents=True)
    monkeypatch.chdir(home)
    return home


def _cwd_without_aegis(home: Path, tmp_path: Path, monkeypatch) -> Path:
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    return plain


def _pin_without_aegis(home: Path, tmp_path: Path, monkeypatch) -> Path:
    plain = tmp_path / "pinned"
    plain.mkdir()
    monkeypatch.setenv("AEGIS_WORKSPACE", str(plain))
    monkeypatch.chdir(home)
    return plain


def _pin_missing_dir(home: Path, tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("AEGIS_WORKSPACE", str(tmp_path / "does-not-exist"))
    monkeypatch.chdir(home)
    return home


@pytest.mark.parametrize(
    "setup",
    [_cwd_is_home, _cwd_is_home_with_v33_user_rules, _cwd_without_aegis,
     _pin_without_aegis, _pin_missing_dir],
    ids=["cwd-is-home", "cwd-is-home-with-v33-user-rules", "cwd-without-aegis",
         "pin-without-aegis", "pin-missing-dir"],
)
def test_ungoverned_server_stays_up_creates_nothing_and_errors_every_tool_call(
    tmp_path: Path, home: Path, setup, monkeypatch, server_state, capsys
) -> None:
    watched = setup(home, tmp_path, monkeypatch)
    home_before, watched_before = _tree(home), _tree(watched)

    rc, frames = _serve(monkeypatch, capsys, [_INIT, _LIST, *_CALLS.values()])

    assert rc == 0
    by_id = {f.get("id"): f for f in frames}
    assert by_id[1]["result"]["serverInfo"]["name"] == "aegis-mcp"
    assert by_id[2]["result"]["tools"], "tools/list must answer normally"
    for call_id in _CALLS:
        assert "error" not in by_id[call_id], by_id[call_id]
        result = by_id[call_id]["result"]
        assert result["isError"] is True
        assert result["content"][0]["text"] == NOT_GOVERNED
    assert _tree(home) == home_before
    assert _tree(watched) == watched_before


def test_governed_workspace_still_dispatches_tools(
    tmp_path: Path, home: Path, monkeypatch, server_state, capsys
) -> None:
    ws = tmp_path / "repo"
    rules = ws / ".aegis" / "rules" / "traps"
    rules.mkdir(parents=True)
    fm = {"id": "guard-src", "type": "trap", "target_paths": ["src/*.py"],
          "hypothesis": "h", "prediction": "p"}
    (rules / "guard-src.md").write_text(dump_frontmatter(fm, body="Body\n"), encoding="utf-8")
    monkeypatch.setenv("AEGIS_WORKSPACE", str(ws))

    rc, frames = _serve(monkeypatch, capsys, [_INIT, _CALLS[3]])

    assert rc == 0
    result = {f.get("id"): f for f in frames}[3]["result"]
    assert result["isError"] is False
    assert "guard-src" in result["content"][0]["text"]

