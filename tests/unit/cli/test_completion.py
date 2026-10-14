"""Tests for `soma completion {bash,zsh,fish}`.

The scripts are generated from soma_cli.cli._build_parser() at runtime, so
these tests enumerate the parser independently and require every subcommand,
option, and choice value to appear in each shell's output.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from aegis_cli.cli import _build_parser, main

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
SHELLS = ("bash", "zsh", "fish")


def _subparsers(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


def _options(parser):
    return [s for a in parser._actions for s in a.option_strings]


def _choices(parser):
    return [str(c) for a in parser._actions
            if a.choices and not isinstance(a, argparse._SubParsersAction)
            for c in a.choices]


def _fish_flag(opt):
    if opt.startswith("--"):
        return f"-l {opt[2:]}"
    return f"-s {opt[1:]}"


def _script(shell):
    from soma_cli.completion import generate
    return generate(_build_parser(), shell)


def test_parser_exposes_completion_subcommand():
    subs = _subparsers(_build_parser())
    assert "completion" in subs
    assert set(SHELLS).issubset(set(_choices(subs["completion"])))
    # Verify global flags are inherited (C-04)
    opts = _options(subs["completion"])
    assert "--plumbing" in opts
    assert "--internal" in opts
    assert "-v" in opts or "--verbose" in opts
    assert "-q" in opts or "--quiet" in opts


@pytest.mark.parametrize("shell", SHELLS)
def test_every_subcommand_option_and_choice_appears(shell):
    parser = _build_parser()
    script = _script(shell)
    subs = _subparsers(parser)
    assert subs, "parser has no subcommands"
    missing = []
    for name, sp in subs.items():
        if name not in script:
            missing.append(name)
        for opt in _options(sp):
            needle = _fish_flag(opt) if shell == "fish" else opt
            if needle not in script:
                missing.append(f"{name} {opt}")
        for choice in _choices(sp):
            if choice not in script:
                missing.append(f"{name} choice {choice}")
    for opt in _options(parser):
        needle = _fish_flag(opt) if shell == "fish" else opt
        if needle not in script:
            missing.append(f"top-level {opt}")
    assert not missing, missing


@pytest.mark.parametrize("shell", SHELLS)
def test_init_platform_choices_and_completion_listed(shell):
    script = _script(shell)
    for platform in ("gemini", "claude", "cursor", "copilot"):
        assert platform in script
    assert "completion" in script


@pytest.mark.parametrize("shell", SHELLS)
def test_output_is_ascii(shell):
    _script(shell).encode("ascii")


def test_bash_uses_complete_F():
    assert "complete -F" in _script("bash")


def test_zsh_uses_compdef_and_arguments():
    script = _script("zsh")
    assert script.startswith("#compdef aegis") or script.startswith("#compdef soma")
    assert "_arguments" in script and "_describe" in script


def test_fish_uses_complete_c_soma():
    assert "complete -c aegis" in _script("fish") or "complete -c soma" in _script("fish")


def test_unknown_shell_rejected():
    from aegis_cli.completion import generate
    with pytest.raises(ValueError):
        generate(_build_parser(), "tcsh")


def test_bash_syntax_ok(tmp_path):
    from conftest import require_bash
    bash_bin = require_bash()
    f = tmp_path / "aegis.bash"
    f.write_text(_script("bash"), encoding="utf-8")
    proc = subprocess.run([bash_bin, "-n", str(f)], cwd=str(tmp_path), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")
def test_zsh_syntax_ok(tmp_path):
    f = tmp_path / "_aegis"
    f.write_text(_script("zsh"), encoding="utf-8")
    proc = subprocess.run(["zsh", "-n", str(f)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish not installed")
def test_fish_syntax_ok(tmp_path):
    f = tmp_path / "aegis.fish"
    f.write_text(_script("fish"), encoding="utf-8")
    proc = subprocess.run(["fish", "--no-execute", str(f)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def _bash_complete(tmp_path, words, cword):
    """Source the bash script and run _soma / _aegis for a simulated command line."""
    f = tmp_path / "aegis.bash"
    content = _script("bash")
    f.write_text(content, encoding="utf-8")
    fn = "_aegis" if "_aegis()" in content else "_soma"
    prog_name = "aegis" if "_aegis()" in content else "soma"
    if words and words[0] in ("soma", "aegis"):
        words = [prog_name] + list(words[1:])
    quoted = " ".join("'" + w + "'" for w in words)
    prog = (f"source '{f}'; COMP_WORDS=({quoted}); COMP_CWORD={cword}; "
            f"{fn}; printf '%s\\n' \"${{COMPREPLY[@]}}\"")
    proc = subprocess.run(["bash", "-c", prog], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.split()


@pytest.mark.skipif(os.name == "nt" or shutil.which("bash") is None,
                    reason="needs POSIX bash")
def test_bash_completes_subcommands_and_choices(tmp_path):
    assert "init" in _bash_complete(tmp_path, ["aegis", "in"], 1)
    assert set(_bash_complete(tmp_path, ["aegis", "init", "--platform", ""], 3)) == {
        "gemini", "claude", "cursor", "copilot", "kiro"}
    assert "--dry-run" in _bash_complete(tmp_path, ["aegis", "init", "--d"], 2)
    assert set(_bash_complete(tmp_path, ["aegis", "completion", ""], 2)) >= set(SHELLS)


def test_cli_prints_script(capsys):
    assert main(["completion", "fish"]) == 0
    out = capsys.readouterr().out
    assert "complete -c aegis" in out or "complete -c soma" in out


def test_cli_rejects_unknown_shell(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["completion", "tcsh"])
    assert exc.value.code == 2


@pytest.mark.parametrize("shell", SHELLS)
def test_cli_output_survives_cp1252_stdout(shell):
    proc = subprocess.run(
        [sys.executable, "-m", "aegis_cli", "completion", shell],
        cwd=str(REPO_ROOT), capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
    )
    assert proc.returncode == 0, proc.stderr
    assert b"aegis" in proc.stdout or b"soma" in proc.stdout


# ── Review hardening: shell words must be inert (eval'd by users) ────────────

def _hostile_parser(word):
    p = argparse.ArgumentParser(prog="soma")
    sub = p.add_subparsers(dest="command")
    x = sub.add_parser("x", help="x")
    x.add_argument("--o", choices=[word])
    return p


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("word", ["$(touch PWNED)", "`touch PWNED`", "a'b", "a b", 'a"b'])
def test_unsafe_completion_words_are_rejected(shell, word):
    from soma_cli.completion import generate
    with pytest.raises(ValueError):
        generate(_hostile_parser(word), shell)


def test_bash_word_lists_are_single_quoted():
    assert 'compgen -W "' not in _script("bash")


# ── zsh _arguments: ':' in a [description] ends it early ─────────────────────

def test_zsh_colons_in_descriptions_are_escaped():
    import re
    script = _script("zsh")
    assert r"(default\: standard)" in script
    descs = re.findall(r"\[([^\]]*)\]", script)
    assert descs
    bad = [d for d in descs if re.search(r"(?<!\\):", d)]
    assert not bad, bad


def test_completion_command_contract():
    import argparse
    from unittest.mock import patch
    from soma_cli.completion import CompletionCommand
    cmd = CompletionCommand()
    parser = argparse.ArgumentParser()
    cmd.configure_parser(parser)
    parsed = parser.parse_args(["bash"])
    assert parsed.shell == "bash"

    with patch("soma_cli.completion.run_completion", return_value=0) as mock_run:
        assert cmd.execute(parsed) == 0
        mock_run.assert_called_once_with(parsed)
