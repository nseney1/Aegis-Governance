"""Every git subprocess Aegis runs (D20, host-matrix §3.7, v4.3 spec §10.1).

A repository's own config is attacker-controlled: ``core.fsmonitor`` names a program
that ``git status``/``git diff`` run, hooks run on many commands, a clean filter
(``filter.<driver>.clean``) runs whenever git hashes a working-tree file that
``.gitattributes`` assigns to that driver, and remotes can prompt for credentials. So
every call here:

- runs ``git`` as an argv list (no shell) with a timeout;
- passes ``-c core.fsmonitor=false -c core.hooksPath=<devnull> -c protocol.allow=never
  -c core.sshCommand=false -c credential.helper=`` (command-line config beats repo config);
- sets ``GIT_TERMINAL_PROMPT=0 GIT_OPTIONAL_LOCKS=0 GIT_NO_REPLACE_OBJECTS=1 LC_ALL=C``.
  The system config is read, as git reads it: the machine's administrator writes it,
  and Git for Windows keeps ``core.autocrlf=true`` there, without which every file of a
  Windows checkout (CRLF in the work tree, LF in the repository) looks modified;
- uses plumbing: ``rev-parse``, ``merge-base``, ``diff-tree``, ``diff-index``,
  ``ls-tree``, ``ls-files``, ``cat-file --batch``, ``hash-object`` and ``config``
  (reads only). ``diff-index`` without ``--cached``, ``ls-files --others`` and
  ``hash-object --stdin-paths`` read the working tree, which is where an fsmonitor or
  a clean filter would run; they are needed (no plumbing lists changed or untracked
  files otherwise, and only git knows its line-ending conversion). The forced
  ``core.fsmonitor=false`` keeps them inert, every filter driver the repository's own
  config defines is switched off for them (a driver from the user's or the system's
  config, git-lfs say, still runs, as in any git command the user types), and
  ``diff-index`` does not look inside a dirty submodule, where it would run ``git
  status`` under the submodule's own config.

Blob content read through ``cat-file`` is checked against the object id it was asked
for, so a replaced or corrupted object is an error rather than silent input.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

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


def _completed(args: Sequence[str], cwd: Path | str, **kwargs) -> Optional[subprocess.CompletedProcess]:
    """The completed call, or None (git is missing or timed out)."""
    try:
        return run(args, cwd, **kwargs)
    except GitError:
        return None


def _out(args: Sequence[str], cwd: Path | str, **kwargs) -> Optional[bytes]:
    """stdout of a successful call, or None (git failed, is missing or timed out)."""
    res = _completed(args, cwd, **kwargs)
    return res.stdout if res is not None and res.returncode == 0 else None


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


# Config scopes the user or the machine's administrator wrote. A filter driver defined in
# any other scope (the repository's .git/config or config.worktree, or a file either
# includes) is switched off before git reads working-tree files.
_TRUSTED_SCOPES = frozenset({"system", "global", "command"})
_FILTER_COMMANDS = ("clean", "smudge", "process")
_REGULAR_MODES = frozenset({"100644", "100755"})
_LINK_MODE = "120000"


def _filter_overrides(cwd: Path | str) -> Optional[Tuple[str, ...]]:
    """``-c`` options that switch off every filter driver the repository's config
    defines, or None when git cannot list them or a driver's name cannot be given to
    ``-c`` (it splits at the first ``=``)."""
    listing = ["config", "--null", "--name-only", "--get-regexp", r"^filter\."]
    res = _completed([listing[0], "--show-scope", *listing[1:]], cwd)
    if res is None:
        return None
    if res.returncode == 1:  # no filter driver is configured anywhere
        return ()
    if res.returncode == 0:
        fields = res.stdout.split(b"\0")
        keys = [key for scope, key in zip(fields[0::2], fields[1::2])
                if key and scope.decode("ascii", "replace") not in _TRUSTED_SCOPES]
    else:  # git before 2.26 has no --show-scope: switch off every driver
        res = _completed(listing, cwd)
        if res is None or res.returncode not in (0, 1):
            return None
        keys = [key for key in res.stdout.split(b"\0") if key]
    overrides: List[str] = []
    for driver in dict.fromkeys(os.fsdecode(key)[len("filter."):].rpartition(".")[0] for key in keys):
        if not driver:
            continue  # "filter.<key>" without a driver name configures nothing
        if "=" in driver:
            return None
        for command in _FILTER_COMMANDS:
            overrides += ["-c", f"filter.{driver}.{command}="]
        overrides += ["-c", f"filter.{driver}.required=false"]
    return tuple(overrides)


def _work_tree_bytes(path: Path, mode: str) -> Tuple[Optional[bytes], bool]:
    """What git hashes for the work-tree entry at ``path`` (None if there is nothing it
    could), and whether that entry is a regular file.

    A symlink entry is its target, which is what git stores for one; a regular file is
    its content (also where core.symlinks=false checked a symlink out as a file).
    Nothing is read through a link and nothing but a regular file is opened.
    """
    try:
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode):
            return (os.fsencode(os.readlink(path)) if mode == _LINK_MODE else None), False
        if stat.S_ISREG(st.st_mode):
            return path.read_bytes(), True
    except OSError:
        pass
    return None, False


def _c_quoted(path: str) -> bytes:
    """``path`` as one C-quoted line, which ``hash-object --stdin-paths`` unquotes."""
    quoted = bytearray(b'"')
    for byte in os.fsencode(path):
        if byte in b'"\\':
            quoted += b"\\" + bytes([byte])
        elif byte < 0x20 or byte == 0x7F:
            quoted += b"\\%03o" % byte
        else:
            quoted.append(byte)
    return bytes(quoted + b'"')


def _clean_blob_ids(root: Path, paths: Sequence[str], hardening: Sequence[str]) -> Optional[List[str]]:
    """The blob ids ``git add`` would store for these work-tree files, after git's clean
    conversion (core.autocrlf and core.eol, the text, eol, ident and
    working-tree-encoding attributes); None when git cannot say. Writes nothing."""
    stdin = b"".join(_c_quoted(path) + b"\n" for path in paths)
    out = _out(["hash-object", "--stdin-paths"], root, stdin=stdin, _hardening=hardening)
    ids = None if out is None else out.decode("ascii", "replace").split()
    return ids if ids is not None and len(ids) == len(paths) else None


def _working_changes(cwd: Path | str, tree: str) -> Optional[List[str]]:
    """Files whose working-tree content differs from ``tree`` (added, copied, modified).

    diff-index lists every file whose stat data is stale, so a listed file is kept only
    if git would store something else for it: a ``touch`` is not a change, and neither
    is a line-ending difference git's clean conversion removes (a CRLF checkout of LF
    blobs under core.autocrlf or ``text``). Its own bytes are compared first; only a
    regular file that differs is hashed by git.
    """
    overrides = _filter_overrides(cwd)
    if overrides is None:
        return None
    hardening = (*_HARDENING, *overrides)
    out = _out(["diff-index", "-z", "--raw", "--no-renames", "--ignore-submodules=dirty", _ACMR, tree],
               cwd, _hardening=hardening)
    if out is None:
        return None
    fields = out.split(b"\0")
    root = toplevel(cwd) or Path(cwd)  # diff-index names paths from the top of the work tree
    listed: List[str] = []
    to_convert: Dict[str, str] = {}  # regular files whose bytes differ: path -> the tree's blob id
    for meta, raw_path in zip(fields[0::2], fields[1::2]):
        parts = meta.split()
        if len(parts) < 5 or not raw_path:
            continue
        old_mode, old_oid = parts[0].lstrip(b":").decode("ascii"), parts[2].decode("ascii")
        path = os.fsdecode(raw_path)
        if set(old_oid) != {"0"}:  # all zeros: not in the tree, so added
            data, is_file = _work_tree_bytes(root / path, old_mode)
            if data is not None and _blob_id(data, len(old_oid)) == old_oid:
                continue
            if is_file and old_mode in _REGULAR_MODES:
                to_convert[path] = old_oid
        listed.append(path)
    if to_convert:
        ids = _clean_blob_ids(root, list(to_convert), hardening)
        if ids is not None:  # otherwise every one of them stays listed
            unchanged = {path for (path, old), new in zip(to_convert.items(), ids) if new == old}
            listed = [path for path in listed if path not in unchanged]
    return listed


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
