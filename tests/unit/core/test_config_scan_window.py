"""``jit.scan_window_s`` (v4.1 spec §2 "Behaviour" 1): how long an aegis_scan row lets
``aegis hook run`` pass an edit of its files. Repo config, default 3600, an integer from 60
to 86400; anything else is ignored with a warning, so a committed file can neither switch
the gate off with a huge window nor break it."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aegis_core.config import DEFAULT_SCAN_WINDOW_S, RepoConfig, scan_window_s


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".aegis").mkdir(parents=True)
    return root


def _repo(ws: Path, data) -> None:
    text = data if isinstance(data, str) else json.dumps(data)
    (ws / ".aegis" / "config.json").write_text(text, encoding="utf-8")


def test_the_default_window_is_an_hour(ws: Path):
    assert DEFAULT_SCAN_WINDOW_S == 3600
    assert RepoConfig.load(ws).scan_window_s == 3600
    _repo(ws, {"jit": {"max_tokens": 1000}})
    config = RepoConfig.load(ws)
    assert (config.scan_window_s, config.warnings) == (3600, ())
    assert scan_window_s(ws) == 3600


@pytest.mark.parametrize("value", [60, 900, 86400, "900"])
def test_a_window_from_a_minute_to_a_day_is_used(ws: Path, value):
    _repo(ws, {"jit": {"scan_window_s": value}})
    config = RepoConfig.load(ws)
    assert (config.scan_window_s, config.warnings) == (int(value), ())
    assert scan_window_s(ws) == int(value)


@pytest.mark.parametrize("value", [59, 86401, 10 ** 9, 0, -60, True, 1.5, "x", None, [900]])
def test_any_other_window_is_ignored_with_a_warning(ws: Path, value):
    _repo(ws, {"jit": {"scan_window_s": value}})
    config = RepoConfig.load(ws)
    assert config.scan_window_s == 3600
    assert config.warnings == (
        "ignored 'jit.scan_window_s' in .aegis/config.json: it must be an integer from 60 to 86400",
    )
    assert scan_window_s(ws) == 3600


def test_the_window_is_a_known_jit_key(ws: Path):
    _repo(ws, {"jit": {"scan_window_s": 120, "max_tokens": 900, "other": 1}})
    config = RepoConfig.load(ws)
    assert (config.scan_window_s, config.jit_max_tokens) == (120, 900)
    assert config.warnings == ("ignored 1 unknown key(s) under 'jit' in .aegis/config.json",)


@pytest.mark.parametrize("content", ["{not json", "[1]", '{"v": 2}'])
def test_an_unusable_repo_config_gives_the_default_window(ws: Path, content: str):
    _repo(ws, content)
    assert scan_window_s(ws) == 3600


def test_a_missing_workspace_gives_the_default_window(tmp_path: Path):
    assert scan_window_s(tmp_path / "nowhere") == 3600


@pytest.mark.parametrize("value,window", [(59, 3600), (60, 60), (61, 61), (86399, 86399), (86400, 86400), (86401, 3600)])
def test_parse_keeps_the_window_only_inside_its_bounds(value, window):
    config = RepoConfig.parse({"jit": {"scan_window_s": value}})
    assert config.scan_window_s == window
    assert bool(config.warnings) is (window == 3600)


def test_parse_without_a_jit_section_or_with_a_bad_one_keeps_the_default():
    assert RepoConfig.parse({}).scan_window_s == 3600
    bad = RepoConfig.parse({"jit": ["scan_window_s", 60]})
    assert (bad.scan_window_s, bad.warnings) == (3600, ("ignored 'jit' in .aegis/config.json: it must be an object",))
