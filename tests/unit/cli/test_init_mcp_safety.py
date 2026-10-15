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

    def test_global_install_writes_through_dotfile_symlink(self, project: Path, home: Path, tmp_path: Path):
        real = tmp_path / "dotfiles" / "mcp.json"
        real.parent.mkdir()
        real.write_text(json.dumps(EXISTING), encoding="utf-8")
        link = home / ".mcp.json"
        symlink_or_skip(real, link)

        res = McpAdapter(workspace=project, home=home).install(local=False)

        assert res.success, res.errors
        assert link.is_symlink()
        data = json.loads(real.read_text(encoding="utf-8"))
        assert "aegis" in data["mcpServers"] and "other" in data["mcpServers"]

    def test_local_install_writes_through_symlink_inside_project(self, project: Path):
        real = project / "config" / "mcp.json"
        real.parent.mkdir()
        real.write_text(json.dumps(EXISTING), encoding="utf-8")
        link = project / ".mcp.json"
        symlink_or_skip(Path("config") / "mcp.json", link)

        res = McpAdapter(workspace=project).install(local=True)

        assert res.success, res.errors
        assert link.is_symlink()
        assert "aegis" in json.loads(real.read_text(encoding="utf-8"))["mcpServers"]

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

    def test_claude_refused_desktop_config_installs_nothing(self, project: Path, home: Path):
        desktop = home / ".config" / "Claude" / "claude_desktop_config.json"
        desktop.parent.mkdir(parents=True)
        desktop.write_bytes(UNMERGEABLE["jsonc_comment"])
        before = _snapshot(home)

        res = ClaudeAdapter(workspace=project, home=home).install(local=False)

        assert res.success is False
        assert any(str(desktop) in e and "nothing was installed" in e for e in res.errors), res.errors
        assert not any(m.startswith("Installed") for m in res.messages), res.messages
        assert _snapshot(home) == before

    def test_cli_claude_install_fails_fast_on_refused_desktop_config(self, project: Path, home: Path):
        desktop = home / ".config" / "Claude" / "claude_desktop_config.json"
        desktop.parent.mkdir(parents=True)
        desktop.write_bytes(UNMERGEABLE["trailing_comma"])

        proc = _cli(["install", "--platform", "claude"], cwd=project, home=home)

        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "Installed Claude configuration" not in proc.stdout
        assert "refusing to modify" in proc.stderr and "nothing was installed" in proc.stderr
        assert not (home / ".claude").exists()
        assert desktop.read_bytes() == UNMERGEABLE["trailing_comma"]

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


# ── Files that hold nothing to lose are merged, not refused ──────────────────

# Valid JSON whose server table is null, and files with no JSON at all: there is no
# user data to destroy, so every writer merges into them instead of refusing.
NO_DATA = {
    "null_servers": b'{"unrelated": {"keep": true}, "mcpServers": null}\n',
    "empty": b"",
    "whitespace_only": b"  \n\t\n",
}


def _assert_only_aegis_added(target: Path, raw: bytes) -> None:
    data = json.loads(target.read_text(encoding="utf-8"))
    assert sorted(data["mcpServers"]) == ["aegis"]
    if b"unrelated" in raw:
        assert data["unrelated"] == {"keep": True}


class TestNoDataConfigsAreMerged:
    @pytest.mark.parametrize("raw", list(NO_DATA.values()), ids=list(NO_DATA))
    def test_mcp_adapter_install_merges(self, project: Path, raw: bytes):
        target = project / ".mcp.json"
        target.write_bytes(raw)

        res = McpAdapter(workspace=project).install(local=True)

        assert res.success, res.errors
        _assert_only_aegis_added(target, raw)

    @pytest.mark.parametrize("raw", list(NO_DATA.values()), ids=list(NO_DATA))
    def test_generate_mcp_config_merges(self, project: Path, raw: bytes):
        target = project / ".mcp.json"
        target.write_bytes(raw)

        generate_mcp_config(project)

        _assert_only_aegis_added(target, raw)

    @pytest.mark.parametrize("raw", list(NO_DATA.values()), ids=list(NO_DATA))
    def test_run_init_succeeds(self, project: Path, home: Path, raw: bytes):
        target = project / ".mcp.json"
        target.write_bytes(raw)

        assert run_init(_init_args(project, home)) == 0

        _assert_only_aegis_added(target, raw)
        assert (project / ".aegis").is_dir()

    @pytest.mark.parametrize("raw", list(NO_DATA.values()), ids=list(NO_DATA))
    def test_claude_desktop_merges(self, project: Path, home: Path, raw: bytes):
        desktop = home / ".config" / "Claude" / "claude_desktop_config.json"
        desktop.parent.mkdir(parents=True)
        desktop.write_bytes(raw)

        res = ClaudeAdapter(workspace=project, home=home).install(local=False)

        assert res.success, res.errors
        _assert_only_aegis_added(desktop, raw)


# ── Edges of the atomic writer ───────────────────────────────────────────────


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
class TestReadOnlyConfigIsRefused:
    """A rename replaces a 0444 file without complaint; the owner's read-only bit is intent."""

    def _read_only(self, path: Path, payload: bytes) -> bytes:
        path.write_bytes(payload)
        os.chmod(path, 0o444)
        return payload

    def test_mcp_adapter_install_refuses(self, project: Path):
        target = project / ".mcp.json"
        original = self._read_only(target, json.dumps(EXISTING).encode())
        before = _snapshot(project)

        res = McpAdapter(workspace=project).install(local=True)

        assert res.success is False
        assert any(str(target) in e and "read-only" in e for e in res.errors), res.errors
        assert _snapshot(project) == before
        assert target.read_bytes() == original
        assert stat.S_IMODE(target.stat().st_mode) == 0o444

    def test_mcp_adapter_uninstall_refuses(self, project: Path):
        target = project / ".mcp.json"
        original = self._read_only(
            target, json.dumps({"mcpServers": {"aegis": {"command": "aegis-mcp"}, "other": {}}}).encode()
        )

        res = McpAdapter(workspace=project).uninstall(local=True)

        assert res.success is False
        assert any("read-only" in e for e in res.errors), res.errors
        assert target.read_bytes() == original

    def test_generate_mcp_config_refuses(self, project: Path):
        from aegis_cli.platforms.base import McpConfigError

        target = project / ".mcp.json"
        original = self._read_only(target, json.dumps(EXISTING).encode())

        with pytest.raises(McpConfigError, match="read-only"):
            generate_mcp_config(project)

        assert target.read_bytes() == original

    def test_run_init_writes_nothing(self, project: Path, home: Path, capsys):
        target = project / ".mcp.json"
        self._read_only(target, json.dumps(EXISTING).encode())
        before = _snapshot(project)

        assert run_init(_init_args(project, home)) == 1

        assert "read-only" in capsys.readouterr().err
        assert _snapshot(project) == before


class TestProjectConfigSymlinkIsConfined:
    """A cloned repo may ship `.mcp.json` as a symlink; never merge into a file outside it."""

    def _outside_link(self, project: Path, tmp_path: Path) -> tuple[Path, bytes]:
        victim = tmp_path / "victim.json"
        original = b'{"theme": "dark"}\n'
        victim.write_bytes(original)
        symlink_or_skip(victim, project / ".mcp.json")
        return victim, original

    def test_generate_refuses_symlink_outside_project(self, project: Path, tmp_path: Path):
        from aegis_cli.platforms.base import McpConfigError

        victim, original = self._outside_link(project, tmp_path)

        with pytest.raises(McpConfigError) as excinfo:
            generate_mcp_config(project)

        assert "outside the project" in str(excinfo.value)
        assert str(victim) in str(excinfo.value)
        assert victim.read_bytes() == original
        assert (project / ".mcp.json").is_symlink()

    def test_run_init_refuses_and_writes_nothing(self, project: Path, home: Path, tmp_path: Path, capsys):
        victim, original = self._outside_link(project, tmp_path)
        before = _snapshot(project)

        assert run_init(_init_args(project, home)) == 1

        assert "outside the project" in capsys.readouterr().err
        assert victim.read_bytes() == original
        assert _snapshot(project) == before

    def test_mcp_adapter_local_install_refuses(self, project: Path, tmp_path: Path):
        victim, original = self._outside_link(project, tmp_path)

        res = McpAdapter(workspace=project).install(local=True)

        assert res.success is False
        assert any("outside the project" in e for e in res.errors), res.errors
        assert victim.read_bytes() == original

    def test_dangling_symlink_outside_project_creates_nothing(self, project: Path, tmp_path: Path):
        from aegis_cli.platforms.base import McpConfigError

        ghost = tmp_path / "elsewhere" / "ghost.json"
        ghost.parent.mkdir()
        symlink_or_skip(ghost, project / ".mcp.json")

        with pytest.raises(McpConfigError, match="outside the project"):
            generate_mcp_config(project)

        assert not ghost.exists()

    def test_generate_reports_symlink_target_inside_project(self, project: Path, capsys):
        real = project / "config" / "mcp.json"
        real.parent.mkdir()
        real.write_text(json.dumps(EXISTING), encoding="utf-8")
        symlink_or_skip(Path("config") / "mcp.json", project / ".mcp.json")

        generate_mcp_config(project)

        assert (project / ".mcp.json").is_symlink()
        assert "aegis" in json.loads(real.read_text(encoding="utf-8"))["mcpServers"]
        assert str(real.resolve()) in capsys.readouterr().out


class TestNonAsciiIsKeptVerbatim:
    USER = {"mcpServers": {"café": {"command": "ü", "args": ["—"]}}}

    def test_mcp_adapter_install(self, project: Path):
        target = project / ".mcp.json"
        target.write_text(json.dumps(self.USER, ensure_ascii=False), encoding="utf-8")

        assert McpAdapter(workspace=project).install(local=True).success

        raw = target.read_bytes()
        assert "café".encode("utf-8") in raw and "—".encode("utf-8") in raw
        assert b"\\u" not in raw
        assert json.loads(raw)["mcpServers"]["café"] == {"command": "ü", "args": ["—"]}

    def test_generate_mcp_config(self, project: Path):
        target = project / ".mcp.json"
        target.write_text(json.dumps(self.USER, ensure_ascii=False), encoding="utf-8")

        generate_mcp_config(project)

        raw = target.read_bytes()
        assert "café".encode("utf-8") in raw and b"\\u" not in raw
