"""The one target_paths matcher (ADR 0005 AD-3 L1, defense #23).

Every place that asks "does this rule apply to this file?" calls ``matches``:
aegis scan, the ``aegis check`` telemetry and forbid_ast gates, credit assignment,
coverage and the grade. One pattern therefore means the same thing everywhere.

Semantics are a superset of posix ``fnmatch.fnmatchcase`` on workspace-relative
POSIX paths:

- ``*`` crosses ``/`` (as in fnmatch): ``aegis_core/*.py`` matches
  ``aegis_core/lifecycle/promotion.py``. Shipped rules rely on this.
- ``**/`` is zero or more directories: ``src/**/*.py`` matches ``src/a.py``, which
  fnmatch alone does not.
- A pattern without ``/`` also matches the basename: ``Makefile`` matches
  ``tools/Makefile``.
- There is no substring glob: ``src`` never matches ``src/a.py`` and ``aegis`` never
  matches ``aegis_core/x.py``.
- Matching is case-sensitive on every platform (``fnmatch.fnmatch`` is not on
  Windows), so the same rule set selects the same rules on every host.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path
import posixpath
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

__all__ = [
    "credit_weights",
    "first_match",
    "is_test_path",
    "matches",
    "matching_files",
    "normalize_path",
    "workspace_files",
]

Patterns = Union[str, Iterable[object], None]

_TEST_SUFFIXES = ("_test.py", "_test.go", ".test.ts", ".spec.ts", ".test.js", ".spec.js")


def normalize_path(path: str) -> str:
    """A path or pattern as workspace-relative POSIX: ``/`` separators, no leading
    ``./`` or ``/``. A leading dot that belongs to a name (``.aegis``) is kept."""
    text = path.replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def _class(body: str) -> str:
    """A ``[...]`` body as a regex class, the way fnmatch reads it."""
    body = body.replace("\\", "\\\\")
    body = re.sub(r"([&~|])", r"\\\1", body)
    if body.startswith("!"):
        return "[^" + body[1:] + "]"
    if body.startswith("^"):
        return "[\\" + body + "]"
    return "[" + body + "]"


@functools.lru_cache(maxsize=4096)
def _compile(pattern: str) -> "re.Pattern[str]":
    out: List[str] = []
    i, n = 0, len(pattern)
    while i < n:
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        char = pattern[i]
        if char == "*":
            while i < n and pattern[i] == "*":
                i += 1
            out.append(".*")
            continue
        if char == "?":
            out.append(".")
            i += 1
            continue
        if char == "[":
            j = i + 1
            if j < n and pattern[j] == "!":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j < n:
                body = pattern[i + 1:j]
                piece = _class(body) if body not in ("", "!") else ("(?!)" if not body else ".")
                try:
                    re.compile(piece)
                except re.error:
                    # A class fnmatch would treat as empty (a reversed range) matches nothing.
                    piece = "(?!)"
                out.append(piece)
                i = j + 1
                continue
            out.append("\\[")
            i += 1
            continue
        out.append(re.escape(char))
        i += 1
    return re.compile("(?s:" + "".join(out) + r")\Z")


def matches(pattern: str, path: str) -> bool:
    """Whether target_paths ``pattern`` applies to the workspace-relative ``path``."""
    if not isinstance(pattern, str) or not isinstance(path, str):
        return False
    pat, rel = normalize_path(pattern), normalize_path(path)
    if not pat or not rel:
        return False
    regex = _compile(pat)
    if regex.match(rel):
        return True
    return "/" not in pat and regex.match(rel.rsplit("/", 1)[-1]) is not None


def _as_list(patterns: Patterns) -> List[object]:
    if patterns is None:
        return []
    if isinstance(patterns, str):
        return [patterns]
    return list(patterns)


def first_match(patterns: Patterns, path: str) -> Optional[str]:
    """The first of ``patterns`` (a list, or one pattern string) that matches ``path``."""
    for pattern in _as_list(patterns):
        if isinstance(pattern, str) and matches(pattern, path):
            return pattern
    return None


def _unique(files: Iterable[str]) -> List[str]:
    """``files`` normalized, in order, each once: ``./src/a.py`` and ``src/a.py`` are one file."""
    return list(dict.fromkeys(normalize_path(f) for f in files if isinstance(f, str)))


def workspace_files(root: Any, files: Iterable[str]) -> List[str]:
    """``files`` as the workspace-relative POSIX paths rules are matched against, each once.

    An absolute path inside ``root`` is made relative to it (both resolved, so a
    symlinked temp dir or a Windows drive spelling compares equal). A path outside the
    workspace, absolute or climbing out with ``..``, is no workspace file: no rule
    applies to it, so it is dropped.
    """
    base: Optional[Path] = None
    out: List[str] = []
    for raw in files:
        if not isinstance(raw, str) or not raw:
            continue
        if os.path.isabs(raw):
            if base is None:
                base = Path(os.fspath(root)).resolve()
            try:
                rel = Path(raw).resolve().relative_to(base).as_posix()
            except (ValueError, OSError):
                continue
        else:
            rel = posixpath.normpath(normalize_path(raw))
        if rel in ("", ".") or rel == ".." or rel.startswith("../"):
            continue
        out.append(rel)
    return _unique(out)


def matching_files(patterns: Patterns, files: Iterable[str]) -> List[str]:
    """The ``files`` some pattern matches, normalized, in order and without duplicates."""
    pats = _as_list(patterns)
    return [f for f in _unique(files) if first_match(pats, f) is not None]


def credit_weights(rules: Mapping[str, Patterns], files: Iterable[str]) -> Dict[str, float]:
    """Split one outcome's credit over the rules, file by file.

    ``rules`` maps a rule id to its target_paths. Each changed file is worth 1.0,
    shared equally by the rules that match it; a rule's weight is the sum over the
    files it matches (callers that record a ledger weight clamp it to 1). A rule
    matching no changed file gets 0.0.
    """
    patterns = {rule: _as_list(pats) for rule, pats in rules.items()}
    weights = {rule: 0.0 for rule in patterns}
    for path in _unique(files):
        hits = [rule for rule, pats in patterns.items() if first_match(pats, path) is not None]
        for rule in hits:
            weights[rule] += 1.0 / len(hits)
    return weights


def is_test_path(path: str) -> bool:
    """Whether ``path`` is a test file: under a ``tests/`` directory, ``test_*``,
    ``conftest.py``, or a ``*_test.py``/``*_test.go``/``*.test.ts``/``*.spec.js`` style name.

    The one test-file predicate (defense #25); callers that also skip support files
    (``__init__.py``) add that themselves.
    """
    rel = normalize_path(path)
    parts = rel.split("/")
    base = parts[-1]
    return (
        "tests" in parts[:-1]
        or base.startswith("test_")
        or base == "conftest.py"
        or base.endswith(_TEST_SUFFIXES)
    )
