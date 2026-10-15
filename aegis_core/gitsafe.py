"""Every git subprocess Aegis runs (D20, host-matrix §3.7, v4.3 spec §10.1).

A repository's own config is attacker-controlled: ``core.fsmonitor`` names a program
that ``git status``/``git diff`` run, hooks run on many commands, and remotes can
prompt for credentials. So every call here:

- runs ``git`` as an argv list (no shell) with a timeout;
- passes ``-c core.fsmonitor=false -c core.hooksPath=<devnull> -c protocol.allow=never
  -c core.sshCommand=false -c credential.helper=`` (command-line config beats repo config);
- sets ``GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0 GIT_OPTIONAL_LOCKS=0
  GIT_NO_REPLACE_OBJECTS=1 LC_ALL=C``;
- uses plumbing: ``rev-parse``, ``merge-base``, ``diff-tree``, ``diff-index``,
  ``ls-tree``, ``ls-files``, ``cat-file --batch`` and ``hash-object``. ``diff-index``
  without ``--cached`` and ``ls-files --others`` stat the working tree, which is where
  an fsmonitor would run; they are needed (no plumbing lists changed or untracked
  files otherwise), and the forced ``core.fsmonitor=false`` keeps them inert.

Blob content read through ``cat-file`` is checked against the object id it was asked
for, so a replaced or corrupted object is an error rather than silent input.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from typing import Iterable, List, Optional, Sequence

from aegis_core.errors import AegisError

__all__ = [
    "CHANGE_MODES",
    "GIT_TIMEOUT_SECONDS",
    "GitError",
    "changed_files",
    "git_path",
    "head_commit",
    "list_files",
    "merge_base",
    "read_blob",
    "resolve_base_ref",
    "resolve_commit",
    "run",
    "toplevel",
]

GIT_TIMEOUT_SECONDS = 10.0
CHANGE_MODES = ("working", "staged", "head", "range")
_ACMR = "--diff-filter=ACMR"
_HARDENING_KEEP_HOOKS_PATH = (
    "-c", "core.fsmonitor=false",
    "-c", "protocol.allow=never",
    "-c", "core.sshCommand=false",
    "-c", "credential.helper=",
)
_HARDENING = ("-c", f"core.hooksPath={os.devnull}", *_HARDENING_KEEP_HOOKS_PATH)
_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "LC_ALL": "C",
}


class GitError(AegisError):
    """git is missing, timed out, or gave an answer that cannot be trusted."""


def _git_executable() -> str:
    found = shutil.which("git")
    if not found:
        raise GitError("git is not installed or not on PATH")
    return found


def run(
    args: Sequence[str],
    cwd: Path | str,
    timeout: float = GIT_TIMEOUT_SECONDS,
    stdin: Optional[bytes] = None,
    _hardening: Sequence[str] = _HARDENING,
) -> subprocess.CompletedProcess:
    """Run ``git <args>`` hardened as described above; return the completed process (bytes).

    A non-zero exit is returned, not raised. Raises GitError when git cannot be started
    or exceeds ``timeout``.
    """
    argv = [_git_executable(), *_hardening, *args]
    env = dict(os.environ)
    env.update(_ENV)
    try:
        return subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            input=stdin,
            stdin=None if stdin is not None else subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0] if args else ''} timed out after {timeout:g}s") from exc
    except OSError as exc:
        raise GitError(f"cannot run git: {exc}") from exc


def _out(args: Sequence[str], cwd: Path | str, **kwargs) -> Optional[bytes]:
    """stdout of a successful call, or None (git failed, is missing or timed out)."""
    try:
        res = run(args, cwd, **kwargs)
    except GitError:
        return None
    return res.stdout if res.returncode == 0 else None


def _text(args: Sequence[str], cwd: Path | str, **kwargs) -> Optional[str]:
    out = _out(args, cwd, **kwargs)
    if out is None:
        return None
    text = os.fsdecode(out.strip())
    return text or None


def _z_paths(out: Optional[bytes]) -> Optional[List[str]]:
    if out is None:
        return None
    return [os.fsdecode(p) for p in out.split(b"\0") if p]


# ── Repository facts ─────────────────────────────────────────────────────────

def toplevel(cwd: Path | str) -> Optional[Path]:
    """The work tree root containing ``cwd``, or None outside a work tree."""
    text = _text(["rev-parse", "--show-toplevel"], cwd)
    return Path(text) if text else None


def git_path(cwd: Path | str, name: str) -> Optional[Path]:
    """``git rev-parse --git-path <name>`` as an absolute path (e.g. the hooks dir), or None.

    This one call omits the ``core.hooksPath`` override: it asks where hooks live, and
    rev-parse runs no hook.
    """
    text = _text(["rev-parse", "--git-path", name], cwd, _hardening=_HARDENING_KEEP_HOOKS_PATH)
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else (Path(cwd) / path).resolve()


def resolve_commit(cwd: Path | str, ref: str) -> Optional[str]:
    """The commit id ``ref`` names, or None. ``ref`` never reaches git as an option."""
    if not ref or ref.startswith("-"):
        return None
    return _text(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd)


def head_commit(cwd: Path | str) -> Optional[str]:
    """HEAD's commit id, or None (unborn branch, not a repository)."""
    return resolve_commit(cwd, "HEAD")


def merge_base(cwd: Path | str, a: str, b: str = "HEAD") -> Optional[str]:
    """The best common ancestor of two commits, or None."""
    first, second = resolve_commit(cwd, a), resolve_commit(cwd, b)
    if not first or not second:
        return None
    return _text(["merge-base", first, second], cwd)


def resolve_base_ref(cwd: Path | str, environ: Optional[dict] = None) -> Optional[str]:
    """The base branch a change is measured against: the first that resolves of
    ``origin/$GITHUB_BASE_REF``, ``$GITHUB_BASE_REF``, ``origin/main``, ``main``,
    ``origin/develop``, ``develop``. Returns the ref name, or None."""
    env = os.environ if environ is None else environ
    candidates: List[str] = []
    base = (env.get("GITHUB_BASE_REF") or "").strip()  # set by GitHub Actions on pull requests
    if base:
        candidates += [f"origin/{base}", base]
    candidates += ["origin/main", "main", "origin/develop", "develop"]
    for ref in candidates:
        if resolve_commit(cwd, ref):
            return ref
    return None


def _empty_tree(cwd: Path | str) -> Optional[str]:
    # hash-object writes nothing without -w; it answers in the repository's hash format.
    return _text(["hash-object", "-t", "tree", "--stdin"], cwd, stdin=b"")


def _head_or_empty_tree(cwd: Path | str) -> Optional[str]:
    return head_commit(cwd) or _empty_tree(cwd)


# ── Changed and listed files ─────────────────────────────────────────────────

def _blob_id(data: bytes, oid_length: int) -> str:
    header = b"blob %d\0" % len(data)
    digest = hashlib.sha256 if oid_length == 64 else hashlib.sha1
    return digest(header + data).hexdigest()


def _working_changes(cwd: Path | str, tree: str) -> Optional[List[str]]:
    """Files whose working-tree content differs from ``tree`` (added, copied, modified).

    diff-index reports every file whose stat data is stale, so a reported file is kept
    only if its bytes really differ from the tree's blob (a ``touch`` is not a change).
    """
    out = _out(["diff-index", "-z", "--raw", "--no-renames", _ACMR, tree], cwd)
    if out is None:
        return None
    fields = out.split(b"\0")
    root = toplevel(cwd) or Path(cwd)  # diff-index names paths from the top of the work tree
    changed: List[str] = []
    for meta, raw_path in zip(fields[0::2], fields[1::2]):
        parts = meta.split()
        if len(parts) < 5 or not raw_path:
            continue
        old_oid = parts[2].decode("ascii")
        path = os.fsdecode(raw_path)
        if set(old_oid) != {"0"}:
            try:
                data = (root / path).read_bytes()
            except OSError:
                data = None
            if data is not None and _blob_id(data, len(old_oid)) == old_oid:
                continue
        changed.append(path)
    return changed


def changed_files(
    cwd: Path | str,
    mode: str = "working",
    base: Optional[str] = None,
    untracked: bool = False,
) -> Optional[List[str]]:
    """Repo-relative paths added, copied or modified (deletions are not listed).

    - ``working``: working tree and index against HEAD (``git diff HEAD`` plus
      ``git diff --cached``); with ``untracked=True`` also untracked, not ignored files.
    - ``staged``: index against HEAD (what a commit would contain).
    - ``head``: the last commit against its parent (or the root commit's files).
    - ``range``: HEAD against its merge base with ``base`` (``git diff base...HEAD``).

    An unborn HEAD compares against the empty tree. Returns None when git cannot answer
    (not a repository, git missing, ``base`` unknown).
    """
    if mode not in CHANGE_MODES:
        raise ValueError(f"mode must be one of {list(CHANGE_MODES)}, got {mode!r}")
    if mode == "range":
        if not base:
            raise ValueError("mode 'range' needs a base")
        start = merge_base(cwd, base)
        end = head_commit(cwd)
        if not start or not end:
            return None
        return _z_paths(_out(["diff-tree", "-r", "-z", "--name-only", "--no-renames", _ACMR, start, end], cwd))
    if mode == "head":
        head = head_commit(cwd)
        if not head:
            return None
        parent = resolve_commit(cwd, f"{head}~1")
        args = [parent, head] if parent else ["--root", head]
        return _z_paths(_out(["diff-tree", "-r", "-z", "--name-only", "--no-renames", "--no-commit-id", _ACMR, *args], cwd))

    tree = _head_or_empty_tree(cwd)
    if not tree:
        return None
    staged = _z_paths(_out(["diff-index", "--cached", "-z", "--name-only", "--no-renames", _ACMR, tree], cwd))
    if staged is None or mode == "staged":
        return staged
    working = _working_changes(cwd, tree)
    if working is None:
        return None
    files = list(dict.fromkeys(working + staged))
    if untracked:
        others = list_files(cwd, tracked=False, untracked=True)
        if others is None:
            return None
        files = list(dict.fromkeys(files + others))
    return files


def list_files(
    cwd: Path | str,
    paths: Iterable[str] = (),
    tracked: bool = True,
    untracked: bool = True,
) -> Optional[List[str]]:
    """Repo-relative files git knows about under ``paths`` (all when empty): tracked
    ones and/or untracked, not ignored ones. None when git cannot answer."""
    args = ["ls-files", "-z"]
    if tracked:
        args.append("--cached")
    if untracked:
        args += ["--others", "--exclude-standard"]
    args.append("--")
    args += list(paths)
    found = _z_paths(_out(args, cwd))
    return None if found is None else list(dict.fromkeys(found))


# ── Reading blobs ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _TreeEntry:
    mode: str
    kind: str
    oid: str


def _tree_entry(cwd: Path | str, commit: str, path: str) -> Optional[_TreeEntry]:
    out = _out(["ls-tree", "-z", "--full-tree", commit, "--", path], cwd)
    if not out:
        return None
    meta, _, _ = out.split(b"\0", 1)[0].partition(b"\t")
    parts = meta.split()
    if len(parts) != 3:
        return None
    return _TreeEntry(*(p.decode("ascii") for p in parts))


def read_blob(cwd: Path | str, rev: str, path: str) -> Optional[bytes]:
    """The bytes of ``path`` (repo-relative, POSIX) at commit ``rev``; None if it is absent.

    Raises GitError when git returns content that does not hash to the object id it
    named (a replaced or corrupt object).
    """
    commit = resolve_commit(cwd, rev)
    if not commit:
        return None
    entry = _tree_entry(cwd, commit, path)
    if entry is None or entry.kind != "blob":
        return None
    out = _out(["cat-file", "--batch"], cwd, stdin=entry.oid.encode("ascii") + b"\n")
    if not out:
        return None
    header, _, rest = out.partition(b"\n")
    fields = header.split()
    if len(fields) != 3 or fields[1] != b"blob":
        return None
    size = int(fields[2])
    data = rest[:size]
    if len(data) != size or _blob_id(data, len(entry.oid)) != entry.oid:
        raise GitError(f"git returned content for {path} at {rev} that does not match object {entry.oid}")
    return data
