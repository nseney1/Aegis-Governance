"""`aegis init --host ...` on a fake HOME: the exact files each host selection writes.

Lens: user-data safety on real config files. A second init changes nothing, a dry run
writes nothing, and a file Aegis cannot change safely (unparseable JSON, a symlinked
AGENTS.md, a hand-edited block) stops init before anything at all is written.
Host CLIs are replaced at the subprocess boundary (``install_hosts._run_cli``).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import symlink_or_skip

import aegis_cli.install_hosts as ih
from aegis_cli.cli import main
from aegis_core.bootstrap import bootstrap_text

STANDARD = {"providence", "destructive-ops", "testing", "cost-optimization", "git-workflow"}


class Runner:
    def __init__(self, returncode: int = 0):
        self.calls: list = []
        self.returncode = returncode

    def __call__(self, argv):
        self.calls.append([Path(argv[0]).name.replace(".exe", ""), *argv[1:]])
        return subprocess.CompletedProcess(argv, self.returncode, "", "" if self.returncode == 0 else "denied")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A project, an empty HOME, a PATH holding only fake host binaries and aegis-mcp."""
    project = tmp_path / "project"
    project.mkdir()
    home = Path.home()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("codex", "claude", "agy", "aegis-mcp"):
        exe = bindir / (name + (".exe" if os.name == "nt" else ""))
        exe.write_bytes(b"#!/bin/sh\nexit 0\n")
        exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    runner = Runner()
    monkeypatch.setattr(ih, "_run_cli", runner)
    mcp = os.path.realpath(bindir / ("aegis-mcp" + (".exe" if os.name == "nt" else "")))
    return type("Env", (), {"project": project, "home": home, "bin": bindir, "runner": runner, "mcp": mcp})


def init(env, *flags) -> int:
    return main(["init", "--workspace", str(env.project), "--yes", "--no-hooks", "--rules", "standard", *flags])


def files(root: Path, skip_state: bool = True) -> set:
    found = set()
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            rel = Path(dirpath, name).relative_to(root).as_posix()
            if skip_state and rel.startswith(".aegis/state/"):
                continue
            found.add(rel)
    return found


def snapshot(*roots: Path) -> dict:
    out = {}
    for root in roots:
        for dirpath, dirs, names in os.walk(root):
            for name in dirs + names:
                p = Path(dirpath, name)
                out[str(p)] = "<dir>" if p.is_dir() and not p.is_symlink() else (
                    os.readlink(p) if p.is_symlink() else p.read_bytes())
    return out


REPO_FILES = {".aegis/config.json", ".aegis/.gitignore", "AGENTS.md"} | {
    f".aegis/rules/personas/{n}.md" for n in STANDARD}


def _codex_add(mcp, *extra):
    return ["codex", "mcp", "add", "aegis", "--env", "AEGIS_CLIENT=codex-cli", *extra, "--", mcp]


def _claude_add(mcp, *extra):
    return ["claude", "mcp", "add", "--scope", "user", "aegis", "-e", "AEGIS_CLIENT=claude-code", *extra, "--", mcp]


class TestExactFilesPerHostSelection:
    def test_no_host_selected_registers_nothing_and_proposes_detected_hosts(self, env, capsys):
        assert init(env) == 0
        assert files(env.project) == REPO_FILES
        assert files(env.home) == {".aegis/workspaces.json"}
        assert env.runner.calls == []
        assert json.loads((env.project / ".aegis" / "config.json").read_text(encoding="utf-8")) == {"v": 1}
        (entry,) = json.loads((env.home / ".aegis" / "workspaces.json").read_text(encoding="utf-8"))["workspaces"]
        assert entry["root"] == str(env.project.resolve()) and entry["hosts"] == []
        out = capsys.readouterr().out
        assert "aegis init --host codex-cli,claude-code,antigravity" in out

    def test_codex_only(self, env):
        assert init(env, "--host", "codex-cli") == 0
        assert files(env.project) == REPO_FILES
        assert files(env.home) == {".aegis/workspaces.json"}
        assert env.runner.calls == [["codex", "mcp", "remove", "aegis"], _codex_add(env.mcp)]
        config = json.loads((env.project / ".aegis" / "config.json").read_text(encoding="utf-8"))
        assert config == {"v": 1, "hosts": ["codex-cli"]}

    def test_claude_code_only_at_user_scope(self, env):
        assert init(env, "--host", "claude-code") == 0
        assert files(env.home) == {".aegis/workspaces.json"}
        assert env.runner.calls == [["claude", "mcp", "remove", "--scope", "user", "aegis"], _claude_add(env.mcp)]

    def test_antigravity_only_merges_its_json_file(self, env):
        assert init(env, "--host", "antigravity") == 0
        assert files(env.home) == {".aegis/workspaces.json", ".gemini/config/mcp_config.json"}
        assert env.runner.calls == []
        data = json.loads((env.home / ".gemini" / "config" / "mcp_config.json").read_text(encoding="utf-8"))
        assert data == {"mcpServers": {"aegis": {"command": env.mcp, "args": [],
                                                 "env": {"AEGIS_CLIENT": "antigravity"}}}}

    def test_all_three_hosts(self, env):
        assert init(env, "--host", "antigravity,claude-code,codex-cli") == 0
        assert files(env.project) == REPO_FILES
        assert files(env.home) == {".aegis/workspaces.json", ".gemini/config/mcp_config.json"}
        assert [c[0] for c in env.runner.calls] == ["codex", "codex", "claude", "claude"]
        registry = json.loads((env.home / ".aegis" / "workspaces.json").read_text(encoding="utf-8"))
        assert registry["v"] == 1
        (entry,) = registry["workspaces"]
        assert entry["hosts"] == ["codex-cli", "claude-code", "antigravity"]
        assert entry["added_by"] == "aegis init"

    def test_auto_registers_only_what_is_detected(self, env, monkeypatch):
        for name in ("codex", "agy"):
            (env.bin / (name + (".exe" if os.name == "nt" else ""))).unlink()
        assert init(env, "--host", "auto") == 0
        assert [c[0] for c in env.runner.calls] == ["claude", "claude"]
        assert not (env.home / ".gemini").exists()

    def test_pin_adds_the_workspace_env(self, env):
        assert init(env, "--host", "codex-cli,antigravity", "--pin") == 0
        root = str(env.project.resolve())
        assert env.runner.calls[-1] == _codex_add(env.mcp, "--env", f"AEGIS_WORKSPACE={root}")
        data = json.loads((env.home / ".gemini" / "config" / "mcp_config.json").read_text(encoding="utf-8"))
        assert data["mcpServers"]["aegis"]["env"] == {"AEGIS_CLIENT": "antigravity", "AEGIS_WORKSPACE": root}

    def test_without_aegis_mcp_on_path_the_interpreter_is_the_command(self, env):
        (env.bin / ("aegis-mcp" + (".exe" if os.name == "nt" else ""))).unlink()
        import sys
        assert init(env, "--host", "codex-cli") == 0
        assert env.runner.calls[-1][-4:] == ["--", sys.executable, "-m", "aegis_mcp"]

    def test_existing_antigravity_servers_are_kept(self, env):
        cfg = env.home / ".gemini" / "config" / "mcp_config.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"mcpServers": {"github": {"command": "gh"}}, "other": True}), encoding="utf-8")
        assert init(env, "--host", "antigravity") == 0
        data = json.loads(cfg.read_text(encoding="utf-8"))
        assert data["other"] is True and data["mcpServers"]["github"] == {"command": "gh"}
        assert "soma" not in data["mcpServers"]


class TestBootstrapAndClaudeShim:
    def test_agents_md_gets_the_bootstrap_block_after_user_text(self, env):
        agents = env.project / "AGENTS.md"
        agents.write_text("# Our agents guide\n", encoding="utf-8")
        assert init(env) == 0
        text = agents.read_text(encoding="utf-8")
        assert text.startswith("# Our agents guide\n\n<!-- aegis:begin id=bootstrap v=1 sha=")
        assert bootstrap_text() in text
        assert text.endswith("<!-- aegis:end id=bootstrap -->\n")

    def test_claude_md_is_never_created(self, env):
        assert init(env, "--host", "claude-code") == 0
        assert not (env.project / "CLAUDE.md").exists()

    def test_existing_claude_md_gets_the_agents_import_block(self, env):
        claude = env.project / "CLAUDE.md"
        claude.write_bytes(b"# Claude notes\r\n")
        assert init(env) == 0
        assert claude.read_bytes() == (
            b"# Claude notes\r\n\r\n<!-- aegis:begin id=agents-import v=1 sha="
            + ih._digest("@AGENTS.md\n").encode() + b" -->\r\n@AGENTS.md\r\n<!-- aegis:end id=agents-import -->\r\n")

    def test_force_replaces_a_hand_edited_bootstrap(self, env):
        agents = env.project / "AGENTS.md"
        agents.write_text("<!-- aegis:begin id=bootstrap v=1 sha=000000000000 -->\nmine\n"
                          "<!-- aegis:end id=bootstrap -->\n", encoding="utf-8")
        assert init(env, "--force") == 0
        assert bootstrap_text() in agents.read_text(encoding="utf-8")


class TestIdempotency:
    def test_second_init_changes_nothing(self, env):
        claude = env.project / "CLAUDE.md"
        claude.write_text("# mine\n", encoding="utf-8")
        assert init(env, "--host", "codex-cli,claude-code,antigravity") == 0
        before = snapshot(env.project, env.home)
        first_calls = list(env.runner.calls)
        assert init(env, "--host", "codex-cli,claude-code,antigravity") == 0
        after = snapshot(env.project, env.home)
        assert {k: v for k, v in after.items() if "/.aegis/state" not in k.replace(os.sep, "/")} == \
               {k: v for k, v in before.items() if "/.aegis/state" not in k.replace(os.sep, "/")}
        # The native registrations converge (remove-then-add with the same argv).
        assert env.runner.calls == first_calls * 2

    def test_a_second_host_is_added_to_config_and_registry(self, env):
        assert init(env, "--host", "antigravity") == 0
        assert init(env, "--host", "codex-cli") == 0
        config = json.loads((env.project / ".aegis" / "config.json").read_text(encoding="utf-8"))
        assert config["hosts"] == ["codex-cli", "antigravity"]
        (entry,) = json.loads((env.home / ".aegis" / "workspaces.json").read_text(encoding="utf-8"))["workspaces"]
        assert entry["hosts"] == ["codex-cli", "antigravity"]


class TestRefusalsWriteNothing:
    def _refused(self, env, capsys, *flags, message):
        before = snapshot(env.project, env.home)
        assert init(env, *flags) == 1
        assert snapshot(env.project, env.home) == before
        assert env.runner.calls == []
        assert message in capsys.readouterr().err

    @pytest.mark.parametrize("raw", [b'{"mcpServers": {}, // jsonc\n}', b"\xef\xbb\xbf{}", b'{"mcpServers": {},}'])
    def test_unparseable_antigravity_config(self, env, capsys, raw):
        cfg = env.home / ".gemini" / "config" / "mcp_config.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_bytes(raw)
        self._refused(env, capsys, "--host", "codex-cli,antigravity", message=str(cfg))

    def test_symlinked_antigravity_config(self, env, capsys, tmp_path):
        real = tmp_path / "dotfiles.json"
        real.write_bytes(b"{}")
        cfg = env.home / ".gemini" / "config" / "mcp_config.json"
        cfg.parent.mkdir(parents=True)
        symlink_or_skip(real, cfg)
        self._refused(env, capsys, "--host", "antigravity", message="symlink")
        assert real.read_bytes() == b"{}"

    def test_symlinked_agents_md(self, env, capsys, tmp_path):
        outside = tmp_path / "outside.md"
        outside.write_bytes(b"not yours\n")
        symlink_or_skip(outside, env.project / "AGENTS.md")
        self._refused(env, capsys, "--host", "codex-cli", message="symlink")
        assert outside.read_bytes() == b"not yours\n"

    def test_hand_edited_bootstrap_block(self, env, capsys):
        (env.project / "AGENTS.md").write_text(
            "<!-- aegis:begin id=bootstrap v=1 sha=000000000000 -->\nmine\n<!-- aegis:end id=bootstrap -->\n",
            encoding="utf-8")
        self._refused(env, capsys, "--host", "codex-cli", message="--force")

    def test_symlinked_claude_md(self, env, capsys, tmp_path):
        outside = tmp_path / "CLAUDE.md"
        outside.write_bytes(b"x\n")
        symlink_or_skip(outside, env.project / "CLAUDE.md")
        self._refused(env, capsys, message="symlink")

    def test_unreadable_registry(self, env, capsys):
        reg = env.home / ".aegis" / "workspaces.json"
        reg.parent.mkdir(parents=True)
        reg.write_bytes(b"[broken")
        self._refused(env, capsys, message="workspaces.json")

    def test_symlinked_config_json(self, env, capsys, tmp_path):
        (env.project / ".aegis").mkdir()
        symlink_or_skip(tmp_path / "planted.json", env.project / ".aegis" / "config.json")
        self._refused(env, capsys, message="symlink")
        assert not (tmp_path / "planted.json").exists()


class TestDryRunAndFailures:
    def test_dry_run_writes_nothing_and_runs_no_host_cli(self, env, capsys):
        before = snapshot(env.project, env.home)
        assert main(["init", "--workspace", str(env.project), "--dry-run", "--host",
                     "codex-cli,claude-code,antigravity"]) == 0
        assert snapshot(env.project, env.home) == before
        assert env.runner.calls == []
        out = capsys.readouterr().out
        assert "codex mcp add aegis --env AEGIS_CLIENT=codex-cli --" in out
        assert "mcp_config.json" in out

    def test_missing_host_cli_prints_the_exact_command(self, env, capsys):
        (env.bin / ("claude" + (".exe" if os.name == "nt" else ""))).unlink()
        assert init(env, "--host", "claude-code") == 0
        assert env.runner.calls == []
        out = capsys.readouterr().out
        assert ih.display_command(_claude_add(env.mcp)) in out

    def test_failed_registration_exits_1_after_the_other_steps(self, env, capsys, monkeypatch):
        monkeypatch.setattr(ih, "_run_cli", Runner(returncode=1))
        assert init(env, "--host", "codex-cli,antigravity") == 1
        assert (env.project / "AGENTS.md").is_file()
        assert (env.home / ".gemini" / "config" / "mcp_config.json").is_file()
        assert "codex-cli" in capsys.readouterr().err
