"""Unit tests for v3.3.1 Security & Cryptographic Provenance and ClaudeAdapter Skills/Desktop MCP."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import pytest

from aegis_cli.platforms.claude import ClaudeAdapter
from aegis_core.receipts import ReceiptManager, compute_file_digest
from aegis_core.skills.handoff import HandoffRouter, consume_handoff, soma_handoff
from aegis_core.workspace import Workspace
from aegis_core.yaml import dump_frontmatter
from aegis_mcp.rule_cache import RuleCache


def _init_git_repo(repo_dir: Path) -> None:
    """Initialize a minimal git repository with one commit."""
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@aegis.local"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Aegis Test"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )
    tracked = repo_dir / "app.py"
    tracked.write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )


class TestGitBoundFileDigest:
    """Verify compute_file_digest binds to git HEAD + working tree status when target_paths=[]."""

    def test_non_git_workspace_empty_paths_returns_baseline_digest(self, tmp_path: Path) -> None:
        d1 = compute_file_digest(tmp_path, [])
        expected = hashlib.sha256(b"soma-file-digest-v1\0").hexdigest()
        assert d1 == expected

    def test_git_workspace_empty_paths_changes_on_working_tree_mutation(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)

        clean_digest = compute_file_digest(tmp_path, [])
        baseline_non_git = hashlib.sha256(b"soma-file-digest-v1\0").hexdigest()
        assert clean_digest != baseline_non_git
        assert compute_file_digest(tmp_path, []) == clean_digest

        # Mutate tracked file in working tree -> digest must change
        (tmp_path / "app.py").write_text("x = 2\n", encoding="utf-8")
        dirty_digest = compute_file_digest(tmp_path, [])
        assert dirty_digest != clean_digest

        # Add untracked file -> digest must change again
        (tmp_path / "untracked.py").write_text("y = 3\n", encoding="utf-8")
        untracked_digest = compute_file_digest(tmp_path, [])
        assert untracked_digest != dirty_digest
        assert untracked_digest != clean_digest


class TestInboundHandoffVerification:
    """Verify HandoffRouter.consume_handoff and 'aegis handoff consume' CLI."""

    def _setup_workspace_with_skills(self, tmp_path: Path) -> Workspace:
        _init_git_repo(tmp_path)
        ws = Workspace(tmp_path)
        ws.scaffold()
        skills_dir = tmp_path / ".aegis" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "sentry.md").write_text(
            "---\nid: sentry\ntier: guardrail\nproduces: [ChargeSheet]\nhandoff_targets: [fixer]\n---\n",
            encoding="utf-8",
        )
        (skills_dir / "fixer.md").write_text(
            "---\nid: fixer\ntier: lane\nconsumes: [ChargeSheet]\n---\n",
            encoding="utf-8",
        )
        return ws

    def test_consume_handoff_valid_and_marks_consumed(self, tmp_path: Path) -> None:
        ws = self._setup_workspace_with_skills(tmp_path)
        issued = soma_handoff(
            workspace=ws,
            from_skill="sentry",
            to_skill="fixer",
            artifact_type="ChargeSheet",
            payload={
                "category": "security",
                "risk": "Unverified handoff envelope",
                "mechanism": "Missing HMAC validation",
            },
            cycle_id="cyc01",
        )

        # Ticket must exist in .aegis/handoffs/<ticket_id>.json
        handoff_file = tmp_path / ".aegis" / "handoffs" / f"{issued.ticket_id}.json"
        assert handoff_file.is_file()

        router = HandoffRouter(ws)
        consumed = router.consume_handoff(issued.ticket_id, verify_tree=True)
        assert consumed.ticket_id == issued.ticket_id
        assert consumed.status == "consumed"
        assert consumed.payload is not None
        assert consumed.payload["risk"] == "Unverified handoff envelope"

        # On-disk status must be marked "consumed"
        disk_data = json.loads(handoff_file.read_text(encoding="utf-8"))
        assert disk_data["status"] == "consumed"

        # Re-consuming an already consumed ticket must fail
        with pytest.raises(ValueError, match="Handoff ticket verification failed"):
            router.consume_handoff(issued.ticket_id)

    def test_consume_handoff_missing_ticket_raises_file_not_found(self, tmp_path: Path) -> None:
        ws = self._setup_workspace_with_skills(tmp_path)
        router = HandoffRouter(ws)
        with pytest.raises(FileNotFoundError):
            router.consume_handoff("nonexistent_ticket")

    def test_consume_handoff_rejects_tampered_signature(self, tmp_path: Path) -> None:
        ws = self._setup_workspace_with_skills(tmp_path)
        issued = soma_handoff(
            workspace=ws,
            from_skill="sentry",
            to_skill="fixer",
            artifact_type="ChargeSheet",
            payload={
                "category": "security",
                "risk": "Original risk",
                "mechanism": "Original mechanism",
            },
            cycle_id="cyc02",
        )

        # Tamper with payload on disk
        handoff_file = tmp_path / ".aegis" / "handoffs" / f"{issued.ticket_id}.json"
        data = json.loads(handoff_file.read_text(encoding="utf-8"))
        data["payload"]["risk"] = "Tampered risk"
        handoff_file.write_text(json.dumps(data), encoding="utf-8")

        router = HandoffRouter(ws)
        with pytest.raises(ValueError, match="Handoff ticket verification failed"):
            router.consume_handoff(issued.ticket_id)

    def test_consume_handoff_rejects_git_tree_hash_drift(self, tmp_path: Path) -> None:
        ws = self._setup_workspace_with_skills(tmp_path)
        issued = soma_handoff(
            workspace=ws,
            from_skill="sentry",
            to_skill="fixer",
            artifact_type="ChargeSheet",
            payload={
                "category": "correctness",
                "risk": "Stale tree state",
                "mechanism": "Commit changed HEAD tree",
            },
            cycle_id="cyc03",
        )

        # Commit a change to advance HEAD^{tree}
        (tmp_path / "app.py").write_text("x = 999\n", encoding="utf-8")
        subprocess.run(["git", "add", "app.py"], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "advance tree"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
        )

        router = HandoffRouter(ws)
        with pytest.raises(ValueError, match="Handoff ticket verification failed"):
            router.consume_handoff(issued.ticket_id, verify_tree=True)

        # With verify_tree=False, consumption succeeds despite tree drift
        consumed = consume_handoff(ws, issued.ticket_id, verify_tree=False)
        assert consumed.status == "consumed"


class TestRuleCacheManifestVerification:
    """Verify RuleCache automatically excludes tampered rules when .aegis/manifest.json exists."""

    def _write_rule(self, rules_dir: Path, name: str, body: str = "Original body.\n") -> Path:
        rules_dir.mkdir(parents=True, exist_ok=True)
        rule_path = rules_dir / f"{name}.md"
        content = dump_frontmatter(
            {"id": name, "type": "wall", "target_paths": ["src/*.py"]},
            body=f"# {name}\n{body}",
        )
        rule_path.write_text(content, encoding="utf-8")
        return rule_path

    def test_rule_cache_excludes_tampered_rule_with_aegis_manifest(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rules_dir = tmp_path / ".aegis" / "rules"
        r1 = self._write_rule(rules_dir, "valid-rule", "Trusted content.\n")
        r2 = self._write_rule(rules_dir, "tampered-rule", "Original content.\n")

        h1 = hashlib.sha256(r1.read_bytes()).hexdigest()
        h2 = hashlib.sha256(r2.read_bytes()).hexdigest()

        manifest_file = tmp_path / ".aegis" / "manifest.json"
        manifest_file.write_text(
            json.dumps(
                {
                    "files": {
                        "valid-rule.md": f"sha256:{h1}",
                        "tampered-rule.md": f"sha256:{h2}",
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        # Tamper with r2 on disk after manifest generation
        self._write_rule(rules_dir, "tampered-rule", "Injected malicious rule body!\n")

        cache = RuleCache()
        loaded = cache.get_rules(str(tmp_path))
        loaded_ids = [r["id"] for r in loaded]
        assert loaded_ids == ["valid-rule"]

        err = capsys.readouterr().err
        assert "tampered" in err.lower()

    def test_rule_cache_works_normally_without_manifest(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / ".aegis" / "rules"
        self._write_rule(rules_dir, "rule-alpha")
        self._write_rule(rules_dir, "rule-beta")

        cache = RuleCache()
        loaded = cache.get_rules(str(tmp_path))
        assert sorted(r["id"] for r in loaded) == ["rule-alpha", "rule-beta"]


class TestClaudeAdapterSkillsAndDesktopMcp:
    """Verify ClaudeAdapter installs skills to .claude/skills/ and configures Claude Desktop MCP."""

    def test_claude_adapter_installs_skills_and_desktop_mcp(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        home = tmp_path / "home"
        home.mkdir()

        # Create source rules and skills in workspace
        rules_src = workspace / "rules"
        rules_src.mkdir()
        (rules_src / "providence.md").write_text("# Providence\n", encoding="utf-8")

        skill_src = workspace / "skills" / "staff-review"
        skill_src.mkdir(parents=True)
        (skill_src / "SKILL.md").write_text("---\nname: staff-review\n---\n# Staff Review\n", encoding="utf-8")

        # Create ~/.config/Claude directory with an existing MCP server
        desktop_dir = home / ".config" / "Claude"
        desktop_dir.mkdir(parents=True)
        desktop_cfg_path = desktop_dir / "claude_desktop_config.json"
        desktop_cfg_path.write_text(
            json.dumps({"mcpServers": {"existing-server": {"command": "npx", "args": []}}}),
            encoding="utf-8",
        )

        adapter = ClaudeAdapter(workspace=workspace, home=home)

        # 1. Global install copies skills into ~/.claude/skills/ and updates claude_desktop_config.json
        res_global = adapter.install(local=False, dry_run=False)
        assert res_global.success
        installed_skill = home / ".claude" / "skills" / "staff-review" / "SKILL.md"
        assert installed_skill.is_file()

        desktop_data = json.loads(desktop_cfg_path.read_text(encoding="utf-8"))
        assert "existing-server" in desktop_data["mcpServers"]
        assert "aegis" in desktop_data["mcpServers"]
        assert desktop_data["mcpServers"]["aegis"]["command"] == "aegis-mcp"
        assert "soma" not in desktop_data["mcpServers"]

        # 2. Local install copies skills into <workspace>/.claude/skills/
        res_local = adapter.install(local=True, dry_run=False)
        assert res_local.success
        local_skill = workspace / ".claude" / "skills" / "staff-review" / "SKILL.md"
        assert local_skill.is_file()

        # 3. Uninstall removes installed skills and cleans MCP config
        un_global = adapter.uninstall(local=False, dry_run=False)
        assert un_global.success
        assert not installed_skill.exists()

        un_local = adapter.uninstall(local=True, dry_run=False)
        assert un_local.success
        assert not local_skill.exists()
