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


def test_supported_versions_cover_the_current_major_line():
    from aegis_core._version import __version__

    major = __version__.split(".", 1)[0]
    table = _section(_security_text(), "Supported Versions")
    rows = [line for line in table.splitlines() if line.lstrip().startswith(f"| {major}.")]
    assert rows, f"the Supported Versions table has no {major}.x row"
    assert "✅" in rows[0], f"the {major}.x row is not marked supported: {rows[0]!r}"


# Claims the code does not back (ADR 0005 §5): each was in a policy document and was cut or
# never implemented. Matching is case-insensitive.
POLICY_DOCS = ("SECURITY.md", "PRIVACY.md", "CONTRIBUTING.md", "NOTICE")
RETRACTED = (
    "Ed25519",                # never implemented; the v3 manifest was HMAC-SHA256 and is gone (D3)
    "aegis_request_receipt",  # receipts were cut (D2)
    "17 MCP tools",           # the server has 4 tools (D4)
    "air-gapped",             # Layer 2 sends a diff to the --llm-cmd command when asked
    "count_tokens",           # the Gemini token measurement was cut with the metrics census (D7)
    "check --release",        # Release Gate 4.5 was cut (D6)
    "aegis system",           # a removed command (D5)
    "DirectSDKBackend",       # the vendor SDK backends were cut (D14)
)


def retracted_claims_in(text):
    lowered = text.lower()
    return [phrase for phrase in RETRACTED if phrase.lower() in lowered]


def test_policy_documents_make_no_retracted_claim():
    found = {name: retracted_claims_in(read(str(ROOT / name))) for name in POLICY_DOCS}
    assert {name: hits for name, hits in found.items() if hits} == {}


def test_retracted_claim_guard_is_case_insensitive():
    assert retracted_claims_in("Keys are ED25519 and the server is Air-Gapped.") == ["Ed25519", "air-gapped"]
