"""MCP config writers must never destroy a user's config (M3) and register only `aegis`.

Covers `aegis init --mcp` (init.generate_mcp_config), `aegis install --platform mcp`
(McpAdapter) and the Claude Desktop writer (ClaudeAdapter.install_desktop_mcp).
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO_ROOT, symlink_or_skip

from aegis_cli.init import generate_mcp_config, run_init
from aegis_cli.platforms import ClaudeAdapter, GeminiAdapter, McpAdapter


# Inputs that a lenient editor accepts but strict JSON does not, plus valid JSON
# with the wrong shape. Each one must be refused byte-for-byte unchanged.
UNMERGEABLE = {
    "jsonc_comment": b'{\n  // my servers\n  "mcpServers": {"other": {"command": "keep"}}\n}\n',
    "trailing_comma": b'{"mcpServers": {"other": {"command": "keep"},}}\n',
    "utf8_bom": b'\xef\xbb\xbf{"mcpServers": {"other": {"command": "keep"}}}\n',
    "truncated": b'{"mcpServers": {"other": ',
    "non_object_root": b'[{"mcpServers": {}}]\n',
    "servers_not_object": b'{"mcpServers": ["other"]}\n',
    "not_utf8": b'{"mcpServers": {"caf\xe9": {}}}\n',
}

EXISTING = {
    "unrelated": {"keep": True},
    "mcpServers": {
        "other": {"command": "keep", "args": ["--flag"]},
        "soma": {"command": "user-owned-soma", "args": []},
    },
}


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else b"<dir>")
        for p in sorted(root.rglob("*"))
    }


def _init_args(project: Path, home: Path, **overrides) -> argparse.Namespace:
    values = dict(
        dry_run=False, platform="gemini", yes=True, force=False, local=False,
        rules="minimal", mcp=True, portable=False, no_hooks=True,
        _project_root=project, _home=home,
    )
    values.update(overrides)
    return argparse.Namespace(**values)


def _cli(argv: list[str], cwd: Path, home: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(home / ".config"))
    env["PYTHONPATH"] = REPO_ROOT + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return subprocess.run(
        [sys.executable, "-m", "aegis_cli.cli", *argv],
        cwd=str(cwd), env=env, capture_output=True, text=True, timeout=120,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    p.mkdir()
    return p


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    return h


# ── McpAdapter.install (aegis install --platform mcp) ────────────────────────


class TestMcpAdapterRefusesUnmergeableConfig:
    @pytest.mark.parametrize("raw", list(UNMERGEABLE.values()), ids=list(UNMERGEABLE))
    def test_install_refuses_and_keeps_file_byte_identical(self, project: Path, raw: bytes):
        target = project / ".mcp.json"
        target.write_bytes(raw)
        before = _snapshot(project)

        res = McpAdapter(workspace=project).install(local=True)

        assert res.success is False
        assert any(str(target) in e and "refusing to modify" in e for e in res.errors), res.errors
        assert not any(m.startswith("Configured") for m in res.messages), res.messages
        assert _snapshot(project) == before

    def test_cli_install_exits_nonzero_with_clear_error(self, project: Path, home: Path):
        target = project / ".mcp.json"
        target.write_bytes(UNMERGEABLE["jsonc_comment"])

        proc = _cli(["install", "--platform", "mcp", "--local"], cwd=project, home=home)

        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "refusing to modify" in proc.stderr
        assert str(target) in proc.stderr
        assert target.read_bytes() == UNMERGEABLE["jsonc_comment"]


class TestMcpAdapterMergesSafely:
    def test_install_preserves_unrelated_keys_and_servers(self, project: Path):
        target = project / ".mcp.json"
        target.write_text(json.dumps(EXISTING), encoding="utf-8")

        res = McpAdapter(workspace=project).install(local=True)

        assert res.success, res.errors
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["unrelated"] == {"keep": True}
        assert data["mcpServers"]["other"] == {"command": "keep", "args": ["--flag"]}
        # A pre-existing user `soma` entry is left alone (cleanup is doctor --fix's job).
        assert data["mcpServers"]["soma"] == {"command": "user-owned-soma", "args": []}
        assert data["mcpServers"]["aegis"]["command"] == "aegis-mcp"

    def test_install_registers_only_aegis(self, project: Path):
        res = McpAdapter(workspace=project).install(local=True)

        assert res.success, res.errors
        data = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
        assert sorted(data["mcpServers"]) == ["aegis"]

    def test_render_config_registers_only_aegis(self, project: Path):
        adapter = McpAdapter(workspace=project)
        assert sorted(adapter.render_config(local=True)["mcpServers"]) == ["aegis"]
        assert sorted(adapter.render_config(local=False)["mcpServers"]) == ["aegis"]

    def test_failed_commit_leaves_original_intact(self, project: Path, monkeypatch):
        target = project / ".mcp.json"
        original = json.dumps(EXISTING, indent=4).encode("utf-8")
        target.write_bytes(original)

        def failing_replace(src, dst):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(os, "replace", failing_replace)
        res = McpAdapter(workspace=project).install(local=True)

        assert res.success is False
        assert any("No space left on device" in e for e in res.errors), res.errors
        assert target.read_bytes() == original
        assert sorted(p.name for p in project.iterdir()) == [".mcp.json"]

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    def test_install_preserves_file_mode(self, project: Path):
        target = project / ".mcp.json"
        target.write_text(json.dumps(EXISTING), encoding="utf-8")
        os.chmod(target, 0o640)

        assert McpAdapter(workspace=project).install(local=True).success

        assert stat.S_IMODE(target.stat().st_mode) == 0o640

    def test_install_writes_through_symlink(self, project: Path, tmp_path: Path):
        real = tmp_path / "dotfiles" / "mcp.json"
        real.parent.mkdir()
        real.write_text(json.dumps(EXISTING), encoding="utf-8")
        link = project / ".mcp.json"
        symlink_or_skip(real, link)

        assert McpAdapter(workspace=project).install(local=True).success

        assert link.is_symlink()
        data = json.loads(real.read_text(encoding="utf-8"))
        assert "aegis" in data["mcpServers"] and "other" in data["mcpServers"]

    def test_uninstall_failed_commit_leaves_original_intact(self, project: Path, monkeypatch):
        target = project / ".mcp.json"
        original = json.dumps({"mcpServers": {"aegis": {"command": "aegis-mcp"}, "other": {}}}).encode()
        target.write_bytes(original)

        def failing_replace(src, dst):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(os, "replace", failing_replace)
        res = McpAdapter(workspace=project).uninstall(local=True)

        assert res.success is False
        assert target.read_bytes() == original
        assert sorted(p.name for p in project.iterdir()) == [".mcp.json"]


# ── aegis init --mcp (generate_mcp_config / run_init) ────────────────────────


class TestInitMcpRefusesUnmergeableConfig:
    @pytest.mark.parametrize("raw", list(UNMERGEABLE.values()), ids=list(UNMERGEABLE))
    def test_generate_raises_clear_error_and_keeps_bytes(self, project: Path, raw: bytes):
        target = project / ".mcp.json"
        target.write_bytes(raw)
        before = _snapshot(project)

        with pytest.raises(ValueError) as excinfo:
            generate_mcp_config(project)

        from aegis_cli.platforms.base import McpConfigError
        assert isinstance(excinfo.value, McpConfigError)
        assert str(target) in str(excinfo.value)
        assert "refusing to modify" in str(excinfo.value)
        assert _snapshot(project) == before

    def test_run_init_writes_nothing_and_returns_nonzero(self, project: Path, home: Path, capsys):
        target = project / ".mcp.json"
        target.write_bytes(UNMERGEABLE["trailing_comma"])
        project_before, home_before = _snapshot(project), _snapshot(home)

        rc = run_init(_init_args(project, home))

        assert rc == 1
        err = capsys.readouterr().err
        assert "refusing to modify" in err and str(target) in err
        assert _snapshot(project) == project_before
        assert _snapshot(home) == home_before

    def test_cli_init_exits_nonzero_and_writes_nothing(self, project: Path, home: Path):
        target = project / ".mcp.json"
        target.write_bytes(UNMERGEABLE["utf8_bom"])
        project_before = _snapshot(project)

        proc = _cli(["init", "--platform", "gemini", "--yes", "--mcp", "--no-hooks"], cwd=project, home=home)

        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "refusing to modify" in proc.stderr
        assert _snapshot(project) == project_before
        assert not (home / ".gemini").exists()


class TestInitMcpMergesSafely:
    def test_generate_registers_only_aegis_and_keeps_user_entries(self, project: Path):
        target = project / ".mcp.json"
        target.write_text(json.dumps(EXISTING), encoding="utf-8")

        generate_mcp_config(project)

        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["unrelated"] == {"keep": True}
        assert data["mcpServers"]["other"] == {"command": "keep", "args": ["--flag"]}
        assert data["mcpServers"]["soma"] == {"command": "user-owned-soma", "args": []}
        assert data["mcpServers"]["aegis"]["env"] == {"AEGIS_WORKSPACE": str(project.resolve())}

    def test_generate_fresh_file_registers_only_aegis(self, project: Path):
        generate_mcp_config(project)

        data = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
        assert sorted(data["mcpServers"]) == ["aegis"]

    def test_generate_failed_commit_leaves_original_intact(self, project: Path, monkeypatch):
        target = project / ".mcp.json"
        original = json.dumps(EXISTING).encode("utf-8")
        target.write_bytes(original)

        def failing_replace(src, dst):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(os, "replace", failing_replace)
        with pytest.raises(OSError, match="No space left on device"):
            generate_mcp_config(project)

        assert target.read_bytes() == original
        assert sorted(p.name for p in project.iterdir()) == [".mcp.json"]


# ── Other writers of the MCP registration ────────────────────────────────────


class TestOtherWritersRegisterOnlyAegis:
    def test_base_render_mcp_config_registers_only_aegis(self, project: Path, home: Path):
        cfg = GeminiAdapter(workspace=project, home=home).render_mcp_config(local=True)
        assert sorted(cfg["mcpServers"]) == ["aegis"]

    def test_claude_render_mcp_config_registers_only_aegis(self, project: Path, home: Path):
        cfg = ClaudeAdapter(workspace=project, home=home).render_mcp_config(local=False)
        assert sorted(cfg["mcpServers"]) == ["aegis"]

    def test_claude_desktop_registers_only_aegis_and_keeps_user_entries(self, project: Path, home: Path):
        desktop = home / ".config" / "Claude" / "claude_desktop_config.json"
        desktop.parent.mkdir(parents=True)
        desktop.write_text(json.dumps(EXISTING), encoding="utf-8")

        res = ClaudeAdapter(workspace=project, home=home).install(local=False)

        assert res.success, res.errors
        data = json.loads(desktop.read_text(encoding="utf-8"))
        assert data["unrelated"] == {"keep": True}
        assert data["mcpServers"]["other"] == {"command": "keep", "args": ["--flag"]}
        assert data["mcpServers"]["soma"] == {"command": "user-owned-soma", "args": []}
        assert data["mcpServers"]["aegis"]["command"] == "aegis-mcp"

    def test_claude_desktop_fresh_file_registers_only_aegis(self, project: Path, home: Path):
        (home / ".config" / "Claude").mkdir(parents=True)

        res = ClaudeAdapter(workspace=project, home=home).install(local=False)

        assert res.success, res.errors
        desktop = home / ".config" / "Claude" / "claude_desktop_config.json"
        assert sorted(json.loads(desktop.read_text(encoding="utf-8"))["mcpServers"]) == ["aegis"]

    def test_claude_desktop_refuses_unparseable_config(self, project: Path, home: Path):
        desktop = home / ".config" / "Claude" / "claude_desktop_config.json"
        desktop.parent.mkdir(parents=True)
        desktop.write_bytes(UNMERGEABLE["jsonc_comment"])

        res = ClaudeAdapter(workspace=project, home=home).install(local=False)

        assert res.success is False
        assert any(str(desktop) in e and "refusing to modify" in e for e in res.errors), res.errors
        assert desktop.read_bytes() == UNMERGEABLE["jsonc_comment"]

    def test_claude_uninstall_failed_commit_leaves_original_intact(self, project: Path, home: Path, monkeypatch):
        target = project / ".mcp.json"
        original = json.dumps({"mcpServers": {"aegis": {"command": "aegis-mcp"}, "other": {}}}).encode()
        target.write_bytes(original)

        def failing_replace(src, dst):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(os, "replace", failing_replace)
        ClaudeAdapter(workspace=project, home=home).uninstall(local=True)

        assert target.read_bytes() == original
        assert sorted(p.name for p in project.iterdir()) == [".mcp.json"]
