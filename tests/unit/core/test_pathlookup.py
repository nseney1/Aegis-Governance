"""aegis_core.pathlookup: the one lookup of a program on PATH (host-matrix §3.7).

Aegis starts what this finds (a host CLI, python3) and writes the aegis-mcp it finds
into a host's config, from inside a repository the user may just have cloned. So only
absolute PATH entries count: an empty or relative entry names the current directory,
where the repository can plant a program. An absolute entry inside a fence (the
workspace, for doctor) does not count either. ``only_skipped`` reports where a program
is reachable when every one of those places was refused, so a caller never reports a
host it passed over as plainly absent.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from aegis_core.pathlookup import Hit, only_skipped, which

EXE = ".exe" if os.name == "nt" else ""


def _program(directory: Path, name: str, data: bytes = b"#!/bin/sh\nexit 0\n") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (name + EXE)
    path.write_bytes(data)
    path.chmod(0o755)
    return path


def _path(*entries) -> str:
    return os.pathsep.join(str(e) for e in entries)


# ── which ────────────────────────────────────────────────────────────────────

def test_the_first_absolute_entry_holding_the_program_wins(tmp_path):
    first = _program(tmp_path / "a", "codex")
    _program(tmp_path / "b", "codex")
    assert which("codex", _path(tmp_path / "empty", tmp_path / "a", tmp_path / "b")) == str(first)


def test_a_name_on_no_entry_is_none(tmp_path):
    (tmp_path / "empty").mkdir()
    assert which("codex", _path(tmp_path / "empty")) is None
    assert which("codex", "") is None


@pytest.mark.parametrize("entry", ["", ".", "bin", os.path.join(".", "bin")])
def test_empty_and_relative_entries_are_never_searched(tmp_path, monkeypatch, entry):
    # Each names a directory relative to the cwd, where a repository plants programs.
    _program(tmp_path, "codex")
    _program(tmp_path / "bin", "codex")
    monkeypatch.chdir(tmp_path)
    assert which("codex", _path(entry)) is None
    real = _program(tmp_path / "real", "codex")
    assert which("codex", _path(entry, real.parent)) == str(real)


def test_the_default_path_is_the_environment_path(tmp_path, monkeypatch):
    exe = _program(tmp_path / "bin", "aegis-mcp")
    monkeypatch.setenv("PATH", str(exe.parent))
    assert which("aegis-mcp") == str(exe)


def test_an_entry_inside_the_fence_is_skipped_and_the_next_one_wins(tmp_path):
    ws = tmp_path / "ws"
    _program(ws / "tools", "codex")
    real = _program(tmp_path / "bin", "codex")
    path = _path(ws / "tools", real.parent)
    assert which("codex", path, outside=ws) == str(real)
    assert which("codex", _path(ws / "tools"), outside=ws) is None
    assert which("codex", _path(ws / "tools")) == str(ws / "tools" / ("codex" + EXE))


def test_the_fence_itself_is_inside_the_fence(tmp_path):
    ws = tmp_path / "ws"
    _program(ws, "codex")
    assert which("codex", _path(ws), outside=ws) is None


def test_a_sibling_sharing_the_fence_prefix_is_outside_it(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    sibling = _program(tmp_path / "ws-tools", "codex")
    assert which("codex", _path(sibling.parent), outside=ws) == str(sibling)


def test_a_linked_entry_into_the_fence_is_inside_it(tmp_path):
    ws = tmp_path / "ws"
    _program(ws / "bin", "codex")
    link = tmp_path / "linkbin"
    try:
        link.symlink_to(ws / "bin", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available")
    assert which("codex", _path(link), outside=ws) is None


def test_a_linked_program_is_returned_under_its_own_name(tmp_path):
    # Version managers dispatch on argv[0]: the name found on PATH is what runs.
    real = _program(tmp_path / "toolchain", "dispatcher")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    try:
        (bindir / ("codex" + EXE)).symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available")
    assert which("codex", _path(bindir)) == str(bindir / ("codex" + EXE))


@pytest.mark.skipif(os.name == "nt", reason="Windows has no execute bit")
def test_a_file_without_the_execute_bit_is_not_a_program(tmp_path):
    exe = _program(tmp_path / "bin", "codex")
    exe.chmod(0o644)
    assert which("codex", _path(exe.parent)) is None


def test_a_directory_named_like_the_program_is_not_a_program(tmp_path):
    (tmp_path / "bin" / ("codex" + EXE)).mkdir(parents=True)
    assert which("codex", _path(tmp_path / "bin")) is None


class TestWindowsLookup:
    """PATHEXT candidates matched case-insensitively against the directory, returned
    in the file's own spelling. Emulated off Windows by the platform name."""

    @pytest.fixture
    def windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("PATHEXT", os.pathsep.join([".COM", ".EXE", ".BAT", ".CMD"]))

    @pytest.mark.parametrize("on_disk", ["codex.exe", "codex.Exe", "CODEX.EXE"])
    def test_the_on_disk_spelling_is_returned(self, tmp_path, windows, on_disk):
        exe = tmp_path / "bin" / on_disk
        exe.parent.mkdir()
        exe.write_bytes(b"MZ")
        exe.chmod(0o755)
        assert which("codex", str(exe.parent)) == str(exe)

    def test_a_cmd_shim_is_found_after_the_exe_extensions(self, tmp_path, windows):
        shim = tmp_path / "npm" / "codex.cmd"
        shim.parent.mkdir()
        shim.write_bytes(b"@echo off\r\n")
        shim.chmod(0o755)
        assert which("codex", str(shim.parent)) == str(shim)

    def test_a_name_that_carries_an_extension_is_looked_up_as_given(self, tmp_path, windows):
        exe = tmp_path / "bin" / "python3.exe"
        exe.parent.mkdir()
        exe.write_bytes(b"MZ")
        exe.chmod(0o755)
        assert which("python3.EXE", str(exe.parent)) == str(exe)

    def test_a_name_without_a_pathext_extension_is_not_a_program(self, tmp_path, windows):
        script = tmp_path / "bin" / "codex"
        script.parent.mkdir()
        script.write_bytes(b"#!/bin/sh\n")
        script.chmod(0o755)
        assert which("codex", str(script.parent)) is None

    def test_relative_entries_are_skipped_on_windows_too(self, tmp_path, windows, monkeypatch):
        shim = tmp_path / "codex.cmd"
        shim.write_bytes(b"@echo off\r\n")
        shim.chmod(0o755)
        monkeypatch.chdir(tmp_path)
        assert which("codex", os.pathsep.join(["", "."])) is None


# ── only_skipped ─────────────────────────────────────────────────────────────

def test_only_skipped_is_empty_when_which_finds_the_program(tmp_path):
    ws = tmp_path / "ws"
    _program(ws / "bin", "codex")
    real = _program(tmp_path / "bin", "codex")
    assert only_skipped("codex", _path("bin", ws / "bin", real.parent), outside=ws, base=ws) == []


def test_only_skipped_is_empty_when_the_program_is_nowhere(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert only_skipped("codex", _path("", ".", "bin", ws), outside=ws, base=ws) == []


@pytest.mark.parametrize("entry, where", [("", "."), (".", "."), ("bin", "bin"),
                                          (os.path.join("..", "tools"), os.path.join("..", "tools"))])
def test_a_program_reachable_only_through_a_relative_entry_is_reported(tmp_path, entry, where):
    ws = tmp_path / "ws"
    exe = _program(ws / where, "codex")
    hits = only_skipped("codex", _path(entry), outside=ws, base=ws)
    assert hits == [Hit(path=os.path.normpath(str(exe)), entry=entry, reason="relative_entry")]


def test_a_relative_entry_resolves_against_the_cwd_by_default(tmp_path, monkeypatch):
    exe = _program(tmp_path / "bin", "codex")
    monkeypatch.chdir(tmp_path)
    assert only_skipped("codex", _path("bin")) == [
        Hit(path=os.path.normpath(os.path.join(os.getcwd(), "bin", "codex" + EXE)), entry="bin",
            reason="relative_entry")]
    assert exe.is_file()


def test_a_program_reachable_only_inside_the_fence_is_reported(tmp_path):
    ws = tmp_path / "ws"
    exe = _program(ws / "tools", "codex")
    assert only_skipped("codex", _path(ws / "tools"), outside=ws) == [
        Hit(path=str(exe), entry=str(ws / "tools"), reason="inside_fence")]


def test_every_refused_place_is_reported_once_in_path_order(tmp_path):
    ws = tmp_path / "ws"
    inside = _program(ws / "tools", "codex")
    relative = _program(ws / "bin", "codex")
    hits = only_skipped("codex", _path(ws / "tools", "bin", ws / "tools", "bin"), outside=ws, base=ws)
    assert [(h.path, h.reason) for h in hits] == [(str(inside), "inside_fence"),
                                                   (os.path.normpath(str(relative)), "relative_entry")]


def test_without_a_fence_only_relative_entries_are_refused(tmp_path):
    ws = tmp_path / "ws"
    _program(ws / "tools", "codex")
    assert only_skipped("codex", _path(ws / "tools"), base=ws) == []

