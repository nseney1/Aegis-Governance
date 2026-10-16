"""What the wheel and sdist ship for `aegis init` names only files that exist.

The starter rules moved from ``aegis_cli/starter_rules/`` to the packaged ``rules``
package (defense #20, one rule-source locator); the packaging entries that named the
old directory made every build warn about it and ship nothing for it.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())


def _package_data() -> dict:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = re.search(r"(?ms)^\[tool\.setuptools\.package-data\]\n(.*?)(?=^\[)", text)
    assert section, "pyproject.toml has no [tool.setuptools.package-data] table"
    entries = {}
    for name, globs in re.findall(r'(?m)^([A-Za-z0-9_.]+)\s*=\s*\[(.*?)\]', section.group(1)):
        entries[name] = re.findall(r'"([^"]+)"', globs)
    return entries


def test_every_package_data_glob_matches_a_file():
    entries = _package_data()
    assert entries, "no package-data entries parsed"
    for package, globs in entries.items():
        base = REPO_ROOT.joinpath(*package.split("."))
        for pattern in globs:
            assert any(p.is_file() for p in base.glob(pattern)), f"{package}: {pattern!r} matches no file"


def test_every_manifest_include_names_an_existing_directory():
    lines = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
    for line in lines:
        words = line.split()
        if words and words[0] in ("recursive-include", "graft"):
            assert (REPO_ROOT / words[1]).is_dir(), line


def test_the_retired_starter_rules_directory_is_named_nowhere_in_packaging():
    for name in ("pyproject.toml", "MANIFEST.in"):
        assert "starter_rules" not in (REPO_ROOT / name).read_text(encoding="utf-8"), name
