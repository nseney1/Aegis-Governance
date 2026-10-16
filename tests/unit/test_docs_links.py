"""Relative links in the repository's Markdown docs must resolve.

Covers every root-level *.md (README, CONTRIBUTING, SECURITY, PRIVACY, ...) and
docs/**/*.md. A link is checked when its target is a repository path: URLs with
a scheme, protocol-relative URLs and same-page anchors are skipped, and any
#fragment or ?query is dropped. Links inside fenced code blocks and inline code
spans are not links. A target must exist with the exact case it is written in,
because GitHub resolves paths case-sensitively even when the checkout's file
system does not, and it must stay inside the repository.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator, List, Optional, Tuple
from urllib.parse import unquote

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())

# Strict xfails document deferrals named in the lane debrief; each must be
# removed when its owner fixes the file (an XPASS fails the suite).
DEFERRED = {
    "README.md": (
        "the v3 README links docs/guides/* and docs/project/CHANGELOG.md, which lane f2 deleted or "
        "moved; lane f1-readme-how rewrites the README, and its merge removes this entry"
    ),
}

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_CODE_SPAN = re.compile(r"(`+)(?:(?!\1).)+?\1")
_INLINE = re.compile(r"!?\[(?:[^\]\\]|\\.)*\]\(\s*(<[^>]*>|[^\s)]+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)")
_REFERENCE = re.compile(r"^ {0,3}\[(?!\^)[^\]]+\]:\s*(<[^>]*>|\S+)")  # [^n]: is a footnote
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def link_targets(text: str) -> Iterator[Tuple[int, str]]:
    """Yield (line number, raw target) for every inline and reference link outside code."""
    fence: Optional[str] = None
    for lineno, line in enumerate(text.splitlines(), 1):
        opener = _FENCE.match(line)
        if fence is not None:
            if opener and opener.group(1)[0] == fence[0] and len(opener.group(1)) >= len(fence):
                fence = None
            continue
        if opener:
            fence = opener.group(1)
            continue
        visible = _CODE_SPAN.sub("", line)
        for match in _INLINE.finditer(visible):
            yield lineno, match.group(1)
        reference = _REFERENCE.match(visible)
        if reference:
            yield lineno, reference.group(1)


def _local_path(target: str) -> Optional[str]:
    target = target[1:-1] if target.startswith("<") and target.endswith(">") else target
    if not target or target.startswith(("#", "//")) or _SCHEME.match(target):
        return None
    path = re.split(r"[#?]", target, maxsplit=1)[0]
    return unquote(path) or None


def _exists_with_exact_case(root: Path, relative: Path) -> bool:
    here = root
    for part in relative.parts:
        try:
            names = os.listdir(here)
        except OSError:
            return False
        if part not in names:
            return False
        here = here / part
    return True


def broken_links(doc: Path, root: Path) -> List[str]:
    """Return 'line: target' for each relative link in doc that does not resolve inside root."""
    problems = []
    for lineno, target in link_targets(doc.read_text(encoding="utf-8")):
        path = _local_path(target)
        if path is None:
            continue
        base = root if path.startswith("/") else doc.parent  # GitHub reads /x as repo-root-relative
        resolved = Path(os.path.normpath(base / path.lstrip("/")))
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            problems.append(f"{lineno}: {target} (outside the repository)")
            continue
        if not _exists_with_exact_case(root, relative):
            problems.append(f"{lineno}: {target}")
    return problems


def _docs() -> List[Path]:
    return sorted(ROOT.glob("*.md")) + sorted((ROOT / "docs").rglob("*.md"))


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _params():
    for doc in _docs():
        reason = DEFERRED.get(_rel(doc))
        marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
        yield pytest.param(doc, id=_rel(doc), marks=marks)


@pytest.mark.parametrize("doc", list(_params()))
def test_relative_links_resolve(doc):
    assert broken_links(doc, ROOT) == [], f"{_rel(doc)} has broken relative links"


def test_the_checked_set_includes_the_readme_and_the_docs_tree():
    checked = {_rel(p) for p in _docs()}
    assert "README.md" in checked
    assert any(name.startswith("docs/") for name in checked)


def test_every_deferral_names_a_checked_doc():
    """A deferral for a moved or deleted doc would otherwise linger silently."""
    checked = {_rel(p) for p in _docs()}
    assert sorted(set(DEFERRED) - checked) == []


# --- the checker itself -----------------------------------------------------------

def _write(root: Path, rel: str, text: str = "x\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_checker_reports_a_missing_target_with_its_line(tmp_path):
    doc = _write(tmp_path, "docs/a.md", "# A\n\nSee [b](b.md) and [gone](gone.md).\n")
    _write(tmp_path, "docs/b.md")
    assert broken_links(doc, tmp_path) == ["3: gone.md"]


def test_checker_resolves_relative_to_the_document_and_accepts_directories(tmp_path):
    doc = _write(tmp_path, "docs/guides/a.md", "[up](../../README.md) [dir](../adr/) [sib](./b.md)\n")
    _write(tmp_path, "README.md")
    _write(tmp_path, "docs/adr/0001.md")
    _write(tmp_path, "docs/guides/b.md")
    assert broken_links(doc, tmp_path) == []


def test_checker_skips_urls_anchors_and_mail(tmp_path):
    doc = _write(tmp_path, "a.md", (
        "[w](https://example.com/x.md) [p](//cdn.example/x.md) [m](mailto:a@b.c)\n"
        "[same page](#install)\n"
    ))
    assert broken_links(doc, tmp_path) == []


def test_checker_drops_fragments_and_queries_but_still_checks_the_path(tmp_path):
    doc = _write(tmp_path, "a.md", "[ok](b.md#section) [q](b.md?plain=1) [bad](c.md#x)\n")
    _write(tmp_path, "b.md")
    assert broken_links(doc, tmp_path) == ["1: c.md#x"]


def test_checker_ignores_fenced_code_and_inline_code(tmp_path):
    doc = _write(tmp_path, "a.md", (
        "```md\n[fenced](missing1.md)\n```\n"
        "~~~~\n```\n[tilde](missing2.md)\n~~~~\n"
        "Inline `[code](missing3.md)` is not a link, but [this](missing4.md) is.\n"
    ))
    assert broken_links(doc, tmp_path) == ["8: missing4.md"]


def test_checker_handles_titles_angle_brackets_images_and_references(tmp_path):
    doc = _write(tmp_path, "a.md", (
        '[t](b.md "Title") ![img](img/missing.png) [sp](<my file.md>)\n'
        "[ref]: missing-ref.md\n"
        "[enc](my%20file.md)\n"
    ))
    _write(tmp_path, "b.md")
    _write(tmp_path, "my file.md")
    assert broken_links(doc, tmp_path) == ["1: img/missing.png", "2: missing-ref.md"]


def test_checker_reads_a_leading_slash_as_the_repository_root(tmp_path):
    doc = _write(tmp_path, "docs/guides/a.md", "[root](/README.md) [bad](/nope.md)\n")
    _write(tmp_path, "README.md")
    assert broken_links(doc, tmp_path) == ["1: /nope.md"]


def test_checker_ignores_footnote_definitions(tmp_path):
    doc = _write(tmp_path, "a.md", "Claim.[^1]\n\n[^1]: Source text, not a link.\n")
    assert broken_links(doc, tmp_path) == []


def test_checker_rejects_links_that_leave_the_repository(tmp_path):
    root = tmp_path / "repo"
    doc = _write(root, "a.md", "[out](../outside.md)\n")
    _write(tmp_path, "outside.md")
    assert broken_links(doc, root) == ["1: ../outside.md (outside the repository)"]


def test_checker_requires_the_exact_case(tmp_path):
    doc = _write(tmp_path, "a.md", "[c](Docs/Guide.md) [ok](docs/guide.md)\n")
    _write(tmp_path, "docs/guide.md")
    assert broken_links(doc, tmp_path) == ["1: Docs/Guide.md"]
