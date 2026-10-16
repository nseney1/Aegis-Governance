"""`aegis init` (host-matrix spec §3.2-3.4): the repository plane, seeding, prompts and output.

The host plane (registrations, ~/.aegis/workspaces.json, refusals of user files) is
covered in test_init_hosts.py. Every test runs with an empty HOME (tests/unit/cli/conftest.py).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pytest

from aegis_cli.cli import _build_parser, main
from aegis_cli.init import InitCommand, install_rules, packaged_rules, preset_rules, run_init

STANDARD = {"providence", "destructive-ops", "testing", "cost-optimization", "git-workflow"}
MINIMAL = {"providence", "destructive-ops"}
# Every shipped rule in rules/ and rules/.oracles/ except META.md (D16).
FULL = {
    "cost-optimization", "destructive-ops", "providence", "subagent-delegation",
    "architectural-tenets", "atomic-workstream-protocol", "documentation",
    "feature-specs", "git-workflow", "polyglot-standards", "tdd-protocol", "testing",
}
REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    # No host CLI and no aegis-mcp on PATH: nothing here may be detected or run.
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    return root


def _args(root: Path, *flags: str, yes: bool = True, hooks: bool = False,
          rules: "str | None" = "minimal") -> argparse.Namespace:
    """Arguments as the real parser builds them from argv (never a hand-made Namespace)."""
    argv = ["init", "--workspace", str(root)]
    argv += ["--yes"] if yes else []
    argv += [] if hooks else ["--no-hooks"]
    argv += ["--rules", rules] if rules else []
    return _build_parser().parse_args(argv + list(flags))


def _seeded(root: Path) -> set:
    return {p.stem for p in (root / ".aegis" / "rules" / "personas").glob("*.md")}


# ── The one rule-source locator (defense #20) ────────────────────────────────


class TestRuleSourceLocator:
    def test_packaged_rules_come_from_the_shipped_rules_package(self):
        found = packaged_rules()
        assert set(found) == FULL
        for name, path in found.items():
            assert path.name == f"{name}.md"
            assert path.resolve().parent in {REPO_ROOT / "rules", REPO_ROOT / "rules" / ".oracles"}

    @pytest.mark.parametrize("preset, names", [("minimal", MINIMAL), ("standard", STANDARD), ("full", FULL)])
    def test_presets_resolve_through_the_locator(self, preset, names):
        assert {p.stem for p in preset_rules(preset)} == names

    def test_unknown_preset_is_refused(self):
        with pytest.raises(ValueError, match="unknown rule preset"):
            preset_rules("huge")

    def test_install_rules_copies_the_packaged_bytes_flat(self, tmp_path):
        installed = install_rules(tmp_path, preset="standard")
        assert set(installed) == STANDARD
        for name in STANDARD:
            assert (tmp_path / f"{name}.md").read_bytes() == packaged_rules()[name].read_bytes()

    def test_install_rules_keeps_existing_files_unless_forced(self, tmp_path):
        (tmp_path / "providence.md").write_text("mine", encoding="utf-8")
        assert "providence" in install_rules(tmp_path, preset="minimal")
        assert (tmp_path / "providence.md").read_text(encoding="utf-8") == "mine"
        install_rules(tmp_path, preset="minimal", force=True)
        assert (tmp_path / "providence.md").read_bytes() == packaged_rules()["providence"].read_bytes()

    def test_install_rules_dry_run_writes_nothing(self, tmp_path):
        assert set(install_rules(tmp_path / "x", preset="minimal", dry_run=True)) == MINIMAL
        assert not (tmp_path / "x").exists()


# ── Seeding the workspace ────────────────────────────────────────────────────


class TestSeeding:
    @pytest.mark.parametrize("preset, names", [("minimal", MINIMAL), ("standard", STANDARD), ("full", FULL)])
    def test_preset_is_seeded_into_the_persona_rules(self, project, preset, names):
        assert run_init(_args(project, rules=preset)) == 0
        assert _seeded(project) == names

    def test_default_preset_is_standard(self, project):
        assert run_init(_args(project, rules=None)) == 0
        assert _seeded(project) == STANDARD

    def test_seeded_rules_load_without_errors(self, project):
        from aegis_core.rules import load_rules

        assert run_init(_args(project, rules="standard")) == 0
        ruleset = load_rules(project)
        assert not ruleset.errors
        assert {r.id for r in ruleset.rules} == STANDARD

    def test_an_existing_rule_with_the_same_id_is_never_overwritten_or_duplicated(self, project):
        mine = project / ".aegis" / "rules" / "invariants" / "providence.md"
        mine.parent.mkdir(parents=True)
        mine.write_text("---\nid: providence\nhypothesis: mine\n---\n# Mine\n", encoding="utf-8")
        edited = project / ".aegis" / "rules" / "personas" / "testing.md"
        edited.parent.mkdir(parents=True)
        edited.write_text("my testing rule", encoding="utf-8")

        assert run_init(_args(project, rules="standard")) == 0

        assert not (project / ".aegis" / "rules" / "personas" / "providence.md").exists()
        assert mine.read_text(encoding="utf-8").endswith("# Mine\n")
        assert edited.read_text(encoding="utf-8") == "my testing rule"

    def test_a_symlinked_rules_dir_is_refused_and_nothing_is_written(self, project, tmp_path):
        from conftest import symlink_or_skip

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (project / ".aegis" / "rules").mkdir(parents=True)
        symlink_or_skip(elsewhere, project / ".aegis" / "rules" / "personas", target_is_directory=True)

        assert run_init(_args(project)) == 1

        assert list(elsewhere.iterdir()) == []
        assert not (project / "AGENTS.md").exists()


# ── Prompt, dry run, output ──────────────────────────────────────────────────


def _snapshot(*roots: Path) -> dict:
    out = {}
    for root in roots:
        for dirpath, dirs, files in os.walk(root):
            for name in dirs + files:
                p = Path(dirpath, name)
                out[str(p)] = None if p.is_dir() else p.read_bytes()
    return out


class TestPromptAndDryRun:
    def test_declining_the_prompt_writes_nothing(self, project, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", lambda _: "n")
        home = Path.home()
        before = _snapshot(project, home)
        assert run_init(_args(project, yes=False)) == 0
        assert "Aborted" in capsys.readouterr().out
        assert _snapshot(project, home) == before

    def test_end_of_input_at_the_prompt_aborts(self, project, monkeypatch):
        def eof(_):
            raise EOFError
        monkeypatch.setattr("builtins.input", eof)
        assert run_init(_args(project, yes=False)) == 0
        assert not (project / ".aegis").exists()

    def test_accepting_the_prompt_proceeds(self, project, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", lambda _: "")
        assert run_init(_args(project, yes=False)) == 0
        assert "Done!" in capsys.readouterr().out
        assert (project / "AGENTS.md").is_file()

    def test_dry_run_writes_nothing_and_says_what_it_would_do(self, project, capsys):
        home = Path.home()
        before = _snapshot(project, home)
        assert run_init(_args(project, "--dry-run", yes=False, hooks=True)) == 0
        out = capsys.readouterr().out
        assert _snapshot(project, home) == before
        assert "Aegis Guardrails — Workspace Setup" in out
        assert "[DRY-RUN] providence" in out
        assert "AGENTS.md" in out
        assert "Dry run complete. No files were created." in out

    def test_header_and_next_step(self, project, capsys):
        assert run_init(_args(project)) == 0
        out = capsys.readouterr().out
        assert "Aegis Guardrails — Workspace Setup" in out
        assert "After a session, run: aegis status" in out
        assert "Soma" not in out

    def test_home_directory_is_refused(self, tmp_path, monkeypatch, capsys):
        home = Path.home()
        assert run_init(_args(home)) == 1
        assert "home directory" in capsys.readouterr().err
        assert not (home / ".aegis").exists()
        assert not (home / "AGENTS.md").exists()


class TestPolyglot:
    def test_languages_are_detected_and_drivers_provisioned(self, project, capsys):
        from aegis_core.skills.slots import SlotRegistry

        (project / "Cargo.toml").write_text("[package]\nname = 'rust_app'\n", encoding="utf-8")
        (project / "src").mkdir()
        (project / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
        assert run_init(_args(project)) == 0
        out = capsys.readouterr().out
        assert "Detected language(s): Rust" in out
        assert "Configured AST driver (.rs):" in out
        assert SlotRegistry.load(project).get_ast_driver(".rs") is not None
        assert not (project / ".aegis" / "drivers").exists()

    def test_dry_run_only_says_it_would_configure(self, project, capsys):
        (project / "Cargo.toml").write_text("[package]\nname = 'rust_app'\n", encoding="utf-8")
        assert run_init(_args(project, "--dry-run")) == 0
        assert "Would configure AST driver (.rs):" in capsys.readouterr().out
        assert not (project / ".aegis" / "config.json").exists()

    def test_unknown_project_type(self, project, capsys):
        assert run_init(_args(project)) == 0
        assert "Project type: unknown" in capsys.readouterr().out


# ── JSON output (fleet dashboards read it) ───────────────────────────────────


class TestJsonOutput:
    def test_json_result_carries_provenance_and_actions(self, project, capsys):
        assert main(["--json", "init", "--workspace", str(project), "--yes", "--no-hooks",
                     "--rules", "minimal"]) == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["source"] == "aegis init"
        assert isinstance(payload["aegis_version"], str) and payload["aegis_version"]
        assert payload["checked_at"].endswith("Z") and "T" in payload["checked_at"]
        assert payload["scope"]["workspace"] == str(project.resolve())
        assert payload["scope"]["hosts"] == []
        assert payload["dry_run"] is False
        assert payload["status"] == "ok"
        targets = {a["target"]: a["result"] for a in payload["actions"]}
        assert targets["AGENTS.md"] == "created"
        assert targets["~/.aegis/workspaces.json"] == "added"

    def test_json_dry_run_plans_and_writes_nothing(self, project, capsys):
        assert main(["--json", "init", "--workspace", str(project), "--dry-run"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is True
        assert not (project / ".aegis").exists()

    def test_json_without_yes_or_dry_run_is_a_usage_error(self, project, capsys):
        assert main(["--json", "init", "--workspace", str(project)]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "--yes or --dry-run" in captured.err
        assert not (project / ".aegis").exists()

    def test_json_refusal_is_reported_as_json(self, project, capsys):
        (project / "AGENTS.md").write_text(
            "<!-- aegis:begin id=bootstrap v=1 sha=000000000000 -->\nmine\n<!-- aegis:end id=bootstrap -->\n",
            encoding="utf-8")
        assert main(["--json", "init", "--workspace", str(project), "--yes", "--no-hooks"]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "refused"
        assert any("edited by hand" in e for e in payload["errors"])


# ── Command line surface ─────────────────────────────────────────────────────


class TestCommandLine:
    def test_parser_contract(self):
        parser = argparse.ArgumentParser()
        InitCommand().configure_parser(parser)
        ns = parser.parse_args(["--host", "antigravity,codex-cli", "--rules", "full", "--dry-run",
                                "--yes", "--force", "--pin", "--no-hooks"])
        assert ns.host == ["codex-cli", "antigravity"]
        assert (ns.rules, ns.dry_run, ns.yes, ns.force, ns.pin, ns.no_hooks) == ("full", True, True, True, True, True)
        defaults = parser.parse_args([])
        assert (defaults.host, defaults.rules, defaults.pin) == (None, "standard", False)
        assert parser.parse_args(["--host", "auto"]).host == "auto"

    def test_execute_delegates_to_run_init(self, monkeypatch):
        seen = []
        monkeypatch.setattr("aegis_cli.init.run_init", lambda a: seen.append(a) or 0)
        ns = argparse.Namespace()
        assert InitCommand().execute(ns) == 0 and seen == [ns]

    @pytest.mark.parametrize("argv, line", [
        (["init", "--platform", "claude"], "aegis init --platform was removed in v4: use aegis init --host"),
        (["init", "--platform=gemini", "--yes"], "aegis init --platform was removed in v4: use aegis init --host"),
        (["init", "--mcp"], "aegis init --mcp was removed in v4: use aegis init --host (no project MCP file is written)"),
        (["init", "--local"], "aegis init --local was removed in v4: rules live in .aegis/rules; use aegis init"),
    ])
    def test_removed_flags_exit_2_with_one_pointer_line(self, project, argv, line, capsys):
        with pytest.raises(SystemExit) as exc:
            main(argv + ["--workspace", str(project)])
        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == line + "\n"
        assert not (project / ".aegis").exists()

    def test_removed_flags_are_not_in_help(self, capsys):
        with pytest.raises(SystemExit):
            main(["init", "--help"])
        out = capsys.readouterr().out
        assert "--host" in out
        for gone in ("--platform", "--mcp", "--local"):
            assert gone not in out

    @pytest.mark.parametrize("value, message", [
        ("cursor", "unknown host 'cursor'"),
        ("claude-desktop", "identity only"),
    ])
    def test_bad_host_is_a_usage_error(self, project, value, message, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["init", "--host", value, "--workspace", str(project)])
        assert exc.value.code == 2
        assert message in capsys.readouterr().err
