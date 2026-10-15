"""CLI-level tests for `aegis rule create` workspace resolution and body input.

Dogfood finding (ADR 0005 §1.5): `aegis rule create --workspace <dir without
.aegis>` walked up and wrote into `$HOME/.aegis/rules`. Every test runs `main`
with argv against an isolated HOME that holds a user-plane rule and a sentinel,
and proves HOME is byte-identical afterwards.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
from pathlib import Path

import pytest

from aegis_cli.cli import main
from aegis_core.yaml import _get_body, parse_frontmatter

MAX_BODY = 64 * 1024


def _tree(root: Path) -> list[tuple[str, str]]:
    out = []
    for dirpath, dirs, files in os.walk(root):
        for d in dirs:
            out.append(((Path(dirpath) / d).relative_to(root).as_posix() + "/", ""))
        for name in files:
            full = Path(dirpath) / name
            out.append((full.relative_to(root).as_posix(), hashlib.sha256(full.read_bytes()).hexdigest()))
    return sorted(out)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    (home / ".aegis" / "rules" / "traps").mkdir(parents=True)
    (home / ".aegis" / "rules" / "traps" / "user-plane.md").write_text(
        "---\nid: user-plane\ntype: trap\n---\nUser rule.\n", encoding="utf-8"
    )
    (home / "SENTINEL").write_text("do not touch\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("AEGIS_WORKSPACE", raising=False)
    monkeypatch.delenv("AEGIS_ROOT", raising=False)
    return home


def _git_repo(path: Path, initialized: bool) -> Path:
    (path / ".git").mkdir(parents=True)
    if initialized:
        (path / ".aegis" / "rules").mkdir(parents=True)
    return path


def _not_a_workspace(directory: Path) -> str:
    return f"not an Aegis workspace (no .aegis/ in {directory}); run aegis init"


# ── Workspace resolution ───────────────────────────────────────────────

def test_explicit_workspace_without_aegis_fails_and_writes_nothing(home, monkeypatch, capsys) -> None:
    repo = _git_repo(home / "code" / "repo", initialized=False)
    monkeypatch.chdir(repo)
    before = _tree(home)

    rc = main(["rule", "create", "--workspace", str(repo), "--hypothesis", "Never land here"])

    err = capsys.readouterr().err
    assert rc == 1
    assert _not_a_workspace(repo) in err
    assert _tree(home) == before
    assert not (repo / ".aegis").exists()


def test_implicit_workspace_never_walks_up_into_home(home, monkeypatch, capsys) -> None:
    repo = _git_repo(home / "code" / "repo", initialized=False)
    monkeypatch.chdir(repo)
    before = _tree(home)

    rc = main(["rule", "create", "--hypothesis", "Never land here"])

    assert rc == 1
    assert _not_a_workspace(repo) in capsys.readouterr().err
    assert _tree(home) == before


def test_explicit_home_workspace_is_rejected(home, monkeypatch, capsys) -> None:
    monkeypatch.chdir(home)
    before = _tree(home)

    rc = main(["rule", "create", "--workspace", str(home), "--hypothesis", "Never land here"])

    assert rc == 1
    assert (
        f"Error: not an Aegis workspace ({home} is the home directory; ~/.aegis is the user rule layer); "
        "run aegis init in a project"
    ) in capsys.readouterr().err
    assert _tree(home) == before


def test_resolution_never_crosses_the_git_toplevel(home, monkeypatch, capsys) -> None:
    outer = home / "code"
    (outer / ".aegis" / "rules").mkdir(parents=True)
    inner = _git_repo(outer / "inner", initialized=False)
    monkeypatch.chdir(inner)
    before_home, before_outer = _tree(home), _tree(outer / ".aegis")

    rc = main(["rule", "create", "--hypothesis", "Stay inside the repo"])

    assert rc == 1
    assert _not_a_workspace(inner) in capsys.readouterr().err
    assert _tree(outer / ".aegis") == before_outer
    assert _tree(home) == before_home


def test_rule_list_does_not_resolve_to_home(home, monkeypatch, capsys) -> None:
    repo = _git_repo(home / "code" / "repo", initialized=False)
    monkeypatch.chdir(repo)

    rc = main(["rule", "list"])

    captured = capsys.readouterr()
    assert rc == 1
    assert _not_a_workspace(repo) in captured.err
    assert "user-plane" not in captured.out


def test_create_from_subdirectory_of_initialized_repo(home, monkeypatch, capsys) -> None:
    repo = _git_repo(home / "code" / "repo", initialized=True)
    (repo / "src").mkdir()
    monkeypatch.chdir(repo / "src")
    before = _tree(home / ".aegis")

    rc = main(["rule", "create", "--hypothesis", "Inside the repo", "--id", "inside"])

    assert rc == 0, capsys.readouterr().err
    assert (repo / ".aegis" / "rules" / "traps" / "inside.md").is_file()
    assert _tree(home / ".aegis") == before


def test_explicit_initialized_workspace_creates_rule(home, tmp_path, monkeypatch, capsys) -> None:
    repo = _git_repo(tmp_path / "elsewhere" / "repo", initialized=True)
    monkeypatch.chdir(tmp_path)
    before = _tree(home)

    rc = main(["rule", "create", "--workspace", str(repo), "--hypothesis", "Explicit", "--id", "explicit", "--json"])

    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["status"] == "created"
    assert Path(payload["path"]).resolve() == (repo / ".aegis" / "rules" / "traps" / "explicit.md").resolve()
    assert _tree(home) == before


def test_json_mode_reports_workspace_error_on_stdout(home, monkeypatch, capsys) -> None:
    repo = _git_repo(home / "code" / "repo", initialized=False)
    monkeypatch.chdir(repo)

    rc = main(["rule", "create", "--workspace", str(repo), "--hypothesis", "x", "--json"])

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"status": "error", "error": _not_a_workspace(repo)}


# ── --body-file ────────────────────────────────────────────────────────

@pytest.fixture
def repo(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = _git_repo(home / "code" / "repo", initialized=True)
    monkeypatch.chdir(repo)
    return repo


def _created(repo: Path, rule_id: str) -> Path:
    return repo / ".aegis" / "rules" / "traps" / f"{rule_id}.md"


def test_body_file_supplies_rule_body(repo, tmp_path, capsys) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text("## Detail\n\nUse argv lists, never shell strings.\n", encoding="utf-8")

    rc = main(["rule", "create", "--hypothesis", "No shell strings", "--id", "argv", "--body-file", str(body_file)])

    assert rc == 0, capsys.readouterr().err
    text = _created(repo, "argv").read_text(encoding="utf-8")
    assert (parse_frontmatter(text) or {})["hypothesis"] == "No shell strings"
    assert _get_body(text).strip() == "## Detail\n\nUse argv lists, never shell strings."


def test_body_file_dash_reads_stdin(repo, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO("Body from stdin ✓\n".encode("utf-8")), encoding="utf-8"))

    rc = main(["rule", "create", "--hypothesis", "Stdin body", "--id", "stdin-body", "--body-file", "-"])

    assert rc == 0, capsys.readouterr().err
    assert _get_body(_created(repo, "stdin-body").read_text(encoding="utf-8")).strip() == "Body from stdin ✓"


@pytest.mark.parametrize("content", [b"", b"  \n\n\t"], ids=["empty", "whitespace"])
def test_empty_body_file_is_rejected(repo, tmp_path, capsys, content: bytes) -> None:
    body_file = tmp_path / "empty.md"
    body_file.write_bytes(content)

    rc = main(["rule", "create", "--hypothesis", "Empty", "--id", "empty", "--body-file", str(body_file)])

    assert rc == 1
    assert f"Error: --body-file {body_file}: rule body is empty" in capsys.readouterr().err
    assert not _created(repo, "empty").exists()


def test_body_file_over_64_kib_is_rejected(repo, tmp_path, capsys) -> None:
    body_file = tmp_path / "huge.md"
    body_file.write_bytes(b"x" * (MAX_BODY + 1))

    rc = main(["rule", "create", "--hypothesis", "Huge", "--id", "huge", "--body-file", str(body_file)])

    assert rc == 1
    assert f"Error: --body-file {body_file}: rule body exceeds 64 KiB (65536 bytes)" in capsys.readouterr().err
    assert not _created(repo, "huge").exists()


def test_body_file_of_exactly_64_kib_is_accepted(repo, tmp_path, capsys) -> None:
    body_file = tmp_path / "max.md"
    body_file.write_bytes(b"y" * MAX_BODY)

    rc = main(["rule", "create", "--hypothesis", "Max", "--id", "max", "--body-file", str(body_file)])

    assert rc == 0, capsys.readouterr().err
    assert _created(repo, "max").is_file()


def test_stdin_body_over_64_kib_is_rejected(repo, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"z" * (MAX_BODY + 1)), encoding="utf-8"))

    rc = main(["rule", "create", "--hypothesis", "Huge stdin", "--id", "huge-stdin", "--body-file", "-"])

    assert rc == 1
    assert "Error: --body-file <stdin>: rule body exceeds 64 KiB (65536 bytes)" in capsys.readouterr().err
    assert not _created(repo, "huge-stdin").exists()


def test_missing_body_file_is_rejected(repo, tmp_path, capsys) -> None:
    missing = tmp_path / "nope.md"

    rc = main(["rule", "create", "--hypothesis", "Missing", "--id", "missing", "--body-file", str(missing)])

    assert rc == 1
    assert f"Error: --body-file {missing}: cannot read file (No such file or directory)" in capsys.readouterr().err
    assert not _created(repo, "missing").exists()


def test_non_utf8_body_file_is_rejected(repo, tmp_path, capsys) -> None:
    body_file = tmp_path / "latin1.md"
    body_file.write_bytes("caf\xe9\n".encode("latin-1"))

    rc = main(["rule", "create", "--hypothesis", "Latin1", "--id", "latin1", "--body-file", str(body_file)])

    assert rc == 1
    assert f"Error: --body-file {body_file}: rule body is not valid UTF-8" in capsys.readouterr().err
    assert not _created(repo, "latin1").exists()


# ── Ghost flag ─────────────────────────────────────────────────────────

def test_from_description_ghost_flag_is_removed(repo, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["rule", "create", "--from-description", "make me a rule"])

    assert exc.value.code == 2
    assert "unrecognized arguments: --from-description" in capsys.readouterr().err
    assert list((repo / ".aegis" / "rules").rglob("*.md")) == []
