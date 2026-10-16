"""The README is also the PyPI project page, so it has to work there too.

PyPI resolves no relative links and renders no mermaid, so the README links the
repository's files by absolute GitHub URLs. tests/unit/test_docs_links.py checks only
relative links; this module checks that every absolute link into this repository (and
every pyproject [project.urls] entry) names a path that exists here, a file for
``blob/`` and a directory for ``tree/``. It also holds ADR 0005 AD-8 to its word: the
README states the enforcement tiers exactly as ``aegis doctor`` reports them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
README = ROOT / "README.md"
PYPROJECT = ROOT / "pyproject.toml"
REPO_URL = "https://github.com/nseney1/Aegis-Guardrails"

# Strict xfails for links whose target another lane of the same wave creates; an XPASS
# fails the suite, so each entry must go when that lane lands.
DEFERRED = {
    "CHANGELOG.md": "lane f2-why-and-rest moves docs/project/CHANGELOG.md to the root CHANGELOG.md",
}

_REPO_LINK = re.compile(re.escape(REPO_URL) + r"/(blob|tree)/main/([^\s)\"'<>#?]+)")


def repo_links(text: str) -> List[Tuple[str, str]]:
    """(kind, path) for each absolute link into this repository's main branch, in order."""
    found = []
    for match in _REPO_LINK.finditer(text):
        link = (match.group(1), match.group(2).rstrip("/"))
        if link not in found:
            found.append(link)
    return found


def link_problem(root: Path, kind: str, path: str) -> Optional[str]:
    """Why ``kind``/``path`` does not resolve inside ``root``, or None when it does."""
    target = root.joinpath(*path.split("/"))
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError:
        return f"{path} is outside the repository"
    if kind == "blob" and not target.is_file():
        return f"blob/main/{path} is not a file in the repository"
    if kind == "tree" and not target.is_dir():
        return f"tree/main/{path} is not a directory in the repository"
    return None


def _all_links() -> List[Tuple[str, str]]:
    links = repo_links(README.read_text(encoding="utf-8"))
    for link in repo_links(PYPROJECT.read_text(encoding="utf-8")):
        if link not in links:
            links.append(link)
    return links


def _params():
    for kind, path in _all_links():
        reason = DEFERRED.get(path)
        marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
        yield pytest.param(kind, path, id=f"{kind}/{path}", marks=marks)


@pytest.mark.parametrize("kind,path", list(_params()))
def test_absolute_repository_links_resolve(kind, path):
    assert link_problem(ROOT, kind, path) is None


def test_the_readme_links_the_docs_by_absolute_url():
    """Without absolute links the PyPI page has no way into the docs."""
    paths = {path for _, path in _all_links()}
    assert {"docs/how-it-works.md", "docs/reference.md"} <= paths


def test_the_readme_has_no_mermaid_block():
    """PyPI shows a mermaid fence as raw text; diagrams belong in docs/."""
    assert not re.search(r"^ {0,3}(`{3,}|~{3,})\s*mermaid", README.read_text(encoding="utf-8"), re.M)


def test_the_readme_states_the_enforcement_tiers_as_doctor_reports_them(tmp_path, monkeypatch, capsys):
    """AD-8: `aegis doctor` reports each tier and the README states it verbatim.

    Doctor runs in an empty directory on a fake machine (own HOME, an empty PATH, host
    CLIs refused), so no real host is read or started.
    """
    from aegis_cli import doctor
    from aegis_cli.cli import main

    home, empty_bin, work = tmp_path / "home", tmp_path / "bin", tmp_path / "work"
    for directory in (home, empty_bin, work):
        directory.mkdir()
    for name, value in (("HOME", home), ("USERPROFILE", home), ("PATH", empty_bin),
                        ("APPDATA", home / "AppData" / "Roaming")):
        monkeypatch.setenv(name, str(value))
    for name in ("CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME", "CODEX_HOME", "AEGIS_WORKSPACE", "AEGIS_CLIENT"):
        monkeypatch.delenv(name, raising=False)

    def refuse(argv, *args, **kwargs):
        raise AssertionError(f"a host CLI was started: {argv}")

    monkeypatch.setattr(doctor, "_run_host_cli", refuse)
    monkeypatch.chdir(work)
    main(["doctor", "--json", "--workspace", str(work)])
    tiers = json.loads(capsys.readouterr().out)["enforcement_tiers"]

    readme = README.read_text(encoding="utf-8")
    assert [t["tier"] for t in tiers] == ["advisory", "best_effort", "local_floor", "authoritative"]
    for tier in tiers:
        name = tier["tier"].replace("_", " ").capitalize().replace("Best effort", "Best-effort")
        row = re.search(rf"^\|\s*{re.escape(name)}\s*\|\s*{re.escape(tier['mechanism'])}\s*\|", readme, re.M)
        assert row, f"README has no tier row '| {name} | {tier['mechanism']} |'"


# --- the link checker itself ---------------------------------------------------------

def test_repo_links_finds_blob_and_tree_links_and_drops_fragments():
    text = (
        f"[a]({REPO_URL}/blob/main/docs/a.md#part) [b]({REPO_URL}/tree/main/rules/) "
        f"[c](https://example.com/blob/main/x.md) [d]({REPO_URL}/blob/main/docs/a.md) "
        f"[e]({REPO_URL}/releases) <{REPO_URL}/blob/main/LICENSE>\n"
        f'Changelog = "{REPO_URL}/blob/main/CHANGELOG.md"\n'
    )
    assert repo_links(text) == [("blob", "docs/a.md"), ("tree", "rules"), ("blob", "LICENSE"),
                                ("blob", "CHANGELOG.md")]


def test_link_problem_requires_a_file_for_blob_and_a_directory_for_tree(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("x\n", encoding="utf-8")
    assert link_problem(tmp_path, "blob", "docs/a.md") is None
    assert link_problem(tmp_path, "tree", "docs") is None
    assert link_problem(tmp_path, "blob", "docs") == "blob/main/docs is not a file in the repository"
    assert link_problem(tmp_path, "tree", "docs/a.md") == "tree/main/docs/a.md is not a directory in the repository"
    assert link_problem(tmp_path, "blob", "docs/gone.md") == "blob/main/docs/gone.md is not a file in the repository"


def test_link_problem_rejects_paths_that_leave_the_repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "outside.md").write_text("x\n", encoding="utf-8")
    assert link_problem(root, "blob", "../outside.md") == "../outside.md is outside the repository"
