"""aegis_core.packaging: the Claude Code plugin directory `aegis package --host claude-code` writes (v4.2 #8).

Layout under test (Claude Code plugin docs, https://code.claude.com/docs/en/plugins and
https://code.claude.com/docs/en/plugins-reference): only ``plugin.json`` lives in
``.claude-plugin/``; ``skills/<id>/SKILL.md``, ``hooks/hooks.json`` ({"hooks": {Event: [groups]}})
and ``.mcp.json`` ({"mcpServers": {name: server}}) sit at the plugin root, where Claude Code
finds them without manifest keys.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from aegis_core import packaging

MCP = {"command": "/opt/aegis/bin/aegis-mcp", "args": [], "env": {"AEGIS_CLIENT": "claude-code"}}
GROUP = {"matcher": "Bash|Write", "hooks": [{"type": "command", "command": "/opt/aegis/bin/aegis",
                                              "args": ["hook", "run", "pre-tool", "--host", "claude-code"],
                                              "timeout": 10}]}
SKILLS = {"alpha-skill": b"---\nname: alpha-skill\ndescription: A\n---\nbody\n", "beta": b"---\nname: beta\n---\nB\n"}


def build(**over: Any) -> Dict[str, bytes]:
    args: Dict[str, Any] = {"version": "4.2.0", "mcp": MCP, "hook_group": GROUP, "skills": SKILLS}
    args.update(over)
    return packaging.build_plugin(**args)


def test_the_plugin_has_exactly_the_documented_files():
    assert sorted(build()) == [
        ".claude-plugin/plugin.json", ".mcp.json", "README.md", "hooks/hooks.json",
        "skills/alpha-skill/SKILL.md", "skills/beta/SKILL.md"]


def test_the_manifest_names_the_plugin_and_says_experimental():
    manifest = json.loads(build()[packaging.MANIFEST])
    assert manifest["name"] == "aegis-guardrails"
    assert manifest["version"] == "4.2.0"
    assert "experimental" in manifest["description"].lower()
    assert set(manifest) == {"name", "version", "description", "homepage"}


def test_mcp_json_wraps_the_server_entry_under_mcpServers():
    assert json.loads(build()[".mcp.json"]) == {"mcpServers": {"aegis": MCP}}


def test_hooks_json_carries_the_exec_form_pretooluse_group():
    doc = json.loads(build()["hooks/hooks.json"])
    assert doc == {"hooks": {"PreToolUse": [GROUP]}}
    handler = doc["hooks"]["PreToolUse"][0]["hooks"][0]
    assert handler["command"] == "/opt/aegis/bin/aegis" and handler["args"][:2] == ["hook", "run"]


def test_skills_are_copied_byte_for_byte():
    files = build()
    assert files["skills/alpha-skill/SKILL.md"] == SKILLS["alpha-skill"]


def test_output_is_deterministic():
    assert build() == build()


def test_the_readme_says_the_dir_is_machine_specific_and_unpublished():
    text = build()["README.md"].decode()
    assert "experimental" in text.lower() and "this machine" in text and "not published" in text


@pytest.mark.parametrize("command", ["aegis-mcp", "./aegis-mcp", "", None])
def test_a_relative_mcp_command_is_refused(command):
    with pytest.raises(packaging.PackagingError) as info:
        build(mcp={**MCP, "command": command})
    assert str(info.value) == f"the MCP server command {command!r} is not an absolute path"


def test_a_python_dash_m_mcp_entry_is_refused():
    with pytest.raises(packaging.PackagingError) as info:
        build(mcp={"command": "/usr/bin/python3", "args": ["-m", "aegis_mcp"], "env": {}})
    assert "-m" in str(info.value) and "imports from the directory the host starts it in" in str(info.value)


def test_the_isolated_runner_form_is_accepted():
    entry = {"command": "/usr/bin/python3", "args": ["-I", "-c", "import sys", "/site"], "env": {}}
    assert json.loads(build(mcp=entry)[".mcp.json"])["mcpServers"]["aegis"] == entry


def test_a_hook_without_an_absolute_command_is_refused():
    bad = {"matcher": "Bash", "hooks": [{"type": "command", "command": "aegis", "args": []}]}
    with pytest.raises(packaging.PackagingError) as info:
        build(hook_group=bad)
    assert str(info.value) == "the hook command 'aegis' is not an absolute path"


@pytest.mark.parametrize("skill_id", ["../evil", "Up", "a/b", "", "a b"])
def test_a_skill_id_outside_the_charset_is_refused(skill_id):
    with pytest.raises(packaging.PackagingError) as info:
        build(skills={skill_id: b"x"})
    assert str(info.value) == f"skill id {skill_id!r} is not [a-z0-9-]"


def test_no_skills_is_refused():
    with pytest.raises(packaging.PackagingError) as info:
        build(skills={})
    assert str(info.value) == "there are no skills to package"


# ── writing ──────────────────────────────────────────────────────────────────

def test_write_creates_every_file(tmp_path):
    out = tmp_path / "plugin"
    result = packaging.write_plugin(out, build())
    assert {path: state for path, state in result} == {p: "created" for p in build()}
    for rel, data in build().items():
        assert (out / rel).read_bytes() == data


def test_a_dry_run_writes_nothing(tmp_path):
    out = tmp_path / "plugin"
    result = packaging.write_plugin(out, build(), dry_run=True)
    assert all(state == "created" for _p, state in result)
    assert not out.exists()


def test_a_second_write_is_unchanged_and_a_changed_file_is_updated(tmp_path):
    out = tmp_path / "plugin"
    packaging.write_plugin(out, build())
    again = dict(packaging.write_plugin(out, build()))
    assert set(again.values()) == {"unchanged"}
    changed = dict(packaging.write_plugin(out, build(version="4.2.1")))
    assert changed[packaging.MANIFEST] == "updated" and changed[".mcp.json"] == "unchanged"


def test_an_empty_existing_directory_is_fine(tmp_path):
    (tmp_path / "plugin").mkdir()
    packaging.write_plugin(tmp_path / "plugin", build())
    assert (tmp_path / "plugin" / ".mcp.json").is_file()


def test_a_directory_that_is_not_an_aegis_plugin_is_refused_untouched(tmp_path):
    out = tmp_path / "plugin"
    out.mkdir()
    (out / "mine.txt").write_text("keep")
    with pytest.raises(packaging.PackagingError) as info:
        packaging.write_plugin(out, build())
    assert str(info.value) == f"{out} is not empty and is not an Aegis plugin directory; choose another --out"
    assert sorted(p.name for p in out.iterdir()) == ["mine.txt"]


def test_another_plugin_named_differently_is_not_overwritten(tmp_path):
    out = tmp_path / "plugin"
    (out / ".claude-plugin").mkdir(parents=True)
    (out / ".claude-plugin" / "plugin.json").write_text('{"name": "other"}')
    with pytest.raises(packaging.PackagingError):
        packaging.write_plugin(out, build())
    assert (out / ".claude-plugin" / "plugin.json").read_text() == '{"name": "other"}'


def test_an_unreadable_manifest_counts_as_not_ours(tmp_path):
    out = tmp_path / "plugin"
    (out / ".claude-plugin").mkdir(parents=True)
    (out / ".claude-plugin" / "plugin.json").write_text("{not json")
    with pytest.raises(packaging.PackagingError):
        packaging.write_plugin(out, build())


def test_out_that_is_a_file_is_refused(tmp_path):
    out = tmp_path / "plugin"
    out.write_text("x")
    with pytest.raises(packaging.PackagingError) as info:
        packaging.write_plugin(out, build())
    assert str(info.value) == f"{out} exists and is not a directory"


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_a_symlinked_out_is_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(packaging.PackagingError) as info:
        packaging.write_plugin(link, build())
    assert str(info.value) == f"{link} is a symbolic link; name the real directory"
    assert list(real.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_a_symlink_inside_our_plugin_is_never_written_through(tmp_path):
    out = tmp_path / "plugin"
    packaging.write_plugin(out, build())
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text("precious")
    (out / ".mcp.json").unlink()
    (out / ".mcp.json").symlink_to(elsewhere)
    with pytest.raises(packaging.PackagingError) as info:
        packaging.write_plugin(out, build())
    assert str(info.value) == f"{out / '.mcp.json'} is a symbolic link; Aegis does not write through links"
    assert elsewhere.read_text() == "precious"


def test_the_refusal_comes_before_any_file_is_written(tmp_path):
    out = tmp_path / "plugin"
    packaging.write_plugin(out, build())
    (out / "hooks" / "hooks.json").unlink()
    (out / "hooks").mkdir(exist_ok=True)
    (out / "hooks" / "hooks.json").mkdir()  # a directory where a file belongs
    before = (out / ".mcp.json").read_bytes()
    with pytest.raises(packaging.PackagingError):
        packaging.write_plugin(out, build(version="9.9.9"))
    assert (out / ".mcp.json").read_bytes() == before
    assert json.loads((out / packaging.MANIFEST).read_text())["version"] == "4.2.0"
