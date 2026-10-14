"""Tests for soma init — Phase B test gate.

All tests use tmp_path to avoid touching the real filesystem.
"""
import argparse

import pytest
from conftest import symlink_or_skip


class TestDetectPlatform:
    """Platform detection based on directory markers."""

    def test_gemini_detected(self, tmp_path):
        (tmp_path / ".gemini").mkdir()
        from aegis_cli.init import detect_platform
        assert detect_platform(tmp_path) == "gemini"

    def test_claude_detected(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        from aegis_cli.init import detect_platform
        assert detect_platform(tmp_path) == "claude"

    def test_cursor_detected_dir(self, tmp_path):
        (tmp_path / ".cursor").mkdir()
        from aegis_cli.init import detect_platform
        assert detect_platform(tmp_path) == "cursor"

    def test_cursor_detected_file(self, tmp_path):
        (tmp_path / ".cursorrules").write_text("")
        from aegis_cli.init import detect_platform
        assert detect_platform(tmp_path) == "cursor"

    def test_copilot_detected(self, tmp_path):
        gh = tmp_path / ".github" / "copilot"
        gh.mkdir(parents=True)
        from aegis_cli.init import detect_platform
        assert detect_platform(tmp_path) == "copilot"

    def test_kiro_detected(self, tmp_path):
        (tmp_path / ".kiro").mkdir()
        from aegis_cli.init import detect_platform
        assert detect_platform(tmp_path) == "kiro"

    def test_unknown_when_empty(self, tmp_path):
        from aegis_cli.init import detect_platform
        assert detect_platform(tmp_path) == "unknown"

    def test_gemini_takes_priority(self, tmp_path):
        """When multiple markers exist, gemini wins (most common)."""
        (tmp_path / ".gemini").mkdir()
        (tmp_path / ".cursor").mkdir()
        from aegis_cli.init import detect_platform
        assert detect_platform(tmp_path) == "gemini"


class TestDetectProjectType:
    """Project type detection based on config files."""

    def test_python_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("")
        from aegis_cli.init import detect_project_type
        assert detect_project_type(tmp_path) == "python"

    def test_python_setup_py(self, tmp_path):
        (tmp_path / "setup.py").write_text("")
        from aegis_cli.init import detect_project_type
        assert detect_project_type(tmp_path) == "python"

    def test_python_setup_cfg(self, tmp_path):
        (tmp_path / "setup.cfg").write_text("")
        from aegis_cli.init import detect_project_type
        assert detect_project_type(tmp_path) == "python"

    def test_javascript(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        from aegis_cli.init import detect_project_type
        assert detect_project_type(tmp_path) == "javascript"

    def test_rust(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("")
        from aegis_cli.init import detect_project_type
        assert detect_project_type(tmp_path) == "rust"

    def test_go(self, tmp_path):
        (tmp_path / "go.mod").write_text("")
        from aegis_cli.init import detect_project_type
        assert detect_project_type(tmp_path) == "go"

    def test_unknown_when_empty(self, tmp_path):
        from aegis_cli.init import detect_project_type
        assert detect_project_type(tmp_path) == "unknown"

    def test_accepts_str_path(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("")
        from aegis_cli.init import detect_project_type
        assert detect_project_type(str(tmp_path)) == "python"


class TestGetRulesDir:
    """Verify correct rules directory per platform."""

    def test_gemini_rules_dir(self, tmp_path):
        from aegis_cli.init import get_rules_dir
        result = get_rules_dir("gemini", tmp_path)
        assert result.parts[-3:] == (".gemini", "config", "rules")

    def test_cursor_rules_dir(self, tmp_path):
        from aegis_cli.init import get_rules_dir
        result = get_rules_dir("cursor", tmp_path)
        assert result.parts[-2:] == (".cursor", "rules")

    def test_claude_rules_dir(self, tmp_path):
        from aegis_cli.init import get_rules_dir
        result = get_rules_dir("claude", tmp_path)
        assert str(result).endswith(".claude")

    def test_kiro_rules_dir(self, tmp_path):
        from aegis_cli.init import get_rules_dir
        result = get_rules_dir("kiro", tmp_path)
        assert result.parts[-2:] == (".kiro", "steering")

    def test_unknown_raises(self, tmp_path):
        from aegis_cli.init import get_rules_dir
        with pytest.raises(ValueError, match="Unsupported platform"):
            get_rules_dir("unknown", tmp_path)

    def test_unknown_raises_local(self, tmp_path):
        from aegis_cli.init import get_rules_dir
        with pytest.raises(ValueError, match="Unsupported platform"):
            get_rules_dir("unknown", tmp_path, local=True)


class TestInstallStarterRules:
    """Verify starter rule installation."""

    def test_dry_run_creates_no_files(self, tmp_path):
        from aegis_cli.init import install_starter_rules
        rules_dir = tmp_path / "rules"
        installed = install_starter_rules(rules_dir, dry_run=True)
        assert len(installed) == 5
        assert not rules_dir.exists()

    def test_installs_five_rules(self, tmp_path):
        from aegis_cli.init import install_starter_rules
        rules_dir = tmp_path / "rules"
        installed = install_starter_rules(rules_dir, dry_run=False)
        assert len(installed) == 5
        assert rules_dir.exists()
        # Each rule should be a .md file in the target
        for name in installed:
            rule_file = rules_dir / f"{name}.md"
            assert rule_file.exists(), f"Missing: {rule_file}"
            content = rule_file.read_text()
            assert len(content) > 100, f"Rule {name} seems too short"

    def test_starter_rules_are_the_right_five(self, tmp_path):
        from aegis_cli.init import STARTER_RULES
        assert len(STARTER_RULES) == 5
        expected = {"providence", "destructive-ops", "testing",
                    "cost-optimization", "git-workflow"}
        assert set(STARTER_RULES) == expected


class TestExistingWorkspaceDir:
    """Verify behavior when .aegis/ or .soma/ already exists."""

    def test_existing_aegis_dir_detected(self, tmp_path):
        (tmp_path / ".aegis" / "rules").mkdir(parents=True)
        from aegis_cli.init import check_existing_install
        assert check_existing_install(tmp_path) is True

    def test_existing_soma_dir_detected(self, tmp_path):
        (tmp_path / ".soma").mkdir()
        from aegis_cli.init import check_existing_install
        assert check_existing_install(tmp_path) is True

    def test_no_governance_dir(self, tmp_path):
        from aegis_cli.init import check_existing_install
        assert check_existing_install(tmp_path) is False



class TestRunInit:
    """End-to-end init flow."""

    def test_init_dry_run(self, tmp_path, capsys):
        from aegis_cli.init import run_init
        (tmp_path / ".gemini").mkdir()
        (tmp_path / "pyproject.toml").write_text("")
        args = argparse.Namespace(
            dry_run=True, platform=None, yes=True,
            _project_root=tmp_path,  # test override
        )
        result = run_init(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "Detected platform" in captured.out or "gemini" in captured.out.lower()

    def test_init_with_forced_platform(self, tmp_path, capsys):
        from aegis_cli.init import run_init
        (tmp_path / "pyproject.toml").write_text("")
        args = argparse.Namespace(
            dry_run=True, platform="claude", yes=True,
            _project_root=tmp_path,
        )
        result = run_init(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "claude" in captured.out.lower()


class TestSkipExistingAndForce:
    """Tests for skip-existing and --force overwrite logic."""

    def test_skips_existing_rules(self, tmp_path):
        """Pre-existing rule with custom content is preserved without --force."""
        from aegis_cli.init import install_starter_rules
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        custom_content = "# My custom providence rule\nDo not touch."
        (rules_dir / "providence.md").write_text(custom_content)

        install_starter_rules(rules_dir, dry_run=False, force=False)

        assert (rules_dir / "providence.md").read_text() == custom_content

    def test_force_overwrites_existing(self, tmp_path):
        """Pre-existing rule is overwritten when force=True."""
        from aegis_cli.init import install_starter_rules
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        (rules_dir / "providence.md").write_text("old content")

        install_starter_rules(rules_dir, dry_run=False, force=True)

        new_content = (rules_dir / "providence.md").read_text()
        assert new_content != "old content"
        assert len(new_content) > 100  # real rule content


class TestSymlinkGuard:
    """Tests for symlink destination guard in install_starter_rules."""

    def test_symlink_destination_skipped(self, tmp_path):
        """Symlink destinations in rules_dir are not followed."""
        from aegis_cli.init import install_starter_rules
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        target_file = tmp_path / "target.txt"
        target_file.write_text("original target content")
        symlink_or_skip(target_file, rules_dir / "providence.md")

        install_starter_rules(rules_dir, dry_run=False, force=True)

        # Symlink should still be a symlink (skipped, not overwritten)
        assert (rules_dir / "providence.md").is_symlink()
        # Target file should be untouched
        assert target_file.read_text() == "original target content"


class TestCopilotInstructionsDetection:
    """Tests for copilot-instructions.md detection."""

    def test_copilot_detected_instructions_file(self, tmp_path):
        """copilot-instructions.md triggers copilot platform detection."""
        from aegis_cli.init import detect_platform
        gh_dir = tmp_path / ".github"
        gh_dir.mkdir()
        (gh_dir / "copilot-instructions.md").write_text("# Instructions")

        assert detect_platform(tmp_path) == "copilot"


class TestClaudeMd:
    """Tests for Claude CLAUDE.md concatenation."""

    def test_claude_md_created(self, tmp_path):
        """CLAUDE.md is created when installing for Claude platform."""
        from aegis_cli.init import _install_claude_md, install_starter_rules
        rules_dir = tmp_path / "claude_rules"
        install_starter_rules(rules_dir, dry_run=False)
        _install_claude_md(rules_dir)

        claude_md = rules_dir / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "<!-- SOMA:START -->" in content
        assert "<!-- SOMA:END -->" in content
        assert "providence" in content.lower()

    def test_claude_md_appends_to_existing(self, tmp_path):
        """CLAUDE.md appends Soma section to existing content."""
        from aegis_cli.init import _install_claude_md, install_starter_rules
        rules_dir = tmp_path / "claude_rules"
        install_starter_rules(rules_dir, dry_run=False)

        claude_md = rules_dir / "CLAUDE.md"
        claude_md.write_text("# Existing project instructions\n")
        _install_claude_md(rules_dir)

        content = claude_md.read_text()
        assert content.startswith("# Existing project instructions")
        assert "<!-- SOMA:START -->" in content

    def test_claude_md_skips_without_force(self, tmp_path):
        """CLAUDE.md soma section not replaced without --force."""
        from aegis_cli.init import _install_claude_md, install_starter_rules
        rules_dir = tmp_path / "claude_rules"
        install_starter_rules(rules_dir, dry_run=False)

        claude_md = rules_dir / "CLAUDE.md"
        claude_md.write_text("<!-- SOMA:START -->\nPLACEHOLDER_ORIGINAL_CONTENT_XYZ\n<!-- SOMA:END -->\n")
        _install_claude_md(rules_dir, force=False)

        assert "PLACEHOLDER_ORIGINAL_CONTENT_XYZ" in claude_md.read_text()

    def test_claude_md_replaces_with_force(self, tmp_path):
        """CLAUDE.md soma section replaced with --force."""
        from aegis_cli.init import _install_claude_md, install_starter_rules
        rules_dir = tmp_path / "claude_rules"
        install_starter_rules(rules_dir, dry_run=False)

        claude_md = rules_dir / "CLAUDE.md"
        claude_md.write_text("<!-- SOMA:START -->\nPLACEHOLDER_ORIGINAL_CONTENT_XYZ\n<!-- SOMA:END -->\n")
        _install_claude_md(rules_dir, force=True)

        content = claude_md.read_text()
        assert "PLACEHOLDER_ORIGINAL_CONTENT_XYZ" not in content
        assert "providence" in content.lower()


class TestConfirmation:
    """Tests for --yes confirmation prompt."""

    def test_init_aborts_without_yes(self, tmp_path, monkeypatch, capsys):
        """Init aborts when user says no to confirmation."""
        from aegis_cli.init import run_init
        (tmp_path / ".gemini").mkdir()
        monkeypatch.setattr("builtins.input", lambda _: "n")
        args = argparse.Namespace(
            dry_run=False, platform="gemini", yes=False, force=False,
            _project_root=tmp_path, _home=tmp_path,
        )
        result = run_init(args)
        assert result == 0
        assert "Aborted" in capsys.readouterr().out

    def test_init_proceeds_with_yes(self, tmp_path, capsys):
        """Init proceeds when --yes is passed."""
        from aegis_cli.init import run_init
        (tmp_path / ".gemini").mkdir()
        args = argparse.Namespace(
            dry_run=False, platform="gemini", yes=True, force=False,
            _project_root=tmp_path, _home=tmp_path,
        )
        result = run_init(args)
        assert result == 0
        assert "Done!" in capsys.readouterr().out


class TestPolyglotInit:
    """Tests for zero-touch polyglot driver provisioning in soma init."""

    def test_init_polyglot_language_detection_and_provisioning(self, tmp_path, capsys):
        from aegis_cli.init import run_init
        from aegis_core.skills.slots import SlotRegistry

        (tmp_path / "Cargo.toml").write_text("[package]\nname = 'rust_app'\n", encoding="utf-8")
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
        (tmp_path / ".git").mkdir()

        args = argparse.Namespace(
            dry_run=False, platform="gemini", yes=True, force=True,
            _project_root=tmp_path, _home=tmp_path, mcp=False, rules="minimal",
        )
        result = run_init(args)
        assert result == 0
        out = capsys.readouterr().out
        assert "Detected language(s): Rust" in out
        assert "Configured AST driver (.rs):" in out

        registry = SlotRegistry.load(tmp_path)
        assert registry.get_ast_driver(".rs") is not None
        assert (tmp_path / ".soma" / "drivers" / "rust_ast.py").is_file()

    def test_init_polyglot_dry_run(self, tmp_path, capsys):
        from aegis_cli.init import run_init

        (tmp_path / "Cargo.toml").write_text("[package]\nname = 'rust_app'\n", encoding="utf-8")
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
        (tmp_path / ".git").mkdir()

        args = argparse.Namespace(
            dry_run=True, platform="gemini", yes=True, force=True,
            _project_root=tmp_path, _home=tmp_path, mcp=False, rules="minimal",
        )
        result = run_init(args)
        assert result == 0
        out = capsys.readouterr().out
        assert "Would configure AST driver (.rs):" in out
        assert not (tmp_path / ".soma" / "slots.yaml").exists()

    def test_init_detected_project_type_fallback(self, tmp_path, capsys):
        from aegis_cli.init import run_init

        (tmp_path / "README.md").write_text("# Readme\n", encoding="utf-8")
        (tmp_path / ".git").mkdir()

        args = argparse.Namespace(
            dry_run=False, platform="gemini", yes=True, force=True,
            _project_root=tmp_path, _home=tmp_path, mcp=False, rules="minimal",
        )
        result = run_init(args)
        assert result == 0
        out = capsys.readouterr().out
        assert "Project type: unknown" in out

    def test_init_command_contract(self):
        from unittest.mock import patch
        from aegis_cli.init import InitCommand
        cmd = InitCommand()
        parser = argparse.ArgumentParser()
        cmd.configure_parser(parser)
        parsed = parser.parse_args([
            "--dry-run", "--platform", "claude", "--rules", "full",
            "--mcp", "--yes", "--force"
        ])
        assert parsed.dry_run is True
        assert parsed.platform == "claude"
        assert parsed.rules == "full"
        assert parsed.mcp is True
        assert parsed.yes is True
        assert parsed.force is True

        with patch("aegis_cli.init.run_init", return_value=0) as mock_run:
            assert cmd.execute(parsed) == 0
            mock_run.assert_called_once_with(parsed)

    def test_init_claude_uses_home_directory_not_project_root(self, tmp_path, monkeypatch):
        """BUG-089 (#143): soma init --platform claude must install to ~/.claude, not <project>/.claude."""
        from aegis_cli.init import run_init
        from aegis_core.workspace import Workspace

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()

        monkeypatch.setenv("HOME", str(home_dir))
        monkeypatch.setattr("pathlib.Path.home", lambda: home_dir)

        args = argparse.Namespace(
            project=str(project_dir),
            _project_root=project_dir,
            ws=Workspace.for_init(project_dir),
            platform="claude",
            rules="minimal",
            mcp=False,
            yes=True,
            force=True,
            dry_run=False,
        )

        rc = run_init(args)
        assert rc == 0
        assert not (project_dir / ".claude").exists(), "Claude rules were incorrectly installed into <project>/.claude!"
        assert (home_dir / ".claude").is_dir(), "Claude rules were not installed to ~/.claude!"
        assert (home_dir / ".claude" / "CLAUDE.md").is_file()

    def test_init_claude_local_installs_to_project_root(self, tmp_path, monkeypatch):
        """BUG-092: soma init --platform claude --local installs to <project>/.claude and <project>/CLAUDE.md."""
        from aegis_cli.init import run_init
        from aegis_core.workspace import Workspace

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        home_dir = tmp_path / "home"
        home_dir.mkdir()

        monkeypatch.setenv("HOME", str(home_dir))
        monkeypatch.setattr("pathlib.Path.home", lambda: home_dir)

        args = argparse.Namespace(
            project=str(project_dir),
            _project_root=project_dir,
            ws=Workspace.for_init(project_dir),
            platform="claude",
            rules="minimal",
            local=True,
            mcp=False,
            yes=True,
            force=True,
            dry_run=False,
        )

        rc = run_init(args)
        assert rc == 0
        assert (project_dir / ".claude").is_dir(), "Claude rules were not installed into <project>/.claude!"
        assert (project_dir / "CLAUDE.md").is_file(), "CLAUDE.md was not created in project root!"
        assert not (home_dir / ".claude").exists(), "Home directory was unexpectedly modified in local mode!"


class TestRuleDiscovery:
    """Tests for _get_soma_root and _discover_full_rules."""

    def test_discover_full_rules_empty(self, monkeypatch, tmp_path):
        from aegis_cli.init import _discover_full_rules
        monkeypatch.setattr("aegis_cli.init._get_soma_root", lambda: tmp_path)
        assert _discover_full_rules() == []

    def test_discover_full_rules_rules_dir(self, monkeypatch, tmp_path):
        from aegis_cli.init import _discover_full_rules
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        (rules_dir / "rule1.md").write_text("# Rule 1", encoding="utf-8")
        (rules_dir / "META.md").write_text("# Meta", encoding="utf-8")
        (rules_dir / "README.md").write_text("# Readme", encoding="utf-8")
        oracles = rules_dir / ".oracles"
        oracles.mkdir()
        (oracles / "oracle1.md").write_text("# Oracle 1", encoding="utf-8")

        monkeypatch.setattr("aegis_cli.init._get_soma_root", lambda: tmp_path)
        discovered = _discover_full_rules()
        names = [f.name for f in discovered]
        assert "rule1.md" in names
        assert "oracle1.md" in names
        assert "META.md" not in names
        assert "README.md" not in names

    def test_discover_full_rules_genome_dir(self, monkeypatch, tmp_path):
        from aegis_cli.init import _discover_full_rules
        genome_dir = tmp_path / "genome"
        genome_dir.mkdir()
        (genome_dir / "rule2.md").write_text("# Rule 2", encoding="utf-8")
        oracles = genome_dir / ".oracles"
        oracles.mkdir()
        (oracles / "oracle2.md").write_text("# Oracle 2", encoding="utf-8")

        monkeypatch.setattr("aegis_cli.init._get_soma_root", lambda: tmp_path)
        discovered = _discover_full_rules()
        names = [f.name for f in discovered]
        assert "rule2.md" in names
        assert "oracle2.md" in names

    def test_get_soma_root_fallbacks(self, monkeypatch, tmp_path):
        from aegis_cli import init as init_mod
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        monkeypatch.setattr("pathlib.Path.cwd", lambda: tmp_path)
        monkeypatch.setattr("importlib.resources.files", lambda mod: empty_dir / "pkg")
        assert init_mod._get_soma_root() == tmp_path

        # Case with genome in pkg_root
        pkg_with_genome = tmp_path / "pkg_root_genome"
        (pkg_with_genome / "genome").mkdir(parents=True)
        monkeypatch.setattr("importlib.resources.files", lambda mod: pkg_with_genome / "aegis_cli")
        assert init_mod._get_soma_root() == pkg_with_genome

        # Case with rules in pkg_root
        pkg_with_rules = tmp_path / "pkg_root_rules"
        (pkg_with_rules / "rules").mkdir(parents=True)
        monkeypatch.setattr("importlib.resources.files", lambda mod: pkg_with_rules / "aegis_cli")
        assert init_mod._get_soma_root() == pkg_with_rules

    def test_init_delegates_detect_platform_and_get_rules_dir_to_platforms_module(self):
        """v3.0.0: init.py re-exports detect_platform and get_rules_dir from aegis_cli.platforms."""
        from aegis_cli import init as init_mod
        from aegis_cli import platforms as platforms_mod

        assert hasattr(platforms_mod, "detect_platform")
        assert hasattr(platforms_mod, "get_rules_dir")
        assert init_mod.detect_platform is platforms_mod.detect_platform
        assert init_mod.get_rules_dir is platforms_mod.get_rules_dir

    def test_init_branded_aegis_header_and_dry_run_badges(self, tmp_path, capsys):
        """v3.0.0: init prints Aegis Guardrails header, aegis report, and [DRY-RUN]/[SKIP] badges."""
        from aegis_cli.init import run_init

        (tmp_path / ".gemini").mkdir()
        args_dry = argparse.Namespace(
            dry_run=True,
            platform="gemini",
            yes=True,
            force=False,
            rules="minimal",
            _project_root=tmp_path,
            _home=tmp_path,
        )
        assert run_init(args_dry) == 0
        out_dry = capsys.readouterr().out
        assert "Aegis Guardrails — Workspace Setup" in out_dry
        assert "Soma Governance" not in out_dry
        assert "aegis report" in out_dry
        assert "[DRY-RUN] providence" in out_dry
        assert "✅ providence" not in out_dry
