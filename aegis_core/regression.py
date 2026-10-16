"""Regression discipline: git is the registry (v4.3 spec §3 T5).

Every non-merge commit in ``merge-base(base, head)..head`` that matches both:

1. a Conventional Commit ``fix`` subject (``fix:``, ``fix(<scope>):``, ``fix!:``) with scope
   outside ``{ci, build, docs, deps, release, chore, tests}`` or a ``Fixes:`` / ``Closes:``
   issue trailer, and
2. at least one changed non-test, non-doc, non-config source file,

must ship with a test that **fails on base and passes on head** when the new or changed test
files are overlaid onto the ``base`` source in a temporary snapshot and run with the hermetic
pytest runner, or carry a verified ``human_gate`` approval (§2.2).

A tautological ``assert True`` test passes on ``base`` as well as ``head`` and therefore fails
the fail-to-pass check (``reason="passed_on_base"``). An ``Aegis-No-Test: <reason>`` trailer is
an explanation, never authorization: without a verified ``human_gate`` approval the commit still
fails the regression check. Rollout starts at ``warning`` tier, reports ``exemption_rate`` (with
a prune box at > 25%), and includes a non-failing ``untested_changes`` report for non-fix
commits that touch source files without tests.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import stat
import sys
import sysconfig
import tempfile
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
import xml.etree.ElementTree as ET

from aegis_core import checkrun, gitsafe, governance, human_gate, match
from aegis_core._version import __version__
from aegis_core.errors import AegisError
from aegis_core.rules import workspace_root
from aegis_core.storage import atomic_write_bytes
from aegis_core.workspace.layout import UserLayout

__all__ = [
    "CommitRegression",
    "DEFAULT_TIER",
    "DEFAULT_TIMEOUT_S",
    "EXEMPT_SCOPES",
    "PRUNE_BOX_EXEMPTION_RATE",
    "RegressionError",
    "RegressionFinding",
    "RegressionReport",
    "SCHEMA",
    "SOURCE",
    "UntestedChange",
    "VALID_TIERS",
    "check_ci",
    "check_ci_regressions",
    "is_config_file",
    "is_doc_file",
    "is_fix_commit",
    "is_python_test_file",
    "is_source_file",
    "is_test_file",
    "parse_fix_subject",
]

SCHEMA = "aegis.regression/v1"
SOURCE = "aegis check --ci"
DEFAULT_TIER = "warning"
VALID_TIERS = ("warning", "gate")
PRUNE_BOX_EXEMPTION_RATE = 0.25
DEFAULT_TIMEOUT_S = 120.0
_GIT_TIMEOUT_S = 60.0
_USER_CONFIG_LIMIT = 64 * 1024

EXEMPT_SCOPES = frozenset({"ci", "build", "docs", "deps", "release", "chore", "tests", "test", "doc"})

_DOC_DIRS = frozenset({"docs", "doc"})
_DOC_EXTENSIONS = frozenset({
    ".md", ".rst", ".txt", ".adoc", ".html", ".pdf", ".png", ".svg", ".jpg", ".jpeg", ".gif",
})
_DOC_BASENAMES = frozenset({
    "readme", "changelog", "changes", "history", "license", "copying", "authors",
    "contributors", "code_of_conduct", "security", "notice", "patents",
})
_CONFIG_EXTENSIONS = frozenset({
    ".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".conf", ".lock", ".env", ".pth",
})
_CONFIG_BASENAMES = frozenset({
    "makefile", "dockerfile", "containerfile", "justfile", "vagrantfile", "procfile",
    "manifest.in", "requirements.txt", "requirements-dev.txt", "pipfile", "tox.ini",
    "setup.cfg", "pyproject.toml", "pytest.ini", ".pytest.ini", "pytest.toml",
    ".pytest.toml", "allowed_signers", "codeowners", "conftest.py", "sitecustomize.py",
})

_CONVENTIONAL_RE = re.compile(r"\A([a-zA-Z]+)(?:\(([^)]*)\))?(!)?:\s*(.*)\Z")
_FIXES_LINE_RE = re.compile(r"^[ \t]*(?:fixes|closes)[ \t]*:[ \t]*(\S.*)$", re.IGNORECASE | re.MULTILINE)
_NO_TEST_LINE_RE = re.compile(r"^[ \t]*aegis-no-test[ \t]*:[ \t]*(\S.*)$", re.IGNORECASE | re.MULTILINE)
_PYTHON_FLAGS = ("--check-hash-based-pycs", "always")
_PYTEST_FLAGS = ("-p", "no:cacheprovider", "-o", "addopts=")


class RegressionError(AegisError):
    """The commit range or repository trees cannot be read."""


# ── Path & commit classification ─────────────────────────────────────────────


def is_test_file(path: str) -> bool:
    """Whether ``path`` is a test file (``aegis_core.match.is_test_path``)."""
    if not isinstance(path, str) or not path:
        return False
    return match.is_test_path(path)


def is_python_test_file(path: str) -> bool:
    """Whether ``path`` is a runnable Python test module (excludes ``conftest.py``)."""
    if not isinstance(path, str) or not path:
        return False
    rel = match.normalize_path(path)
    base = posixpath.basename(rel)
    return match.is_test_path(rel) and rel.endswith(".py") and base != "conftest.py" and base != "__init__.py"


def is_doc_file(path: str) -> bool:
    """Whether ``path`` is documentation (``docs/``, markdown/text files, README/LICENSE/etc.)."""
    if not isinstance(path, str) or not path:
        return False
    rel = match.normalize_path(path)
    parts = [p.lower() for p in rel.split("/") if p]
    if not parts:
        return False
    if any(p in _DOC_DIRS for p in parts[:-1]):
        return True
    base = parts[-1]
    stem, ext = posixpath.splitext(base)
    if stem in _DOC_BASENAMES or base in _DOC_BASENAMES:
        return True
    if ext in _DOC_EXTENSIONS:
        return True
    return False


def is_config_file(path: str) -> bool:
    """Whether ``path`` is a governance, CI, build, or configuration file."""
    if not isinstance(path, str) or not path:
        return False
    rel = match.normalize_path(path)
    if governance.category_of(rel) is not None:
        return True
    parts = [p for p in rel.split("/") if p]
    if not parts:
        return False
    if any(p.startswith(".") for p in parts):
        return True
    base = parts[-1].lower()
    if base in _CONFIG_BASENAMES:
        return True
    _, ext = posixpath.splitext(base)
    return ext in _CONFIG_EXTENSIONS


def is_source_file(path: str) -> bool:
    """Whether ``path`` is a non-test, non-doc, non-config source file."""
    if not isinstance(path, str) or not path:
        return False
    return not is_test_file(path) and not is_doc_file(path) and not is_config_file(path)


def parse_fix_subject(subject: str) -> Tuple[bool, Optional[str]]:
    """Parse a commit subject line into ``(is_non_exempt_fix_subject, normalized_scope)``."""
    first = (subject or "").splitlines()[0].strip() if subject else ""
    found = _CONVENTIONAL_RE.match(first)
    if not found:
        return False, None
    kind = found.group(1).strip().lower()
    raw_scope = found.group(2)
    scope = raw_scope.strip().lower() if raw_scope is not None and raw_scope.strip() else None
    if kind != "fix":
        return False, scope
    if scope in EXEMPT_SCOPES:
        return False, scope
    return True, scope


def is_fix_commit(subject: str, fixes_trailers: Sequence[str], changed_files: Sequence[str]) -> bool:
    """Whether a non-merge commit requires a fail-to-pass regression test (v4.3 spec §3 T5)."""
    fix_subject, scope = parse_fix_subject(subject)
    if scope in EXEMPT_SCOPES:
        return False
    has_fix_signal = fix_subject or any(str(t).strip() for t in fixes_trailers)
    if not has_fix_signal:
        return False
    return any(is_source_file(path) for path in changed_files)


# ── Records & report ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RegressionFinding:
    """One unapproved fail-to-pass regression finding."""

    code: str
    commit: str
    path: str
    message: str
    no_test_reason: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "code": self.code,
            "commit": self.commit,
            "path": self.path,
            "message": self.message,
        }
        if self.no_test_reason is not None:
            out["no_test_reason"] = self.no_test_reason
        return out


@dataclass(frozen=True)
class CommitRegression:
    """The T5 evaluation of one fix commit in ``merge-base(base, head)..head``."""

    commit: str
    subject: str
    status: str  # "passed" | "failed" | "exempted"
    reason: str  # "ok" | "no_test_changes" | "passed_on_base" | "failed_on_head" | "collection_error_on_base" | "no_tests_collected" | "exempted"
    failed_on_base: bool
    passed_on_head: bool
    fail_to_pass_tests: Tuple[str, ...] = ()
    source_files: Tuple[str, ...] = ()
    test_files: Tuple[str, ...] = ()
    fixes: Tuple[str, ...] = ()
    no_test_reason: Optional[str] = None
    exempted: bool = False
    approval: Optional[Any] = None

    @property
    def passed(self) -> bool:
        return self.status in ("passed", "exempted")

    def as_dict(self, workspace: Any = None) -> Dict[str, Any]:
        return {
            "commit": self.commit,
            "subject": self.subject,
            "status": self.status,
            "reason": self.reason,
            "passed": self.passed,
            "failed_on_base": self.failed_on_base,
            "passed_on_head": self.passed_on_head,
            "fail_to_pass_tests": list(self.fail_to_pass_tests),
            "source_files": list(self.source_files),
            "test_files": list(self.test_files),
            "fixes": list(self.fixes),
            "no_test_reason": self.no_test_reason,
            "exempted": self.exempted,
            "approval": None if self.approval is None else self.approval.as_dict(workspace),
        }


@dataclass(frozen=True)
class UntestedChange:
    """A non-fix commit that changed source files without changing any test file."""

    commit: str
    subject: str
    source_files: Tuple[str, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "commit": self.commit,
            "subject": self.subject,
            "source_files": list(self.source_files),
        }


@dataclass(frozen=True)
class RegressionReport:
    """Full T5 report over ``merge-base(base, head)..head``."""

    base: str
    head: str
    merge_base: str
    tier: str = DEFAULT_TIER
    commits: Tuple[CommitRegression, ...] = ()
    findings: Tuple[RegressionFinding, ...] = ()
    untested_changes: Tuple[UntestedChange, ...] = ()
    approval: Optional[Any] = None

    @property
    def total_fix_commits(self) -> int:
        return len(self.commits)

    @property
    def fix_commits(self) -> Tuple[CommitRegression, ...]:
        return self.commits

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.commits if c.status == "passed")

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.commits if c.status == "failed")

    @property
    def exempted_count(self) -> int:
        return sum(1 for c in self.commits if c.exempted)

    @property
    def exemption_rate(self) -> float:
        if not self.commits:
            return 0.0
        return round(self.exempted_count / len(self.commits), 4)

    @property
    def prune_box_exceeded(self) -> bool:
        return self.exemption_rate > PRUNE_BOX_EXEMPTION_RATE

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.commits)

    @property
    def blocking(self) -> bool:
        return self.tier == "gate" and not self.passed

    @property
    def status(self) -> str:
        if self.passed:
            return "pass"
        return "fail" if self.tier == "gate" else "warning"

    def as_dict(self, workspace: Any = None) -> Dict[str, Any]:
        return {
            "schema": SCHEMA,
            "tier": self.tier,
            "status": self.status,
            "passed": self.passed,
            "blocking": self.blocking,
            "total_fix_commits": self.total_fix_commits,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "exempted_count": self.exempted_count,
            "exemption_rate": self.exemption_rate,
            "prune_box_exceeded": self.prune_box_exceeded,
            "commits": [c.as_dict(workspace) for c in self.commits],
            "findings": [f.as_dict() for f in self.findings],
            "untested_changes": [u.as_dict() for u in self.untested_changes],
            "approval": None if self.approval is None else self.approval.as_dict(workspace),
        }


# ── User-scope tier configuration ────────────────────────────────────────────


def _within(path: Path, root: Path) -> bool:
    try:
        resolved, base = path.resolve(), root.resolve()
        return os.path.commonpath([str(resolved), str(base)]) == str(base)
    except (OSError, ValueError, RuntimeError):
        return False


def _user_regression_tier(root: str) -> str:
    """Read ``regression.tier`` from user-scope ``~/.aegis/config.json`` (never from the repo)."""
    layout = UserLayout.current()
    if layout is None:
        return DEFAULT_TIER
    path = layout.config_file
    try:
        if not path.is_file() or _within(path, Path(root)):
            return DEFAULT_TIER
        with open(path, "rb") as handle:
            raw = handle.read(_USER_CONFIG_LIMIT + 1)
        if len(raw) > _USER_CONFIG_LIMIT:
            return DEFAULT_TIER
        data = json.loads(raw.decode("utf-8-sig"))
    except (OSError, ValueError):
        return DEFAULT_TIER
    reg = data.get("regression") if isinstance(data, dict) else None
    tier = reg.get("tier") if isinstance(reg, dict) else None
    if isinstance(tier, str) and tier.strip().lower() in VALID_TIERS:
        return tier.strip().lower()
    return DEFAULT_TIER


# ── Git plumbing helpers ─────────────────────────────────────────────────────


def _git_run(cwd: str, args: Sequence[str], stdin: Optional[bytes] = None) -> bytes:
    try:
        res = gitsafe.run(list(args), cwd, timeout=_GIT_TIMEOUT_S, stdin=stdin)
    except gitsafe.GitError as exc:
        raise RegressionError(str(exc)) from exc
    if res.returncode != 0:
        detail = " ".join(res.stderr.decode("utf-8", "replace").split())[:200]
        raise RegressionError(f"git {args[0]} failed: {detail}")
    return res.stdout


def _blob_oid(data: bytes, oid_length: int) -> str:
    digest = hashlib.sha256 if oid_length == 64 else hashlib.sha1
    return digest(b"blob %d\0" % len(data) + data).hexdigest()


def _tree_blobs(cwd: str, commit: str) -> Dict[str, Tuple[str, str]]:
    """``{path: (mode, oid)}`` of regular files in ``commit``'s tree."""
    out = _git_run(cwd, ["ls-tree", "-r", "-z", "--full-tree", commit])
    found: Dict[str, Tuple[str, str]] = {}
    for record in out.split(b"\0"):
        meta, _, raw_path = record.partition(b"\t")
        fields = meta.split()
        if len(fields) != 3 or not raw_path:
            continue
        mode, kind, oid = (f.decode("ascii", "replace") for f in fields)
        path = os.fsdecode(raw_path)
        if kind != "blob" or mode == "120000":
            continue
        found[path] = (mode, oid)
    return found


def _read_blobs(cwd: str, oids: Iterable[str]) -> Dict[str, bytes]:
    """Read blob contents via ``git cat-file --batch`` and verify each against its oid."""
    wanted = list(dict.fromkeys(oids))
    if not wanted:
        return {}
    out = _git_run(cwd, ["cat-file", "--batch"], stdin=("\n".join(wanted) + "\n").encode("ascii"))
    blobs: Dict[str, bytes] = {}
    position = 0
    for oid in wanted:
        end = out.find(b"\n", position)
        header = out[position:end].split() if end >= 0 else []
        if len(header) != 3 or header[0].decode("ascii", "replace") != oid or header[1] != b"blob" or not header[2].isdigit():
            raise RegressionError(f"git cannot read object {oid}")
        size = int(header[2])
        data = out[end + 1 : end + 1 + size]
        if len(data) != size or _blob_oid(data, len(oid)) != oid:
            raise RegressionError(f"git returned content for {oid} that does not match the object id")
        blobs[oid] = data
        position = end + 1 + size + 1
    return blobs


def _safe_relpath(path: str) -> Optional[str]:
    norm = posixpath.normpath(match.normalize_path(path))
    if not norm or norm == "." or norm == ".." or norm.startswith("../") or norm.startswith("/"):
        return None
    return norm


def _export_snapshot(
    destination: Path,
    tree_entries: Mapping[str, Tuple[str, str]],
    blobs: Mapping[str, bytes],
    overlay_entries: Optional[Mapping[str, Tuple[str, str]]] = None,
) -> None:
    """Write ``tree_entries`` (plus optional ``overlay_entries``) into ``destination``."""
    combined = dict(tree_entries)
    if overlay_entries:
        combined.update(overlay_entries)
    destination.mkdir(parents=True, exist_ok=True)
    for rel, (mode, oid) in combined.items():
        safe = _safe_relpath(rel)
        if not safe or oid not in blobs:
            continue
        target = destination.joinpath(*safe.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        mode_int = 0o755 if (mode == "100755" and os.name != "nt") else None
        atomic_write_bytes(target, blobs[oid], mode=mode_int)


@dataclass(frozen=True)
class _CommitMeta:
    oid: str
    parent: Optional[str]
    subject: str
    fixes: Tuple[str, ...]
    no_test_reason: Optional[str]
    changed_files: Tuple[str, ...]
    present_files: Tuple[str, ...]


def _commit_meta(cwd: str, oid: str, default_parent: str) -> _CommitMeta:
    fmt = "%P%x00%s%x00%(trailers:key=Fixes,valueonly)%x00%(trailers:key=Closes,valueonly)%x00%(trailers:key=Aegis-No-Test,valueonly)%x00%B"
    raw = _git_run(cwd, ["log", "-1", f"--format={fmt}", oid]).decode("utf-8", "replace")
    parts = raw.split("\0", 5)
    parents_str = parts[0].strip() if len(parts) > 0 else ""
    parent = parents_str.split()[0] if parents_str else default_parent
    subject = parts[1].strip() if len(parts) > 1 else ""
    fixes_trailer = parts[2].strip() if len(parts) > 2 else ""
    closes_trailer = parts[3].strip() if len(parts) > 3 else ""
    no_test_trailer = parts[4].strip() if len(parts) > 4 else ""
    body = parts[5] if len(parts) > 5 else ""

    fixes: List[str] = []
    for chunk in (fixes_trailer, closes_trailer):
        for line in chunk.splitlines():
            if line.strip() and line.strip() not in fixes:
                fixes.append(line.strip())
    body_after_subject = body.partition("\n")[2]
    for found in _FIXES_LINE_RE.findall(body_after_subject):
        val = found.strip()
        if val and val not in fixes:
            fixes.append(val)

    no_test: Optional[str] = None
    for line in no_test_trailer.splitlines():
        if line.strip():
            no_test = line.strip()
            break
    if no_test is None:
        matches_nt = _NO_TEST_LINE_RE.findall(body_after_subject)
        if matches_nt:
            no_test = matches_nt[-1].strip()

    diff_out = _git_run(cwd, ["diff-tree", "--no-commit-id", "-r", "-z", "--name-status", "--root", oid])
    fields = diff_out.split(b"\0")
    changed: List[str] = []
    present: List[str] = []
    idx = 0
    while idx + 1 < len(fields) and fields[idx]:
        status = fields[idx].decode("ascii", "replace")[:1]
        path = match.normalize_path(os.fsdecode(fields[idx + 1]))
        if path and path not in changed:
            changed.append(path)
        if status != "D" and path and path not in present:
            present.append(path)
        idx += 2

    return _CommitMeta(
        oid=oid,
        parent=parent,
        subject=subject,
        fixes=tuple(fixes),
        no_test_reason=no_test,
        changed_files=tuple(changed),
        present_files=tuple(present),
    )


# ── Hermetic pytest execution ────────────────────────────────────────────────


@dataclass(frozen=True)
class _PytestOutcome:
    exit_code: int
    timed_out: bool
    passed_ids: FrozenSet[str]
    failed_ids: FrozenSet[str]
    collection_errors: FrozenSet[str]


def _hermetic_env(home: Path, scratch: Path) -> Dict[str, str]:
    if os.name == "nt":
        system = os.environ.get("SystemRoot", r"C:\Windows")
        return {
            "PATH": rf"{system}\System32;{system}",
            "SystemRoot": system,
            "HOME": str(home),
            "USERPROFILE": str(home),
            "TEMP": str(scratch),
            "TMP": str(scratch),
        }
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "TMPDIR": str(scratch),
        "LC_ALL": "C",
    }


def _seed_pytest_site(home: Path, workspace: Path) -> None:
    """Expose the host interpreter's ``pytest`` site-packages inside the fake ``HOME`` via a
    ``.pth`` file without passing any ``PYTHON*`` environment variable."""
    spec = importlib.util.find_spec("pytest")
    if spec is None or not spec.origin:
        return
    site_dir = Path(spec.origin).resolve().parent.parent
    if _within(site_dir, workspace):
        return
    candidates: Set[Path] = set()
    pyver = f"python{sys.version_info[0]}.{sys.version_info[1]}"
    candidates.add(home / ".local" / "lib" / pyver / "site-packages")
    for scheme in ("posix_user", "nt_user", "osx_framework_user"):
        try:
            user_purelib = sysconfig.get_path("purelib", scheme, {"userbase": str(home / ".local")})
            if user_purelib:
                candidates.add(Path(user_purelib))
        except (KeyError, ValueError):
            continue
    for target_dir in candidates:
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(target_dir / "_aegis_pytest.pth", (str(site_dir) + "\n").encode("utf-8"))
        except OSError:
            continue


def _parse_junit(path: Path) -> Tuple[Set[str], Set[str], Set[str]]:
    """Return ``(passed_ids, failed_ids, collection_errors)`` from pytest's JUnit XML."""
    passed: Set[str] = set()
    failed: Set[str] = set()
    collection_errors: Set[str] = set()
    if not path.is_file():
        return passed, failed, collection_errors
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return passed, failed, collection_errors
    for case in root.iter("testcase"):
        classname = (case.get("classname") or "").strip()
        name = (case.get("name") or "").strip()
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        if error is not None and (not classname or error.get("message") == "collection failure"):
            collection_errors.add(name or classname or "<collection>")
            continue
        if not name:
            continue
        nodeid = f"{classname}::{name}" if classname else name
        if failure is not None or error is not None:
            failed.add(nodeid)
        elif skipped is None:
            passed.add(nodeid)
    return passed, failed, collection_errors


def _run_pytest_in_snapshot(
    snapshot: Path,
    test_files: Sequence[str],
    workspace: Path,
    scratch: Path,
    timeout: float,
) -> _PytestOutcome:
    home = scratch / "home"
    tmp = scratch / "tmp"
    junit = scratch / "junit.xml"
    output = scratch / "output.txt"
    home.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    _seed_pytest_site(home, workspace)
    env = _hermetic_env(home, tmp)
    argv = [
        sys.executable,
        *_PYTHON_FLAGS,
        "-m",
        "pytest",
        *_PYTEST_FLAGS,
        f"--junitxml={junit}",
        "--",
        *test_files,
    ]
    res = checkrun.run_tests(argv, snapshot, env, timeout, junit, output)
    passed, failed, col_errors = _parse_junit(junit)
    return _PytestOutcome(res.exit, res.timed_out, frozenset(passed), frozenset(failed), frozenset(col_errors))


# ── Main T5 check ────────────────────────────────────────────────────────────


def _find_branch_approval(root: str, base_commit: str, head_commit: str) -> Optional[human_gate.Approval]:
    try:
        found = human_gate.find_approval(root, head_commit, base_commit)
        if found is not None and found.valid:
            return found
    except (human_gate.HumanGateError, gitsafe.GitError):
        pass
    return None


def _evaluate_fix_commit(
    root: str,
    workspace: Path,
    meta: _CommitMeta,
    merge_commit: str,
    head_commit: str,
    tree_cache: Dict[str, Dict[str, Tuple[str, str]]],
    branch_approval: Optional[human_gate.Approval],
    timeout: float,
) -> Tuple[CommitRegression, Optional[RegressionFinding]]:
    source_files = tuple(p for p in meta.changed_files if is_source_file(p))
    test_files = tuple(p for p in meta.present_files if is_python_test_file(p))
    primary_path = (test_files[0] if test_files else (source_files[0] if source_files else ""))

    approval = branch_approval
    if approval is None:
        try:
            digest = human_gate.governance_tree_hash(root, meta.oid)
            cand = human_gate.verify_approval(root, meta.oid, digest, merge_commit)
            if cand.valid:
                approval = cand
        except (human_gate.HumanGateError, gitsafe.GitError):
            approval = None

    if not test_files:
        if approval is not None and approval.valid:
            return (
                CommitRegression(
                    commit=meta.oid,
                    subject=meta.subject,
                    status="exempted",
                    reason="exempted",
                    failed_on_base=False,
                    passed_on_head=False,
                    source_files=source_files,
                    test_files=test_files,
                    fixes=meta.fixes,
                    no_test_reason=meta.no_test_reason,
                    exempted=True,
                    approval=approval,
                ),
                None,
            )
        explanation = (
            f" (Aegis-No-Test: {meta.no_test_reason!r} is an explanation only; exemption requires human_gate approval)"
            if meta.no_test_reason
            else ""
        )
        finding = RegressionFinding(
            code="no_test_changes",
            commit=meta.oid,
            path=primary_path,
            message=f"fix commit {meta.oid[:10]} ({meta.subject}) modifies source without adding or updating a test{explanation}",
            no_test_reason=meta.no_test_reason,
        )
        return (
            CommitRegression(
                commit=meta.oid,
                subject=meta.subject,
                status="failed",
                reason="no_test_changes",
                failed_on_base=False,
                passed_on_head=False,
                source_files=source_files,
                test_files=test_files,
                fixes=meta.fixes,
                no_test_reason=meta.no_test_reason,
                exempted=False,
                approval=None,
            ),
            finding,
        )

    def get_tree(commit_oid: str) -> Dict[str, Tuple[str, str]]:
        if commit_oid not in tree_cache:
            tree_cache[commit_oid] = _tree_blobs(root, commit_oid)
        return tree_cache[commit_oid]

    base_tree = get_tree(merge_commit)
    commit_tree = get_tree(meta.oid)
    overlay = {path: commit_tree[path] for path in test_files if path in commit_tree}

    needed_oids: Set[str] = {oid for _mode, oid in base_tree.values()}
    needed_oids.update(oid for _mode, oid in commit_tree.values())
    if meta.parent and meta.parent != merge_commit:
        parent_tree = get_tree(meta.parent)
        needed_oids.update(oid for _mode, oid in parent_tree.values())
    else:
        parent_tree = base_tree
    blobs = _read_blobs(root, needed_oids)

    scratch = Path(tempfile.mkdtemp(prefix="aegis-regression-"))
    try:
        os.chmod(scratch, 0o700)
        head_snap = scratch / "head_snap"
        _export_snapshot(head_snap, commit_tree, blobs)
        head_run = _run_pytest_in_snapshot(head_snap, test_files, workspace, scratch / "head_run", timeout)

        base_snap = scratch / "base_snap"
        _export_snapshot(base_snap, base_tree, blobs, overlay_entries=overlay)
        base_run = _run_pytest_in_snapshot(base_snap, test_files, workspace, scratch / "base_run", timeout)

        if not (base_run.failed_ids & head_run.passed_ids) and parent_tree is not base_tree:
            parent_snap = scratch / "parent_snap"
            _export_snapshot(parent_snap, parent_tree, blobs, overlay_entries=overlay)
            parent_run = _run_pytest_in_snapshot(parent_snap, test_files, workspace, scratch / "parent_run", timeout)
            if parent_run.failed_ids & head_run.passed_ids:
                base_run = parent_run
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    passed_on_head = (
        head_run.exit_code == 0
        and not head_run.timed_out
        and bool(head_run.passed_ids)
        and not head_run.failed_ids
        and not head_run.collection_errors
    )
    fail_to_pass = sorted(base_run.failed_ids & head_run.passed_ids) if passed_on_head else []
    failed_on_base = bool(base_run.failed_ids) and not base_run.collection_errors

    if passed_on_head and fail_to_pass:
        return (
            CommitRegression(
                commit=meta.oid,
                subject=meta.subject,
                status="passed",
                reason="ok",
                failed_on_base=True,
                passed_on_head=True,
                fail_to_pass_tests=tuple(fail_to_pass),
                source_files=source_files,
                test_files=test_files,
                fixes=meta.fixes,
                no_test_reason=meta.no_test_reason,
                exempted=False,
                approval=None,
            ),
            None,
        )

    if approval is not None and approval.valid:
        return (
            CommitRegression(
                commit=meta.oid,
                subject=meta.subject,
                status="exempted",
                reason="exempted",
                failed_on_base=failed_on_base,
                passed_on_head=passed_on_head,
                fail_to_pass_tests=tuple(fail_to_pass),
                source_files=source_files,
                test_files=test_files,
                fixes=meta.fixes,
                no_test_reason=meta.no_test_reason,
                exempted=True,
                approval=approval,
            ),
            None,
        )

    if not head_run.passed_ids and not head_run.failed_ids and not head_run.collection_errors:
        reason = "no_tests_collected"
        detail = "no tests were collected from the changed test files"
    elif not passed_on_head:
        reason = "failed_on_head"
        detail = "the changed test files failed or errored on head"
    elif base_run.collection_errors and not base_run.failed_ids:
        reason = "collection_error_on_base"
        detail = "the changed test files failed collection on base instead of failing a test assertion"
    else:
        reason = "passed_on_base"
        detail = "no test failed on base and passed on head (tests passed on base too)"

    if meta.no_test_reason:
        detail += f" (Aegis-No-Test: {meta.no_test_reason!r} is an explanation only; exemption requires human_gate approval)"

    finding = RegressionFinding(
        code=reason,
        commit=meta.oid,
        path=primary_path,
        message=f"fix commit {meta.oid[:10]} ({meta.subject}): {detail}",
        no_test_reason=meta.no_test_reason,
    )
    return (
        CommitRegression(
            commit=meta.oid,
            subject=meta.subject,
            status="failed",
            reason=reason,
            failed_on_base=failed_on_base,
            passed_on_head=passed_on_head,
            fail_to_pass_tests=tuple(fail_to_pass),
            source_files=source_files,
            test_files=test_files,
            fixes=meta.fixes,
            no_test_reason=meta.no_test_reason,
            exempted=False,
            approval=None,
        ),
        finding,
    )


def check_ci_regressions(
    workspace: Any,
    base: str,
    head: str = "HEAD",
    *,
    tier: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> RegressionReport:
    """Evaluate T5 fail-to-pass regression discipline over ``merge-base(base, head)..head``."""
    root = workspace_root(workspace)
    workspace_path = Path(root).resolve()
    base_commit = gitsafe.resolve_commit(root, base)
    head_commit = gitsafe.resolve_commit(root, head)
    if not base_commit:
        raise RegressionError(f"cannot resolve the base {base!r} to a commit")
    if not head_commit:
        raise RegressionError(f"cannot resolve the head {head!r} to a commit")
    merge_commit = gitsafe.merge_base(root, base_commit, head_commit)
    if not merge_commit:
        raise RegressionError(f"{base!r} and {head!r} share no history (fetch with fetch-depth: 0)")

    effective_tier = (tier.strip().lower() if isinstance(tier, str) and tier.strip() else _user_regression_tier(root))
    if effective_tier not in VALID_TIERS:
        effective_tier = DEFAULT_TIER

    rev_out = _git_run(root, ["rev-list", "--no-merges", "--reverse", f"{merge_commit}..{head_commit}"])
    commit_oids = [oid for oid in rev_out.decode("ascii", "replace").split() if oid]

    commits_meta = [_commit_meta(root, oid, merge_commit) for oid in commit_oids]
    fix_metas: List[_CommitMeta] = []
    untested: List[UntestedChange] = []

    for meta in commits_meta:
        if is_fix_commit(meta.subject, meta.fixes, meta.changed_files):
            fix_metas.append(meta)
        else:
            src = tuple(p for p in meta.changed_files if is_source_file(p))
            tst = tuple(p for p in meta.changed_files if is_test_file(p))
            if src and not tst:
                untested.append(UntestedChange(commit=meta.oid, subject=meta.subject, source_files=src))

    if not fix_metas:
        return RegressionReport(
            base=base_commit,
            head=head_commit,
            merge_base=merge_commit,
            tier=effective_tier,
            commits=(),
            findings=(),
            untested_changes=tuple(untested),
            approval=None,
        )

    branch_approval = _find_branch_approval(root, base_commit, head_commit)
    tree_cache: Dict[str, Dict[str, Tuple[str, str]]] = {}
    evaluated: List[CommitRegression] = []
    findings: List[RegressionFinding] = []

    for meta in fix_metas:
        result, finding = _evaluate_fix_commit(
            root=root,
            workspace=workspace_path,
            meta=meta,
            merge_commit=merge_commit,
            head_commit=head_commit,
            tree_cache=tree_cache,
            branch_approval=branch_approval,
            timeout=timeout,
        )
        evaluated.append(result)
        if finding is not None:
            findings.append(finding)

    return RegressionReport(
        base=base_commit,
        head=head_commit,
        merge_base=merge_commit,
        tier=effective_tier,
        commits=tuple(evaluated),
        findings=tuple(findings),
        untested_changes=tuple(untested),
        approval=branch_approval,
    )


check_ci = check_ci_regressions
