"""`aegis package --host claude-code`: an experimental Claude Code plugin directory (v4.2 #8).

The layout is tested in tests/unit/core/test_packaging.py. Here: the host check (only
claude-code; every other host, the retired Gemini CLI included, gets a clear refusal), the
absolute commands (aegis-mcp or the isolated runner, never -m), the hook probe, the skills
rendered as `aegis skills sync` renders them for Claude Code, the exit codes (0 done, 1
refused, 2 usage), the machine-readable envelope, the one `package` event, --dry-run, and
that the real HOME is untouched. No host CLI and no model is run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import List

import pytest

from aegis_cli import skills_sync
from aegis_cli.cli import main
from aegis_cli.hooks import registrar
from aegis_cli.init import packaged_dir
from aegis_core import events, hosts as host_table, packaging

TS = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / ".aegis" / "rules").mkdir(parents=True)
    return root.resolve()


@pytest.fixture
def fake_aegis(tmp_path: Path, monkeypatch) -> str:
    """An absolute 'aegis' the hook probe can run: it exits 0 on any arguments."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / ("aegis.cmd" if os.name == "nt" else "aegis")
    script.write_text("@exit /b 0\n" if os.name == "nt" else "#!/bin/sh\nexit 0\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    mcp = bindir / "aegis-mcp"
    mcp.write_text("#!/bin/sh\nexit 0\n")
    mcp.chmod(mcp.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setattr(registrar, "aegis_command", lambda *a, **k: str(script))
    return str(script)


def _run(capsys, ws: Path, *argv: str):
    rc = main(["package", "--workspace", str(ws), *argv])
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _tree(root: Path) -> List[str]:
    return sorted(str(p.relative_to(root)).replace(os.sep, "/") for p in root.rglob("*"))


def test_it_writes_the_plugin_dir_with_the_documented_layout(ws, fake_aegis, capsys, tmp_path):
    out = tmp_path / "plugin"
    rc, stdout, err = _run(capsys, ws, "--host", "claude-code", "--out", str(out))
    assert (rc, err) == (0, "")
    manifest = json.loads((out / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "aegis-guardrails"
    skill_ids = sorted(p.parent.name for p in (out / "skills").glob("*/SKILL.md"))
    packaged = sorted(p.parent.name for p in packaged_dir("skills").glob("*/SKILL.md"))
    assert skill_ids == packaged and len(skill_ids) >= 10
    assert "experimental" in stdout.lower() and "nothing is published" in stdout.lower()


def test_the_mcp_entry_is_the_absolute_server_and_never_dash_m(ws, fake_aegis, capsys, tmp_path):
    out = tmp_path / "plugin"
    _run(capsys, ws, "--host", "claude-code", "--out", str(out))
    server = json.loads((out / ".mcp.json").read_text())["mcpServers"]["aegis"]
    if os.name == "nt":  # the stub dir holds only aegis.exe; the real aegis-mcp.exe is found elsewhere
        assert Path(server["command"]).is_absolute() and Path(server["command"]).stem == "aegis-mcp"
    else:
        assert server["command"] == str(Path(fake_aegis).parent / "aegis-mcp")
    assert server["args"] == [] and server["env"]["AEGIS_CLIENT"] == "claude-code"


def test_without_an_installed_script_the_isolated_runner_is_used(ws, fake_aegis, capsys, tmp_path, monkeypatch):
    from aegis_cli import install_hosts

    monkeypatch.setattr(install_hosts, "mcp_command", lambda *a, **k: [sys.executable, "-I", "-c", "x", "/site"])
    out = tmp_path / "plugin"
    assert _run(capsys, ws, "--host", "claude-code", "--out", str(out))[0] == 0
    server = json.loads((out / ".mcp.json").read_text())["mcpServers"]["aegis"]
    assert server["command"] == sys.executable and server["args"][:2] == ["-I", "-c"]
    assert "-m" not in server["args"]


def test_the_hook_is_the_registrars_exec_form_group(ws, fake_aegis, capsys, tmp_path):
    out = tmp_path / "plugin"
    _run(capsys, ws, "--host", "claude-code", "--out", str(out))
    doc = json.loads((out / "hooks" / "hooks.json").read_text())
    assert doc == {"hooks": {"PreToolUse": [registrar.hook_group("claude-code", fake_aegis)]}}


def test_the_skills_are_the_claude_code_projection_of_skills_sync(ws, fake_aegis, capsys, tmp_path):
    out = tmp_path / "plugin"
    _run(capsys, ws, "--host", "claude-code", "--out", str(out))
    skills, errors = skills_sync._packaged_skills(packaged_dir("skills"))
    assert errors == []
    profile = host_table.get("claude-code").slot_profile
    for skill in skills:
        assert (out / "skills" / skill.id / "SKILL.md").read_bytes() == skills_sync._render(skill, profile)


@pytest.mark.parametrize("host", ["codex-cli", "antigravity", "gemini-cli", "cursor", "nope", "claude-code,codex-cli"])
def test_any_other_host_is_refused_with_nothing_written(ws, fake_aegis, capsys, tmp_path, host):
    out = tmp_path / "plugin"
    rc, stdout, err = _run(capsys, ws, "--host", host, "--out", str(out))
    assert (rc, stdout) == (2, "")
    assert err.startswith("Error: ")
    assert "only --host claude-code is supported" in err
    assert not out.exists() and events.read(ws).rows == []


def test_the_retired_gemini_cli_is_named_as_retired(ws, fake_aegis, capsys, tmp_path):
    rc, _out, err = _run(capsys, ws, "--host", "gemini-cli", "--out", str(tmp_path / "p"))
    assert rc == 2 and "retired" in err


def test_a_missing_host_is_a_usage_error(ws, fake_aegis, capsys, tmp_path):
    rc, out, err = _run(capsys, ws, "--out", str(tmp_path / "p"))
    assert (rc, out) == (2, "")
    assert "only --host claude-code is supported" in err


def test_without_an_absolute_aegis_it_is_refused(ws, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(registrar, "aegis_command", lambda *a, **k: None)
    out = tmp_path / "plugin"
    rc, stdout, err = _run(capsys, ws, "--host", "claude-code", "--out", str(out))
    assert (rc, stdout) == (1, "")
    assert "no absolute aegis" in err and not out.exists()


def test_an_aegis_without_hook_run_is_refused(ws, fake_aegis, capsys, tmp_path, monkeypatch):
    from aegis_cli.install_hosts import InstallError

    def old(host, aegis, **kw):
        raise InstallError(f"{aegis} does not support `hook run` (exit 2)")

    monkeypatch.setattr(registrar, "probe_hook_run", old)
    out = tmp_path / "plugin"
    rc, _o, err = _run(capsys, ws, "--host", "claude-code", "--out", str(out))
    assert rc == 1 and "does not support `hook run`" in err and not out.exists()


def test_the_probe_runs_the_chosen_aegis_with_hook_run(ws, fake_aegis, capsys, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(registrar, "probe_hook_run", lambda host, aegis, **kw: seen.append((host, aegis)))
    _run(capsys, ws, "--host", "claude-code", "--out", str(tmp_path / "p"))
    assert seen == [("claude-code", fake_aegis)]


def test_a_directory_that_is_not_ours_is_refused_untouched(ws, fake_aegis, capsys, tmp_path):
    out = tmp_path / "plugin"
    out.mkdir()
    (out / "mine.txt").write_text("keep")
    rc, stdout, err = _run(capsys, ws, "--host", "claude-code", "--out", str(out))
    assert (rc, stdout) == (1, "")
    assert err == f"Error: {out} is not empty and is not an Aegis plugin directory; choose another --out\n"
    assert _tree(out) == ["mine.txt"] and events.read(ws).rows == []


def test_a_dry_run_writes_neither_files_nor_event(ws, fake_aegis, capsys, tmp_path):
    out = tmp_path / "plugin"
    rc, stdout, err = _run(capsys, ws, "--host", "claude-code", "--out", str(out), "--dry-run")
    assert (rc, err) == (0, "")
    assert "would create" in stdout and not out.exists() and events.read(ws).rows == []


def test_the_default_out_is_aegis_claude_plugin_in_the_workspace(ws, fake_aegis, capsys):
    rc, _o, _e = _run(capsys, ws, "--host", "claude-code")
    assert rc == 0 and (ws / "aegis-claude-plugin" / ".claude-plugin" / "plugin.json").is_file()


def test_one_package_event_records_what_was_written(ws, fake_aegis, capsys, tmp_path):
    out = tmp_path / "plugin"
    _run(capsys, ws, "--host", "claude-code", "--out", str(out))
    (row,) = events.read(ws, "package").rows
    assert row["result"] == "ok" and row["host"] == "claude-code"
    assert row["detail"]["files"] == sum(1 for p in out.rglob("*") if p.is_file())
    assert row["detail"]["out"] == out.as_posix() and row["detail"]["experimental"] is True
    assert row["detail"]["counts"] == {"created": row["detail"]["files"]}


def test_a_rerun_is_unchanged_and_still_records_an_event(ws, fake_aegis, capsys, tmp_path):
    out = tmp_path / "plugin"
    _run(capsys, ws, "--host", "claude-code", "--out", str(out))
    rc, stdout, _e = _run(capsys, ws, "--host", "claude-code", "--out", str(out), "--json")
    doc = json.loads(stdout)
    assert rc == 0 and set(doc["counts"]) == {"unchanged"}
    assert len(events.read(ws, "package").rows) == 2


def test_outside_a_workspace_it_still_packages_and_says_no_event_was_recorded(tmp_path, fake_aegis, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    out = tmp_path / "plugin"
    rc, stdout, err = _run(capsys, plain, "--host", "claude-code", "--out", str(out), "--json")
    doc = json.loads(stdout)
    assert (rc, err) == (0, "") and doc["recorded"] is False
    assert not (plain / ".aegis").exists() and (out / ".mcp.json").is_file()


def test_an_event_that_cannot_be_recorded_is_a_warning(ws, fake_aegis, capsys, tmp_path, monkeypatch):
    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(events, "append", broken)
    rc, _o, err = _run(capsys, ws, "--host", "claude-code", "--out", str(tmp_path / "p"))
    assert rc == 0 and err == "Warning: the package event could not be recorded (OSError: disk full)\n"


def test_the_json_envelope(ws, fake_aegis, capsys, tmp_path):
    from aegis_core._version import __version__

    out = tmp_path / "plugin"
    rc, stdout, err = _run(capsys, ws, "--host", "claude-code", "--out", str(out), "--json")
    doc = json.loads(stdout)
    assert (rc, err) == (0, "")
    assert doc["source"] == "aegis package" and doc["aegis_version"] == __version__ and TS.match(doc["checked_at"])
    assert doc["scope"] == {"workspace": str(ws), "host": "claude-code", "out": str(out)}
    assert doc["status"] == "ok" and doc["experimental"] is True and doc["dry_run"] is False
    assert doc["notice"] == "experimental: nothing is published; the directory works only on this machine"
    assert {f["path"] for f in doc["files"]} >= {".claude-plugin/plugin.json", ".mcp.json", "hooks/hooks.json"}
    assert doc["recorded"] is True and doc["warnings"] == []


def test_the_json_of_a_refusal_is_an_enveloped_error(ws, fake_aegis, capsys, tmp_path):
    out = tmp_path / "plugin"
    out.mkdir()
    (out / "mine.txt").write_text("keep")
    rc, stdout, err = _run(capsys, ws, "--host", "claude-code", "--out", str(out), "--json")
    doc = json.loads(stdout)
    assert (rc, err) == (1, "")
    assert doc["status"] == "error" and doc["source"] == "aegis package" and "not an Aegis plugin" in doc["error"]


def test_the_real_home_is_untouched(ws, fake_aegis, capsys, tmp_path):
    home = Path(os.environ["HOME"])
    before = _tree(home)
    _run(capsys, ws, "--host", "claude-code", "--out", str(tmp_path / "plugin"))
    assert _tree(home) == before


def test_the_help_says_experimental_and_unpublished(capsys):
    with pytest.raises(SystemExit) as info:
        main(["package", "--help"])
    out = " ".join(capsys.readouterr().out.split()).lower()
    assert info.value.code == 0 and "experimental" in out and "claude-code" in out and "published" in out
