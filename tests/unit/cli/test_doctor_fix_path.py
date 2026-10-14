"""`soma doctor --fix-path` and its uninstall round trip (C1).

`soma doctor --fix-path` is the opt-in alternative to copying the BUG-041
PATH line by hand. Contract:
- dry run by default; applies only with --yes or an interactive "y";
- appends exactly the pathcheck line plus a marker, once (idempotent);
- refuses rc files that resolve outside HOME; never edits a PowerShell $PROFILE;
- records the file and line in ~/.aegis/manifest.json (keys preserved), so
  install/uninstall.sh can remove exactly that line again.

Every test uses an isolated HOME under tmp_path; env is passed explicitly, so
the real user's dotfiles are never read or written.
"""
import io
import json
import os
import stat
import sys

import pytest

from conftest import REPO_ROOT, require_bash, run, symlink_or_skip

from aegis_cli.doctor import FIX_PATH_MARKER, fix_path


posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX rc files and modes")


class FakeStdin(io.StringIO):
    def __init__(self, text="", tty=False):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


@pytest.fixture
def env_layout(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    scripts = home / ".local" / "bin"
    scripts.mkdir(parents=True)
    soma = scripts / "soma"
    soma.write_text("#!/bin/sh\n", encoding="utf-8")
    soma.chmod(0o755)
    return {"home": home, "project": project, "scripts": scripts, "tmp": tmp_path}


def do_fix(lay, shell="zsh", yes=True, extra_env=None, stdin=None, platform="linux"):
    nobin = lay["tmp"] / "nobin"
    nobin.mkdir(exist_ok=True)
    env = {"SHELL": f"/bin/{shell}", "PATH": str(nobin)}
    env.update(extra_env or {})
    return fix_path(
        yes=yes, env=env, home=str(lay["home"]), candidates=[str(lay["scripts"])],
        platform=platform, os_name="posix",
        stdin=stdin if stdin is not None else FakeStdin(),
    )


def manifest_of(lay):
    p = lay["home"] / ".aegis" / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


EXPECTED_ZSH = 'export PATH="$HOME/.local/bin:$PATH"  ' + FIX_PATH_MARKER




# ── doctor --fix-path ────────────────────────────────────────────────────

def test_marker_text():
    assert FIX_PATH_MARKER == "# added by soma doctor --fix-path"


def test_default_is_dry_run_and_changes_nothing(env_layout, capsys):
    rc = do_fix(env_layout, yes=False)
    out = capsys.readouterr().out
    assert rc == 0
    zshrc = env_layout["home"] / ".zshrc"
    assert not zshrc.exists(), "dry run must not create the rc file"
    assert manifest_of(env_layout) is None, "dry run must not write the manifest"
    assert str(zshrc) in out and EXPECTED_ZSH in out, out


@posix_only
def test_yes_appends_marked_line_and_records_it(env_layout, capsys):
    zshrc = env_layout["home"] / ".zshrc"
    zshrc.write_bytes(b"alias ll='ls -l'\n")
    zshrc.chmod(0o600)
    assert do_fix(env_layout) == 0
    assert zshrc.read_bytes() == b"alias ll='ls -l'\n" + EXPECTED_ZSH.encode() + b"\n"
    assert stat.S_IMODE(zshrc.stat().st_mode) == 0o600, "mode must be preserved"
    entry = manifest_of(env_layout)["path_lines"]
    assert entry == [{"file": str(zshrc), "line": EXPECTED_ZSH,
                      "created": False, "prefix_newline": False}]
    # No temp files left behind.
    assert sorted(p.name for p in env_layout["home"].iterdir()) == [".aegis", ".local", ".zshrc"]


def test_missing_trailing_newline_is_handled(env_layout):
    zshrc = env_layout["home"] / ".zshrc"
    zshrc.write_bytes(b"export A=1")
    assert do_fix(env_layout) == 0
    assert zshrc.read_bytes() == b"export A=1\n" + EXPECTED_ZSH.encode() + b"\n"
    assert manifest_of(env_layout)["path_lines"][0]["prefix_newline"] is True


def test_crlf_file_keeps_crlf(env_layout):
    zshrc = env_layout["home"] / ".zshrc"
    zshrc.write_bytes(b"export A=1\r\n")
    assert do_fix(env_layout) == 0
    assert zshrc.read_bytes() == b"export A=1\r\n" + EXPECTED_ZSH.encode() + b"\r\n"


def test_idempotent(env_layout, capsys):
    assert do_fix(env_layout) == 0
    first = (env_layout["home"] / ".zshrc").read_bytes()
    assert do_fix(env_layout) == 0
    assert (env_layout["home"] / ".zshrc").read_bytes() == first
    assert len(manifest_of(env_layout)["path_lines"]) == 1
    assert "already" in capsys.readouterr().out.lower()


@posix_only
def test_creates_missing_file_with_umask_mode(env_layout):
    old = os.umask(0o022)
    try:
        assert do_fix(env_layout) == 0
    finally:
        os.umask(old)
    zshrc = env_layout["home"] / ".zshrc"
    assert zshrc.read_bytes() == EXPECTED_ZSH.encode() + b"\n"
    assert stat.S_IMODE(zshrc.stat().st_mode) == 0o644
    assert manifest_of(env_layout)["path_lines"][0]["created"] is True


def test_zdotdir_is_honoured(env_layout):
    zdot = env_layout["home"] / "zdot"
    zdot.mkdir()
    assert do_fix(env_layout, extra_env={"ZDOTDIR": str(zdot)}) == 0
    assert (zdot / ".zshrc").read_text(encoding="utf-8") == EXPECTED_ZSH + "\n"
    assert not (env_layout["home"] / ".zshrc").exists()


def test_zdotdir_outside_home_is_refused(env_layout, capsys):
    outside = env_layout["tmp"] / "outside"
    outside.mkdir()
    rc = do_fix(env_layout, extra_env={"ZDOTDIR": str(outside)})
    assert rc != 0
    assert not (outside / ".zshrc").exists()
    assert manifest_of(env_layout) is None
    assert "outside" in capsys.readouterr().out.lower()


def test_bash_uses_bashrc_on_linux(env_layout):
    assert do_fix(env_layout, shell="bash") == 0
    assert (env_layout["home"] / ".bashrc").read_text(encoding="utf-8") == EXPECTED_ZSH + "\n"


def test_bash_on_macos_follows_pathcheck_choice(env_layout):
    assert do_fix(env_layout, shell="bash", platform="darwin") == 0
    assert (env_layout["home"] / ".bash_profile").exists()
    assert not (env_layout["home"] / ".bashrc").exists()


def test_fish_honours_xdg_and_creates_parent(env_layout):
    xdg = env_layout["home"] / "xdg"
    assert do_fix(env_layout, shell="fish", extra_env={"XDG_CONFIG_HOME": str(xdg)}) == 0
    cfg = xdg / "fish" / "config.fish"
    assert cfg.read_text(encoding="utf-8") == (
        'fish_add_path "$HOME/.local/bin"  ' + FIX_PATH_MARKER + "\n")


def test_fish_default_location(env_layout):
    assert do_fix(env_layout, shell="fish") == 0
    assert (env_layout["home"] / ".config" / "fish" / "config.fish").exists()


@pytest.mark.parametrize("shell", ["pwsh", "unknown-shell"])
def test_pwsh_and_unknown_get_guidance_only(env_layout, capsys, shell):
    rc = do_fix(env_layout, shell=shell)
    out = capsys.readouterr().out
    assert rc == 0
    assert manifest_of(env_layout) is None
    assert sorted(p.name for p in env_layout["home"].iterdir()) == [".local"]
    if shell == "pwsh":
        assert "$PROFILE" in out


def test_already_on_path_changes_nothing(env_layout, capsys):
    rc = do_fix(env_layout, extra_env={"PATH": f"{env_layout['scripts']}{os.pathsep}/usr/bin"})
    assert rc == 0
    assert "already on PATH" in capsys.readouterr().out
    assert not (env_layout["home"] / ".zshrc").exists()
    assert manifest_of(env_layout) is None


def test_interactive_yes_applies(env_layout):
    assert do_fix(env_layout, yes=False, stdin=FakeStdin("y\n", tty=True)) == 0
    assert (env_layout["home"] / ".zshrc").exists()


def test_interactive_no_declines(env_layout):
    assert do_fix(env_layout, yes=False, stdin=FakeStdin("\n", tty=True)) == 0
    assert not (env_layout["home"] / ".zshrc").exists()
    assert manifest_of(env_layout) is None


def test_symlinked_rc_outside_home_is_refused(env_layout, capsys):
    outside = env_layout["tmp"] / "outside"
    outside.mkdir()
    target = outside / "zshrc"
    target.write_bytes(b"outside\n")
    symlink_or_skip(target, env_layout["home"] / ".zshrc")
    rc = do_fix(env_layout)
    assert rc != 0
    assert target.read_bytes() == b"outside\n"
    assert manifest_of(env_layout) is None


def test_symlinked_rc_inside_home_is_written_through(env_layout):
    dot = env_layout["home"] / "dotfiles"
    dot.mkdir()
    target = dot / "zshrc"
    target.write_bytes(b"x\n")
    link = env_layout["home"] / ".zshrc"
    symlink_or_skip(target, link)
    assert do_fix(env_layout) == 0
    assert link.is_symlink(), "the symlink must be kept"
    assert target.read_bytes() == b"x\n" + EXPECTED_ZSH.encode() + b"\n"


def test_existing_manifest_keys_are_preserved(env_layout):
    mpath = env_layout["home"] / ".aegis" / "manifest.json"
    mpath.parent.mkdir()
    original = {"version": "0.89.0", "platform": "kiro", "files": ["/x"], "hooks": []}
    mpath.write_text(json.dumps(original, indent=2), encoding="utf-8")
    assert do_fix(env_layout) == 0
    data = manifest_of(env_layout)
    for k, v in original.items():
        assert data[k] == v
    assert list(data)[:4] == list(original), "key order preserved"
    assert len(data["path_lines"]) == 1


def test_corrupt_manifest_aborts_before_editing_rc(env_layout):
    mpath = env_layout["home"] / ".aegis" / "manifest.json"
    mpath.parent.mkdir()
    mpath.write_text("{not json", encoding="utf-8")
    assert do_fix(env_layout) != 0
    assert mpath.read_text(encoding="utf-8") == "{not json"
    assert not (env_layout["home"] / ".zshrc").exists()


def test_cli_parser_accepts_fix_path_and_yes():
    from aegis_cli.cli import _build_parser
    args = _build_parser().parse_args(["system", "doctor", "--fix-path", "--yes"])
    assert args.fix_path is True and args.yes is True
    args = _build_parser().parse_args(["system", "doctor"])
    assert args.fix_path is False



