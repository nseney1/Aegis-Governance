"""SECURITY.md must exist, cover the required sections and name a private reporting channel."""
import re
from pathlib import Path

from conftest import REPO_ROOT, read

ROOT = Path(REPO_ROOT)
SECURITY = ROOT / "SECURITY.md"


def _security_text():
    assert SECURITY.is_file(), "SECURITY.md is missing from the repository root"
    return read(str(SECURITY))


def _section(text, title):
    match = re.search(rf"^##\s+{re.escape(title)}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    assert match, f"SECURITY.md has no '## {title}' section"
    return match.group(1)


def test_security_policy_has_required_sections():
    text = _security_text()
    for title in ("Supported Versions", "Reporting a Vulnerability", "Scope"):
        assert _section(text, title).strip(), f"'## {title}' section is empty"


def test_reporting_uses_private_channel_not_public_issues():
    reporting = _section(_security_text(), "Reporting a Vulnerability")
    assert "Report a vulnerability" in reporting
    assert "private" in reporting.lower()


def test_readme_links_to_security_policy():
    readme = read(str(ROOT / "README.md"))
    assert re.search(r"\]\((\./)?SECURITY\.md\)", readme), "README.md does not link to SECURITY.md"
