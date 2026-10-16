"""`aegis doctor`: the read-only host matrix, enforcement tiers and warnings (host-matrix §3.9-3.10).

Doctor never claims more than it checked: a host CLI that fails or times out makes the
registration *unknown*, not absent; nothing is read from the network; and a read run
writes nothing anywhere. Host CLIs are faked at the process boundary (``_run_host_cli``)
and every host binary is a stub on a private PATH, so no real host is ever touched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional

import pytest

from aegis_cli import doctor
from aegis_cli.doctor import run_doctor
from aegis_core.bootstrap import BOOTSTRAP_ID, bootstrap_text

PHASE1 = ["codex-cli", "claude-code", "antigravity"]
STATES = {"ok", "missing_binary", "unregistered", "auth_unknown", "policy_gap"}


# ── environment ─────────────────────────────────────────────────────────────

class Env:
    """A fake machine: HOME, a private PATH of stub binaries, a workspace, host CLI replies."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.ws = tmp_path / "repo"
        rules = self.ws / ".aegis" / "rules" / "invariants"
        rules.mkdir(parents=True)
        (rules / "invariant-sample.md").write_text(
            "---\nid: invariant-sample\ntype: invariant\nenforcement: gate\n"
            "hypothesis: Sample rule for doctor tests.\ntarget_paths:\n  - src/*.py\n---\n"
            "# Sample\n\nKeep the sample rule body long enough to be a real rule body.\n",
            encoding="utf-8")
        self.replies: Dict[str, Any] = {}
        self.calls: List[Dict[str, Any]] = []
        for name, value in (("HOME", self.home), ("USERPROFILE", self.home), ("PATH", self.bin),
                            ("APPDATA", self.home / "AppData" / "Roaming")):
            monkeypatch.setenv(name, str(value))
        for name in ("CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME", "CODEX_HOME", "AEGIS_WORKSPACE", "AEGIS_CLIENT"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(doctor, "_run_host_cli", self._run)
        self.stub("aegis")
        self.mcp = self.stub("aegis-mcp")

    def stub(self, name: str) -> Path:
        path = self.bin / (name + (".exe" if os.name == "nt" else ""))
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def _run(self, argv, cwd, timeout):
        self.calls.append({"argv": list(argv), "cwd": cwd, "timeout": timeout})
        reply = self.replies.get(Path(argv[0]).stem)
        if reply is None:
            raise AssertionError(f"unexpected host CLI call {argv}")
        if isinstance(reply, BaseException):
            raise reply
        rc, out, err = reply
        return subprocess.CompletedProcess(argv, rc, out, err)

    # host state helpers
    def codex_registered(self, command: Optional[str] = None, client: str = "codex-cli", enabled: bool = True):
        self.stub("codex")
        env = {"AEGIS_CLIENT": client} if client else {}
        self.replies["codex"] = (0, json.dumps({
            "name": "aegis", "enabled": enabled, "disabled_reason": None,
            "transport": {"type": "stdio", "command": command or str(self.mcp), "args": [],
                          "env": env, "env_vars": [], "cwd": None}}), "")

    def claude_json(self, data: Dict[str, Any]) -> Path:
        path = self.home / ".claude.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def claude_registered(self, client: str = "claude-code"):
        self.stub("claude")
        self.claude_json({"numStartups": 3, "mcpServers": {"aegis": {
            "type": "stdio", "command": str(self.mcp), "args": [], "env": {"AEGIS_CLIENT": client}}}})

    def antigravity_registered(self, **extra):
        self.stub("agy")
        cfg = self.home / ".gemini" / "config" / "mcp_config.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        entry = {"command": str(self.mcp), "args": [], "env": {"AEGIS_CLIENT": "antigravity"}}
        entry.update(extra)
        cfg.write_text(json.dumps({"mcpServers": {"aegis": entry}}, indent=2), encoding="utf-8")
        return cfg

    def register_workspace(self, hosts=PHASE1):
        reg = self.home / ".aegis" / "workspaces.json"
        reg.parent.mkdir(parents=True, exist_ok=True)
        reg.write_text(json.dumps({"v": 1, "workspaces": [{
            "root": os.path.realpath(str(self.ws)), "added_at": "2026-10-15T00:00:00Z",
            "added_by": "aegis init", "hosts": list(hosts)}]}), encoding="utf-8")

    def bootstrap(self, text: Optional[str] = None, sha: Optional[str] = None, before: str = "", after: str = ""):
        body = bootstrap_text() if text is None else text
        digest = sha or hashlib.sha256(body.replace("\r\n", "\n").encode("utf-8")).hexdigest()[:12]
        (self.ws / "AGENTS.md").write_text(
            f"{before}<!-- aegis:begin id={BOOTSTRAP_ID} v=1 sha={digest} -->\n{body}"
            f"<!-- aegis:end id={BOOTSTRAP_ID} -->\n{after}", encoding="utf-8")

    def all_ok(self):
        self.codex_registered()
        self.claude_registered()
        self.antigravity_registered()
        self.register_workspace()
        self.bootstrap()

    def doctor(self, **kw) -> Dict[str, Any]:
        rc, out = self.run(json=True, **kw)
        payload = json.loads(out)
        payload["_rc"] = rc
        return payload

    def run(self, **kw):
        import contextlib
        import io
        args = argparse.Namespace(workspace=str(self.ws), fix=False, yes=False, drivers=False, json=False)
        for key, value in kw.items():
            setattr(args, key, value)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run_doctor(args)
        return rc, buf.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch) -> Env:
    return Env(tmp_path, monkeypatch)


def host(payload: Dict[str, Any], host_id: str) -> Dict[str, Any]:
    return next(h for h in payload["hosts"] if h["id"] == host_id)


def codes(row: Dict[str, Any]) -> List[str]:
    return [r["code"] for r in row["reasons"]]


def finding_codes(payload: Dict[str, Any]) -> List[str]:
    return sorted(f["code"] for f in payload["findings"])


def _tree(root: Path) -> Dict[str, Any]:
    out = {}
    for path in sorted(root.rglob("*")):
        st = path.lstat()
        out[path.relative_to(root).as_posix()] = (st.st_mode, st.st_size, st.st_mtime_ns,
                                                    path.read_bytes() if path.is_file() else None)
    return out


# ── the machine-readable envelope ───────────────────────────────────────────

def test_json_carries_schema_source_version_time_scope_and_reserved_trust_tier(env):
    env.all_ok()
    payload = env.doctor()
    assert payload["schema"] == "aegis.doctor/v1"
    assert payload["source"] == "aegis doctor"
    assert isinstance(payload["aegis_version"], str) and payload["aegis_version"]
    checked = datetime.strptime(payload["checked_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - checked).total_seconds()) < 120
    assert payload["scope"]["workspace"] == str(env.ws.resolve())
    assert payload["scope"]["hosts"] == PHASE1
    assert payload["scope"]["host_selection"] == "default"
    assert payload["stale"] is False
    for row in payload["hosts"]:
        assert row["state"] in STATES
        assert row["trust_tier"] is None and row["trust_tier_status"] == "unavailable"
        assert row["stale"] is False


def test_every_phase_one_host_is_ok_when_installed_registered_bootstrapped_and_bound(env):
    env.all_ok()
    payload = env.doctor()
    assert {h["id"]: h["state"] for h in payload["hosts"]} == dict.fromkeys(PHASE1, "ok")
    codex = host(payload, "codex-cli")
    assert codex["registration"]["status"] == "registered"
    assert codex["registration"]["source"] == "codex mcp get aegis --json"
    assert codex["registration"]["command_exists"] is True
    assert codex["identity"] == {"status": "explicit", "aegis_client": "codex-cli"}
    assert codex["workspace_registered"] is True
    assert codex["bootstrap"]["status"] == "current" and codex["bootstrap"]["reaches_host"] is True
    assert codex["budget"]["within"] is True and codex["budget"]["budget_bytes"] == 32 * 1024
    assert payload["findings"] == []


def test_a_read_run_writes_nothing_and_never_creates_the_user_plane(env, tmp_path):
    env.all_ok()
    (env.home / ".aegis" / "workspaces.json").unlink()
    (env.home / ".aegis").rmdir()
    before = _tree(tmp_path)
    env.doctor()
    env.run()
    assert _tree(tmp_path) == before
    assert not (env.home / ".aegis").exists()


def test_the_codex_probe_is_bounded_and_runs_without_a_shell_from_the_workspace(env):
    env.all_ok()
    env.doctor()
    (call,) = [c for c in env.calls if Path(c["argv"][0]).stem == "codex"]
    assert call["argv"][1:] == ["mcp", "get", "aegis", "--json"]
    assert Path(call["argv"][0]).parent == env.bin
    assert Path(call["cwd"]) == env.ws.resolve()
    assert 0 < call["timeout"] <= 15
    assert all(Path(c["argv"][0]).stem == "codex" for c in env.calls), "claude and agy are read from files"


# ── the four states ─────────────────────────────────────────────────────────

def test_no_binaries_means_missing_binary_and_no_host_cli_runs(env):
    env.bootstrap()
    payload = env.doctor()
    for host_id in PHASE1:
        row = host(payload, host_id)
        assert row["state"] == "missing_binary", host_id
        assert row["binary"]["found"] is False
    assert host(payload, "codex-cli")["registration"]["status"] == "unavailable"
    assert env.calls == []


def test_a_host_cli_that_says_not_found_is_unregistered(env):
    env.all_ok()
    env.replies["codex"] = (1, "", "Error: No MCP server named 'aegis' found.\n")
    row = host(env.doctor(), "codex-cli")
    assert row["state"] == "unregistered"
    assert row["registration"]["status"] == "absent"
    assert "not_registered" in codes(row)


@pytest.mark.parametrize("reply", [
    subprocess.TimeoutExpired(["codex"], 10),
    OSError("exec format error"),
    (1, "", "thread 'main' panicked\n"),
    (0, "not json", ""),
    (0, json.dumps({"name": "other"}), ""),
])
def test_an_unanswered_codex_probe_is_auth_unknown_never_unregistered(env, reply):
    env.all_ok()
    env.replies["codex"] = reply
    row = host(env.doctor(), "codex-cli")
    assert row["state"] == "auth_unknown"
    assert row["registration"]["status"] == "unknown"
    assert "registration_unverifiable" in codes(row)
    assert "registration" in row["unknown"]


def test_a_registration_whose_command_is_gone_is_unregistered(env):
    env.all_ok()
    env.codex_registered(command=str(env.bin / "gone-aegis-mcp"))
    row = host(env.doctor(), "codex-cli")
    assert row["state"] == "unregistered"
    assert row["registration"]["command_exists"] is False
    assert "command_missing" in codes(row)


def test_claude_registration_is_read_from_claude_json_not_by_running_claude(env):
    env.all_ok()
    payload = env.doctor()
    row = host(payload, "claude-code")
    assert row["state"] == "ok"
    assert row["registration"]["scope"] == "user"
    assert row["registration"]["source"] == "~/.claude.json"
    assert not [c for c in env.calls if Path(c["argv"][0]).stem == "claude"]


def test_claude_project_scope_only_needs_an_approval_doctor_cannot_see(env):
    env.all_ok()
    env.claude_json({"mcpServers": {}})
    (env.ws / ".mcp.json").write_text(json.dumps({"mcpServers": {"aegis": {"command": str(env.mcp)}}}))
    row = host(env.doctor(), "claude-code")
    assert row["state"] == "auth_unknown"
    assert row["registration"]["scope"] == "project"
    assert "approval_unknown" in codes(row)


def test_claude_md_without_agents_import_is_a_policy_gap_for_claude_only(env):
    env.all_ok()
    (env.ws / "CLAUDE.md").write_text("# Project notes\n", encoding="utf-8")
    payload = env.doctor()
    claude = host(payload, "claude-code")
    assert claude["state"] == "policy_gap"
    assert "claude_md_shadows_agents_md" in codes(claude)
    assert claude["bootstrap"]["reaches_host"] is False
    assert host(payload, "codex-cli")["state"] == "ok"
    assert "claude_md_without_agents_import" in finding_codes(payload)


def test_claude_md_importing_agents_md_lets_the_bootstrap_through(env):
    env.all_ok()
    (env.ws / "CLAUDE.md").write_text(
        "# Notes\n\n<!-- aegis:begin id=agents-import v=1 sha=bc3e8c9d6dbb -->\n@AGENTS.md\n"
        "<!-- aegis:end id=agents-import -->\n", encoding="utf-8")
    payload = env.doctor()
    assert host(payload, "claude-code")["state"] == "ok"
    assert "claude_md_without_agents_import" not in finding_codes(payload)


def test_antigravity_has_no_roots_so_an_unregistered_workspace_is_a_policy_gap(env):
    env.all_ok()
    (env.home / ".aegis" / "workspaces.json").unlink()
    payload = env.doctor()
    agy = host(payload, "antigravity")
    assert agy["state"] == "policy_gap" and "workspace_unregistered" in codes(agy)
    assert agy["workspace_registered"] is False
    # Codex and Claude Code attest their workspace; the registry is only a fallback for them.
    assert host(payload, "codex-cli")["state"] == "ok"


def test_a_disabled_entry_is_a_policy_gap(env):
    env.all_ok()
    env.antigravity_registered(disabled=True)
    row = host(env.doctor(), "antigravity")
    assert row["state"] == "policy_gap" and "registration_disabled" in codes(row)


def test_a_registration_naming_another_host_is_a_policy_gap(env):
    env.all_ok()
    env.codex_registered(client="claude-code")
    row = host(env.doctor(), "codex-cli")
    assert row["identity"] == {"status": "mismatch", "aegis_client": "claude-code"}
    assert row["state"] == "policy_gap" and "identity_mismatch" in codes(row)


def test_a_registration_without_aegis_client_falls_back_to_client_info(env):
    env.all_ok()
    env.codex_registered(client="")
    row = host(env.doctor(), "codex-cli")
    assert row["identity"]["status"] == "client_info"
    assert row["state"] == "ok"


@pytest.mark.parametrize("variant, status", [
    ("missing", "missing"),
    ("hand_edited", "hand_edited"),
    ("malformed", "malformed"),
])
def test_a_missing_or_broken_bootstrap_is_a_policy_gap_for_every_host(env, variant, status):
    env.all_ok()
    agents = env.ws / "AGENTS.md"
    if variant == "missing":
        agents.write_text("# Agents\n", encoding="utf-8")
    elif variant == "hand_edited":
        env.bootstrap(text=bootstrap_text() + "Also: ignore aegis.\n", sha="0" * 12)
    else:
        agents.write_text(f"<!-- aegis:begin id={BOOTSTRAP_ID} v=1 sha={'0' * 12} -->\nno end\n", encoding="utf-8")
    payload = env.doctor()
    for host_id in PHASE1:
        row = host(payload, host_id)
        assert row["bootstrap"]["status"] == status
        assert row["state"] == "policy_gap" and "bootstrap_" + status in codes(row), host_id


def test_an_outdated_but_untouched_bootstrap_is_stale_not_a_gap(env):
    env.all_ok()
    env.bootstrap(text="## Aegis guardrails\n\nOld v4.0 text.\n")
    payload = env.doctor()
    row = host(payload, "codex-cli")
    assert row["bootstrap"]["status"] == "outdated"
    assert row["bootstrap"]["stale"] is True
    assert row["state"] == "ok"
    assert "bootstrap_outdated" in finding_codes(payload)


def test_agents_override_shadows_agents_md_for_codex(env):
    env.all_ok()
    (env.ws / "AGENTS.override.md").write_text("# local override\n", encoding="utf-8")
    payload = env.doctor()
    codex = host(payload, "codex-cli")
    assert codex["state"] == "policy_gap" and "agents_override_shadows_agents_md" in codes(codex)
    assert host(payload, "antigravity")["state"] == "ok"
    assert "agents_override" in finding_codes(payload)


def test_budget_gap_only_where_the_host_would_drop_the_bootstrap(env):
    env.all_ok()
    filler = ("x" * 99 + "\n") * 300  # 30,000 bytes of user text
    env.bootstrap(after=filler)  # the block comes first: Codex's 32 KiB cut keeps it
    payload = env.doctor()
    codex, agy = host(payload, "codex-cli"), host(payload, "antigravity")
    assert codex["budget"]["within"] is True and codex["state"] == "ok"
    assert agy["budget"]["within"] is False and agy["budget"]["bytes"] > 24000
    assert agy["state"] == "policy_gap" and "over_budget" in codes(agy)

    env.bootstrap(after=filler + filler)  # over 32 KiB, but the cut falls after the block
    payload = env.doctor()
    codex = host(payload, "codex-cli")
    assert codex["budget"]["within"] is False and codex["state"] == "ok"
    assert any(f["code"] == "instructions_over_budget" and Path(f["path"]).name == "AGENTS.md"
               for f in payload["findings"])

    env.bootstrap(before=filler + filler)  # now the block starts after byte 32768
    codex = host(env.doctor(), "codex-cli")
    assert codex["budget"]["within"] is False
    assert codex["state"] == "policy_gap" and "over_budget" in codes(codex)


def test_an_ungoverned_directory_is_a_policy_gap_not_a_crash(env, tmp_path):
    env.all_ok()
    bare = tmp_path / "bare"
    bare.mkdir()
    rc, out = env.run(json=True, workspace=str(bare))
    payload = json.loads(out)
    assert payload["scope"]["workspace_governed"] is False
    assert all("workspace_not_governed" in codes(h) for h in payload["hosts"])
    assert rc == 1


# ── selection and enforcement tiers ─────────────────────────────────────────

def test_the_matrix_follows_the_hosts_the_workspace_selected(env):
    env.all_ok()
    (env.ws / ".aegis" / "config.json").write_text(json.dumps({"v": 1, "hosts": ["codex-cli"]}))
    payload = env.doctor()
    assert payload["scope"]["host_selection"] == "config"
    assert [h["id"] for h in payload["hosts"]] == ["codex-cli"]
    advisory = next(t for t in payload["enforcement_tiers"] if t["tier"] == "advisory")
    assert advisory["hosts"] == ["codex-cli"]


def test_enforcement_tiers_report_what_is_in_force_here_and_nothing_more(env):
    env.all_ok()
    payload = env.doctor()
    floor = next(t for t in payload["enforcement_tiers"] if t["tier"] == "local_floor")
    assert floor["status"] == "unavailable"  # not a git repository: no hook can run

    hooks = env.ws / ".git" / "hooks"
    hooks.mkdir(parents=True)
    payload = env.doctor()
    tiers = {t["tier"]: t for t in payload["enforcement_tiers"]}
    assert list(tiers) == ["advisory", "best_effort", "local_floor", "authoritative"]
    assert tiers["advisory"]["status"] == "active"
    assert tiers["best_effort"]["status"] == "unavailable"
    assert tiers["local_floor"]["status"] == "inactive"
    assert tiers["authoritative"]["status"] == "unknown"
    assert all(h["enforcement_level"] == "advisory" for h in payload["hosts"])

    from aegis_cli.hooks.management import generate_hook_block
    (hooks / "pre-commit").write_text("#!/bin/sh\n" + generate_hook_block(sys.executable), encoding="utf-8")
    payload = env.doctor()
    tiers = {t["tier"]: t for t in payload["enforcement_tiers"]}
    assert tiers["local_floor"]["status"] == "active"
    assert all(h["enforcement_level"] == "local_floor" for h in payload["hosts"])


def test_an_unregistered_host_without_the_bootstrap_has_no_enforcement(env):
    env.claude_registered()
    env.claude_json({})
    row = host(env.doctor(), "claude-code")
    assert row["state"] == "unregistered"
    assert row["enforcement_level"] == "none"


# ── warnings (findings) ─────────────────────────────────────────────────────

def test_stale_soma_and_misplaced_aegis_entries_are_reported_where_they_are(env):
    env.all_ok()
    env.claude_json({
        "mcpServers": {"aegis": {"command": str(env.mcp), "env": {"AEGIS_CLIENT": "claude-code"}},
                       "soma": {"command": "soma-mcp"}},
        "projects": {"/elsewhere": {"mcpServers": {"soma": {"command": "soma-mcp"},
                                                   "aegis": {"command": "aegis-mcp"}}}}})
    (env.home / ".mcp.json").write_text(json.dumps({"mcpServers": {"soma": {}, "aegis": {}}}))
    (env.ws / ".mcp.json").write_text(json.dumps({"mcpServers": {"soma": {}, "other": {}}}))
    desktop = env.home / ".config" / "Claude" / "claude_desktop_config.json"
    desktop.parent.mkdir(parents=True)
    desktop.write_text(json.dumps({"mcpServers": {"aegis": {"command": "aegis-mcp"}, "soma": {}}}))
    payload = env.doctor()
    got = sorted((f["code"], Path(f["path"]).name, f["location"]) for f in payload["findings"])
    assert got == sorted([
        ("legacy_mcp_entry", ".claude.json", "mcpServers.soma"),
        ("legacy_mcp_entry", ".claude.json", "projects[/elsewhere].mcpServers.soma"),
        ("misplaced_mcp_entry", ".claude.json", "projects[/elsewhere].mcpServers.aegis"),
        ("legacy_mcp_entry", ".mcp.json", "mcpServers.soma"),
        ("misplaced_mcp_entry", ".mcp.json", "mcpServers.aegis"),
        ("legacy_mcp_entry", ".mcp.json", "mcpServers.soma"),
        ("desktop_mcp_entry", "claude_desktop_config.json", "mcpServers.aegis"),
        ("legacy_mcp_entry", "claude_desktop_config.json", "mcpServers.soma"),
    ])
    assert all(f["fixable"] for f in payload["findings"])


def test_a_misplaced_aegis_entry_is_not_fixable_while_no_user_registration_replaces_it(env):
    env.claude_registered()
    env.claude_json({})
    (env.home / ".mcp.json").write_text(json.dumps({"mcpServers": {"aegis": {"command": str(env.mcp)}}}))
    finding = next(f for f in env.doctor()["findings"] if f["code"] == "misplaced_mcp_entry")
    assert finding["fixable"] is False
    assert "aegis init --host claude-code" in finding["message"]


def test_a_local_scope_registration_alone_is_a_registration_not_a_finding(env):
    env.claude_registered()
    env.claude_json({"projects": {str(env.ws.resolve()): {"mcpServers": {"aegis": {
        "command": str(env.mcp), "env": {"AEGIS_CLIENT": "claude-code"}}}}}})
    payload = env.doctor()
    assert host(payload, "claude-code")["registration"]["scope"] == "local"
    assert "misplaced_mcp_entry" not in finding_codes(payload)


def test_legacy_marker_blocks_are_reported_in_project_and_global_instruction_files(env):
    env.all_ok()
    (env.ws / "CLAUDE.md").write_text(
        "@AGENTS.md\n\n<!-- SOMA:START -->\n# Soma Governance Rules\nold\n<!-- SOMA:END -->\n", encoding="utf-8")
    glob_claude = env.home / ".claude" / "CLAUDE.md"
    glob_claude.parent.mkdir()
    glob_claude.write_text("mine\n<!-- AEGIS:START -->\nrules\n<!-- AEGIS:END -->\n", encoding="utf-8")
    broken = env.home / ".codex" / "AGENTS.md"
    broken.parent.mkdir()
    broken.write_text("<!-- SOMA:START -->\nno end\n", encoding="utf-8")
    found = {(Path(f["path"]), f["code"], f["fixable"]) for f in env.doctor()["findings"]}
    assert (env.ws / "CLAUDE.md", "legacy_block", True) in found
    assert (glob_claude, "legacy_block", True) in found
    assert (broken, "legacy_block", False) in found


def test_an_inlined_rules_claude_md_over_budget_is_reported(env):
    env.all_ok()
    big = env.home / ".claude" / "CLAUDE.md"
    big.parent.mkdir()
    big.write_text("# Aegis Governance Rules\n" + "rule text\n" * 5000, encoding="utf-8")
    finding = next(f for f in env.doctor()["findings"] if f["code"] == "instructions_over_budget")
    assert Path(finding["path"]) == big and finding["fixable"] is False


def test_an_empty_home_rules_dir_left_by_v3_auto_mkdir_is_reported(env):
    env.all_ok()
    (env.home / ".aegis" / "rules").mkdir()
    assert "home_rules_dir" in finding_codes(env.doctor())
    (env.home / ".aegis" / "rules" / "mine.md").write_text("# a user rule\n")
    assert "home_rules_dir" not in finding_codes(env.doctor())


def test_v3_flat_rule_copies_are_matched_by_sha256_never_by_name(env, monkeypatch):
    env.all_ok()
    shipped = b"---\nid: providence\n---\n# Providence (as v3.3.0 shipped it)\n"
    monkeypatch.setattr(doctor, "V3_SHIPPED_RULE_SHA256", frozenset({hashlib.sha256(shipped).hexdigest()}))
    leak = env.home / ".gemini" / "config" / "rules" / "providence.md"
    oracle = env.home / ".kiro" / "steering" / ".oracles" / "testing.md"
    edited = env.home / ".kiro" / "steering" / "providence.md"
    user = env.home / ".gemini" / "config" / "rules" / "my-rule.md"
    for path, data in ((leak, shipped), (oracle, shipped), (edited, shipped + b"my edit\n"), (user, b"# mine\n")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    findings = [f for f in env.doctor()["findings"] if f["code"] == "v3_rule_copy"]
    assert sorted(Path(f["path"]) for f in findings) == sorted([leak, oracle])
    assert all(f["fixable"] for f in findings)


def test_the_embedded_v3_digests_are_sha256_hex():
    assert len(doctor.V3_SHIPPED_RULE_SHA256) == 28
    assert all(len(d) == 64 and int(d, 16) >= 0 for d in doctor.V3_SHIPPED_RULE_SHA256)


def test_unparseable_host_config_is_reported_and_makes_registration_unknown(env):
    env.all_ok()
    (env.home / ".gemini" / "config" / "mcp_config.json").write_text("{ // jsonc\n}", encoding="utf-8")
    payload = env.doctor()
    row = host(payload, "antigravity")
    assert row["state"] == "auth_unknown" and row["registration"]["status"] == "unknown"
    assert "unreadable_config" in finding_codes(payload)


# ── human output ────────────────────────────────────────────────────────────

def test_text_output_prints_the_matrix_and_the_tier_table(env):
    env.all_ok()
    env.replies["codex"] = (1, "", "Error: No MCP server named 'aegis' found.\n")
    rc, out = env.run()
    assert "Codex CLI (codex-cli): unregistered" in out
    assert "Claude Code (claude-code): ok" in out
    assert "Enforcement tiers" in out
    for tier in ("Advisory", "Best-effort", "Local floor", "Authoritative"):
        assert tier in out
    assert "aegis init --host codex-cli" in out


def test_claude_budget_counts_agents_md_only_when_claude_md_imports_it(env):
    env.all_ok()
    env.bootstrap(after=("y" * 99 + "\n") * 450)  # AGENTS.md ~45 KB, over Claude Code's 40 KiB
    (env.ws / "CLAUDE.md").write_bytes(b"# Notes only\n")
    budget = host(env.doctor(), "claude-code")["budget"]
    assert (budget["file"], budget["bytes"], budget["within"]) == ("CLAUDE.md", 13, True)

    (env.ws / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    budget = host(env.doctor(), "claude-code")["budget"]
    assert budget["file"] == "CLAUDE.md + AGENTS.md" and budget["within"] is False


def test_a_registration_waiting_for_approval_is_not_counted_as_advisory(env):
    env.claude_registered()
    env.claude_json({})
    (env.ws / ".mcp.json").write_text(json.dumps({"mcpServers": {"aegis": {"command": str(env.mcp)}}}))
    row = host(env.doctor(), "claude-code")
    assert row["state"] == "auth_unknown"
    assert row["enforcement_level"] == "none"  # no bootstrap either: nothing is known to reach it


def test_a_host_doctor_cannot_check_yet_is_never_reported_ok(env):
    env.all_ok()
    env.stub("gemini")
    (env.ws / ".aegis" / "config.json").write_text(json.dumps({"v": 1, "hosts": ["gemini-cli"]}))
    row = host(env.doctor(), "gemini-cli")
    assert row["registration"]["status"] == "unavailable"
    assert row["state"] == "auth_unknown" and "registration_unverifiable" in codes(row)
    assert row["verified_row"] is False
