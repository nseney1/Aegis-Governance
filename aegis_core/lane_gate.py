"""The post-lane gate, ``aegis check --lane`` (v4.1 spec §1, ADR 0005 AD-7).

**Range.** ``merge-base(<base>, HEAD)..HEAD`` through ``gitsafe.diff_entries``, which
lists every path: additions, deletions, type changes, both sides of a move (git's
rename detection is off) and gitlinks. ``<base>`` is the caller's or
``gitsafe.resolve_base_ref()``. A shallow clone, a base that does not resolve and a
base with no history in common with HEAD all fail with ``needs history: fetch with
fetch-depth 0``: a cut history can hide the true merge base. Only committed changes
count.

**Allowed set and provenance.** Self-attested by default: the lane's live lease (or
``paths``, given on the command line) plus ``shared`` from the working tree's
``.aegis/team.json``. With ``base_policy``, ``lanes[<lane>]`` and ``shared`` come from
team.json at the base tip (never the merge base, never the candidate) and the lane's
paths cannot be given. Each input's source is recorded (``lease``, ``cli``,
``worktree`` or ``base@<sha>``); the label is ``witnessed: base policy`` only when
every input came from base. team.json is read at the repository's top level, where
``team.load_team_at`` reads it.

**Containment.** Every listed path must match an allowed glob, with the one matcher's
semantics (``shared: ["CHANGELOG.md"]`` also admits ``docs/CHANGELOG.md``).
``.aegis/**`` and ``.github/workflows/**`` (and those directories themselves, case
folded, as a case-insensitive checkout sees them) are allowed only by a glob read
from base.

**Test integrity**, for Python test files (``match.is_test_path`` and ``.py``) and
pytest's config files; other test files are listed as not checked. Each finding has
a stable id, the first 12 hex characters of sha256(``kind|path|name``):

- ``removed``: a test id (``name``, ``Class::name``, ``Outer::Inner::name``: functions
  and methods named ``test*``, as pytest's default discovery collects them) present
  at the merge base and not collected at HEAD. A deleted, moved or symlinked file
  loses all of its ids; so does a class that gains ``__init__`` or ``__new__``, a
  test name rebound or deleted after its ``def``, and a test made a fixture
  (``@pytest.fixture``), which pytest does not collect.
- ``skip``: an occurrence introduced at HEAD, per scope, of ``pytest.mark.skip``,
  ``skipif`` or ``xfail``; ``unittest.skip``, ``skipIf``, ``skipUnless`` or
  ``expectedFailure``; a module- or class-level ``pytestmark`` or ``__test__``, or
  either set as an attribute (``test_x.__test__ = False``); ``pytest.skip``,
  ``pytest.xfail`` or ``pytest.importorskip``; ``.skipTest``; ``unittest.SkipTest``;
  or ``pytest.exit`` and ``os._exit``, which end the run early. Import aliases (star
  imports from pytest, unittest and os too) and simple assignments are followed
  (``needs_git = pytest.mark.skipif(...)`` makes each ``@needs_git`` count), every
  binding anywhere in the module, so rebinding ``pytest`` where it never runs adds a
  reading and hides none. An
  occurrence is its whole expression and the blocks around it (``if``, ``while``,
  ``for``, ``try``, ``with``, ``match``, a conditional expression, ``and``/``or``), so
  a weakened condition or a removed or changed guard is a new skip. A test that
  moves under a condition (``if``, ``try``, a loop) is a ``skip`` finding too.
- ``collection``: in a ``conftest.py``, any change to ``collect_ignore``,
  ``collect_ignore_glob`` or a ``pytest_*`` name (the hooks, such as
  ``pytest_collection_modifyitems``, and ``pytest_plugins``); in any other Python
  test file, a change to a ``pytest_*`` hook it defines (a plugin module); in
  ``pytest.toml`` or ``.pytest.toml`` (``[pytest]``), ``pytest.ini``, ``.pytest.ini``,
  ``pyproject.toml`` (``[tool.pytest.ini_options]``, ``[tool.pytest]``), ``setup.cfg``
  (``[tool:pytest]``) or ``tox.ini`` (``[pytest]``), a change to
  ``addopts``, ``testpaths``, ``python_files``, ``python_classes``,
  ``python_functions`` or ``norecursedirs``, or a pytest configuration appearing or
  disappearing (which changes the file pytest reads).
- ``unparseable``: a side of such a file that cannot be parsed.

Any finding fails the check and sets ``protected_changed``. There is no exemption:
the reviewer or the person merging decides with the findings in view. LIMITS lists
what is not detected, assert weakening first.

Every check appends a ``lane_check`` event with the label, both results and the
provenance record; an event that cannot be written is a warning, never a failure. A
HEAD already contained in the base leaves nothing to check: it passes with a warning.
"""
from __future__ import annotations

import ast
import configparser
import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import time
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple

from aegis_core import events, gitsafe, team
from aegis_core._version import __version__
from aegis_core.errors import AegisError, AegisValidationError
from aegis_core.match import is_test_path, matches, normalize_path
from aegis_core.workspace.layout import AEGIS_DIRNAME

__all__ = [
    "COLLECTION_KEYS",
    "COVERED",
    "KINDS",
    "LIMITS",
    "NEEDS_HISTORY",
    "PROTECTED",
    "PYTEST_CONFIG_FILES",
    "SELF_ATTESTED",
    "SOURCE",
    "WITNESSED",
    "Finding",
    "LaneCheck",
    "LaneGateError",
    "LaneGateUsage",
    "PathCheck",
    "check_lane",
    "collected_ids",
    "collection_hooks",
    "error_report",
    "finding_id",
    "is_protected",
    "pytest_settings",
    "skip_forms",
]

SOURCE = "aegis check --lane"
NEEDS_HISTORY = "needs history: fetch with fetch-depth 0"
WITNESSED = "witnessed: base policy"
SELF_ATTESTED = "self-attested"
PROTECTED = (f"{AEGIS_DIRNAME}/**", ".github/workflows/**")
KINDS = ("removed", "skip", "collection", "unparseable")
COVERED = ("python",)
COLLECTION_KEYS = ("addopts", "testpaths", "python_files", "python_classes", "python_functions", "norecursedirs")
# pytest's own search order; it reads the first that holds a configuration.
PYTEST_CONFIG_FILES = ("pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini", "pyproject.toml", "tox.ini",
                       "setup.cfg")
MAX_FILE_BYTES = 8 * 1024 * 1024
LIMITS = (
    "Assert weakening is not detected: a test that still exists but checks less passes.",
    "Only Python test files and pytest's config files are checked; other test files are listed as not checked.",
    "Test ids follow pytest's default discovery (functions and methods named test*), whatever "
    "python_functions or python_classes the repository configures.",
    "Skips reached indirectly are not detected: through a fixture or helper function, a marker imported "
    "from another module, or getattr or setattr with a string.",
    "A skip is compared by its own text and the blocks around it (if, while, for, try, with, match, a "
    "conditional expression, and/or), not by what its condition evaluates to: a condition set elsewhere "
    "(a module constant such as SLOW = True, an environment variable, a helper) or an earlier "
    "'if ...: return' can change without a finding.",
    "A decorator that replaces a test with something pytest does not collect (one that returns None, say) "
    "is not detected; pytest.fixture is.",
    "Trimming @pytest.mark.parametrize cases is not detected, nor are tests generated at import time "
    "(exec, globals(), loops), which have no def to compare, or removed through globals() or vars().",
    "Of the ways to end the run early only pytest.exit and os._exit are detected, not os.kill, a signal or "
    "a plugin outside the test files.",
    "The test command itself (a CI workflow, a Makefile, tox commands) is not read; containment and the "
    "protection on .github/** cover the workflow.",
    "Only committed changes are checked: the range is merge-base(base, HEAD)..HEAD.",
)
NOTE_SELF_ATTESTED = (
    "self-attested: the allowed paths came from the lane's lease, --paths or the working tree's team.json, "
    "all of which the lane can write. --base-policy reads them from team.json at the base tip instead."
)
NOTE_WITNESSED = (
    "witnessed: base policy: every allowed path came from team.json at the base tip. A witness is only as "
    "strong as the protection on .github/** and on the base branch."
)
NOTE_EXEMPTION = (
    "Assert weakening is not detected. Any finding fails the check; there is no exemption flag: the reviewer "
    "or the person merging decides with the itemized findings in view."
)

_REGULAR = ("100644", "100755")
_OID = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_PARSE_ERRORS = (SyntaxError, ValueError, RecursionError)


# ── Errors and records ───────────────────────────────────────────────────────

class LaneGateError(AegisError):
    """The gate could not check the lane (no usable history, no allowed paths, no policy
    for the lane at base); nothing was decided. The CLI exits 1."""


class LaneGateUsage(AegisValidationError):
    """Arguments the gate cannot use (``--paths`` with base policy, an invalid glob, no git
    work tree). The CLI exits 2."""


def finding_id(kind: str, path: str, name: str) -> str:
    """The stable id of a finding: sha256 of ``kind|path|name``, first 12 hex characters."""
    text = f"{kind}|{path}|{name}".encode("utf-8", "surrogateescape")
    return hashlib.sha256(text).hexdigest()[:12]


@dataclass(frozen=True)
class Finding:
    """One test-integrity finding (``kind`` is one of KINDS)."""

    id: str
    kind: str
    path: str
    name: str
    detail: str

    def as_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "path": self.path, "name": self.name, "detail": self.detail}


def _finding(kind: str, path: str, name: str, detail: str) -> Finding:
    return Finding(finding_id(kind, path, name), kind, path, name, detail)


@dataclass(frozen=True)
class PathCheck:
    """One listed path: git's status and modes, whether an allowed glob admits it, which
    glob from which source, and whether it is a protected path."""

    path: str
    status: str
    old_mode: str
    new_mode: str
    allowed: bool
    glob: Optional[str]
    source: Optional[str]
    protected: bool

    def as_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "status": self.status, "old_mode": self.old_mode, "new_mode": self.new_mode,
                "allowed": self.allowed, "glob": self.glob, "source": self.source, "protected": self.protected}


def _stamp(epoch: Optional[int] = None) -> str:
    moment = int(time.time()) if epoch is None else int(epoch)
    return datetime.fromtimestamp(moment, timezone.utc).strftime(_TS_FORMAT)


def _source_label(source: str, base: str) -> str:
    if source.startswith("base@"):
        return f"team.json at {base} {source[len('base@'):][:12]}"
    return {"lease": "the lane's lease", "cli": "--paths", "worktree": "the working tree's team.json"}[source]


@dataclass(frozen=True)
class LaneCheck:
    """The outcome of one gate run. ``changes`` lists every path in git's order,
    ``findings`` are sorted by path, kind and name, ``not_checked`` pairs a test file
    with why it was not read."""

    lane: str
    workspace: str
    repository: str
    base: str
    base_commit: str
    merge_base: str
    head: str
    paths: Tuple[str, ...]
    paths_source: str
    shared: Tuple[str, ...]
    shared_source: str
    changes: Tuple[PathCheck, ...]
    findings: Tuple[Finding, ...]
    checked: Tuple[str, ...]
    not_checked: Tuple[Tuple[str, str], ...]
    checked_at: str
    warnings: Tuple[str, ...] = ()

    @property
    def label(self) -> str:
        from_base = all(s.startswith("base@") for s in (self.paths_source, self.shared_source))
        return WITNESSED if from_base else SELF_ATTESTED

    @property
    def violations(self) -> Tuple[PathCheck, ...]:
        return tuple(change for change in self.changes if not change.allowed)

    @property
    def containment_passed(self) -> bool:
        return not self.violations

    @property
    def integrity_passed(self) -> bool:
        return not self.findings

    @property
    def passed(self) -> bool:
        return self.containment_passed and self.integrity_passed

    @property
    def protected_changed(self) -> bool:
        return bool(self.findings)

    def _range(self) -> Dict[str, str]:
        return {"base": self.base, "base_commit": self.base_commit, "merge_base": self.merge_base, "head": self.head}

    def event_detail(self) -> Dict[str, Any]:
        """The ``lane_check`` event's detail: the label, both results and the provenance."""
        return {
            "lane": self.lane,
            "label": self.label,
            "provenance": {"paths": self.paths_source, "shared": self.shared_source},
            "containment": {"passed": self.containment_passed, "violations": len(self.violations)},
            "integrity": {"passed": self.integrity_passed, "findings": [f.id for f in self.findings]},
            "range": self._range(),
        }

    def as_dict(self) -> Dict[str, Any]:
        """The ``--json`` document."""
        return {
            "source": SOURCE,
            "aegis_version": __version__,
            "checked_at": self.checked_at,
            "scope": {"workspace": self.workspace, "repository": self.repository, "lane": self.lane, **self._range()},
            "status": "pass" if self.passed else "fail",
            "label": self.label,
            "provenance": {"paths": self.paths_source, "shared": self.shared_source},
            "allowed": {"paths": list(self.paths), "shared": list(self.shared)},
            "containment": {
                "passed": self.containment_passed,
                "paths": [change.as_dict() for change in self.changes],
                "violations": [change.path for change in self.violations],
            },
            "integrity": {
                "passed": self.integrity_passed,
                "covered": list(COVERED),
                "checked": list(self.checked),
                "not_checked": [{"path": path, "reason": reason} for path, reason in self.not_checked],
                "findings": [f.as_dict() for f in self.findings],
                "limits": list(LIMITS),
            },
            "protected_changed": self.protected_changed,
            "notes": [NOTE_WITNESSED if self.label == WITNESSED else NOTE_SELF_ATTESTED, NOTE_EXEMPTION],
            "warnings": list(self.warnings),
        }

    def text_lines(self) -> List[str]:
        """The text report, one line per item; repository text is not sanitized here."""
        verdict = "PASSED" if self.passed else "FAILED"
        lines = [
            f"{SOURCE} {self.lane}: {verdict} ({self.label})",
            f"  range: {self.merge_base[:12]}..{self.head[:12]} (from the merge base of {self.base} and HEAD), "
            f"{len(self.changes)} changed path(s)",
            f"  allowed paths from {_source_label(self.paths_source, self.base)}: {', '.join(self.paths) or '(none)'}",
            f"  shared from {_source_label(self.shared_source, self.base)}: {', '.join(self.shared) or '(none)'}",
        ]
        if self.violations:
            lines.append(f"containment: FAILED, {len(self.violations)} of {len(self.changes)} changed path(s) "
                         "outside the allowed set")
            for change in self.violations:
                why = ("protected: only team.json at the base tip (--base-policy) can allow "
                       + " and ".join(PROTECTED)) if change.protected else "outside the allowed set"
                lines.append(f"  [FAIL] {change.status} {change.path}: {why}")
        else:
            lines.append(f"containment: passed, {len(self.changes)} changed path(s) inside the allowed set")
        if self.findings:
            lines.append(f"test integrity (Python): FAILED, {len(self.findings)} finding(s); protected_changed: true")
            for f in self.findings:
                lines.append(f"  [FAIL] {f.id} {f.kind} {f.path}: {f.name} ({f.detail})")
        else:
            lines.append(f"test integrity (Python): passed, {len(self.checked)} file(s) checked; "
                         "protected_changed: false")
        for path, reason in self.not_checked:
            lines.append(f"  not checked: {path} ({reason})")
        lines.extend(f"warning: {warning}" for warning in self.warnings)
        lines.append(NOTE_WITNESSED if self.label == WITNESSED else NOTE_SELF_ATTESTED)
        lines.append(NOTE_EXEMPTION)
        return lines


def error_report(workspace: Any, lane: str, message: str, now: Optional[int] = None) -> Dict[str, Any]:
    """The ``--json`` document of a gate that could not run."""
    return {
        "source": SOURCE,
        "aegis_version": __version__,
        "checked_at": _stamp(now),
        "scope": {"workspace": str(workspace), "lane": lane},
        "status": "error",
        "error": message,
    }


# ── The gate ─────────────────────────────────────────────────────────────────

def is_protected(path: str) -> bool:
    """Whether ``path`` is under ``.aegis/`` or ``.github/workflows/`` (or is one of those
    directories, or ``.github``), compared case-folded: on a case-insensitive checkout
    ``.AEGIS/team.json`` is ``.aegis/team.json``."""
    folded = normalize_path(path).casefold()
    if folded == ".github":
        return True
    return any(folded == root or folded.startswith(root + "/") for root in (AEGIS_DIRNAME, ".github/workflows"))


def _cli_globs(paths: object) -> Tuple[str, ...]:
    if not isinstance(paths, (list, tuple)):  # a lone string is one glob's characters
        raise LaneGateUsage("--paths: give a list of globs")
    if not paths:
        raise LaneGateUsage("--paths: give at least one glob")
    out: List[str] = []
    for ordinal, glob in enumerate(paths, 1):
        if not isinstance(glob, str) or _CONTROL.search(glob):
            raise LaneGateUsage(f"--paths: glob {ordinal} is not text without control characters")
        clean = normalize_path(glob)
        if not clean:
            raise LaneGateUsage(f"--paths: glob {ordinal} is empty")
        if ".." in clean.split("/"):
            raise LaneGateUsage(f"--paths: glob {ordinal} climbs out of the repository with '..'")
        if clean not in out:
            out.append(clean)
    return tuple(out)


def _commit_range(top: Path, base: Optional[str]) -> Tuple[str, str, str, str]:
    """(base ref, base commit, merge base, HEAD), or LaneGateError."""
    shallow = gitsafe.run(["rev-parse", "--is-shallow-repository"], top)
    answer = shallow.stdout.strip()
    if shallow.returncode != 0 or answer not in (b"true", b"false"):
        raise gitsafe.GitError(f"git cannot say whether {top} is a shallow clone")
    if answer == b"true":
        raise LaneGateError(f"{NEEDS_HISTORY} (this is a shallow clone)")
    ref = base if base is not None else gitsafe.resolve_base_ref(top)
    if ref is None:
        raise LaneGateError(f"{NEEDS_HISTORY} (no base branch: none of origin/$GITHUB_BASE_REF, origin/main, "
                            "main, origin/develop or develop exists; pass --base)")
    base_commit = gitsafe.resolve_commit(top, ref)
    if not base_commit:
        raise LaneGateError(f"{NEEDS_HISTORY} (cannot resolve the base {ref!r})")
    head = gitsafe.head_commit(top)
    if not head:
        raise LaneGateError("HEAD names no commit yet: there is nothing to check")
    merge_base = gitsafe.merge_base(top, base_commit, head)
    if not merge_base:
        raise LaneGateError(f"{NEEDS_HISTORY} ({ref!r} and HEAD share no history)")
    return ref, base_commit, merge_base, head


def _lease_paths(top: Path, lane: str, now: int) -> Tuple[str, ...]:
    found = team.read_leases(top)
    lease = found.get(lane)
    if lease is not None and not lease.expired(now):
        return lease.paths
    if lease is not None:
        why = f"its lease expired at {_stamp(lease.expires_at)}"
    elif found.unreadable_lane(lane) is not None:
        why = "its lease is unreadable"
    else:
        why = "it holds no lease"
    raise LaneGateError(f"lane {lane} has no live lease ({why}): claim it with aegis team claim, "
                        "give its globs with --paths, or read them from base with --base-policy")


def _contain(entry: Tuple[str, str, str, str], allowed: Sequence[Tuple[str, str]]) -> PathCheck:
    status, old_mode, new_mode, path = entry
    protected = is_protected(path)
    for glob, source in allowed:
        if protected and not source.startswith("base@"):
            continue
        if matches(glob, path):
            return PathCheck(path, status, old_mode, new_mode, True, glob, source, protected)
    return PathCheck(path, status, old_mode, new_mode, False, None, None, protected)


def _read(top: Path, commit: str, path: str, mode: str) -> Optional[bytes]:
    """The blob at ``commit:path`` when ``mode`` is a regular file's, else None. The
    revision syntax names the path literally (no pathspec magic); the content is
    checked against its object id."""
    if mode not in _REGULAR:
        return None
    res = gitsafe.run(["rev-parse", "--verify", "--quiet", f"{commit}:{path}"], top)
    oid = os.fsdecode(res.stdout).strip() if res.returncode == 0 else ""
    if not _OID.match(oid):
        raise gitsafe.GitError(f"cannot find {path!r} at {commit}")
    return gitsafe.read_object(top, oid, MAX_FILE_BYTES)


def _irregular(old_mode: str, new_mode: str) -> str:
    side, mode = ("HEAD", new_mode) if new_mode != "000000" else ("the merge base", old_mode)
    what = {"120000": "a symlink", "160000": "a submodule"}.get(mode, f"mode {mode}")
    return f"{what} at {side}"


def _python_findings(path: str, before: Optional[bytes], after: Optional[bytes]) -> List[Finding]:
    conftest = posixpath.basename(path) == "conftest.py"
    facts = []
    errors = []
    for side, data in (("base", before), ("head", after)):
        try:
            if data is None:
                facts.append(({}, {}, {}))
            else:
                facts.append((collected_ids(data), skip_forms(data), collection_hooks(data, hooks_only=not conftest)))
        except _PARSE_ERRORS as exc:
            where = "the merge base" if side == "base" else "HEAD"
            errors.append(_finding("unparseable", path, side, f"cannot parse the file at {where}: {type(exc).__name__}"))
    if errors:
        return errors
    (base_ids, base_forms, base_hooks), (head_ids, head_forms, head_hooks) = facts
    out: List[Finding] = []
    for test_id, unconditional in base_ids.items():
        if test_id not in head_ids:
            out.append(_finding("removed", path, test_id, "present at the merge base, not collected at HEAD"))
        elif unconditional and not head_ids[test_id]:
            out.append(_finding("skip", path, f"conditional definition in {test_id}",
                                "defined only under a condition at HEAD"))
    for (scope, form), count in head_forms.items():
        for occurrence in range(base_forms.get((scope, form), 0) + 1, count + 1):
            name = f"{form} in {scope}" + (f" #{occurrence}" if occurrence > 1 else "")
            out.append(_finding("skip", path, name, "introduced at HEAD"))
    for hook in set(base_hooks) | set(head_hooks):
        if base_hooks.get(hook) != head_hooks.get(hook):
            out.append(_finding("collection", path, hook, _changed(hook in base_hooks, hook in head_hooks)))
    return out


def _changed(before: bool, after: bool) -> str:
    if before and after:
        return "changed at HEAD"
    return "added at HEAD" if after else "removed at HEAD"


def _config_findings(path: str, before: Optional[bytes], after: Optional[bytes]) -> List[Finding]:
    name = posixpath.basename(path)
    sides: List[Optional[Dict[str, str]]] = []
    errors = []
    for side, data in (("base", before), ("head", after)):
        try:
            sides.append(None if data is None else pytest_settings(name, data))
        except ValueError as exc:
            where = "the merge base" if side == "base" else "HEAD"
            errors.append(_finding("unparseable", path, side, f"cannot read the file at {where}: {exc}"))
    if errors:
        return errors
    old, new = sides
    out: List[Finding] = []
    if (old is None) != (new is None):
        out.append(_finding("collection", path, "pytest configuration", _changed(old is not None, new is not None)))
    old, new = old or {}, new or {}
    for key in set(old) | set(new):
        if old.get(key) != new.get(key):
            out.append(_finding("collection", path, key, _changed(key in old, key in new)))
    return out


def _integrity(top: Path, merge_base: str, head: str, entries: Sequence[Tuple[str, str, str, str]]):
    findings: List[Finding] = []
    checked: List[str] = []
    not_checked: List[Tuple[str, str]] = []
    for _status, old_mode, new_mode, path in entries:
        python_test = is_test_path(path) and path.endswith(".py")
        config = posixpath.basename(path) in PYTEST_CONFIG_FILES
        if not (python_test or config):
            if is_test_path(path):
                not_checked.append((path, "not a Python file"))
            continue
        before = _read(top, merge_base, path, old_mode)
        after = _read(top, head, path, new_mode)
        if before is None and after is None:
            not_checked.append((path, _irregular(old_mode, new_mode)))
            continue
        checked.append(path)
        findings.extend(_python_findings(path, before, after) if python_test else _config_findings(path, before, after))
    findings.sort(key=lambda f: (f.path, f.kind, f.name))
    return tuple(findings), tuple(checked), tuple(not_checked)


def _record(top: Path, result: LaneCheck) -> Tuple[str, ...]:
    try:
        events.append(top, "lane_check", "pass" if result.passed else "fail", result.event_detail())
    except (ValueError, TypeError, OSError, AegisError) as exc:
        return (f"event not recorded: {exc}",)
    return ()


def check_lane(root: Any, lane: str, base: Optional[str] = None, paths: Optional[Sequence[str]] = None,
               base_policy: bool = False, now: Optional[int] = None) -> LaneCheck:
    """Check what ``lane`` changed since ``merge-base(base, HEAD)`` (see the module
    docstring) and append a ``lane_check`` event.

    Raises TeamUsageError for an invalid lane name; LaneGateUsage for ``paths`` with
    ``base_policy``, an invalid glob or no git work tree; TeamFileError for an unusable
    team.json; LaneGateError when there is no usable history, no live lease (without
    ``paths``) or no ``lanes`` entry at base (with ``base_policy``); GitError when git
    fails.
    """
    team.lane_ref(lane)
    if base_policy and paths is not None:
        raise LaneGateUsage("--paths cannot be combined with --base-policy: the lane's paths then come only "
                            "from team.json at the base tip")
    cli_paths = _cli_globs(paths) if paths is not None else None
    workspace = Path(os.fspath(root))
    top = gitsafe.toplevel(workspace)
    if top is None:
        raise LaneGateUsage("not in a git work tree: the lane gate checks git history")
    moment = int(time.time()) if now is None else int(now)
    ref, base_commit, merge_base, head = _commit_range(top, base)
    if base_policy:
        policy = team.load_team_at(top, base_commit)
        if policy.lanes is None or lane not in policy.lanes:
            raise LaneGateError(f"team.json at {ref} ({base_commit[:12]}) has no lanes entry for {lane}: "
                                "--base-policy takes the lane's paths only from there")
        lane_paths, paths_source = policy.lanes[lane], f"base@{base_commit}"
        shared, shared_source = policy.shared, f"base@{base_commit}"
    else:
        if cli_paths is not None:
            lane_paths, paths_source = cli_paths, "cli"
        else:
            lane_paths, paths_source = _lease_paths(top, lane, moment), "lease"
        shared, shared_source = team.load_team(top).shared, "worktree"
    allowed = [(glob, paths_source) for glob in lane_paths] + [(glob, shared_source) for glob in shared]
    entries = gitsafe.diff_entries(top, merge_base, head)
    findings, checked, not_checked = _integrity(top, merge_base, head, entries)
    # Passing is right (the lane changed nothing), but a reader of "PASSED" should know why.
    empty = (f"HEAD is already contained in {ref}: nothing was checked",) if merge_base == head else ()
    result = LaneCheck(
        lane=lane, workspace=str(workspace), repository=str(top), base=ref, base_commit=base_commit,
        merge_base=merge_base, head=head, paths=tuple(lane_paths), paths_source=paths_source,
        shared=tuple(shared), shared_source=shared_source,
        changes=tuple(_contain(entry, allowed) for entry in entries),
        findings=findings, checked=checked, not_checked=not_checked, checked_at=_stamp(moment), warnings=empty,
    )
    return dataclasses.replace(result, warnings=empty + _record(top, result))


# ── Python test files ────────────────────────────────────────────────────────

def _unbind(state: Dict[str, bool], key: str, conditional: bool, keep: bool = False) -> None:
    """A name rebound in a body: the test ids it held (itself, or a class's members) are
    gone, or only conditionally there when the rebinding is conditional."""
    for found in [k for k in state if k == key or k.startswith(key + "::")]:
        if keep and found == key:
            continue
        if conditional:
            state[found] = False
        else:
            del state[found]


def _target_names(node: ast.AST) -> List[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for element in node.elts for name in _target_names(element)]
    if isinstance(node, ast.Starred):
        return _target_names(node.value)
    return []


def _bound_names(stmt: ast.stmt) -> List[str]:
    """Names a statement binds in its own body (assignment, deletion, import)."""
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        return [(alias.asname or alias.name).split(".")[0] for alias in stmt.names if alias.name != "*"]
    if isinstance(stmt, (ast.Assign, ast.Delete)):
        targets = stmt.targets
    elif isinstance(stmt, ast.AugAssign) or (isinstance(stmt, ast.AnnAssign) and stmt.value is not None):
        targets = [stmt.target]
    else:
        targets = []
    return [name for target in targets for name in _target_names(target)]


def _compound_names(stmt: ast.stmt) -> List[str]:
    """Names a compound statement binds itself: loop targets, ``with ... as``, handlers."""
    names = _target_names(getattr(stmt, "target", None)) if isinstance(stmt, (ast.For, ast.AsyncFor)) else []
    for item in getattr(stmt, "items", ()) or ():
        if item.optional_vars is not None:
            names.extend(_target_names(item.optional_vars))
    names.extend(handler.name for handler in getattr(stmt, "handlers", ()) or () if handler.name)
    return names


def _blocks(stmt: ast.stmt) -> List[List[ast.stmt]]:
    blocks = [getattr(stmt, field) for field in ("body", "orelse", "finalbody")
              if isinstance(getattr(stmt, field, None), list)]
    blocks.extend(handler.body for handler in getattr(stmt, "handlers", ()) or ())
    blocks.extend(case.body for case in getattr(stmt, "cases", ()) or ())
    return blocks


def _constructs(cls: ast.ClassDef) -> bool:
    """A class pytest will not collect: it defines ``__init__`` or ``__new__``."""
    for stmt in cls.body:
        names = [stmt.name] if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) else _bound_names(stmt)
        if "__init__" in names or "__new__" in names:
            return True
    return False


def _fixture(func: Any, aliases: _Aliases) -> bool:
    """A function decorated with ``pytest.fixture`` (called or not, through any alias):
    pytest collects it as a fixture, never as a test, whatever its name."""
    return any(chain in _FIXTURES
               for decorator in func.decorator_list
               for chain in _resolve(decorator.func if isinstance(decorator, ast.Call) else decorator, aliases))


def _scan_ids(body: Sequence[ast.stmt], prefix: str, conditional: bool, state: Dict[str, bool],
              aliases: _Aliases) -> None:
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            key = prefix + stmt.name
            test = stmt.name.startswith("test") and not _fixture(stmt, aliases)
            _unbind(state, key, conditional, keep=test)
            if test:
                # A conditional redefinition of a test keeps a test there either way.
                state[key] = state.get(key, False) if conditional else True
        elif isinstance(stmt, ast.ClassDef):
            key = prefix + stmt.name
            _unbind(state, key, conditional)
            if not _constructs(stmt):
                _scan_ids(stmt.body, key + "::", conditional, state, aliases)
        else:
            for name in _bound_names(stmt):
                _unbind(state, prefix + name, conditional)
            for name in _compound_names(stmt):
                _unbind(state, prefix + name, True)
            for block in _blocks(stmt):
                _scan_ids(block, prefix, True, state, aliases)


def collected_ids(source: bytes) -> Dict[str, bool]:
    """The test ids pytest's default discovery collects from ``source``, each mapped to
    whether it is defined unconditionally (directly in the module or class body, not
    under an ``if``, ``try``, ``with`` or loop). Functions and methods named ``test*``,
    in classes of any name at any nesting; a class with ``__init__`` or ``__new__``
    contributes none, nor does a ``pytest.fixture``; the last binding of a name wins.
    Raises SyntaxError, ValueError or RecursionError for source that does not parse."""
    tree = ast.parse(source)
    state: Dict[str, bool] = {}
    _scan_ids(tree.body, "", False, state, _aliases(tree))
    return state


_FORMS = (
    ("pytest", "mark", "skip"),
    ("pytest", "mark", "skipif"),
    ("pytest", "mark", "xfail"),
    ("pytest", "skip"),
    ("pytest", "xfail"),
    ("pytest", "importorskip"),
    ("unittest", "skip"),
    ("unittest", "skipIf"),
    ("unittest", "skipUnless"),
    ("unittest", "expectedFailure"),
    ("unittest", "SkipTest"),
    # They end the whole run, so the tests after them never run; pytest.exit with
    # returncode=0 and os._exit(0) even report success.
    ("pytest", "exit"),
    ("os", "_exit"),
)
# Calls that return a skip or xfail decorator: a name bound to one is the form itself.
_DECORATOR_FACTORIES = frozenset({
    ("pytest", "mark", "skip"), ("pytest", "mark", "skipif"), ("pytest", "mark", "xfail"),
    ("unittest", "skip"), ("unittest", "skipIf"), ("unittest", "skipUnless"),
})
# pytest.fixture(...) returns a decorator too; neither is a skip form.
_FIXTURES = frozenset({("pytest", "fixture"), ("pytest", "yield_fixture")})
_PREFIXES = frozenset(form[:i] for form in _FORMS + tuple(_FIXTURES) for i in range(1, len(form)))
_MARKERS = ("pytestmark", "__test__")
_Chain = Tuple[str, ...]
# Every chain each name is bound to anywhere in the module; stored chains are forms,
# prefixes or fixture decorators only, so the sets stay small and the fixed point ends.
_Aliases = Dict[str, Set[_Chain]]


def _canonical(chain: Tuple[str, ...]) -> Tuple[str, ...]:
    return ("unittest",) + chain[2:] if chain[:2] == ("unittest", "case") else chain


def _form_of(chain: Optional[Tuple[str, ...]]) -> Optional[Tuple[str, ...]]:
    if chain:
        for form in _FORMS:
            if chain[:len(form)] == form:
                return form
    return None


def _resolve(node: ast.AST, aliases: _Aliases) -> List[_Chain]:
    """Every chain a ``Name`` or ``a.b.c`` chain may stand for, as dotted parts: as
    written, then with its head replaced by each alias bound to it anywhere in the
    module. A name rebound elsewhere (``import unittest as pytest`` in a function that
    never runs) so adds a reading and never hides one."""
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return []
    tail = tuple(reversed(parts))
    return [_canonical(head + tail) for head in [(node.id,)] + sorted(aliases.get(node.id, ()))]


def _first_form(chains: Sequence[_Chain]) -> Optional[_Chain]:
    return next((form for form in map(_form_of, chains) if form is not None), None)


def _aliasable(chain: _Chain) -> Optional[_Chain]:
    """What a name bound to ``chain`` is recorded as: the skip form it starts with (so
    ``pytest.skip.Exception`` is ``pytest.skip``), or itself when it is a part of a form
    or a fixture decorator; None for anything else."""
    form = _form_of(chain)
    if form is not None:
        return form
    return chain if chain in _PREFIXES or chain in _FIXTURES else None


def _alias_values(value: ast.AST, aliases: _Aliases) -> Set[_Chain]:
    if isinstance(value, ast.Call):
        chains = _resolve(value.func, aliases)
        return ({chain for chain in chains if chain in _FIXTURES}
                | {form for form in map(_form_of, chains) if form in _DECORATOR_FACTORIES})
    return {alias for alias in map(_aliasable, _resolve(value, aliases)) if alias is not None}


def _bind(aliases: _Aliases, name: str, chain: _Chain) -> None:
    alias = _aliasable(chain)
    if alias is not None:
        aliases.setdefault(name, set()).add(alias)


def _star_names(module: Tuple[str, ...]) -> Dict[str, Tuple[str, ...]]:
    """What ``from <module> import *`` binds among the known names: each one that
    starts a skip form or fixture decorator under ``module``."""
    depth = len(module)
    return {chain[depth]: chain[:depth + 1] for chain in _FORMS + tuple(_FIXTURES)
            if len(chain) > depth and chain[:depth] == module}


def _aliases(tree: ast.AST) -> _Aliases:
    """Names bound, anywhere in the module, to pytest, unittest, os, a part of a skip
    form, a skip decorator or pytest.fixture: by import (a star import of those
    modules binds each such name), or by assignment followed to a fixed point. Every
    binding is kept, whatever the order or the branch it is in."""
    aliases: _Aliases = {}
    assigned: List[Tuple[str, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:  # without one, the name bound is the module itself
                    _bind(aliases, alias.asname, _canonical(tuple(alias.name.split("."))))
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            module = _canonical(tuple(node.module.split(".")))
            for alias in node.names:
                if alias.name == "*":
                    for name, chain in _star_names(module).items():
                        _bind(aliases, name, chain)
                else:
                    _bind(aliases, alias.asname or alias.name, _canonical(module + (alias.name,)))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            assigned.extend((target.id, node.value) for target in targets if isinstance(target, ast.Name))
    # Each round adds a chain to some name or ends; the chains come from a finite set.
    while True:
        grown = False
        for name, value in assigned:
            new = _alias_values(value, aliases) - aliases.get(name, set())
            if new:
                aliases.setdefault(name, set()).update(new)
                grown = True
        if not grown:
            return aliases


def _shown(node: ast.AST) -> str:
    try:
        text = ast.unparse(node)
    except (RecursionError, ValueError, AttributeError):
        text = ast.dump(node)
    text = " ".join(text.split())
    if len(text) > 120:
        digest = hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()[:12]
        text = f"{text[:96]}... sha256:{digest}"
    return text


def _flat_targets(node: ast.AST) -> Iterator[ast.AST]:
    if isinstance(node, (ast.Tuple, ast.List)):
        for element in node.elts:
            yield from _flat_targets(element)
    elif isinstance(node, ast.Starred):
        yield from _flat_targets(node.value)
    else:
        yield node


class _FormCounter(ast.NodeVisitor):
    """Counts skip and xfail forms per scope (``Class::method``, ``<module>``)."""

    def __init__(self, aliases: _Aliases) -> None:
        self.aliases = aliases
        self.scope: List[Tuple[str, bool]] = []  # (name, is a class)
        # The blocks around the node being visited, outermost first, across scopes: a
        # decorator under a module-level ``if`` is guarded by it, and so is the body.
        self.guards: List[str] = []
        self.counts: Dict[Tuple[str, str], int] = {}

    def _add(self, form: str) -> None:
        # The guards are part of the occurrence, so removing or changing the condition
        # around an existing skip (``if win: pytest.skip()`` -> ``pytest.skip()``) is new.
        if self.guards:
            form = f"{form} under {' > '.join(self.guards)}"
        key = ("::".join(name for name, _ in self.scope) or "<module>", form)
        self.counts[key] = self.counts.get(key, 0) + 1

    def _under(self, guard: str, nodes: Sequence[ast.AST]) -> None:
        self.guards.append(guard)
        for node in nodes:
            self.visit(node)
        self.guards.pop()

    def _branches(self, word: str, test: ast.AST, body: Sequence[ast.AST], orelse: Sequence[ast.AST]) -> None:
        self.visit(test)
        shown = _shown(test)
        self._under(f"{word} {shown}", body)
        if orelse:
            self._under(f"else of {word} {shown}", orelse)

    def visit_If(self, node: ast.If) -> None:
        self._branches("if", node.test, node.body, node.orelse)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self._branches("if", node.test, [node.body], [node.orelse])

    def visit_While(self, node: ast.While) -> None:
        self._branches("while", node.test, node.body, node.orelse)

    def visit_For(self, node: Any) -> None:
        self.visit(node.target)
        self.visit(node.iter)
        loop = f"for {_shown(node.target)} in {_shown(node.iter)}"
        self._under(loop, node.body)
        if node.orelse:
            self._under(f"else of {loop}", node.orelse)

    visit_AsyncFor = visit_For

    def visit_Try(self, node: Any) -> None:
        self._under("try", node.body)
        for handler in node.handlers:
            if handler.type is not None:
                self.visit(handler.type)
            self._under("except" if handler.type is None else f"except {_shown(handler.type)}", handler.body)
        if node.orelse:
            self._under("else of try", node.orelse)
        if node.finalbody:
            self._under("finally", node.finalbody)

    visit_TryStar = visit_Try  # Python 3.11+

    def visit_With(self, node: Any) -> None:
        for item in node.items:
            self.visit(item)
        self._under("with " + ", ".join(_shown(item) for item in node.items), node.body)

    visit_AsyncWith = visit_With

    def visit_Match(self, node: Any) -> None:  # Python 3.10+
        self.visit(node.subject)
        subject = _shown(node.subject)
        for case in node.cases:
            if case.guard is not None:
                self.visit(case.guard)
            guard = "" if case.guard is None else f" if {_shown(case.guard)}"
            self._under(f"match {subject} case {_shown(case.pattern)}{guard}", case.body)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # Each operand runs only after the ones before it: ``win or pytest.skip()``.
        word = "and" if isinstance(node.op, ast.And) else "or"
        depth = len(self.guards)
        for value in node.values:
            self.visit(value)
            self.guards.append(f"{_shown(value)} {word}")
        del self.guards[depth:]

    def _enter(self, node: Any, is_class: bool) -> None:
        self.scope.append((node.name, is_class))
        self.generic_visit(node)  # decorators count in the scope they decorate
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter(node, False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter(node, False)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node, True)

    def _marker(self, node: Any, targets: Sequence[ast.AST]) -> None:
        # pytestmark and __test__ act as names in a module or class body, and as
        # attributes of a test or class anywhere (test_x.__test__ = False); the whole
        # statement is the form, so any change to what it holds is a new occurrence.
        marker_level = not self.scope or self.scope[-1][1]
        for target in (t for whole in targets for t in _flat_targets(whole)):
            if (isinstance(target, ast.Attribute) and target.attr in _MARKERS) or (
                    marker_level and isinstance(target, ast.Name) and target.id in _MARKERS):
                self._add(_shown(node))
                return
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._marker(node, node.targets)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._marker(node, [node.target] if node.value is not None else [])

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._marker(node, [node.target])

    def _reference(self, node: ast.AST) -> Optional[str]:
        """The canonical form a name, attribute chain or callee refers to, or None."""
        form = _first_form(_resolve(node, self.aliases))
        if form is not None:
            return ".".join(form)
        return "skipTest" if isinstance(node, ast.Attribute) and node.attr == "skipTest" else None

    def _add_form(self, canonical: str, node: ast.AST) -> None:
        # The whole expression is the occurrence, so a weakened condition or another
        # reason is a new skip: skipif(sys.platform == "win32") -> skipif(True).
        shown = _shown(node)
        self._add(canonical if shown == canonical else f"{canonical}: {shown}")

    def visit_Call(self, node: ast.Call) -> None:
        canonical = self._reference(node.func)
        if canonical is None:
            self.generic_visit(node)
            return
        self._add_form(canonical, node)
        for argument in [*node.args, *node.keywords]:
            self.visit(argument)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        canonical = self._reference(node) if isinstance(node.ctx, ast.Load) else None
        if canonical is None:
            self.generic_visit(node)
            return
        self._add_form(canonical, node)

    def visit_Name(self, node: ast.Name) -> None:
        canonical = self._reference(node) if isinstance(node.ctx, ast.Load) else None
        if canonical is not None:
            self._add_form(canonical, node)


def skip_forms(source: bytes) -> Dict[Tuple[str, str], int]:
    """How often each skip or xfail occurrence is in ``source``, by (scope, form): the
    scope is the enclosing ``Class::function`` chain or ``<module>``; the form is the
    canonical name (``pytest.mark.skipif``, ``unittest.SkipTest``, ``skipTest``), then
    ``: `` and the whole expression (the call, or the alias used) when that is spelled
    otherwise, or a whole ``pytestmark``/``__test__`` statement. Raises SyntaxError,
    ValueError or RecursionError for source that does not parse."""
    tree = ast.parse(source)
    counter = _FormCounter(_aliases(tree))
    counter.visit(tree)
    return counter.counts


def _watched(name: str) -> bool:
    return name in ("collect_ignore", "collect_ignore_glob") or name.startswith("pytest_")


def _names_in(stmt: ast.stmt) -> Iterator[str]:
    for node in ast.walk(stmt):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.name
        elif isinstance(node, ast.alias):
            yield (node.asname or node.name).split(".")[0]


def collection_hooks(source: bytes, hooks_only: bool = False) -> Dict[str, Tuple[str, ...]]:
    """For a conftest: each watched name (``collect_ignore``, ``collect_ignore_glob``,
    any ``pytest_*`` hook or ``pytest_plugins``) mapped to the sorted AST dumps of the
    top-level statements that mention it, so formatting and comments do not count
    and any change to what they do does. With ``hooks_only`` (any other Python test
    file, which acts on collection only as a plugin), just its top-level ``pytest_*``
    function definitions. Raises like ``collected_ids``."""
    found: Dict[str, List[str]] = {}
    for stmt in ast.parse(source).body:
        if hooks_only:
            hook = isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name.startswith("pytest_")
            names = {stmt.name} if hook else set()  # type: ignore[union-attr]
        else:
            names = {name for name in _names_in(stmt) if _watched(name)}
        if names:
            dump = ast.dump(stmt)
            for name in names:
                found.setdefault(name, []).append(dump)
    return {name: tuple(sorted(dumps)) for name, dumps in found.items()}


# ── pytest's config files ────────────────────────────────────────────────────

_INI_SECTIONS = {"pytest.ini": "pytest", ".pytest.ini": "pytest", "tox.ini": "pytest", "setup.cfg": "tool:pytest"}


def pytest_settings(filename: str, data: bytes) -> Optional[Dict[str, str]]:
    """The pytest collection settings in a config file named ``filename``: None when the
    file holds no pytest configuration, else ``{"[section] key": value}`` for the
    COLLECTION_KEYS it sets (``{}`` for a configuration without them; a
    ``pytest.toml``, ``.pytest.toml``, ``pytest.ini`` or ``.pytest.ini`` is one even
    when empty, as pytest reads it). Values are compared as text: whitespace around ini
    lines and, in TOML, whitespace and comments outside strings do not count. Raises
    ValueError for a file that cannot be read."""
    text = bytes(data).decode("utf-8-sig")
    if filename == "pyproject.toml":
        return _toml_settings(text, _PYPROJECT_TABLES, always=False)
    if filename in ("pytest.toml", ".pytest.toml"):
        return _toml_settings(text, _PYTEST_TOML_TABLES, always=True)
    section = _INI_SECTIONS.get(filename)
    if section is None:
        raise ValueError(f"{filename} is not a pytest configuration file")
    # As pytest's own ini reader: no [DEFAULT] inheritance, case-sensitive keys, and a
    # duplicated section or key is an error (then the file is unreadable, a finding).
    parser = configparser.ConfigParser(interpolation=None, strict=True, default_section="\x00")
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise ValueError(f"not a valid ini file ({type(exc).__name__})") from None
    if not parser.has_section(section):
        return {} if filename in ("pytest.ini", ".pytest.ini") else None
    return {
        f"[{section}] {key}": "\n".join(line.strip() for line in parser.get(section, key).splitlines()
                                        if line.strip())
        for key in COLLECTION_KEYS if parser.has_option(section, key)
    }


# The tables pytest reads settings from, the last being the root of its configuration.
_PYPROJECT_TABLES = (("tool", "pytest", "ini_options"), ("tool", "pytest"))
_PYTEST_TOML_TABLES = (("pytest",),)
_TOML_BARE = re.compile(r"[A-Za-z0-9_-]+")


def _toml_settings(text: str, tables: Tuple[Tuple[str, ...], ...], always: bool) -> Optional[Dict[str, str]]:
    root = tables[-1]
    holders = {watched[:i] for watched in tables for i in range(1, len(watched) + 1)}
    found: Dict[str, str] = {}
    present = always
    table: Tuple[str, ...] = ()
    for is_table, key, value in _toml_statements(text):
        if is_table:
            table = key
            present = present or key[:len(root)] == root
            continue
        full = table + key
        present = present or full[:len(root)] == root
        for watched in tables:
            if full[:-1] == watched and full[-1] in COLLECTION_KEYS:
                found[f"[{'.'.join(watched)}] {full[-1]}"] = value
        # An inline table that holds the pytest tables: kept whole, so any change counts.
        # Above the root (``tool = {...}``) it counts only when it mentions pytest.
        if full in holders and value.startswith("{") and (len(full) >= len(root) or "pytest" in value):
            present = True
            found[f"{'.'.join(full)} (inline table)"] = value
    return found if present else None


def _toml_skip(text: str, i: int, newlines: bool) -> int:
    """Past spaces, tabs and comments (and newlines when ``newlines``)."""
    while i < len(text):
        char = text[i]
        if char == "#":
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        elif char in " \t" or (newlines and char in "\r\n"):
            i += 1
        else:
            break
    return i


def _toml_line_end(text: str, i: int) -> int:
    i = _toml_skip(text, i, newlines=False)
    if i < len(text) and text[i] == "\r":
        i += 1
    if i < len(text) and text[i] != "\n":
        raise ValueError("unexpected text after a TOML statement")
    return i + 1


def _toml_string_end(text: str, i: int) -> int:
    quote = text[i]
    if text.startswith(quote * 3, i):
        j = i + 3
        while True:
            k = text.find(quote * 3, j)
            if k < 0:
                raise ValueError("unterminated multi-line TOML string")
            backslashes = len(text[j:k]) - len(text[j:k].rstrip("\\"))
            if quote == '"' and backslashes % 2:
                j = k + 1
                continue
            end = k + 3
            while end < len(text) and text[end] == quote and end - k < 5:  # up to two quotes of content
                end += 1
            return end
    j = i + 1
    while j < len(text) and text[j] != "\n":
        if quote == '"' and text[j] == "\\":
            j += 2
            continue
        if text[j] == quote:
            return j + 1
        j += 1
    raise ValueError("unterminated TOML string")


def _toml_key(text: str, i: int, stop: str) -> Tuple[Tuple[str, ...], int]:
    parts: List[str] = []
    while True:
        i = _toml_skip(text, i, newlines=False)
        if i < len(text) and text[i] in "\"'":
            end = _toml_string_end(text, i)
            raw = text[i:end]
            try:
                parts.append(json.loads(raw) if raw[0] == '"' else raw[1:-1])
            except ValueError:
                parts.append(raw[1:-1])
            i = end
        else:
            bare = _TOML_BARE.match(text, i)
            if bare is None:
                raise ValueError("invalid TOML key")
            parts.append(bare.group())
            i = bare.end()
        i = _toml_skip(text, i, newlines=False)
        if i < len(text) and text[i] == ".":
            i += 1
        elif i < len(text) and text[i] == stop:
            return tuple(parts), i
        else:
            raise ValueError("invalid TOML key")


def _toml_value(text: str, i: int) -> Tuple[str, int]:
    """A value as text without whitespace and comments outside strings (arrays and
    inline tables may span lines), and the index of the end of its line."""
    out: List[str] = []
    depth = 0
    i = _toml_skip(text, i, newlines=False)
    while i < len(text):
        char = text[i]
        if char in "\"'":
            end = _toml_string_end(text, i)
            out.append(text[i:end])
            i = end
            continue
        if char == "#":
            i = _toml_skip(text, i, newlines=False)
            continue
        if char == "\n" and depth == 0:
            break
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced brackets in a TOML value")
        if not char.isspace():
            out.append(char)
        i += 1
    if depth:
        raise ValueError("unterminated TOML array or inline table")
    if not out:
        raise ValueError("a TOML key without a value")
    return "".join(out), i


def _toml_statements(text: str) -> Iterator[Tuple[bool, Tuple[str, ...], str]]:
    """(is a table header, dotted key, value text) for each statement of a TOML file."""
    i = 0
    while True:
        i = _toml_skip(text, i, newlines=True)
        if i >= len(text):
            return
        if text[i] == "[":
            close = "]]" if text.startswith("[[", i) else "]"
            key, i = _toml_key(text, i + len(close), "]")
            if not text.startswith(close, i):
                raise ValueError("unterminated TOML table header")
            i = _toml_line_end(text, i + len(close))
            yield True, key, ""
        else:
            key, i = _toml_key(text, i, "=")
            value, i = _toml_value(text, i + 1)
            i = _toml_line_end(text, i)
            yield False, key, value
