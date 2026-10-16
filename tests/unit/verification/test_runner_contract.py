"""Layer 1 runner contracts: which changed files the structural checks read, and the
staged snapshot `aegis check --hook` checks (runner.snapshot_index, runner.run_layer1_on_index)."""
from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from aegis_core import gitsafe
from aegis_core.verification import runner


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=str(repo), check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    return root


def _stage(repo: Path, rel: str, data: bytes) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    _git(repo, "add", rel)


def _tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def batch_reads(monkeypatch) -> list:
    """The object ids of each `git cat-file --batch` call, one list per call."""
    real_run, calls = gitsafe.run, []

    def spy(args, cwd, *rest, **kwargs):
        if list(args[:2]) == ["cat-file", "--batch"]:
            calls.append((kwargs.get("stdin") or b"").decode("ascii").split())
        return real_run(args, cwd, *rest, **kwargs)

    monkeypatch.setattr(gitsafe, "run", spy)
    return calls


def test_tests_and_package_markers_get_no_structural_checks(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("import requests\n", encoding="utf-8")
    (tmp_path / "tests" / "test_mod.py").write_text("import requests\n", encoding="utf-8")
    (tmp_path / "pkg" / "mod.py").write_text("def double(x):\n    return x + x\n", encoding="utf-8")

    results = runner.run_layer1(["pkg/__init__.py", "tests/test_mod.py", "pkg/mod.py"], str(tmp_path), fast_mode=True)

    assert sorted((r.tool, r.target) for r in results) == [("call_graph", "mod.py"), ("import_guard", "mod.py")]


class TestSnapshotIndex:
    def test_writes_the_staged_bytes_and_empty_python_siblings_of_their_folders(self, repo: Path, tmp_path: Path):
        _stage(repo, "pkg/a.py", b"STAGED = 1\n")
        _stage(repo, "pkg/b.py", b"SIBLING = 2\n")
        _stage(repo, "pkg/data.json", b"{}\n")
        _stage(repo, "other/c.py", b"OTHER = 3\n")
        (repo / "pkg" / "a.py").write_bytes(b"WORKING_COPY = 1\n")  # not what the commit records
        snapshot = tmp_path / "snap"
        snapshot.mkdir()

        written, too_large = runner.snapshot_index(str(repo), ["pkg/a.py"], str(snapshot))

        assert (written, too_large) == (["pkg/a.py"], {})
        assert _tree(snapshot) == {"pkg/a.py": b"STAGED = 1\n", "pkg/b.py": b""}

    def test_paths_the_index_does_not_hold_as_files_are_not_written(self, repo: Path, tmp_path: Path):
        _stage(repo, "kept.py", b"x = 1\n")
        snapshot = tmp_path / "snap"
        snapshot.mkdir()

        written, _ = runner.snapshot_index(str(repo), ["kept.py", "never_staged.py", "kept.py"], str(snapshot))

        assert written == ["kept.py"]
        assert _tree(snapshot) == {"kept.py": b"x = 1\n"}

    def test_a_file_over_the_limit_is_reported_by_size_and_never_read(self, repo, tmp_path, monkeypatch, batch_reads):
        monkeypatch.setattr(runner, "INDEX_BLOB_LIMIT_BYTES", 64)
        _stage(repo, "big.py", b"#" * 65 + b"\n")
        _stage(repo, "small.py", b"y = 2\n")
        snapshot = tmp_path / "snap"
        snapshot.mkdir()

        written, too_large = runner.snapshot_index(str(repo), ["big.py", "small.py"], str(snapshot))

        assert (written, too_large) == (["small.py"], {"big.py": 66})
        assert _tree(snapshot) == {"big.py": b"", "small.py": b"y = 2\n"}  # big.py: an empty sibling only
        assert _git(repo, "rev-parse", ":big.py") not in sum(batch_reads, [])

    def test_staged_files_are_read_in_batches_of_at_most_the_limit(self, repo, tmp_path, monkeypatch, batch_reads):
        monkeypatch.setattr(runner, "INDEX_BLOB_LIMIT_BYTES", 100)
        for name, size in (("a.py", 30), ("b.py", 30), ("c.py", 60), ("d.py", 10)):
            _stage(repo, name, name.encode() + b"#" * (size - len(name) - 1) + b"\n")
        oid = {name: _git(repo, "rev-parse", f":{name}") for name in ("a.py", "b.py", "c.py", "d.py")}
        snapshot = tmp_path / "snap"
        snapshot.mkdir()

        written, _ = runner.snapshot_index(str(repo), ["a.py", "b.py", "c.py", "d.py"], str(snapshot))

        assert written == ["a.py", "b.py", "c.py", "d.py"]
        assert batch_reads == [[oid["a.py"], oid["b.py"]], [oid["c.py"], oid["d.py"]]]
        assert {rel: len(data) for rel, data in _tree(snapshot).items()} == {"a.py": 30, "b.py": 30, "c.py": 60, "d.py": 10}


class TestLayer1OnIndex:
    def test_the_staged_python_content_is_what_is_checked(self, repo: Path):
        _stage(repo, "app.py", b"import requests\n\ndef main():\n    return requests\n")
        (repo / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")

        results = runner.run_layer1_on_index(["app.py"], str(repo))

        blocked = [(r.tool, r.target) for r in results if not r.verdict]
        assert blocked == [("import_guard", "app.py")]
        assert "requests" in next(r.detail for r in results if r.tool == "import_guard")

    def test_a_file_whose_driver_lookup_fails_is_still_read_and_fails_closed(self, repo: Path):
        (repo / ".aegis").mkdir()
        (repo / ".aegis" / "config.json").write_text("{not json", encoding="utf-8")
        _stage(repo, "app.ts", b"export function run() {}\n")

        results = runner.run_layer1_on_index(["app.ts"], str(repo))

        assert [(r.tool, r.target, r.verdict) for r in results] == [("call_graph", "app.ts", False)]
        assert results[0].detail.startswith("call_graph: cannot verify app.ts: ")
