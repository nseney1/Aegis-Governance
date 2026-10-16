"""The host table and bootstrap text are the shared contract for the host plane."""
import os

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
        ("kiro", "kiro"),  # SECONDARY: a Kiro IDE 0.11 log; the Kiro CLI's name is unknown
        ("Q DEV CLI", "generic"),  # the Kiro CLI's predecessor: a hint, never a match
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


def test_phase_one_hosts_are_the_three_the_author_runs_plus_kiro_and_desktop_identity():
    assert {h.id for h in hosts.all_hosts(phase=1)} == {
        "codex-cli", "claude-code", "claude-desktop", "antigravity", "kiro"}
    assert hosts.get("claude-desktop").registration is None


RETIRED_GEMINI_CLI = ("gemini-cli is not supported: Google retired Gemini CLI for individual Code Assist "
                      "accounts; use --host antigravity.")


def test_without_a_phase_every_host_is_listed_in_table_order():
    assert hosts.all_hosts() == hosts.HOSTS
    assert {h.id for h in hosts.all_hosts(phase=1)} < {h.id for h in hosts.all_hosts()}


def test_gemini_cli_is_retired_and_kept_only_to_name_the_client():
    # Google no longer serves Gemini CLI to individual Code Assist accounts; Antigravity is
    # the Gemini-family host. The row stays so identify() can name the client if it connects,
    # and that client keeps its own ${SLOT.*} profile.
    row = hosts.get("gemini-cli")
    assert row.retired == RETIRED_GEMINI_CLI
    assert row.registration is None
    assert row.verified is False
    assert row.slot_profile == "gemini-cli"
    assert row.phase == 2
    assert row.notes == (
        "Retired: Google no longer serves Gemini CLI to individual Code Assist accounts; "
        "Antigravity is the Gemini-family host. Identity only.",
    )
    assert hosts.identify("gemini-cli-mcp-client") == "gemini-cli"


def test_only_gemini_cli_is_retired_and_a_retired_row_never_registers():
    assert [h.id for h in hosts.HOSTS if h.retired] == ["gemini-cli"]
    assert hosts.get("claude-desktop").retired == ""
    for h in hosts.HOSTS:
        if h.retired:
            assert h.registration is None, h.id


def test_skills_dirs_are_the_documented_project_directories_and_none_is_verified():
    # v4.1 §3: skills project to .claude/skills (Claude Code, DOC) and the shared
    # .agents/skills (Antigravity DOC, Codex UNVERIFIED). Nothing was probed on a real
    # install, so no skills_verified is True; it is separate from the row's verified.
    assert {h.id: (h.skills_dir, h.skills_verified) for h in hosts.HOSTS} == {
        "codex-cli": (".agents/skills", False),
        "claude-code": (".claude/skills", False),
        "claude-desktop": (None, False),
        "antigravity": (".agents/skills", False),
        "gemini-cli": (None, False),
        "kiro": (None, False),
    }
    assert hosts.get("claude-code").verified is True  # the row's own flag is untouched


def test_a_skills_dir_is_a_workspace_relative_posix_directory():
    for h in hosts.HOSTS:
        if h.skills_dir is None:
            continue
        assert not h.skills_dir.startswith(("/", "~", ".\\")) and "\\" not in h.skills_dir, h.id
        assert ".." not in h.skills_dir.split("/") and not h.skills_dir.endswith("/"), h.id
        assert h.registration is not None and not h.retired, h.id


def test_new_host_fields_default_to_no_skills():
    row = hosts.HostSpec(id="x", display_name="X", vendor="V")
    assert row.skills_dir is None and row.skills_verified is False


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


def test_the_hook_notes_state_the_planned_v41_tiers_as_adr_0005_ad8_does():
    """AD-8 as amended on 2026-10-16: Claude Code blocks with exit 2; Codex blocks once the
    hook is trusted in /hooks; every hook fails open on an Aegis error."""
    assert "PreToolUse hooks can block with exit 2." in hosts.get("claude-code").notes
    assert "Hooks need trust in /hooks and fail open on errors." in hosts.get("codex-cli").notes
    for row in hosts.HOSTS:
        assert not any("strongest host" in n or "need user approval" in n for n in row.notes), row.id


# ── surfaces, aliases and app detection (v4.1 rev 3.1, d4-host-surfaces) ────────────

def test_a_host_is_a_config_plane_and_lists_the_surfaces_that_share_it():
    """The CLI, IDE extension and desktop app of one family read one config plane, so they
    are one host; ``surfaces`` names them so users see their app or IDE is covered."""
    assert {h.id: h.surfaces for h in hosts.HOSTS} == {
        "codex-cli": ("Codex CLI", "Codex IDE extension", "ChatGPT desktop app (Codex mode)"),
        "claude-code": ("Claude Code CLI", "Claude Code IDE extensions", "Claude desktop app (Code tab)"),
        "claude-desktop": ("Claude desktop app (chat)", "Claude desktop app (Cowork)"),
        "antigravity": ("Antigravity app", "Antigravity IDE", "agy CLI"),
        "gemini-cli": (),
        "kiro": ("Kiro IDE", "Kiro CLI"),
    }


@pytest.mark.parametrize("name, plane", [
    ("codex-cli", "codex-cli"), ("codex", "codex-cli"), ("codex-ide", "codex-cli"), ("codex-app", "codex-cli"),
    ("chatgpt-desktop", "codex-cli"), ("claude-code", "claude-code"), ("claude-desktop-code", "claude-code"),
    ("antigravity-app", "antigravity"), ("antigravity-ide", "antigravity"), ("kiro-ide", "kiro"),
    ("kiro-cli", "kiro"), ("kiro", "kiro"), ("claude-desktop", "claude-desktop"), ("gemini-cli", "gemini-cli"),
])
def test_resolve_maps_a_surface_alias_to_its_plane_id(name, plane):
    assert hosts.resolve(name) == plane


@pytest.mark.parametrize("name", ["gemini", "Codex-App", "cursor", "", " codex"])
def test_resolve_refuses_anything_else_and_names_the_ids_and_aliases(name):
    with pytest.raises(KeyError) as exc:
        hosts.resolve(name)
    assert "codex-cli" in str(exc.value) and "codex-app" in str(exc.value)


def test_aliases_are_unique_and_never_shadow_a_plane_id():
    ids = {h.id for h in hosts.HOSTS}
    aliases = [a for h in hosts.HOSTS for a in h.aliases]
    assert len(aliases) == len(set(aliases))
    assert not ids & set(aliases)
    # A retired or identity-only row takes no alias: an alias exists to reach a plane Aegis registers.
    assert all(not h.aliases for h in hosts.HOSTS if h.registration is None)


def test_kiro_is_an_experimental_json_file_host_that_reads_agents_md():
    """Kiro IDE and Kiro CLI share ~/.kiro (DOC): MCP in settings/mcp.json under mcpServers,
    AGENTS.md always included. No hooks and no project skills in v4.1; the row stays
    unverified until it is checked on a real install."""
    row = hosts.get("kiro")
    assert row.registration == hosts.Registration(kind="json_file", path="~/.kiro/settings/mcp.json",
                                                  key="mcpServers")
    assert row.instructions == "agents_md"
    assert row.binaries == ("kiro-cli",)
    assert row.config_paths == ("~/.kiro",)
    assert row.client_names == ("kiro",)
    assert (row.phase, row.verified, row.retired, row.skills_dir) == (1, False, "", None)
    assert row.slot_profile == hosts.GENERIC


def test_claude_desktop_stays_identity_only_and_points_the_code_tab_at_claude_code():
    row = hosts.get("claude-desktop")
    assert row.registration is None and row.instructions == "none"
    assert "--host claude-code" in row.redirect


def test_config_paths_cover_claude_codes_user_config_file():
    assert hosts.get("claude-code").config_paths == ("~/.claude", "~/.claude.json")
    assert hosts.get("antigravity").config_paths == ("~/.gemini/config", "~/.gemini/antigravity")


def test_app_paths_follow_the_platform_and_resolve_home_and_environment(tmp_path):
    home = tmp_path / "home"
    local = tmp_path / "local"
    kiro, codex = hosts.get("kiro"), hosts.get("codex-cli")
    assert hosts.app_paths(kiro, home, {}, "darwin") == [
        os.path.join("/Applications", "Kiro.app"), os.path.join(str(home), "Applications", "Kiro.app")]
    assert hosts.app_paths(codex, home, {}, "darwin") == [
        os.path.join("/Applications", "Codex.app"), os.path.join(str(home), "Applications", "Codex.app")]
    assert hosts.app_paths(kiro, home, {"LOCALAPPDATA": str(local)}, "win32") == [
        os.path.join(str(local), "Programs", "Kiro")]
    # An unset or relative variable names no place: nothing is guessed.
    assert hosts.app_paths(kiro, home, {}, "win32") == []
    assert hosts.app_paths(kiro, home, {"LOCALAPPDATA": "rel"}, "win32") == []
    assert hosts.app_paths(kiro, home, {}, "linux") == []
    assert hosts.app_paths(hosts.get("claude-code"), home, {}, "darwin") == []
