"""aegis_core.team: ``.aegis/team.json`` and lane names (v4.1 spec §1).

``parse_team`` is strict: invalid UTF-8 or JSON, a non-object, more than
``config.MAX_CONFIG_BYTES``, unknown keys, ``v`` other than 1, non-list or empty-string
globs and lane names outside the grammar are refused with ``team.json: <reason>``, and
no repository-chosen text (a key, a glob) is ever echoed. ``load_team`` reads the
working tree with the config file checks; ``load_team_at`` reads a commit's blob and
refuses a symlink tree entry. A missing file is ``{"v": 1}``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from aegis_core import config, gitsafe, team
from aegis_core.config import ConfigError
from tests.conftest import symlink_or_skip

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

EXAMPLE = b'{"v":1,"shared":["CHANGELOG.md"],"lanes":{"docs":["docs/**","README.md"]}}'
SECRET = "SECRETKEYTEXT"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=T", *args],
        cwd=str(repo), check=True, capture_output=True, text=True,
    ).stdout


def _refused(data: bytes) -> str:
    with pytest.raises(team.TeamFileError) as info:
        team.parse_team(data)
    message = str(info.value)
    assert message.startswith("team.json: ")
    assert SECRET not in message
    return message


# ── parse_team ───────────────────────────────────────────────────────────────

def test_the_plan_example_parses():
    policy = team.parse_team(EXAMPLE)
    assert policy.shared == ("CHANGELOG.md",)
    assert dict(policy.lanes) == {"docs": ("docs/**", "README.md")}


def test_only_v_is_required_and_lanes_stay_absent_when_not_given():
    policy = team.parse_team(b'{"v":1}')
    assert policy == team.TeamPolicy()
    assert policy.shared == () and policy.lanes is None


def test_an_empty_lanes_object_and_an_empty_glob_list_are_kept():
    policy = team.parse_team(b'{"v":1,"shared":[],"lanes":{"docs":[]}}')
    assert policy.shared == () and dict(policy.lanes) == {"docs": ()}


def test_globs_are_kept_in_workspace_relative_posix_spelling():
    policy = team.parse_team(b'{"v":1,"shared":["./CHANGELOG.md"],"lanes":{"docs":["docs\\\\**"]}}')
    assert policy.shared == ("CHANGELOG.md",)
    assert dict(policy.lanes) == {"docs": ("docs/**",)}


def test_a_utf8_bom_is_accepted_as_in_config_json():
    assert team.parse_team(b"\xef\xbb\xbf" + EXAMPLE).shared == ("CHANGELOG.md",)


def test_the_parsed_lanes_cannot_be_changed_by_a_caller():
    policy = team.parse_team(EXAMPLE)
    with pytest.raises(TypeError):
        policy.lanes["api"] = ("src/**",)  # type: ignore[index]


@pytest.mark.parametrize("data, reason", [
    (b"\xff\xfe{}", "not valid UTF-8"),
    (b"{\"v\":1,", "not valid JSON"),
    (b"[1]", "must hold a JSON object"),
    (b'"v"', "must hold a JSON object"),
    (b'{"v":1,"shared":[NaN]}', "not valid JSON"),
    (b'{"v":2}', "v must be 1"),
    (b'{"v":"1"}', "v must be 1"),
    (b'{"v":true}', "v must be 1"),
    (b'{"v":1.0}', "v must be 1"),
    (b'{}', "v must be 1"),
    (b'{"v":1,"shared":"CHANGELOG.md"}', "shared must be a list of globs"),
    (b'{"v":1,"shared":[""]}', "shared glob 1 must be a non-empty glob"),
    (b'{"v":1,"shared":["a",1]}', "shared glob 2 must be a non-empty glob"),
    (b'{"v":1,"shared":["/"]}', "shared glob 1 must be a non-empty glob"),
    (b'{"v":1,"lanes":["docs"]}', "lanes must be an object"),
    (b'{"v":1,"lanes":{"docs":"docs/**"}}', "lanes entry 1 must be a list of globs"),
    (b'{"v":1,"lanes":{"docs":["docs/**",""]}}', "lanes entry 1 glob 2 must be a non-empty glob"),
    (b'{"v":1,"lanes":{"a":[],"b":[null]}}', "lanes entry 2 glob 1 must be a non-empty glob"),
])
def test_invalid_content_is_refused_with_its_reason(data: bytes, reason: str):
    assert _refused(data) == f"team.json: {reason}"


def test_more_than_the_config_cap_is_refused():
    pad = b" " * (config.MAX_CONFIG_BYTES - len(EXAMPLE) + 1)
    assert _refused(EXAMPLE + pad) == f"team.json: larger than {config.MAX_CONFIG_BYTES // 1024} KiB"
    assert team.parse_team(EXAMPLE + pad[:-1]).shared == ("CHANGELOG.md",)  # exactly at the cap


def test_unknown_keys_are_counted_never_echoed():
    data = json.dumps({"v": 1, SECRET: 1, SECRET + "2": [], "roles": []}).encode()
    assert _refused(data) == "team.json: 3 unknown key(s)"


def test_a_duplicated_key_is_refused_without_echoing_it():
    assert _refused(b'{"v":1,"shared":[],"shared":["x"]}') == "team.json: duplicate key"
    data = ('{"v":1,"lanes":{"%s":[],"%s":[]}}' % ("docs", "docs")).encode()
    assert _refused(data) == "team.json: duplicate key"


@pytest.mark.parametrize("name", [
    "Docs", "-docs", ".docs", "_docs", "a/b", "a:b", "a=b", "a,b", "a b", "", "a" * 64,
    "a..b", "docs.lock", "docs.", SECRET,
])
def test_a_lane_name_outside_the_grammar_is_refused_without_echoing_it(name: str):
    data = json.dumps({"v": 1, "lanes": {"ok": [], name: ["x/**"]}}).encode()
    assert _refused(data) == "team.json: lanes entry 2 has a name outside [a-z0-9][a-z0-9._-]{0,62}"


# ── Lane names ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["docs", "a", "0", "d1-team", "v4.1_x", "a" * 63, "a.b-c_d"])
def test_valid_lane_names(name: str):
    assert team.valid_lane(name) is True
    assert team.lane_ref(name) == f"refs/aegis/lanes/{name}"


@pytest.mark.parametrize("name", [
    "", "Docs", "-a", ".a", "_a", "a/b", "a:b", "a=b", "a,b", "a b", "a" * 64, "a..b", "a.lock",
    "a.", "é", "a\n", None, 7,
])
def test_invalid_lane_names(name):
    assert team.valid_lane(name) is False
    with pytest.raises(team.TeamUsageError, match=r"\Ainvalid lane name: "):
        team.lane_ref(name)


# ── load_team (working tree) ─────────────────────────────────────────────────

def test_load_team_without_a_file_is_the_default(tmp_path: Path):
    (tmp_path / ".aegis").mkdir()
    assert team.load_team(tmp_path) == team.TeamPolicy()
    assert team.load_team(tmp_path / "no-aegis-here") == team.TeamPolicy()


def test_load_team_parses_the_working_tree_file(tmp_path: Path):
    (tmp_path / ".aegis").mkdir()
    (tmp_path / ".aegis" / "team.json").write_bytes(EXAMPLE)
    assert team.load_team(tmp_path).shared == ("CHANGELOG.md",)


def test_load_team_refuses_invalid_content_with_the_parse_reason(tmp_path: Path):
    (tmp_path / ".aegis").mkdir()
    (tmp_path / ".aegis" / "team.json").write_bytes(b'{"v":3}')
    with pytest.raises(team.TeamFileError, match=r"\Ateam\.json: v must be 1\Z"):
        team.load_team(tmp_path)


def test_load_team_refuses_a_symlink(tmp_path: Path):
    (tmp_path / ".aegis").mkdir()
    (tmp_path / "elsewhere.json").write_bytes(EXAMPLE)
    symlink_or_skip(tmp_path / "elsewhere.json", tmp_path / ".aegis" / "team.json")
    with pytest.raises(team.TeamFileError, match=r"\Ateam\.json: is a symlink\Z"):
        team.load_team(tmp_path)


def test_load_team_refuses_a_file_reached_through_a_linked_aegis_dir_outside(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "team.json").write_bytes(EXAMPLE)
    ws = tmp_path / "ws"
    ws.mkdir()
    symlink_or_skip(outside, ws / ".aegis", target_is_directory=True)
    with pytest.raises(team.TeamFileError, match=r"\Ateam\.json: resolves outside the workspace\Z"):
        team.load_team(ws)


def test_load_team_refuses_a_directory(tmp_path: Path):
    (tmp_path / ".aegis" / "team.json").mkdir(parents=True)
    with pytest.raises(team.TeamFileError, match=r"\Ateam\.json: (?:not a regular file|cannot be read)\Z"):
        team.load_team(tmp_path)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs FIFOs")
def test_load_team_refuses_a_fifo_without_blocking(tmp_path: Path):
    (tmp_path / ".aegis").mkdir()
    os.mkfifo(str(tmp_path / ".aegis" / "team.json"))
    with pytest.raises(team.TeamFileError, match=r"\Ateam\.json: not a regular file\Z"):
        team.load_team(tmp_path)


def test_load_team_refuses_an_oversized_file(tmp_path: Path):
    (tmp_path / ".aegis").mkdir()
    (tmp_path / ".aegis" / "team.json").write_bytes(EXAMPLE + b" " * config.MAX_CONFIG_BYTES)
    with pytest.raises(team.TeamFileError, match=r"\Ateam\.json: larger than 64 KiB\Z"):
        team.load_team(tmp_path)


def test_team_file_errors_are_config_errors():
    assert issubclass(team.TeamFileError, ConfigError)


# ── load_team_at (a commit's blob) ───────────────────────────────────────────

@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / ".aegis").mkdir()
    (root / ".aegis" / "team.json").write_bytes(EXAMPLE)
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


@needs_git
def test_load_team_at_reads_the_commit_not_the_working_tree(repo: Path):
    (repo / ".aegis" / "team.json").write_bytes(b'{"v":1,"shared":["edited.md"]}')
    assert team.load_team_at(repo, "main").shared == ("CHANGELOG.md",)
    assert team.load_team(repo).shared == ("edited.md",)


@needs_git
def test_load_team_at_reads_the_named_commit(repo: Path):
    first = _git(repo, "rev-parse", "HEAD").strip()
    (repo / ".aegis" / "team.json").write_bytes(b'{"v":1,"shared":["second.md"]}')
    _git(repo, "commit", "-q", "-am", "second")
    assert team.load_team_at(repo, first).shared == ("CHANGELOG.md",)
    assert team.load_team_at(repo, "HEAD").shared == ("second.md",)


@needs_git
def test_load_team_at_without_the_file_is_the_default(repo: Path):
    _git(repo, "rm", "-q", ".aegis/team.json")
    _git(repo, "commit", "-q", "-m", "drop")
    assert team.load_team_at(repo, "HEAD") == team.TeamPolicy()


@needs_git
def test_load_team_at_refuses_invalid_content(repo: Path):
    (repo / ".aegis" / "team.json").write_bytes(b'{"v":1,"lanes":{"Bad":[]}}')
    _git(repo, "commit", "-q", "-am", "bad")
    with pytest.raises(team.TeamFileError, match=r"\Ateam\.json: lanes entry 1 has a name outside"):
        team.load_team_at(repo, "HEAD")


@needs_git
def test_load_team_at_refuses_a_symlink_tree_entry(repo: Path):
    # A symlink blob's content is its target path; it must never be read as policy.
    target = b".aegis/real.json"
    oid = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=str(repo), input=target,
                         capture_output=True, check=True).stdout.decode().strip()
    _git(repo, "update-index", "--cacheinfo", f"120000,{oid},.aegis/team.json")
    _git(repo, "commit", "-q", "-m", "link")
    with pytest.raises(team.TeamFileError, match=r"\Ateam\.json: is a symlink at HEAD\Z"):
        team.load_team_at(repo, "HEAD")


@needs_git
def test_load_team_at_refuses_a_directory_entry(repo: Path):
    _git(repo, "rm", "-q", ".aegis/team.json")  # git also removes the emptied .aegis/
    (repo / ".aegis" / "team.json").mkdir(parents=True)
    (repo / ".aegis" / "team.json" / "x").write_text("x", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "dir")
    with pytest.raises(team.TeamFileError, match=r"\Ateam\.json: is not a file at HEAD\Z"):
        team.load_team_at(repo, "HEAD")


@needs_git
def test_load_team_at_refuses_an_oversized_blob_before_reading_it(repo: Path):
    (repo / ".aegis" / "team.json").write_bytes(EXAMPLE + b" " * config.MAX_CONFIG_BYTES)
    _git(repo, "commit", "-q", "-am", "big")
    with pytest.raises(team.TeamFileError, match=r"\Ateam\.json: larger than 64 KiB at HEAD\Z"):
        team.load_team_at(repo, "HEAD")


@needs_git
@pytest.mark.parametrize("ref", ["no-such-branch", "-p", ""])
def test_load_team_at_an_unresolvable_ref_is_a_git_error(repo: Path, ref: str):
    with pytest.raises(gitsafe.GitError, match="cannot resolve"):
        team.load_team_at(repo, ref)


def test_a_long_invalid_lane_name_is_shown_cut_to_80_characters():
    name = "A" * 200
    with pytest.raises(team.TeamUsageError) as info:
        team.lane_ref(name)
    assert str(info.value).split(" (use ")[0] == "invalid lane name: " + repr(name)[:80]


def _ls_tree_answers(monkeypatch, returncode: int, stdout: bytes) -> None:
    """git's answer to ``ls-tree`` only (the subprocess boundary); every other call is real."""
    real = gitsafe.run

    def run(args, cwd, **kwargs):
        if args and args[0] == "ls-tree":
            return subprocess.CompletedProcess(args, returncode, stdout, b"")
        return real(args, cwd, **kwargs)

    monkeypatch.setattr(gitsafe, "run", run)


@needs_git
def test_load_team_at_when_git_cannot_list_the_tree_is_a_git_error(repo: Path, monkeypatch):
    _ls_tree_answers(monkeypatch, 128, b"")
    with pytest.raises(gitsafe.GitError, match=r"\Agit ls-tree failed for \.aegis/team\.json at [0-9a-f]{40}\Z"):
        team.load_team_at(repo, "HEAD")


@needs_git
@pytest.mark.parametrize("record", [
    b"100644 blob " + b"a" * 40 + b" 12\t.aegis/other.json\0",  # another path
    b"100644 blob " + b"a" * 40 + b"\t.aegis/team.json\0",  # no size column
])
def test_load_team_at_refuses_an_entry_it_cannot_read(repo: Path, monkeypatch, record: bytes):
    _ls_tree_answers(monkeypatch, 0, record)
    with pytest.raises(gitsafe.GitError, match=r"\Agit ls-tree gave an unreadable entry for \.aegis/team\.json at "):
        team.load_team_at(repo, "HEAD")
