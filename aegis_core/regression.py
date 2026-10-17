"""Regression discipline: git is the registry (v4.3 spec §3 T5)."""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util, os, posixpath, re, shutil, sys, sysconfig, tempfile, xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Set, Tuple

from aegis_core import checkrun, gitsafe, governance, human_gate, match, rule_integrity
from aegis_core.errors import AegisError
from aegis_core.rules import workspace_root
from aegis_core.storage import atomic_write_bytes
from aegis_core.workspace.layout import UserLayout

__all__ = [
    "CommitRegression", "DEFAULT_TIER", "DEFAULT_TIMEOUT_S", "EXEMPT_SCOPES", "PRUNE_BOX_EXEMPTION_RATE",
    "RegressionError", "RegressionFinding", "RegressionReport", "SCHEMA", "SOURCE", "UntestedChange",
    "VALID_TIERS", "check_ci", "check_ci_regressions", "is_config_file", "is_doc_file", "is_fix_commit",
    "is_python_test_file", "is_source_file", "is_test_file", "parse_fix_subject",
]

SCHEMA, SOURCE, DEFAULT_TIER = "aegis.regression/v1", "aegis check --ci", "warning"
VALID_TIERS = ("warning", "gate")
PRUNE_BOX_EXEMPTION_RATE, DEFAULT_TIMEOUT_S, _GIT_TIMEOUT_S = 0.25, 120.0, 60.0
EXEMPT_SCOPES = frozenset({"ci", "build", "docs", "deps", "release", "chore", "tests", "test", "doc"})
_DOC_DIRS = frozenset({"docs", "doc"})
_DOC_EXTENSIONS = frozenset({".md", ".rst", ".txt", ".adoc", ".html", ".pdf", ".png", ".svg", ".jpg", ".jpeg", ".gif"})
_DOC_BASENAMES = frozenset({"readme", "changelog", "changes", "history", "license", "copying", "authors", "contributors", "code_of_conduct", "security", "notice", "patents"})
_CONFIG_EXTENSIONS = frozenset({".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".conf", ".lock", ".env", ".pth"})
_CONFIG_BASENAMES = frozenset({
    "makefile", "dockerfile", "containerfile", "justfile", "vagrantfile", "procfile", "manifest.in",
    "requirements.txt", "requirements-dev.txt", "pipfile", "tox.ini", "setup.cfg", "pyproject.toml",
    "pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml", "allowed_signers", "codeowners", "conftest.py", "sitecustomize.py",
})
_CONVENTIONAL_RE = re.compile(r"\A([a-zA-Z]+)(?:\(([^)]*)\))?(!)?:\s*(.*)\Z")
_FIXES_LINE_RE = re.compile(r"^[ \t]*(?:fixes|closes)[ \t]*:[ \t]*(\S.*)$", re.IGNORECASE | re.MULTILINE)
_NO_TEST_LINE_RE = re.compile(r"^[ \t]*aegis-no-test[ \t]*:[ \t]*(\S.*)$", re.IGNORECASE | re.MULTILINE)
_PYTHON_FLAGS, _PYTEST_FLAGS = ("--check-hash-based-pycs", "always"), ("-p", "no:cacheprovider", "-o", "addopts=")

class RegressionError(AegisError):
    """The commit range or repository trees cannot be read."""

def is_test_file(path: str) -> bool:
    return bool(isinstance(path, str) and path and match.is_test_path(path))

def is_python_test_file(path: str) -> bool:
    if not isinstance(path, str) or not path: return False
    rel = match.normalize_path(path)
    return match.is_test_path(rel) and rel.endswith(".py") and posixpath.basename(rel) not in ("conftest.py", "__init__.py")

def is_doc_file(path: str) -> bool:
    if not isinstance(path, str) or not path: return False
    parts = [p.lower() for p in match.normalize_path(path).split("/") if p]
    if not parts: return False
    stem, ext = posixpath.splitext(parts[-1])
    return any(p in _DOC_DIRS for p in parts[:-1]) or stem in _DOC_BASENAMES or parts[-1] in _DOC_BASENAMES or ext in _DOC_EXTENSIONS

def is_config_file(path: str) -> bool:
    if not isinstance(path, str) or not path: return False
    rel = match.normalize_path(path)
    parts = [p for p in rel.split("/") if p]
    if not parts: return False
    base = parts[-1].lower()
    return governance.category_of(rel) is not None or any(p.startswith(".") for p in parts) or base in _CONFIG_BASENAMES or posixpath.splitext(base)[1] in _CONFIG_EXTENSIONS

def is_source_file(path: str) -> bool:
    return bool(isinstance(path, str) and path and not is_test_file(path) and not is_doc_file(path) and not is_config_file(path))

def parse_fix_subject(subject: str) -> Tuple[bool, Optional[str]]:
    found = _CONVENTIONAL_RE.match((subject or "").splitlines()[0].strip() if subject else "")
    if not found: return False, None
    kind, raw_scope = found.group(1).strip().lower(), found.group(2)
    scope = raw_scope.strip().lower() if raw_scope is not None and raw_scope.strip() else None
    return (kind == "fix" and scope not in EXEMPT_SCOPES), scope

def is_fix_commit(subject: str, fixes_trailers: Sequence[str], changed_files: Sequence[str]) -> bool:
    fix_subject, scope = parse_fix_subject(subject)
    return scope not in EXEMPT_SCOPES and (fix_subject or any(str(t).strip() for t in fixes_trailers)) and any(is_source_file(p) for p in changed_files)

@dataclass(frozen=True)
class RegressionFinding:
    code: str; commit: str; path: str; message: str; no_test_reason: Optional[str] = None
    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"code": self.code, "commit": self.commit, "path": self.path, "message": self.message}
        if self.no_test_reason is not None: out["no_test_reason"] = self.no_test_reason
        return out

@dataclass(frozen=True)
class CommitRegression:
    commit: str; subject: str; status: str; reason: str; failed_on_base: bool; passed_on_head: bool
    fail_to_pass_tests: Tuple[str, ...] = (); source_files: Tuple[str, ...] = (); test_files: Tuple[str, ...] = ()
    fixes: Tuple[str, ...] = (); no_test_reason: Optional[str] = None; exempted: bool = False; approval: Optional[Any] = None
    passed = property(lambda self: self.status in ("passed", "exempted"))

    def as_dict(self, workspace: Any = None) -> Dict[str, Any]:
        return {"commit": self.commit, "subject": self.subject, "status": self.status, "reason": self.reason, "passed": self.passed,
                "failed_on_base": self.failed_on_base, "passed_on_head": self.passed_on_head, "fail_to_pass_tests": list(self.fail_to_pass_tests),
                "source_files": list(self.source_files), "test_files": list(self.test_files), "fixes": list(self.fixes),
                "no_test_reason": self.no_test_reason, "exempted": self.exempted, "approval": None if self.approval is None else self.approval.as_dict(workspace)}

class UntestedChange(NamedTuple):
    commit: str; subject: str; source_files: Tuple[str, ...]
    def as_dict(self) -> Dict[str, Any]: return {"commit": self.commit, "subject": self.subject, "source_files": list(self.source_files)}

@dataclass(frozen=True)
class RegressionReport:
    base: str; head: str; merge_base: str; tier: str = DEFAULT_TIER
    commits: Tuple[CommitRegression, ...] = (); findings: Tuple[RegressionFinding, ...] = ()
    untested_changes: Tuple[UntestedChange, ...] = (); approval: Optional[Any] = None
    total_fix_commits = property(lambda self: len(self.commits))
    fix_commits = property(lambda self: self.commits)
    passed_count = property(lambda self: sum(1 for c in self.commits if c.status == "passed"))
    failed_count = property(lambda self: sum(1 for c in self.commits if c.status == "failed"))
    exempted_count = property(lambda self: sum(1 for c in self.commits if c.exempted))
    exemption_rate = property(lambda self: round(self.exempted_count / len(self.commits), 4) if self.commits else 0.0)
    prune_box_exceeded = property(lambda self: self.exemption_rate > PRUNE_BOX_EXEMPTION_RATE)
    passed = property(lambda self: all(c.passed for c in self.commits))
    blocking = property(lambda self: self.tier == "gate" and not self.passed)
    status = property(lambda self: "pass" if self.passed else ("fail" if self.tier == "gate" else "warning"))

    def as_dict(self, workspace: Any = None) -> Dict[str, Any]:
        return {"schema": SCHEMA, "tier": self.tier, "status": self.status, "passed": self.passed, "blocking": self.blocking,
                "total_fix_commits": self.total_fix_commits, "passed_count": self.passed_count, "failed_count": self.failed_count,
                "exempted_count": self.exempted_count, "exemption_rate": self.exemption_rate, "prune_box_exceeded": self.prune_box_exceeded,
                "commits": [c.as_dict(workspace) for c in self.commits], "findings": [f.as_dict() for f in self.findings],
                "untested_changes": [u.as_dict() for u in self.untested_changes], "approval": None if self.approval is None else self.approval.as_dict(workspace)}

def _user_regression_tier(root: str) -> str:
    layout = UserLayout.current()
    data = checkrun._read_user_config(layout.config_file, Path(root)) if layout else None
    reg = data.get("regression") if isinstance(data, dict) else None
    tier = reg.get("tier") if isinstance(reg, dict) else None
    return tier.strip().lower() if isinstance(tier, str) and tier.strip().lower() in VALID_TIERS else DEFAULT_TIER

def _git_run(cwd: str, args: Sequence[str], stdin: Optional[bytes] = None) -> bytes:
    try: res = gitsafe.run(list(args), cwd, timeout=_GIT_TIMEOUT_S, stdin=stdin)
    except gitsafe.GitError as exc: raise RegressionError(str(exc)) from exc
    if res.returncode != 0: raise RegressionError(f"git {args[0]} failed: {' '.join(res.stderr.decode('utf-8', 'replace').split())[:200]}")
    return res.stdout

def _tree_blobs(cwd: str, commit: str) -> Dict[str, Tuple[str, str]]:
    found: Dict[str, Tuple[str, str]] = {}
    for record in _git_run(cwd, ["ls-tree", "-r", "-z", "--full-tree", commit]).split(b"\0"):
        meta, _, raw_path = record.partition(b"\t")
        fields = meta.split()
        if len(fields) == 3 and raw_path:
            mode, kind, oid = (f.decode("ascii", "replace") for f in fields)
            if kind == "blob" and mode != "120000": found[os.fsdecode(raw_path)] = (mode, oid)
    return found

def _read_blobs(cwd: str, oids: Iterable[str]) -> Dict[str, bytes]:
    try: return rule_integrity._read_blobs(cwd, oids)
    except rule_integrity.IntegrityError as exc: raise RegressionError(str(exc)) from exc

def _export_snapshot(destination: Path, tree_entries: Mapping[str, Tuple[str, str]], blobs: Mapping[str, bytes], overlay_entries: Optional[Mapping[str, Tuple[str, str]]] = None) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for rel, (mode, oid) in {**tree_entries, **(overlay_entries or {})}.items():
        norm = posixpath.normpath(match.normalize_path(rel))
        if not norm or norm in (".", "..") or norm.startswith(("../", "/")) or oid not in blobs: continue
        target = destination.joinpath(*norm.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, blobs[oid], mode=0o755 if (mode == "100755" and os.name != "nt") else None)

class _CommitMeta(NamedTuple):
    oid: str; parent: Optional[str]; subject: str; fixes: Tuple[str, ...]
    no_test_reason: Optional[str]; changed_files: Tuple[str, ...]; present_files: Tuple[str, ...]

def _commit_meta(cwd: str, oid: str, default_parent: str) -> _CommitMeta:
    fmt = "%P%x00%s%x00%(trailers:key=Fixes,valueonly)%x00%(trailers:key=Closes,valueonly)%x00%(trailers:key=Aegis-No-Test,valueonly)%x00%B"
    parts = (_git_run(cwd, ["log", "-1", f"--format={fmt}", oid]).decode("utf-8", "replace").split("\0", 5) + [""] * 6)[:6]
    parent = parts[0].split()[0] if parts[0].strip() else default_parent
    subject, body_after = parts[1].strip(), parts[5].partition("\n")[2]
    fixes = list(dict.fromkeys(ln.strip() for ln in [*parts[2].splitlines(), *parts[3].splitlines(), *_FIXES_LINE_RE.findall(body_after)] if ln.strip()))
    nt_lines = [ln.strip() for ln in parts[4].splitlines() if ln.strip()]
    no_test = nt_lines[0] if nt_lines else ((_NO_TEST_LINE_RE.findall(body_after) or [None])[-1])
    fields = _git_run(cwd, ["diff-tree", "--no-commit-id", "-r", "-z", "--name-status", "--root", oid]).split(b"\0")
    changed, present = [], []
    for idx in range(0, len(fields) - 1, 2):
        if not fields[idx]: break
        status, path = fields[idx].decode("ascii", "replace")[:1], match.normalize_path(os.fsdecode(fields[idx + 1]))
        if path and path not in changed: changed.append(path)
        if status != "D" and path and path not in present: present.append(path)
    return _CommitMeta(oid, parent, subject, tuple(fixes), no_test.strip() if isinstance(no_test, str) else None, tuple(changed), tuple(present))

class _PytestOutcome(NamedTuple):
    exit_code: int; timed_out: bool; passed_ids: FrozenSet[str]; failed_ids: FrozenSet[str]; collection_errors: FrozenSet[str]

def _seed_pytest_site(home: Path, workspace: Path) -> None:
    spec = importlib.util.find_spec("pytest")
    if spec is None or not spec.origin: return
    site_dir = Path(spec.origin).resolve().parent.parent
    if rule_integrity._within(site_dir, workspace): return
    candidates: Set[Path] = {home / ".local" / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "site-packages"}
    for scheme in ("posix_user", "nt_user", "osx_framework_user"):
        try:
            purelib = sysconfig.get_path("purelib", scheme, {"userbase": str(home / ".local")})
            if purelib: candidates.add(Path(purelib))
        except (KeyError, ValueError): continue
    for target_dir in candidates:
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(target_dir / "_aegis_pytest.pth", (str(site_dir) + "\n").encode("utf-8"))
        except OSError: continue

def _parse_junit(path: Path) -> Tuple[Set[str], Set[str], Set[str]]:
    passed, failed, col_errors = set(), set(), set()
    if not path.is_file(): return passed, failed, col_errors
    try: root = ET.parse(path).getroot()
    except (OSError, ET.ParseError): return passed, failed, col_errors
    for case in root.iter("testcase"):
        cls, name, err = (case.get("classname") or "").strip(), (case.get("name") or "").strip(), case.find("error")
        if err is not None and (not cls or err.get("message") == "collection failure"):
            col_errors.add(name or cls or "<collection>")
        elif name and (case.find("failure") is not None or err is not None or case.find("skipped") is None):
            (failed if (case.find("failure") is not None or err is not None) else passed).add(f"{cls}::{name}" if cls else name)
    return passed, failed, col_errors

def _run_pytest_in_snapshot(snapshot: Path, test_files: Sequence[str], workspace: Path, scratch: Path, timeout: float) -> _PytestOutcome:
    home, tmp, junit, output = scratch / "home", scratch / "tmp", scratch / "junit.xml", scratch / "output.txt"
    home.mkdir(parents=True, exist_ok=True); tmp.mkdir(parents=True, exist_ok=True)
    _seed_pytest_site(home, workspace)
    argv = [sys.executable, *_PYTHON_FLAGS, "-m", "pytest", *_PYTEST_FLAGS, f"--junitxml={junit}", "--", *test_files]
    res = checkrun.run_tests(argv, snapshot, checkrun._hermetic_env(home, tmp), timeout, junit, output)
    passed, failed, col_errors = _parse_junit(junit)
    return _PytestOutcome(res.exit, res.timed_out, frozenset(passed), frozenset(failed), frozenset(col_errors))

def _find_branch_approval(root: str, base_commit: str, head_commit: str) -> Optional[human_gate.Approval]:
    try:
        found = human_gate.find_approval(root, head_commit, base_commit)
        return found if (found is not None and found.valid) else None
    except (human_gate.HumanGateError, gitsafe.GitError): return None

def _evaluate_fix_commit(
    root: str, workspace: Path, meta: _CommitMeta, merge_commit: str,
    tree_cache: Dict[str, Dict[str, Tuple[str, str]]], branch_approval: Optional[human_gate.Approval], timeout: float,
) -> Tuple[CommitRegression, Optional[RegressionFinding]]:
    source_files = tuple(p for p in meta.changed_files if is_source_file(p))
    test_files = tuple(p for p in meta.present_files if is_python_test_file(p))
    primary_path = test_files[0] if test_files else (source_files[0] if source_files else "")
    approval = branch_approval
    if approval is None:
        try:
            cand = human_gate.verify_approval(root, meta.oid, human_gate.governance_tree_hash(root, meta.oid), merge_commit)
            approval = cand if cand.valid else None
        except (human_gate.HumanGateError, gitsafe.GitError): approval = None

    def _make(status: str, reason: str, f_base: bool = False, p_head: bool = False, f2p: Tuple[str, ...] = (), exempted: bool = False, app: Any = None) -> CommitRegression:
        return CommitRegression(meta.oid, meta.subject, status, reason, f_base, p_head, f2p, source_files, test_files, meta.fixes, meta.no_test_reason, exempted, app)

    nt_note = f" (Aegis-No-Test: {meta.no_test_reason!r} is an explanation only; exemption requires human_gate approval)" if meta.no_test_reason else ""
    if not test_files:
        if approval is not None and approval.valid: return _make("exempted", "exempted", exempted=True, app=approval), None
        msg = f"fix commit {meta.oid[:10]} ({meta.subject}) modifies source without adding or updating a test{nt_note}"
        return _make("failed", "no_test_changes"), RegressionFinding("no_test_changes", meta.oid, primary_path, msg, meta.no_test_reason)

    get_tree = lambda c_oid: tree_cache.setdefault(c_oid, _tree_blobs(root, c_oid))
    base_tree, commit_tree = get_tree(merge_commit), get_tree(meta.oid)
    parent_tree = get_tree(meta.parent) if (meta.parent and meta.parent != merge_commit) else base_tree
    overlay = {p: commit_tree[p] for p in test_files if p in commit_tree}
    blobs = _read_blobs(root, {oid for t in (base_tree, commit_tree, parent_tree) for _m, oid in t.values()})

    scratch = Path(tempfile.mkdtemp(prefix="aegis-regression-"))
    try:
        os.chmod(scratch, 0o700)
        _export_snapshot(scratch / "head_snap", commit_tree, blobs)
        head_run = _run_pytest_in_snapshot(scratch / "head_snap", test_files, workspace, scratch / "head_run", timeout)
        _export_snapshot(scratch / "base_snap", base_tree, blobs, overlay)
        base_run = _run_pytest_in_snapshot(scratch / "base_snap", test_files, workspace, scratch / "base_run", timeout)
        if not (base_run.failed_ids & head_run.passed_ids) and parent_tree is not base_tree:
            _export_snapshot(scratch / "parent_snap", parent_tree, blobs, overlay)
            parent_run = _run_pytest_in_snapshot(scratch / "parent_snap", test_files, workspace, scratch / "parent_run", timeout)
            if parent_run.failed_ids & head_run.passed_ids: base_run = parent_run
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    passed_on_head = head_run.exit_code == 0 and not head_run.timed_out and bool(head_run.passed_ids) and not head_run.failed_ids and not head_run.collection_errors
    f2p = tuple(sorted(base_run.failed_ids & head_run.passed_ids)) if passed_on_head else ()
    failed_on_base = bool(base_run.failed_ids) and not base_run.collection_errors

    if passed_on_head and f2p: return _make("passed", "ok", True, True, f2p), None
    if approval is not None and approval.valid: return _make("exempted", "exempted", failed_on_base, passed_on_head, f2p, True, approval), None

    if not head_run.passed_ids and not head_run.failed_ids and not head_run.collection_errors:
        reason, detail = "no_tests_collected", "no tests were collected from the changed test files"
    elif not passed_on_head:
        reason, detail = "failed_on_head", "the changed test files failed or errored on head"
    elif base_run.collection_errors and not base_run.failed_ids:
        reason, detail = "collection_error_on_base", "the changed test files failed collection on base instead of failing a test assertion"
    else:
        reason, detail = "passed_on_base", "no test failed on base and passed on head (tests passed on base too)"
    finding = RegressionFinding(reason, meta.oid, primary_path, f"fix commit {meta.oid[:10]} ({meta.subject}): {detail}{nt_note}", meta.no_test_reason)
    return _make("failed", reason, failed_on_base, passed_on_head, f2p), finding

def check_ci_regressions(workspace: Any, base: str, head: str = "HEAD", *, tier: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT_S) -> RegressionReport:
    root, workspace_path = workspace_root(workspace), Path(workspace_root(workspace)).resolve()
    base_commit, head_commit = gitsafe.resolve_commit(root, base), gitsafe.resolve_commit(root, head)
    if not base_commit: raise RegressionError(f"cannot resolve the base {base!r} to a commit")
    if not head_commit: raise RegressionError(f"cannot resolve the head {head!r} to a commit")
    merge_commit = gitsafe.merge_base(root, base_commit, head_commit)
    if not merge_commit: raise RegressionError(f"{base!r} and {head!r} share no history (fetch with fetch-depth: 0)")

    effective_tier = tier.strip().lower() if isinstance(tier, str) and tier.strip() else _user_regression_tier(root)
    if effective_tier not in VALID_TIERS: effective_tier = DEFAULT_TIER

    rev_out = _git_run(root, ["rev-list", "--no-merges", "--reverse", f"{merge_commit}..{head_commit}"])
    fix_metas, untested = [], []
    for oid in (o for o in rev_out.decode("ascii", "replace").split() if o):
        meta = _commit_meta(root, oid, merge_commit)
        if is_fix_commit(meta.subject, meta.fixes, meta.changed_files):
            fix_metas.append(meta)
        else:
            src = tuple(p for p in meta.changed_files if is_source_file(p))
            if src and not any(is_test_file(p) for p in meta.changed_files):
                untested.append(UntestedChange(meta.oid, meta.subject, src))
    if not fix_metas:
        return RegressionReport(base_commit, head_commit, merge_commit, effective_tier, (), (), tuple(untested), None)

    branch_approval = _find_branch_approval(root, base_commit, head_commit)
    tree_cache: Dict[str, Dict[str, Tuple[str, str]]] = {}
    evaluated, findings = [], []
    for meta in fix_metas:
        res, finding = _evaluate_fix_commit(root, workspace_path, meta, merge_commit, tree_cache, branch_approval, timeout)
        evaluated.append(res)
        if finding is not None: findings.append(finding)
    return RegressionReport(base_commit, head_commit, merge_commit, effective_tier, tuple(evaluated), tuple(findings), tuple(untested), branch_approval)

check_ci = check_ci_regressions
