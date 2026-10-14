"""Behavioral tests for pure Python PlatformAdapters."""
import json
from pathlib import Path
import pytest

from aegis_cli.platforms import (
    PlatformAdapter,
    PlatformInstallResult,
    GeminiAdapter,
    ClaudeAdapter,
    KiroAdapter,
    CopilotAdapter,
    McpAdapter,
    get_adapter,
)


def test_get_adapter_registry():
    """Verify registry returns correct adapter instances for all supported platforms."""
    expected = {
        "gemini": GeminiAdapter,
        "claude": ClaudeAdapter,
        "kiro": KiroAdapter,
        "copilot": CopilotAdapter,
        "mcp": McpAdapter,
    }
    for name, expected_cls in expected.items():
        adapter = get_adapter(name)
        assert isinstance(adapter, expected_cls)
        assert adapter.name == name

    with pytest.raises(ValueError, match="Unknown platform"):
        get_adapter("unknown-platform-xyz")


def test_gemini_adapter_install_and_uninstall(tmp_path):
    """Verify GeminiAdapter installs rules, skills, and hooks in isolated environment."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    genome = workspace / "genome"
    genome.mkdir()
    (genome / "providence.md").write_text("# Providence", encoding="utf-8")

    organs = workspace / "organs" / "test-skill"
    organs.mkdir(parents=True)
    (organs / "SKILL.md").write_text("# Test Skill", encoding="utf-8")

    adapter = GeminiAdapter(workspace=workspace, home=home)

    res = adapter.install(local=False, dry_run=False)
    assert res.success
    assert res.scope == "global"
    assert (home / ".gemini" / "config" / "rules" / "providence.md").is_file()
    assert (home / ".gemini" / "config" / "skills" / "test-skill" / "SKILL.md").is_file()
    assert (home / ".gemini" / "config" / "plugins" / "governance" / "hooks.json").is_file()
    assert adapter.verify(local=False)

    un_res = adapter.uninstall(local=False, dry_run=False)
    assert un_res.success
    assert not (home / ".gemini" / "config" / "rules" / "providence.md").exists()
    assert not (home / ".gemini" / "config" / "plugins" / "governance" / "hooks.json").exists()


def test_claude_adapter_install_and_uninstall(tmp_path):
    """Verify ClaudeAdapter writes CLAUDE.md integration instructions."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    adapter = ClaudeAdapter(workspace=workspace, home=home)
    res = adapter.install(local=True, dry_run=False)
    assert res.success
    claude_md = workspace / "CLAUDE.md"
    assert claude_md.is_file()
    assert adapter.verify(local=True)

    un_res = adapter.uninstall(local=True, dry_run=False)
    assert un_res.success
    assert not claude_md.exists()


def test_claude_adapter_preserves_user_content_on_uninstall(tmp_path):
    """BUG-088 (#142): Uninstalling Claude configuration must preserve existing user content."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    claude_md = workspace / "CLAUDE.md"
    user_content = "# My Custom Claude Config\n\n- Do not delete this file!\n"
    claude_md.write_text(user_content, encoding="utf-8")

    adapter = ClaudeAdapter(workspace=workspace, home=home)
    install_res = adapter.install(local=True, dry_run=False)
    assert install_res.success
    assert "Soma Governance Rules" in claude_md.read_text(encoding="utf-8")
    assert "# My Custom Claude Config" in claude_md.read_text(encoding="utf-8")

    uninstall_res = adapter.uninstall(local=True, dry_run=False)
    assert uninstall_res.success
    assert claude_md.is_file(), "CLAUDE.md was deleted instead of preserving user content!"
    assert claude_md.read_text(encoding="utf-8").strip() == user_content.strip()
    assert "Soma Governance Rules" not in claude_md.read_text(encoding="utf-8")
    assert not adapter.verify(local=True)


def test_claude_adapter_cleans_mcp_server_on_uninstall(tmp_path):
    """BUG-088 (#142): ClaudeAdapter uninstall cleans soma entry from .mcp.json."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    mcp_json = workspace / ".mcp.json"
    mcp_json.write_text(json.dumps({
        "mcpServers": {
            "soma": {"command": "soma-mcp", "args": []},
            "other": {"command": "other-tool", "args": []},
        }
    }), encoding="utf-8")

    adapter = ClaudeAdapter(workspace=workspace, home=home)
    res = adapter.uninstall(local=True, dry_run=False)
    assert res.success
    assert mcp_json.is_file()
    data = json.loads(mcp_json.read_text(encoding="utf-8"))
    assert "soma" not in data.get("mcpServers", {})
    assert "other" in data.get("mcpServers", {})


def test_claude_adapter_strips_legacy_header_on_uninstall(tmp_path):
    """Verify uninstall strips legacy un-marked Soma Governance Integration headers."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    claude_md = workspace / "CLAUDE.md"
    legacy_content = (
        "# Custom Intro\n\n"
        "# Soma Governance Integration\n\n"
        "Rules are checked adaptively.\n\n"
        "## Active Core Rules\n"
        "- `providence`: Providence\n\n"
        "# Custom Footer\n"
        "Keep this too.\n"
    )
    claude_md.write_text(legacy_content, encoding="utf-8")

    adapter = ClaudeAdapter(workspace=workspace, home=home)
    assert adapter.verify(local=True)

    un_res = adapter.uninstall(local=True, dry_run=False)
    assert un_res.success
    assert claude_md.is_file()
    content = claude_md.read_text(encoding="utf-8")
    assert "# Custom Intro" in content
    assert "# Custom Footer" in content
    assert "Keep this too." in content
    assert "Soma Governance Integration" not in content
    assert not adapter.verify(local=True)


def test_claude_adapter_idempotent_reinstall(tmp_path):
    """Verify reinstalling updates the marked block without duplication."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    claude_md = workspace / "CLAUDE.md"
    claude_md.write_text("# My Project\n", encoding="utf-8")

    adapter = ClaudeAdapter(workspace=workspace, home=home)
    res1 = adapter.install(local=True, dry_run=False)
    assert res1.success
    content1 = claude_md.read_text(encoding="utf-8")
    assert content1.count("<!-- SOMA:START -->") == 1

    res2 = adapter.install(local=True, dry_run=False)
    assert res2.success
    content2 = claude_md.read_text(encoding="utf-8")
    assert content2.count("<!-- SOMA:START -->") == 1
    assert content2.count("<!-- SOMA:END -->") == 1
    assert "# My Project" in content2


def test_claude_adapter_dry_run(tmp_path):
    """Verify dry_run does not mutate files on disk."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    adapter = ClaudeAdapter(workspace=workspace, home=home)
    res_install = adapter.install(local=True, dry_run=True)
    assert res_install.success
    assert not (workspace / "CLAUDE.md").exists()

    # Create file and test dry run uninstall
    claude_md = workspace / "CLAUDE.md"
    adapter.install(local=True, dry_run=False)
    assert claude_md.exists()

    res_uninstall = adapter.uninstall(local=True, dry_run=True)
    assert res_uninstall.success
    assert claude_md.exists()



def test_kiro_adapter_install_and_uninstall(tmp_path):
    """Verify KiroAdapter installs steering rules and skills."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    genome = workspace / "genome"
    genome.mkdir()
    (genome / "providence.md").write_text("# Providence", encoding="utf-8")

    adapter = KiroAdapter(workspace=workspace, home=home)
    res = adapter.install(local=False, dry_run=False)
    assert res.success
    assert (home / ".kiro" / "steering" / "providence.md").is_file()
    assert adapter.verify(local=False)

    un_res = adapter.uninstall(local=False, dry_run=False)
    assert un_res.success
    assert not (home / ".kiro" / "steering" / "providence.md").exists()


def test_copilot_adapter_install_and_uninstall(tmp_path):
    """Verify CopilotAdapter writes .github/copilot-instructions.md and instructions/."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    genome = workspace / "genome"
    genome.mkdir()
    (genome / "providence.md").write_text("# Providence", encoding="utf-8")

    adapter = CopilotAdapter(workspace=workspace)
    res = adapter.install(local=True, dry_run=False)
    assert res.success
    assert (workspace / ".github" / "copilot-instructions.md").is_file()
    assert (workspace / ".github" / "instructions" / "providence.md").is_file()
    assert adapter.verify()

    un_res = adapter.uninstall(local=True, dry_run=False)
    assert un_res.success
    assert not (workspace / ".github" / "copilot-instructions.md").exists()


def test_mcp_adapter_install_and_uninstall(tmp_path):
    """Verify McpAdapter writes and removes .mcp.json."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    adapter = McpAdapter(workspace=workspace)
    res = adapter.install(local=True, dry_run=False)
    assert res.success
    assert (workspace / ".mcp.json").is_file()
    assert adapter.verify(local=True)

    un_res = adapter.uninstall(local=True, dry_run=False)
    assert un_res.success
    assert not adapter.verify(local=True)


def test_claude_adapter_cleans_rule_files_on_uninstall(tmp_path):
    """BUG-091: ClaudeAdapter uninstall removes rule files installed in rules directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    adapter = ClaudeAdapter(workspace=workspace, home=home)
    install_res = adapter.install(local=False, dry_run=False)
    assert install_res.success
    claude_dir = home / ".claude"
    assert (claude_dir / "CLAUDE.md").is_file()
    # Starter rules should have been installed
    assert (claude_dir / "providence.md").is_file()

    un_res = adapter.uninstall(local=False, dry_run=False)
    assert un_res.success
    assert not (claude_dir / "providence.md").exists()


def test_claude_adapter_dry_run_wording(tmp_path):
    """BUG-093: Dry-run uninstall uses [dry-run] Would uninstall prefix."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    adapter = ClaudeAdapter(workspace=workspace, home=home)
    adapter.install(local=False, dry_run=False)
    claude_dir = home / ".claude"
    assert (claude_dir / "CLAUDE.md").is_file()

    dry_res = adapter.uninstall(local=False, dry_run=True)
    assert dry_res.success
    assert any("[dry-run] Would uninstall" in msg for msg in dry_res.messages)
    # File must still exist after dry-run
    assert (claude_dir / "CLAUDE.md").is_file()


def test_gemini_adapter_installs_meta_and_all_gate_rules(tmp_path: Path):
    """GeminiAdapter.install() must include META.md and all gate rules in installed rule files."""
    repo_root = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
    home = tmp_path / "home"
    home.mkdir()
    adapter = GeminiAdapter(workspace=repo_root, home=home)

    source_names = {p.name for p in adapter.get_source_rules()}
    assert "META.md" in source_names
    assert "gitflow-review-gate.md" in source_names
    assert "core-change-protocol.md" in source_names
    assert "ci-green-before-release.md" in source_names
    assert "no-pre-existing-excuse.md" in source_names

    res = adapter.install(local=False, dry_run=False)
    assert res.success
    installed_rules_dir = home / ".gemini" / "config" / "rules"
    for expected in (
        "META.md",
        "gitflow-review-gate.md",
        "core-change-protocol.md",
        "ci-green-before-release.md",
        "no-pre-existing-excuse.md",
        "providence.md",
    ):
        assert (installed_rules_dir / expected).is_file(), f"Missing installed rule: {expected}"


def test_gemini_adapter_local_target_dirs_prefers_aegis_workspace(tmp_path: Path):
    """When installing locally in a pure .aegis workspace, GeminiAdapter resolves .aegis rather than .soma."""
    ws = tmp_path / "ws"
    (ws / ".aegis" / "rules").mkdir(parents=True)
    adapter = GeminiAdapter(workspace=ws, home=tmp_path)
    rules_dir, skills_dir, hooks_dir = adapter.get_target_dirs(local=True)
    assert ".aegis" in str(rules_dir)
    assert ".soma" not in str(rules_dir)


