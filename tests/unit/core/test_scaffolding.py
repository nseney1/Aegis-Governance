"""Unit tests for ``aegis_core.scaffolding``: rule locator, preset resolution, frontmatter
type projection, and CI workflow generation/inspection."""
from __future__ import annotations

from pathlib import Path

import pytest

from aegis_core import __version__
from aegis_core.scaffolding import (
    ACTIVE_STARTERS,
    CI_WORKFLOW_PATH,
    DEFAULT_RULE_PRESET,
    RULE_PRESETS,
    _declare_type,
    _runs_aegis_check,
    _workflow_files,
    ci_workflow,
    install_rules,
    packaged_active_rules,
    packaged_dir,
    packaged_rules,
    preset_rules,
)

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())


class TestPackagedDirAndRules:
    def test_packaged_dir_resolves_wheel_and_checkout(self, tmp_path: Path) -> None:
        site = tmp_path / "site" / "aegis_core"
        (site / "_data" / "rules").mkdir(parents=True)
        assert packaged_dir("rules", base=site) == site / "_data" / "rules"

        checkout = tmp_path / "checkout"
        (checkout / "aegis_core").mkdir(parents=True)
        (checkout / "rules").mkdir()
        (checkout / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        assert packaged_dir("rules", base=checkout / "aegis_core") == checkout / "rules"

    def test_packaged_rules_excludes_active_starters(self) -> None:
        guidance = packaged_rules()
        active = packaged_active_rules()
        assert set(active) == set(ACTIVE_STARTERS) == {"no-eval"}
        assert "no-eval" not in guidance
        assert {"providence", "destructive-ops", "testing"} <= set(guidance)

    def test_packaged_active_rules_raises_when_missing(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not found; reinstall aegis-guardrails"):
            packaged_active_rules(locator=lambda name: tmp_path / "missing" / name)

    def test_preset_rules_resolves_presets_and_rejects_unknown(self) -> None:
        assert DEFAULT_RULE_PRESET == "standard"
        minimal = {p.stem for p in preset_rules("minimal")}
        standard = {p.stem for p in preset_rules("standard")}
        full = {p.stem for p in preset_rules("full")}
        assert minimal == set(RULE_PRESETS["minimal"] or ())
        assert standard == set(RULE_PRESETS["standard"] or ())
        assert minimal < standard < full
        with pytest.raises(ValueError, match="unknown rule preset"):
            preset_rules("nonexistent")


class TestDeclareTypeAndInstallRules:
    def test_declare_type_inserts_or_replaces_type_and_target_paths(self, tmp_path: Path) -> None:
        rule_file = tmp_path / "sample.md"
        rule_file.write_bytes(b"---\nid: sample\ndomain: governance\n---\n# Title\n")
        projected = _declare_type(rule_file, "persona")
        assert projected == (
            b"---\nid: sample\ntype: persona\ntarget_paths: []\ndomain: governance\n---\n# Title\n"
        )

        typed_file = tmp_path / "typed.md"
        typed_file.write_bytes(b"---\r\nid: typed\r\ntype: trap\r\ntarget_paths: [\"*.py\"]\r\n---\r\n# Body\r\n")
        replaced = _declare_type(typed_file, "persona")
        assert replaced == b"---\r\nid: typed\r\ntype: persona\r\ntarget_paths: [\"*.py\"]\r\n---\r\n# Body\r\n"

    def test_declare_type_rejects_missing_frontmatter(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.md"
        bad.write_text("# No frontmatter\n", encoding="utf-8")
        with pytest.raises(ValueError, match="has no frontmatter"):
            _declare_type(bad, "persona")

    def test_install_rules_respects_skip_force_and_dry_run(self, tmp_path: Path) -> None:
        dry_dest = tmp_path / "dry"
        names = install_rules(dry_dest, preset="minimal", dry_run=True)
        assert set(names) == {"providence", "destructive-ops"}
        assert not dry_dest.exists()

        dest = tmp_path / "dest"
        installed = install_rules(dest, preset="minimal", skip=("destructive-ops",), rule_type="persona")
        assert installed == ["providence"]
        assert (dest / "providence.md").is_file()
        assert not (dest / "destructive-ops.md").exists()

        (dest / "providence.md").write_text("custom", encoding="utf-8")
        install_rules(dest, preset="minimal", skip=("destructive-ops",), force=False)
        assert (dest / "providence.md").read_text(encoding="utf-8") == "custom"
        install_rules(dest, preset="minimal", skip=("destructive-ops",), force=True)
        assert (dest / "providence.md").read_text(encoding="utf-8") != "custom"


class TestCiWorkflowHelpers:
    def test_ci_workflow_pins_version_and_runs_aegis_check(self, tmp_path: Path) -> None:
        assert CI_WORKFLOW_PATH == ".github/workflows/aegis.yml"
        wf = ci_workflow()
        assert f"pip install aegis-guardrails=={__version__}" in wf
        wf_file = tmp_path / ".github" / "workflows" / "aegis.yml"
        wf_file.parent.mkdir(parents=True)
        wf_file.write_text(wf, encoding="utf-8")
        other_file = wf_file.parent / "other.yaml"
        other_file.write_text("name: Test\non: push\njobs: {}\n", encoding="utf-8")

        assert _workflow_files(tmp_path) == [wf_file, other_file]
        assert _runs_aegis_check(wf_file) is True
        assert _runs_aegis_check(other_file) is False
        assert _runs_aegis_check(tmp_path / "missing.yml") is False
