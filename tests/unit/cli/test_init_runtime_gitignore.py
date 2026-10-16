"""`aegis init` keeps machine-local state out of git via `.aegis/.gitignore` ("state/").

Rules and config under `.aegis/` must stay committable; the ledger, the lock and
every other machine-local file of the D12 layout live under `.aegis/state/` and must not.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import symlink_or_skip

from aegis_cli.init import run_init
from aegis_core.workspace.layout import WorkspaceLayout

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _init_args(project: Path, home: Path, **overrides) -> argparse.Namespace:
    values = dict(
        dry_run=False, yes=True, force=False, rules="minimal", no_hooks=True, _project_root=project,
    )
    values.update(overrides)
    return argparse.Namespace(**values)


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
    return path


def _ignored(repo: Path, rel: str) -> bool:
    # --no-index: judge the ignore rules alone, independent of what is tracked.
    res = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", "--no-index", rel],
        capture_output=True, text=True,
    )
    assert res.returncode in (0, 1), res.stderr
    return res.returncode == 0


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _git_repo(tmp_path / "proj")


def _runtime_paths(repo: Path) -> list[str]:
    """Machine-local files the D12 layout writes, as repo-relative paths."""
    layout = WorkspaceLayout(repo)
    paths = [
        layout.ledger_file,
        layout.derived_file,
        layout.lock_file,
        layout.lifecycle_log,
        layout.gate_log,
        layout.migrate_backup_dir("20261015T000000Z") / "evidence" / "signals.jsonl",
        layout.state_dir / ".ledger.jsonl.abc123.tmp",
    ]
    return [p.relative_to(layout.root).as_posix() for p in paths]


COMMITTABLE = [
    ".aegis/config.json",
    ".aegis/rules/invariants/providence.md",

    ".aegis/rules/manifest.json",
    ".aegis/rules/traps/evidence/notes.md",   # a dir named like runtime state, deeper down
    ".aegis/legacy-notes.md",
    ".aegis/config.yaml",
    ".aegis/.gitignore",
]


class TestInitWritesRuntimeGitignore:
    def test_runtime_state_is_ignored(self, repo: Path, home: Path):
        assert run_init(_init_args(repo, home)) == 0

        assert (repo / ".aegis" / ".gitignore").is_file()
        not_ignored = [rel for rel in _runtime_paths(repo) if not _ignored(repo, rel)]
        assert not_ignored == []

    @pytest.mark.parametrize("rel", COMMITTABLE)
    def test_rules_and_config_stay_committable(self, repo: Path, home: Path, rel: str):
        assert run_init(_init_args(repo, home)) == 0

        assert not _ignored(repo, rel)

    def test_second_init_is_byte_identical(self, repo: Path, home: Path):
        assert run_init(_init_args(repo, home)) == 0
        assert (repo / ".aegis" / ".gitignore").is_file()
        first = (repo / ".aegis" / ".gitignore").read_bytes()

        assert run_init(_init_args(repo, home)) == 0

        assert (repo / ".aegis" / ".gitignore").read_bytes() == first

    def test_user_lines_are_kept_and_missing_entries_appended(self, repo: Path, home: Path):
        gi = repo / ".aegis" / ".gitignore"
        gi.parent.mkdir()
        user = "# mine\nscratch-notes.txt\n/evidence/"  # no trailing newline
        gi.write_text(user, encoding="utf-8")

        assert run_init(_init_args(repo, home)) == 0

        text = gi.read_text(encoding="utf-8")
        assert text.startswith(user + "\n")
        assert text.splitlines().count("state/") == 1
        assert _ignored(repo, ".aegis/scratch-notes.txt")
        assert _ignored(repo, ".aegis/state/ledger.jsonl")

    def test_a_negated_entry_is_not_added_again(self, repo: Path, home: Path):
        gi = repo / ".aegis" / ".gitignore"
        gi.parent.mkdir()
        gi.write_text("!state/\n", encoding="utf-8")

        assert run_init(_init_args(repo, home)) == 0

        assert gi.read_text(encoding="utf-8") == "!state/\n"

    def test_dry_run_writes_nothing(self, repo: Path, home: Path):
        assert run_init(_init_args(repo, home, dry_run=True)) == 0

        assert not (repo / ".aegis" / ".gitignore").exists()

    def test_symlinked_gitignore_is_not_written_through(self, repo: Path, home: Path, tmp_path: Path, capsys):
        shared = tmp_path / "shared.gitignore"
        shared.write_text("shared-rule\n", encoding="utf-8")
        (repo / ".aegis").mkdir()
        symlink_or_skip(shared, repo / ".aegis" / ".gitignore")

        assert run_init(_init_args(repo, home)) == 0

        assert shared.read_text(encoding="utf-8") == "shared-rule\n"
        assert ".aegis/.gitignore is a symlink" in capsys.readouterr().err


class TestLineEndingsAreKept:
    """Appending must not rewrite the user's bytes; the block follows their line ending."""

    def _seed(self, repo: Path, raw: bytes) -> Path:
        gi = repo / ".aegis" / ".gitignore"
        gi.parent.mkdir()
        gi.write_bytes(raw)
        return gi

    def test_crlf_file_keeps_bytes_and_block_uses_crlf(self, repo: Path, home: Path):
        original = b"keep-me\r\nother\r\n"
        gi = self._seed(repo, original)

        assert run_init(_init_args(repo, home)) == 0

        out = gi.read_bytes()
        assert out.startswith(original)
        appended = out[len(original):]
        assert appended and appended.endswith(b"\r\n")
        assert appended.count(b"\n") == appended.count(b"\r\n")
        assert _ignored(repo, ".aegis/state/ledger.jsonl")
        assert _ignored(repo, ".aegis/keep-me")

    def test_crlf_file_without_final_newline(self, repo: Path, home: Path):
        original = b"keep-me\r\nother"
        gi = self._seed(repo, original)

        assert run_init(_init_args(repo, home)) == 0

        out = gi.read_bytes()
        assert out.startswith(original + b"\r\n")
        assert out.count(b"\n") == out.count(b"\r\n")
        assert _ignored(repo, ".aegis/other")

    def test_crlf_rerun_is_byte_identical(self, repo: Path, home: Path):
        gi = self._seed(repo, b"keep-me\r\n")
        assert run_init(_init_args(repo, home)) == 0
        first = gi.read_bytes()

        assert run_init(_init_args(repo, home)) == 0

        assert gi.read_bytes() == first

    def test_lone_cr_file_keeps_bytes(self, repo: Path, home: Path):
        original = b"keep-me\rother\r"
        gi = self._seed(repo, original)

        assert run_init(_init_args(repo, home)) == 0

        assert gi.read_bytes().startswith(original)
        assert _ignored(repo, ".aegis/state/ledger.jsonl")


class TestInitConfigJson:
    """`aegis init` writes .aegis/config.json (D12) and never writes it through a link."""

    def test_init_writes_a_v1_config(self, repo: Path, home: Path):
        assert run_init(_init_args(repo, home)) == 0
        assert (repo / ".aegis" / "config.json").read_text(encoding="utf-8") == '{\n  "v": 1\n}\n'

    def test_symlinked_config_is_refused_and_not_written_through(self, repo: Path, home: Path, tmp_path: Path, capsys):
        user_config = tmp_path / "user-config.json"
        (repo / ".aegis").mkdir()
        symlink_or_skip(user_config, repo / ".aegis" / "config.json")

        assert run_init(_init_args(repo, home)) == 1

        assert not user_config.exists()
        assert "is a symlink" in capsys.readouterr().err

    def test_unreadable_config_is_kept_and_reported(self, repo: Path, home: Path, capsys):
        config = repo / ".aegis" / "config.json"
        config.parent.mkdir()
        config.write_text("{hand-edited", encoding="utf-8")

        assert run_init(_init_args(repo, home)) == 0

        assert config.read_text(encoding="utf-8") == "{hand-edited"
        assert ".aegis/config.json is not valid JSON" in capsys.readouterr().err
