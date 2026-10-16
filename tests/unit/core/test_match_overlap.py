"""aegis_core.match.may_overlap / sets_overlap: can two path globs select one file?

The lease overlap test of the v4.1 team spec (§1 "Overlap"). It is conservative: it may
answer "overlap" for globs no path matches both of, but it must never answer "disjoint"
when some path matches both under ``match.matches``.
"""
from __future__ import annotations

import itertools
import random
from typing import Dict, FrozenSet, List

import pytest

from aegis_core.match import matches, may_overlap, sets_overlap


# ── The cases the spec requires ──────────────────────────────────────────────

@pytest.mark.parametrize(
    "a, b, expected",
    [
        ("Makefile", "tools/**", True),  # a slashless glob matches the basename at any depth
        ("*.py", "src/**", True),
        ("a/b*", "a/c/**", False),
        ("src/*.py", "src/a/**", True),  # "*" crosses "/"
    ],
)
def test_required_cases(a: str, b: str, expected: bool):
    assert may_overlap(a, b) is expected
    assert may_overlap(b, a) is expected


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ("docs/**", "README.md", True),  # slashless: prefix ""
        ("docs/**", "src/**", False),
        ("docs/**", "docs/a.md", True),
        ("docs/a.md", "docs/b.md", False),
        ("docs/a.md", "docs/a.md", True),
        ("**/x.py", "src/a/**", True),  # "**/" first: prefix ""
        ("src/[ab]/x.py", "src/c/**", True),  # "[" ends the literal prefix
        ("src/?/x.py", "src/zz/**", True),  # "?" ends the literal prefix
        ("src/a", "src/ab/**", True),  # no path matches both, but "src/a" prefixes "src/ab/": conservative
    ],
)
def test_literal_prefix_rule(a: str, b: str, expected: bool):
    assert may_overlap(a, b) is expected
    assert may_overlap(b, a) is expected


@pytest.mark.parametrize(
    "a, b",
    [
        ("./docs/**", "docs/a.md"),
        ("/docs/**", "docs/a.md"),
        ("docs\\**", "docs/a.md"),
        (".\\docs\\a.md", "docs/**"),
    ],
)
def test_both_globs_are_normalized_first(a: str, b: str):
    assert may_overlap(a, b) is True


def test_a_leading_slash_or_dot_slash_does_not_make_a_glob_slashed():
    # "/Makefile" normalizes to "Makefile", which matches tools/Makefile by basename.
    assert matches("/Makefile", "tools/Makefile")
    assert may_overlap("/Makefile", "tools/**") is True
    assert may_overlap("./Makefile", "tools/**") is True


def test_prefixes_compare_casefolded():
    # The matcher is case-sensitive, but on a case-insensitive file system Docs/ and docs/
    # are one directory: unsure means conflict.
    assert may_overlap("Docs/**", "docs/**") is True
    assert may_overlap("SRC/a.py", "src/**") is True
    assert may_overlap("STRASSE/**", "straße/**") is True  # casefold, not lower


@pytest.mark.parametrize("empty", ["", "/", "./", "././", "//"])
def test_a_glob_empty_after_normalizing_never_conflicts(empty: str):
    assert may_overlap(empty, "**") is False
    assert may_overlap("**", empty) is False
    assert may_overlap(empty, empty) is False


@pytest.mark.parametrize("bad", [None, 3, b"docs/**", ["docs/**"]])
def test_a_non_string_glob_matches_nothing_and_never_conflicts(bad):
    assert may_overlap(bad, "**") is False
    assert may_overlap("**", bad) is False


def test_sets_overlap_when_any_pair_overlaps():
    assert sets_overlap(["docs/**", "README.md"], ["src/**"]) is True  # README.md is slashless
    assert sets_overlap(["docs/**", "site/**"], ["src/**", "tests/**"]) is False
    assert sets_overlap(["docs/**"], ["src/**", "docs/api/*.md"]) is True


def test_sets_overlap_edge_inputs():
    assert sets_overlap([], ["**"]) is False
    assert sets_overlap(["**"], []) is False
    assert sets_overlap("docs/**", "docs/a.md") is True  # one glob given as a string
    assert sets_overlap(["", None, "docs/**"], ["src/**", 7]) is False  # unusable globs ignored
    assert sets_overlap((g for g in ["a/**"]), (g for g in ["a/b"])) is True  # any iterable


# ── Property: a path matching both globs always means "may overlap" ─────────

_SEGMENTS = ["a", "b", "ab", "A", "src", "x.py", "Makefile", ".d"]
_COMPONENTS = [
    "a", "b", "ab", "A", "src", "x.py", "Makefile", ".d",
    "*", "**", "*.py", "a*", "*b", "s*c", "?", "[ab]", "[!a]*", "[A-Z]*", "a?", "*a*",
]
_LEADS = ["", "", "", "./", "/", "**/", "./**/", ".\\"]


def _paths() -> List[str]:
    out: List[str] = []
    for depth in (1, 2, 3):
        out += ["/".join(p) for p in itertools.product(_SEGMENTS, repeat=depth)]
    return out


def _globs(count: int, seed: int) -> List[str]:
    rng = random.Random(seed)
    fixed = [
        "Makefile", "*.py", "**", "*", "a/**", "a/b*", "a/c/**", "src/*.py", "src/a/**",
        "**/x.py", "a*b", "a*/x.py", "A/**", "./a/b", "a\\b", ".d/**", "*/src/*",
    ]
    out = list(fixed)
    while len(out) < count:
        depth = rng.choice((1, 1, 2, 2, 3))
        parts = [rng.choice(_COMPONENTS) for _ in range(depth)]
        sep = rng.choice(("/", "/", "/", "\\"))
        out.append(rng.choice(_LEADS) + sep.join(parts))
    return out


def test_property_never_disjoint_when_a_path_matches_both():
    paths = _paths()
    globs = list(dict.fromkeys(_globs(260, seed=20261016)))
    matched: Dict[str, FrozenSet[str]] = {g: frozenset(p for p in paths if matches(g, p)) for g in globs}

    common_pairs = disjoint_answers = 0
    unsound = []
    for a, b in itertools.combinations_with_replacement(globs, 2):
        answer = may_overlap(a, b)
        assert answer is may_overlap(b, a), (a, b)
        both = matched[a] & matched[b]
        if both:
            common_pairs += 1
            if not answer:
                unsound.append((a, b, sorted(both)[:3]))
        elif not answer:
            disjoint_answers += 1
    assert unsound == [], f"may_overlap said disjoint for globs a path matches both of: {unsound[:5]}"
    # The generator exercises both answers, so the property is not vacuous.
    assert common_pairs > 1000
    assert disjoint_answers > 1000
