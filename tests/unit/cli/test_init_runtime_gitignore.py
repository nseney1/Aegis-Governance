"""`aegis init` keeps machine-local runtime state out of git via `.aegis/.gitignore`.

Rules and config under `.aegis/` must stay committable; the ledger, locks, keys,
receipts, cursors and other runtime files written by the current layout must not.
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
        dry_run=False, platform="gemini", yes=True, force=False, local=False,
        rules="minimal", mcp=False, no_hooks=True, _project_root=project, _home=home,
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
    """Runtime state the current and earlier layouts write, as repo-relative paths."""
    layout = WorkspaceLayout(repo)
    paths = [
        layout.signals_file,                         # evidence/ ledger
        layout.evidence_dir / ".signals.lock",
        layout.evidence_dir / "outcomes.jsonl",
        layout.evidence_dir / "checkpoint_rollup.json",
        layout.aegis_dir / "telemetry" / "checkpoint_rollup.json",
        layout.lock_file("signals"),                 # locks/
        layout.manifest_key_file,                    # keys/
        layout.keys_dir / "receipt.key",
        layout.aegis_dir / "receipt_key",            # legacy HMAC key still read
        layout.aegis_dir / "receipts.jsonl",
        layout.metrics_dir / "escaped_defects.jsonl",
        layout.aegis_dir / "governance" / "gate_events.jsonl",
        layout.aegis_dir / "quarantine" / "quarantine_log.jsonl",
        layout.aegis_dir / "swarm" / "leases.json",
        layout.aegis_dir / "swarm" / "handoffs" / "t1_review.json",
        layout.aegis_dir / "handoffs" / "t1_review.json",
        layout.aegis_dir / "human_insights.jsonl",
        layout.aegis_dir / "insight_cursor",
        layout.aegis_dir / ".insight_cursor.abc123.tmp",
        layout.aegis_dir / "jobs_state.json",
        layout.aegis_dir / "epoch_generation",
        layout.aegis_dir / "migration.lock",
    ]
    return [p.relative_to(repo).as_posix() for p in paths]


COMMITTABLE = [
    ".aegis/rules/invariants/providence.md",
    ".aegis/rules/manifest.json",
    ".aegis/rules/traps/evidence/notes.md",   # a dir named like runtime state, deeper down
    ".aegis/slots.yaml",
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
        user = "# mine\nscratch-notes.txt\n/evidence/\n!/keys/"  # no trailing newline
        gi.write_text(user, encoding="utf-8")

        assert run_init(_init_args(repo, home)) == 0

        text = gi.read_text(encoding="utf-8")
        assert text.startswith(user + "\n")
        lines = text.splitlines()
        assert lines.count("/evidence/") == 1
        # The user's own negation wins: we never re-add an entry they negated.
        assert "/keys/" not in lines
        assert not _ignored(repo, ".aegis/keys/manifest.key")
        assert _ignored(repo, ".aegis/scratch-notes.txt")
        assert _ignored(repo, ".aegis/receipts.jsonl")

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
        assert ".aegis/.gitignore is a symlink" in capsys.readouterr().out


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
        assert _ignored(repo, ".aegis/receipts.jsonl")
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
        assert _ignored(repo, ".aegis/receipts.jsonl")
