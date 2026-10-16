"""The AD-4 workspace binding resolver (host-matrix §3.6): pin, host-attested roots,
the registry, a bounded walk-up; never $HOME, never the filesystem root, never above
the git toplevel, and a HOLD with a machine-readable reason when sources disagree.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from aegis_core.errors import WorkspaceNotFoundError
from aegis_core.workspace.binding import (
    Attested,
    WorkspaceHold,
    bounded_walk_up,
    read_registry,
    resolve_binding,
    resolve_cli_root,
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    (home / ".aegis" / "rules").mkdir(parents=True)  # what v3.3 auto-created
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home.resolve()


def _governed(path: Path) -> Path:
    (path / ".aegis" / "rules").mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _git_marker(path: Path) -> Path:
    (path / ".git").mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _registry(home: Path, roots, v=1) -> Path:
    path = home / ".aegis" / "workspaces.json"
    entries = [{"root": str(r), "added_at": "2026-10-15T00:00:00Z", "added_by": "aegis init", "hosts": []}
               for r in roots]
    path.write_text(json.dumps({"v": v, "workspaces": entries}), encoding="utf-8")
    return path


# ── bounded walk-up ──────────────────────────────────────────────────────────

def test_walk_up_finds_the_workspace_from_a_subdirectory(home, tmp_path):
    root = _governed(tmp_path / "repo")
    (root / "src" / "pkg").mkdir(parents=True)
    assert bounded_walk_up(root / "src" / "pkg") == root


def test_walk_up_never_crosses_the_git_marker(home, tmp_path):
    _governed(tmp_path / "outer")
    inner = _git_marker(tmp_path / "outer" / "inner")
    (inner / "src").mkdir()
    assert bounded_walk_up(inner / "src") is None


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_walk_up_never_crosses_a_real_git_toplevel(home, tmp_path):
    _governed(tmp_path / "outer")
    inner = tmp_path / "outer" / "inner"
    inner.mkdir()
    subprocess.run(["git", "init", "-q", str(inner)], check=True, capture_output=True)
    (inner / "src").mkdir()
    assert bounded_walk_up(inner / "src") is None


def test_walk_up_never_selects_home_even_with_v33_user_rules(home):
    project = home / "code" / "project"
    project.mkdir(parents=True)
    assert bounded_walk_up(project) is None
    assert bounded_walk_up(home) is None


def test_walk_up_never_goes_above_home(home, tmp_path):
    _governed(tmp_path)  # tmp_path contains home: a workspace above $HOME is never chosen
    project = home / "project"
    project.mkdir()
    assert bounded_walk_up(project) is None


# ── 1. operator pin ──────────────────────────────────────────────────────────

def test_a_valid_pin_binds_with_operator_confidence(home, tmp_path):
    root = _governed(tmp_path / "repo")
    binding = resolve_binding(pin=str(root))
    assert (binding.status, binding.root, binding.source, binding.confidence) == ("bound", root, "pin", "operator")


@pytest.mark.parametrize("case,reason", [
    ("missing", "pin_missing"),
    ("plain", "pin_not_a_workspace"),
    ("home", "pin_denied"),
])
def test_an_invalid_pin_is_an_error_never_a_fallback(home, tmp_path, case, reason):
    plain = tmp_path / "plain"
    plain.mkdir()
    _governed(tmp_path / "cwd")
    pin = {"missing": tmp_path / "nope", "plain": plain, "home": home}[case]
    binding = resolve_binding(pin=str(pin), cwd=tmp_path / "cwd")
    assert (binding.status, binding.reason, binding.root) == ("error", reason, None)
    assert str(pin) in binding.message


def test_pin_and_a_disagreeing_host_root_hold(home, tmp_path):
    pin = _governed(tmp_path / "a")
    other = _governed(tmp_path / "b")
    binding = resolve_binding(pin=str(pin), attested=[Attested("claude_project_dir", str(other))])
    assert (binding.status, binding.reason) == ("hold", "pin_conflicts_with_host_root")
    assert binding.as_dict()["details"] == {"pin": str(pin), "host_roots": [str(other)]}


def test_pin_agrees_with_a_host_root_inside_it(home, tmp_path):
    pin = _governed(tmp_path / "repo")
    (pin / "pkg").mkdir()
    binding = resolve_binding(pin=str(pin), attested=[Attested("claude_project_dir", str(pin / "pkg"))])
    assert (binding.status, binding.root, binding.source) == ("bound", pin, "pin")


def test_pin_holds_when_the_files_belong_to_another_registered_workspace(home, tmp_path):
    pin = _governed(tmp_path / "a")
    other = _governed(tmp_path / "b")
    binding = resolve_binding(pin=str(pin), files=[str(other / "x.py")], registry=read_registry(_registry(home, [pin, other])))
    assert (binding.status, binding.reason) == ("hold", "pin_conflicts_with_registry")
    assert binding.as_dict()["details"]["registered_root"] == str(other)


# ── 2. host-attested roots ───────────────────────────────────────────────────

def test_a_codex_workspace_binds_as_host_attested(home, tmp_path):
    root = _governed(tmp_path / "repo")
    binding = resolve_binding(attested=[Attested("codex_meta", str(root))], cwd=tmp_path)
    assert (binding.status, binding.root, binding.source, binding.confidence) == (
        "bound", root, "codex_meta", "host_attested")


def test_a_host_root_in_a_monorepo_subdirectory_binds_to_the_governed_toplevel(home, tmp_path):
    root = _governed(_git_marker(tmp_path / "mono"))
    (root / "services" / "api").mkdir(parents=True)
    binding = resolve_binding(attested=[Attested("mcp_roots", str(root / "services" / "api"))])
    assert (binding.status, binding.root) == ("bound", root)


def test_several_host_roots_are_chosen_by_the_calls_files(home, tmp_path):
    a = _governed(tmp_path / "a")
    b = _governed(tmp_path / "b")
    (b / "src").mkdir()
    (b / "src" / "x.py").write_text("x\n", encoding="utf-8")
    roots = [Attested("mcp_roots", str(a)), Attested("mcp_roots", str(b))]
    assert resolve_binding(attested=roots, files=[str(b / "src" / "y.py")]).root == b
    assert resolve_binding(attested=roots, files=["src/x.py"]).root == b


@pytest.mark.parametrize("files", [None, [], ["nowhere.py"]])
def test_several_host_roots_without_deciding_files_hold(home, tmp_path, files):
    a = _governed(tmp_path / "a")
    b = _governed(tmp_path / "b")
    binding = resolve_binding(attested=[Attested("mcp_roots", str(a)), Attested("mcp_roots", str(b))], files=files)
    assert (binding.status, binding.reason) == ("hold", "ambiguous_host_roots")
    assert binding.as_dict()["details"]["candidates"] == [str(a), str(b)]


def test_ungoverned_host_roots_are_not_governed_and_skip_the_cwd(home, tmp_path):
    plain = _git_marker(tmp_path / "plain")
    cwd = _governed(tmp_path / "elsewhere")
    binding = resolve_binding(attested=[Attested("codex_meta", str(plain))], cwd=cwd)
    assert (binding.status, binding.reason, binding.root) == ("unbound", "host_roots_not_governed", None)


def test_ungoverned_host_root_and_files_in_a_registered_workspace_hold(home, tmp_path):
    plain = _git_marker(tmp_path / "plain")
    other = _governed(tmp_path / "b")
    binding = resolve_binding(
        attested=[Attested("codex_meta", str(plain))], files=[str(other / "x.py")],
        registry=read_registry(_registry(home, [other])),
    )
    assert (binding.status, binding.reason) == ("hold", "host_root_conflicts_with_registry")


def test_a_host_root_at_home_is_never_a_candidate(home):
    binding = resolve_binding(attested=[Attested("mcp_roots", str(home))])
    assert (binding.status, binding.reason) == ("unbound", "host_roots_not_governed")


# ── 3. registry ──────────────────────────────────────────────────────────────

def test_absolute_files_select_a_registered_workspace(home, tmp_path):
    a = _governed(tmp_path / "a")
    b = _governed(tmp_path / "b")
    binding = resolve_binding(files=[str(b / "new.py")], registry=read_registry(_registry(home, [a, b])), cwd=home)
    assert (binding.status, binding.root, binding.source, binding.confidence) == ("bound", b, "registry", "registered")


def test_relative_files_select_the_one_registered_workspace_holding_them(home, tmp_path):
    a = _governed(tmp_path / "a")
    b = _governed(tmp_path / "b")
    (b / "only_in_b.py").write_text("x\n", encoding="utf-8")
    binding = resolve_binding(files=["only_in_b.py"], registry=read_registry(_registry(home, [a, b])), cwd=home)
    assert (binding.status, binding.root) == ("bound", b)


def test_files_cannot_introduce_an_unregistered_workspace(home, tmp_path):
    a = _governed(tmp_path / "a")
    stray = _governed(tmp_path / "stray")
    binding = resolve_binding(files=[str(stray / "x.py")], registry=read_registry(_registry(home, [a])), cwd=home)
    assert (binding.status, binding.root) == ("unbound", None)


def test_no_files_never_pick_a_registered_workspace(home, tmp_path):
    a = _governed(tmp_path / "a")
    binding = resolve_binding(files=None, registry=read_registry(_registry(home, [a])), cwd=home)
    assert (binding.status, binding.reason) == ("unbound", "no_workspace")


def test_files_in_two_registered_workspaces_hold(home, tmp_path):
    a = _governed(tmp_path / "a")
    b = _governed(tmp_path / "b")
    for root in (a, b):
        (root / "same.py").write_text("x\n", encoding="utf-8")
    binding = resolve_binding(files=["same.py"], registry=read_registry(_registry(home, [a, b])), cwd=home)
    assert (binding.status, binding.reason) == ("hold", "ambiguous_registry_selection")


def test_a_registered_root_without_aegis_or_at_home_is_ignored(home, tmp_path):
    gone = tmp_path / "gone"
    gone.mkdir()
    registry = read_registry(_registry(home, [gone, home]))
    binding = resolve_binding(files=[str(gone / "x.py"), str(home / "y.py")], registry=registry, cwd=home)
    assert binding.status == "unbound"


def test_relative_files_held_by_the_cwd_workspace_bind_it_over_another_registered_one(home, tmp_path):
    """A clone with a committed .aegis/ that was never registered: README.md in it is its own, not B's."""
    cwd_ws = _governed(tmp_path / "clone")
    b = _governed(tmp_path / "b")
    for root in (cwd_ws, b):
        (root / "README.md").write_text("x\n", encoding="utf-8")
    binding = resolve_binding(files=["README.md"], registry=read_registry(_registry(home, [b])), cwd=cwd_ws)
    assert (binding.status, binding.root, binding.source) == ("bound", cwd_ws, "walk_up")


def test_relative_files_in_two_registered_workspaces_follow_the_cwd(home, tmp_path):
    a = _governed(tmp_path / "a")
    b = _governed(tmp_path / "b")
    for root in (a, b):
        (root / "src").mkdir()
        (root / "src" / "x.py").write_text("x\n", encoding="utf-8")
    binding = resolve_binding(files=["src/x.py"], registry=read_registry(_registry(home, [a, b])), cwd=a / "src")
    assert (binding.status, binding.root, binding.source) == ("bound", a, "registry")


def test_relative_files_only_in_another_registered_workspace_hold_against_the_cwd(home, tmp_path):
    cwd_ws = _governed(tmp_path / "a")
    b = _governed(tmp_path / "b")
    (b / "only_in_b.py").write_text("x\n", encoding="utf-8")
    binding = resolve_binding(files=["only_in_b.py"], registry=read_registry(_registry(home, [cwd_ws, b])), cwd=cwd_ws)
    assert (binding.status, binding.root, binding.reason) == ("hold", None, "cwd_conflicts_with_registry")
    assert binding.as_dict()["details"] == {"cwd_root": str(cwd_ws), "candidates": [str(b)]}


def test_absolute_files_still_select_a_registered_workspace_from_a_governed_cwd(home, tmp_path):
    cwd_ws = _governed(tmp_path / "a")
    b = _governed(tmp_path / "b")
    binding = resolve_binding(files=[str(b / "new.py")], registry=read_registry(_registry(home, [b])), cwd=cwd_ws)
    assert (binding.status, binding.root, binding.source) == ("bound", b, "registry")


@pytest.mark.parametrize("files", [["proj/app.py"], ["{home}/proj/app.py"]], ids=["relative", "absolute"])
def test_a_registry_listing_home_and_the_filesystem_root_never_binds_them(home, files):
    """$HOME holds .aegis/ (the user layer) and every file under it; the denylist alone keeps it out."""
    (home / "proj").mkdir()
    (home / "proj" / "app.py").write_text("x\n", encoding="utf-8")
    registry = read_registry(_registry(home, [home, Path(home.anchor)]))
    assert registry.roots == (home, Path(home.anchor))

    binding = resolve_binding(files=[f.format(home=home) for f in files], registry=registry)

    assert (binding.status, binding.root, binding.reason) == ("unbound", None, "no_workspace")


@pytest.mark.parametrize("content,problem", [
    ("{not json", "not valid JSON"),
    ('{"v": 2, "workspaces": []}', "unsupported registry version 2"),
    ('{"v": 1, "workspaces": {}}', "'workspaces' must be a list"),
    ("[1, 2]", "must be a JSON object"),
])
def test_a_malformed_registry_reads_as_empty_with_a_problem(home, content, problem):
    path = home / ".aegis" / "workspaces.json"
    path.write_text(content, encoding="utf-8")
    registry = read_registry(path)
    assert registry.roots == ()
    assert any(problem in p for p in registry.problems), registry.problems


def test_registry_entries_must_be_absolute_roots(home, tmp_path):
    a = _governed(tmp_path / "a")
    path = home / ".aegis" / "workspaces.json"
    path.write_text(json.dumps({"v": 1, "workspaces": [{"root": "relative/dir"}, {"nope": 1}, {"root": str(a)}]}),
                    encoding="utf-8")
    registry = read_registry(path)
    assert registry.roots == (a,)
    assert len(registry.problems) == 2


def test_a_missing_registry_is_empty_and_nothing_is_created(home):
    before = sorted(p.name for p in (home / ".aegis").iterdir())
    registry = read_registry()
    assert (registry.roots, registry.problems) == ((), ())
    assert sorted(p.name for p in (home / ".aegis").iterdir()) == before


# ── 4. walk-up from the server cwd, 5. nothing ───────────────────────────────

def test_the_cwd_walk_up_binds_as_inferred(home, tmp_path):
    root = _governed(tmp_path / "repo")
    (root / "src").mkdir()
    binding = resolve_binding(cwd=root / "src")
    assert (binding.status, binding.root, binding.source, binding.confidence) == ("bound", root, "walk_up", "inferred")


@pytest.mark.parametrize("cwd", ["home", "root", None])
def test_nothing_resolves_to_unbound(home, cwd):
    where = {"home": home, "root": Path(home.anchor), None: None}[cwd]
    binding = resolve_binding(cwd=where)
    assert (binding.status, binding.root, binding.reason) == ("unbound", None, "no_workspace")


def test_binding_as_dict_is_json_ready(home, tmp_path):
    root = _governed(tmp_path / "repo")
    data = resolve_binding(pin=str(root)).as_dict()
    assert json.loads(json.dumps(data)) == {
        "status": "bound", "root": str(root), "source": "pin", "confidence": "operator",
        "reason": None, "message": "", "details": {},
    }


# ── the CLI's global --workspace (wave A deferral) ───────────────────────────

def test_cli_explicit_target_walks_up_within_its_git_toplevel(home, tmp_path):
    root = _governed(_git_marker(tmp_path / "repo"))
    (root / "src").mkdir()
    assert resolve_cli_root(explicit=str(root / "src"), cwd=tmp_path) == root


def test_cli_explicit_target_never_resolves_above_its_git_toplevel(home, tmp_path):
    _governed(tmp_path / "outer")
    inner = _git_marker(tmp_path / "outer" / "inner")
    assert resolve_cli_root(explicit=str(inner), cwd=tmp_path) == inner


def test_cli_relative_explicit_target_is_relative_to_the_cwd(home, tmp_path):
    root = _governed(tmp_path / "repo")
    assert resolve_cli_root(explicit="repo", cwd=tmp_path) == root


@pytest.mark.parametrize("explicit", [True, False])
def test_cli_home_is_never_a_workspace(home, explicit):
    with pytest.raises(WorkspaceNotFoundError) as exc:
        resolve_cli_root(explicit=str(home) if explicit else None, cwd=home)
    assert str(exc.value) == (
        f"not an Aegis workspace ({home} is the home directory; ~/.aegis is the user rule layer); "
        "run aegis init in a project"
    )


def test_cli_pin_wins_over_the_cwd(home, tmp_path):
    pin = _governed(tmp_path / "pinned")
    cwd = _governed(tmp_path / "cwd")
    assert resolve_cli_root(cwd=cwd, pin=str(pin)) == pin


def test_cli_pin_and_explicit_target_that_agree_bind(home, tmp_path):
    pin = _governed(tmp_path / "pinned")
    (pin / "src").mkdir()
    assert resolve_cli_root(explicit=str(pin / "src"), cwd=tmp_path, pin=str(pin)) == pin


def test_cli_pin_and_a_different_explicit_target_hold(home, tmp_path):
    pin = _governed(tmp_path / "pinned")
    target = _governed(tmp_path / "target")
    with pytest.raises(WorkspaceHold) as exc:
        resolve_cli_root(explicit=str(target), cwd=tmp_path, pin=str(pin))
    assert exc.value.binding.as_dict()["status"] == "hold"
    assert exc.value.binding.reason == "pin_conflicts_with_target"
    assert exc.value.binding.as_dict()["details"] == {"pin": str(pin), "target": str(target)}


@pytest.mark.parametrize("case", ["missing", "home"])
def test_cli_an_unusable_pin_is_an_error(home, tmp_path, case):
    pin = {"missing": tmp_path / "nope", "home": home}[case]
    with pytest.raises(WorkspaceNotFoundError) as exc:
        resolve_cli_root(cwd=tmp_path, pin=str(pin))
    assert f"AEGIS_WORKSPACE is set to {pin}" in str(exc.value)


def test_cli_uninitialized_directory_resolves_to_itself(home, tmp_path):
    plain = _git_marker(tmp_path / "plain")
    assert resolve_cli_root(cwd=plain) == plain


@pytest.mark.skipif(os.name == "nt", reason="POSIX filesystem root")
def test_cli_filesystem_root_is_never_a_workspace(home):
    with pytest.raises(WorkspaceNotFoundError):
        resolve_cli_root(explicit="/", cwd=home)


def test_a_host_root_enclosing_the_pin_agrees(home, tmp_path):
    pin = _governed(tmp_path / "code" / "repo")
    binding = resolve_binding(pin=str(pin), attested=[Attested("mcp_roots", str(tmp_path / "code"))])
    assert (binding.status, binding.root) == ("bound", pin)


# ── Workspace.resolve (every CLI command's own re-resolution) uses the same walk ──

def test_workspace_resolve_never_walks_out_of_a_nested_repository(home, tmp_path, monkeypatch):
    from aegis_core.workspace.base import Workspace

    _governed(tmp_path / "outer")
    inner = _git_marker(tmp_path / "outer" / "inner")
    (inner / "src").mkdir()
    assert Workspace.resolve(inner).root == inner
    assert Workspace.resolve(inner / "src").root == inner / "src"
    monkeypatch.chdir(inner / "src")
    assert Workspace.resolve().root == inner / "src"


def test_workspace_resolve_never_selects_home(home, monkeypatch):
    from aegis_core.workspace.base import Workspace

    project = home / "code" / "project"
    project.mkdir(parents=True)
    assert Workspace.resolve(project).root == project
    monkeypatch.chdir(project)
    assert Workspace.resolve().root == project


def test_workspace_resolve_still_walks_up_inside_one_repository(home, tmp_path, monkeypatch):
    from aegis_core.workspace.base import Workspace

    root = _governed(_git_marker(tmp_path / "repo"))
    (root / "a" / "b").mkdir(parents=True)
    assert Workspace.resolve(root / "a" / "b").root == root
    monkeypatch.chdir(root / "a")
    assert Workspace.resolve().root == root


def test_without_deciding_files_the_highest_precedence_host_source_wins(home, tmp_path):
    project = _governed(tmp_path / "project")
    added = _governed(tmp_path / "added")
    attested = [Attested("claude_project_dir", str(project)), Attested("mcp_roots", str(project)),
                Attested("mcp_roots", str(added))]
    assert resolve_binding(attested=attested).root == project
    assert resolve_binding(attested=attested, files=[str(added / "x.py")]).root == added


def test_a_chosen_host_root_holds_when_the_files_belong_to_another_registered_workspace(home, tmp_path):
    host = _governed(tmp_path / "a")
    other = _governed(tmp_path / "b")
    binding = resolve_binding(
        attested=[Attested("codex_meta", str(host))], files=[str(other / "x.py")],
        registry=read_registry(_registry(home, [host, other])),
    )
    assert (binding.status, binding.reason) == ("hold", "host_root_conflicts_with_registry")
    assert binding.as_dict()["details"] == {"host_root": str(host), "registered_root": str(other)}


# ── unresolvable paths: a symlink loop (RuntimeError before Python 3.13) or a NUL
#    byte (ValueError) is "cannot be resolved", never an exception ─────────────────

def _loop(where: Path) -> Path:
    """``where/l1 -> where/l2 -> where/l1``; skipped where symlinks cannot be made."""
    where.mkdir(parents=True, exist_ok=True)
    first, second = where / "l1", where / "l2"
    try:
        os.symlink(second, first)
        os.symlink(first, second)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    return first


def _unresolvable(tmp_path: Path, kind: str) -> str:
    return str(_loop(tmp_path / "links")) if kind == "loop" else str(tmp_path / "nul\0byte")


@pytest.mark.parametrize("kind", ["loop", "nul"])
def test_an_unresolvable_pin_is_the_pin_missing_error(home, tmp_path, kind):
    _governed(tmp_path / "cwd")
    binding = resolve_binding(pin=_unresolvable(tmp_path, kind), cwd=tmp_path / "cwd")
    assert (binding.status, binding.reason, binding.source, binding.root) == ("error", "pin_missing", "pin", None)


@pytest.mark.parametrize("kind", ["loop", "nul"])
def test_an_unresolvable_cwd_is_unbound(home, tmp_path, kind):
    binding = resolve_binding(cwd=_unresolvable(tmp_path, kind))
    assert (binding.status, binding.reason) == ("unbound", "no_workspace")


@pytest.mark.parametrize("kind", ["loop", "nul"])
def test_an_unresolvable_host_root_is_not_governed(home, tmp_path, kind):
    binding = resolve_binding(attested=[Attested("codex_meta", _unresolvable(tmp_path, kind))], cwd=tmp_path)
    assert (binding.status, binding.reason) == ("unbound", "host_roots_not_governed")


@pytest.mark.parametrize("kind", ["loop", "nul"])
def test_an_unresolvable_host_root_disagrees_with_the_pin(home, tmp_path, kind):
    pin = _governed(tmp_path / "a")
    binding = resolve_binding(pin=str(pin), attested=[Attested("codex_meta", _unresolvable(tmp_path, kind))])
    assert (binding.status, binding.reason) == ("hold", "pin_conflicts_with_host_root")
    assert len(binding.as_dict()["details"]["host_roots"]) == 1


@pytest.mark.parametrize("kind", ["loop", "nul"])
def test_an_unresolvable_host_root_with_files_in_a_registered_workspace_holds(home, tmp_path, kind):
    other = _governed(tmp_path / "b")
    binding = resolve_binding(
        attested=[Attested("codex_meta", _unresolvable(tmp_path, kind))], files=[str(other / "x.py")],
        registry=read_registry(_registry(home, [other])),
    )
    assert (binding.status, binding.reason) == ("hold", "host_root_conflicts_with_registry")


def test_call_files_through_a_symlink_loop_never_raise(home, tmp_path):
    a = _governed(tmp_path / "a")
    b = _governed(tmp_path / "b")
    _loop(a)
    registry = read_registry(_registry(home, [a]))
    for files in (["l1/x.py"], [str(a / "l1" / "x.py")], ["nul\0.py"], [str(a / "nul\0.py")]):
        unbound = resolve_binding(files=files, registry=registry, cwd=home)
        assert unbound.status in ("unbound", "bound") and unbound.root in (None, a), files
        both = resolve_binding(attested=[Attested("mcp_roots", str(a)), Attested("mcp_roots", str(b))], files=files)
        assert both.status in ("hold", "bound") and both.root in (None, a), files


@pytest.mark.parametrize("kind", ["loop", "nul"])
def test_a_registry_root_that_cannot_be_resolved_is_skipped(home, tmp_path, kind):
    a = _governed(tmp_path / "a")
    registry = read_registry(_registry(home, [_unresolvable(tmp_path, kind), a]))
    assert registry.roots[-1] == a


def test_cli_a_target_through_a_symlink_loop_is_a_workspace_error_or_itself(home, tmp_path):
    loop = _loop(tmp_path / "links")
    try:
        root = resolve_cli_root(explicit=str(loop), cwd=tmp_path)
    except WorkspaceNotFoundError as exc:
        assert "cannot be resolved" in str(exc)
    else:  # Python 3.13+ resolves a loop leniently: the target names itself
        assert not (root / ".aegis").is_dir()
