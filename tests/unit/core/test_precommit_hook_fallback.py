"""BUG-047: the `soma init` pre-commit hook must not abort with `soma: not found`.

The old block ran bare `soma checkpoint --pre-commit`. When `soma` is not on
the hook's PATH (zsh/non-login shells, GUI git clients, BUG-041 setups) git
aborted every commit with only `soma: not found`. The block now tries `soma`,
then the interpreter that ran `soma init`, and otherwise fails closed with a
message naming `soma doctor`. Re-running `soma init` replaces the block in place.
"""
import os
import subprocess

import pytest

from aegis_cli.init import (
    _AEGIS_HOOK_END,
    _AEGIS_HOOK_START,
    _SOMA_HOOK_END,
    _SOMA_HOOK_START,
    install_hook,
)

pytestmark = pytest.mark.skipif(os.name == "nt", reason="runs the hook with /bin/sh")

OLD_BLOCK = (f"{_SOMA_HOOK_START}\n"
             "# Installed by soma init — runs deterministic quality checks before commit.\n"
             "soma checkpoint --pre-commit\n"
             f"{_SOMA_HOOK_END}\n")


def repo(tmp_path):
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    return tmp_path


def stub(path, log):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\necho "$0 $*" >> "{log}"\nexit 0\n', encoding="utf-8")
    path.chmod(0o755)
    return path


def run_hook(project, path_dirs):
    hook = project / ".git" / "hooks" / "pre-commit"
    return subprocess.run(["/bin/sh", str(hook)], cwd=str(project),
                          env={"PATH": os.pathsep.join(str(d) for d in path_dirs)},
                          capture_output=True, text=True, timeout=30)


def test_falls_back_to_init_interpreter_when_soma_not_on_path(tmp_path):
    project = repo(tmp_path / "p")
    log = tmp_path / "log"
    # A space and a quote in the path prove the interpreter is shell-quoted.
    py = stub(tmp_path / "py dir'x" / "python", log)
    install_hook(project, python=str(py))
    empty = tmp_path / "empty"
    empty.mkdir()
    proc = run_hook(project, [empty])
    assert proc.returncode == 0, proc.stderr
    calls = log.read_text(encoding="utf-8")
    assert "check --hook" in calls


def test_prefers_soma_on_path(tmp_path):
    project = repo(tmp_path / "p")
    log = tmp_path / "log"
    py = stub(tmp_path / "py" / "python", log)
    bindir = tmp_path / "bin"
    stub(bindir / "soma", log)
    install_hook(project, python=str(py))
    proc = run_hook(project, [bindir])
    assert proc.returncode == 0, proc.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert calls == [f"{bindir / 'soma'} check --hook"]


def test_checkpoint_failure_propagates(tmp_path):
    project = repo(tmp_path / "p")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    soma = bindir / "soma"
    soma.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    soma.chmod(0o755)
    install_hook(project, python=str(tmp_path / "nope" / "python"))
    hook = project / ".git" / "hooks" / "pre-commit"
    hook.write_text(hook.read_text(encoding="utf-8") + "echo user-tail\n", encoding="utf-8")
    proc = run_hook(project, [bindir])
    assert proc.returncode == 3
    assert "user-tail" not in proc.stdout


def test_neither_available_fails_closed_with_message(tmp_path):
    project = repo(tmp_path / "p")
    install_hook(project, python=str(tmp_path / "gone" / "python3"))
    empty = tmp_path / "empty"
    empty.mkdir()
    proc = run_hook(project, [empty])
    assert proc.returncode == 1
    assert "doctor" in proc.stderr
    assert "PATH" in proc.stderr
    assert "soma: not found" not in proc.stderr, "must not be the bare shell error"


def test_hook_is_posix_sh(tmp_path):
    project = repo(tmp_path / "p")
    install_hook(project, python="/usr/bin/python3")
    text = (project / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    for bashism in ("[[", "function ", "$(<", "local "):
        assert bashism not in text


def test_reinit_replaces_old_block_in_place(tmp_path):
    project = repo(tmp_path / "p")
    hook = project / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho user-before\n\n" + OLD_BLOCK + "echo user-after\n",
                    encoding="utf-8")
    install_hook(project, python="/usr/bin/python3")
    text = hook.read_text(encoding="utf-8")
    assert (text.count(_AEGIS_HOOK_START) == 1 and text.count(_AEGIS_HOOK_END) == 1) or (text.count(_SOMA_HOOK_START) == 1 and text.count(_SOMA_HOOK_END) == 1)
    assert text.startswith("#!/bin/sh\necho user-before\n\n")
    assert text.endswith(_AEGIS_HOOK_END + "\necho user-after\n") or text.endswith(_SOMA_HOOK_END + "\necho user-after\n")
    assert "check --hook" in text
    # Idempotent: a second run is byte-identical.
    install_hook(project, python="/usr/bin/python3")
    assert hook.read_text(encoding="utf-8") == text


def test_unterminated_block_is_left_alone(tmp_path):
    project = repo(tmp_path / "p")
    hook = project / ".git" / "hooks" / "pre-commit"
    broken = "#!/bin/sh\n" + _SOMA_HOOK_START + "\nsoma checkpoint --pre-commit\necho mine\n"
    hook.write_text(broken, encoding="utf-8")
    install_hook(project, python="/usr/bin/python3")
    assert hook.read_text(encoding="utf-8") == broken


def test_default_interpreter_is_sys_executable(tmp_path):
    import shlex
    import sys
    project = repo(tmp_path / "p")
    install_hook(project)
    text = (project / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    assert shlex.quote(sys.executable) in text


def test_doctor_flags_old_format_hook(tmp_path, capsys):
    from aegis_cli.doctor import _check_precommit_hook
    project = repo(tmp_path / "p")
    (project / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\n" + OLD_BLOCK,
                                                          encoding="utf-8")
    assert _check_precommit_hook(project) is False
    out = capsys.readouterr().out
    assert "hook install" in out or "init" in out


def test_doctor_accepts_current_hook(tmp_path, capsys):
    from aegis_cli.doctor import _check_precommit_hook
    project = repo(tmp_path / "p")
    install_hook(project, python="/usr/bin/python3")
    assert _check_precommit_hook(project) is True


def test_doctor_silent_without_hook(tmp_path):
    from aegis_cli.doctor import _check_precommit_hook
    assert _check_precommit_hook(repo(tmp_path / "p")) is None
