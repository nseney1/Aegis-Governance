"""The host table and bootstrap text are the shared contract for the host plane."""
import pytest

from aegis_core import bootstrap, hosts


@pytest.mark.parametrize(
    "client_name, expected",
    [
        ("codex-mcp-client", "codex-cli"),
        ("claude-code", "claude-code"),
        ("local-agent-mode-3f9a", "claude-desktop"),
        ("antigravity-client", "antigravity"),
        ("gemini-cli-mcp-client", "gemini-cli"),
        ("cursor-vscode", "generic"),
        ("Claude-Code", "generic"),  # exact match only: no case folding guesses
        ("", "generic"),
        (None, "generic"),
    ],
)
def test_identify_maps_client_names_exactly_and_never_guesses_a_vendor(client_name, expected):
    assert hosts.identify(client_name) == expected


def test_unknown_host_id_names_the_known_ones():
    with pytest.raises(KeyError) as exc:
        hosts.get("gemini")
    assert "codex-cli" in str(exc.value) and "antigravity" in str(exc.value)


def test_every_row_is_well_formed():
    ids = [h.id for h in hosts.HOSTS]
    assert len(ids) == len(set(ids))
    for h in hosts.HOSTS:
        assert h.instructions in hosts.INSTRUCTION_MODES, h.id
        if h.registration is None:
            continue
        if h.registration.kind == "native_cli":
            assert "{command}" in h.registration.argv, h.id
            assert "aegis" in h.registration.argv, h.id
            assert f"AEGIS_CLIENT={h.id}" in h.registration.argv, h.id
        else:
            assert h.registration.kind == "json_file", h.id
            assert h.registration.path.startswith("~/"), h.id


def test_phase_one_hosts_are_the_three_the_author_runs_plus_desktop_identity():
    assert {h.id for h in hosts.all_hosts(phase=1)} == {"codex-cli", "claude-code", "claude-desktop", "antigravity"}
    assert hosts.get("claude-desktop").registration is None


def test_gemini_cli_is_retired_and_kept_only_to_name_the_client():
    # Google no longer serves Gemini CLI to individual Code Assist accounts; Antigravity is
    # the Gemini-family host. The row stays so identify() can name the client if it connects.
    row = hosts.get("gemini-cli")
    assert row.registration is None
    assert row.verified is False
    assert row.slot_profile == hosts.GENERIC
    assert row.phase == 2
    assert row.notes == (
        "Retired: Google no longer serves Gemini CLI to individual Code Assist accounts; "
        "Antigravity is the Gemini-family host. Identity only.",
    )
    assert hosts.identify("gemini-cli-mcp-client") == "gemini-cli"


def test_bootstrap_fits_every_host_budget_and_carries_no_rule_bodies():
    text = bootstrap.bootstrap_text()
    size = len(text.encode("utf-8"))
    assert size <= 700
    for h in hosts.HOSTS:
        if h.budget_bytes:
            assert size < h.budget_bytes
    assert "aegis_scan" in text and "aegis_report_outcome" in text and "aegis scan" in text
    assert "---" not in text  # no frontmatter, so no rule file was pasted in


def test_instructions_first_512_characters_stand_alone():
    head = bootstrap.instructions_text()[:512]
    assert "aegis_scan" in head and "aegis_report_outcome" in head
