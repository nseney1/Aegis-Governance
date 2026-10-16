"""aegis init — set up governance for this repository and register it with your agent hosts.

The repository plane (committed): ``.aegis/config.json`` (``hosts``), ``.aegis/.gitignore``,
the starter rules under ``.aegis/rules/personas/``, the Aegis bootstrap block in
``AGENTS.md`` and, only when a ``CLAUDE.md`` already exists, an ``@AGENTS.md`` block in it
(host-matrix spec §3.2, §3.4). A new workspace also gets one active rule, the
``no-eval`` invariant in ``.aegis/rules/invariants/`` (``--rules none-active`` leaves it
out), and ``--ci`` writes ``.github/workflows/aegis.yml``; without it init only prints that
workflow. The user plane (this machine): the ``aegis`` MCP
registration of each selected host and the workspace entry in ``~/.aegis/workspaces.json``
(see :mod:`aegis_cli.install_hosts` for its schema). Plus the git pre-commit hook.

Host detection only proposes: hosts are registered only when named with ``--host``
(``--host auto`` takes the detected ones). A host is found by its CLI on PATH, its config
directory or its desktop app, since an IDE or desktop app puts nothing on PATH; ``--host``
also takes a surface alias (``codex-app``, ``kiro-ide``) and stores the plane id. Every
step is checked before anything is written, so a file Aegis cannot change safely stops init with nothing written. A
``CLAUDE.md`` that is a link is never written through: a link to ``AGENTS.md`` already
gives Claude Code the bootstrap, and a link elsewhere is left alone with a warning.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.resources
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from aegis_cli.base import CommandCategory, AegisCommand
from aegis_cli.install_hosts import (
    REGISTRY_LABEL,
    InstallError,
    ordered_hosts,
    detection_evidence,
    display_command,
    is_denied_root,
    mcp_command,
    parse_hosts,
    register_host,
    register_workspace,
    registrable_hosts,
    write_managed_block,
)
from aegis_core.storage import atomic_write_bytes
from aegis_core.taxonomy import RULE_TYPES, RuleType
from aegis_core.workspace.layout import AEGIS_DIRNAME, RULES_RELDIR

# Re-exported for tests/unit/core/test_worktree_hooks.py until that facade is retired.
from aegis_cli.hooks import (  # noqa: F401
    _AEGIS_HOOK_START,
    _SOMA_HOOK_START,
    AEGIS_HOOK_FORMAT,
    SOMA_HOOK_FORMAT,
    install_hook,
)
from aegis_cli.hooks.management import hook_status, work_tree_warning

__all__ = [
    "ACTIVE_STARTERS",
    "AGENTS_FILE",
    "CI_WORKFLOW_LABEL",
    "CLAUDE_FILE",
    "CLAUDE_SHIM_ID",
    "CLAUDE_SHIM_TEXT",
    "InitCommand",
    "RULE_PRESETS",
    "RemovedOption",
    "Report",
    "Step",
    "ci_workflow",
    "hook_refusal",
    "install_rules",
    "packaged_active_rules",
    "packaged_dir",
    "packaged_rules",
    "preset_rules",
    "report_partial",
    "run_init",
    "seed_active_rules",
    "seed_workspace_rules",
]

CONFIG_LABEL = f"{AEGIS_DIRNAME}/config.json"
GITIGNORE_LABEL = f"{AEGIS_DIRNAME}/.gitignore"
SCAFFOLD_LABEL = f"{AEGIS_DIRNAME}/"
AGENTS_FILE = "AGENTS.md"
CLAUDE_FILE = "CLAUDE.md"
CLAUDE_SHIM_ID = "agents-import"
CLAUDE_SHIM_TEXT = "@AGENTS.md\n"

# ── Starter rules: one locator over the packaged rules/ (defense #20, D16) ───

_STANDARD = ("providence", "destructive-ops", "testing", "cost-optimization", "git-workflow")
RULE_PRESETS: Dict[str, Optional[Tuple[str, ...]]] = {
    "minimal": ("providence", "destructive-ops"),
    "standard": _STANDARD,
    "full": None,  # every shipped guidance rule
    "none-active": _STANDARD,  # the standard personas, and no active starter
}
# Shipped rules seeded as they are, active, into their own type directory of a new
# workspace: the personas apply to no file until someone sets their target_paths, so
# without one `aegis check` enforced nothing on day one (v4.1 field report). They are in
# no persona preset; ``--rules none-active`` leaves them out.
ACTIVE_STARTERS: Dict[str, str] = {"no-eval": "bans eval() and exec() in **/*.py, methods named eval or exec included (df.eval(), model.eval())"}
NO_ACTIVE_PRESETS = ("none-active",)
ACTIVE_TYPE_DIR = RULE_TYPES[RuleType.INVARIANT].directory
_ACTIVE_LABEL = f"{RULES_RELDIR}/{ACTIVE_TYPE_DIR}"
# The shipped rules are process guidance (what to do, not where), so they are seeded as
# persona rules whose frontmatter says so: ``type: persona`` (the repository's own lint,
# `aegis check`, requires a declared type) and ``target_paths: []`` (they apply to no file
# until the repository names the files each one governs; `aegis status` lists them).
SEED_TYPE = RuleType.PERSONA
SEED_TYPE_DIR = RULE_TYPES[SEED_TYPE].directory
_NOT_RULES = {"META.md", "README.md"}


def packaged_dir(name: str, base: Optional[Path] = None) -> Path:
    """The directory of Aegis's shipped ``rules`` or ``skills``.

    A wheel carries them in ``aegis_core/_data/<name>`` (pyproject.toml maps the
    repository's ``<name>/`` there); a source checkout has them at its root, next to its
    pyproject.toml. ``base`` is the aegis_core package directory. Nothing is imported by
    name: a top-level ``rules`` package may be another distribution's, or a repository's
    own directory first on sys.path. A missing directory is returned as is, for the
    caller to report.
    """
    base = Path(str(importlib.resources.files("aegis_core"))) if base is None else Path(base)
    installed = base / "_data" / name
    if installed.is_dir():
        return installed
    checkout = base.parent
    if (checkout / "pyproject.toml").is_file() and (checkout / name).is_dir():
        return checkout / name
    return installed


def _shipped_rules() -> Dict[str, Path]:
    base = packaged_dir("rules")
    found: Dict[str, Path] = {}
    for directory in (base, base / ".oracles"):
        if directory.is_dir():
            for path in sorted(directory.glob("*.md")):
                if path.is_file() and path.name not in _NOT_RULES:
                    found.setdefault(path.stem, path)
    return found


def packaged_rules() -> Dict[str, Path]:
    """Every shipped guidance rule (``rules/*.md``, ``rules/.oracles/*.md``, through
    ``packaged_dir``) by id: what the persona presets seed. The active starters are not
    among them (see packaged_active_rules)."""
    return {k: v for k, v in _shipped_rules().items() if k not in ACTIVE_STARTERS}


def packaged_active_rules() -> Dict[str, Path]:
    """The shipped active starters (ACTIVE_STARTERS) by id; ValueError when one is missing."""
    shipped = _shipped_rules()
    missing = [n for n in ACTIVE_STARTERS if n not in shipped]
    if missing:
        raise ValueError(f"packaged rule(s) {', '.join(missing)} not found; reinstall aegis-guardrails")
    return {n: shipped[n] for n in ACTIVE_STARTERS}


def preset_rules(preset: str) -> List[Path]:
    """The packaged rule files of ``preset``; ValueError for an unknown preset or a missing rule."""
    if preset not in RULE_PRESETS:
        raise ValueError(f"unknown rule preset {preset!r}; presets: {', '.join(RULE_PRESETS)}")
    shipped = packaged_rules()
    names = RULE_PRESETS[preset]
    if names is None:
        return [shipped[n] for n in sorted(shipped)]
    missing = [n for n in names if n not in shipped]
    if missing:
        raise ValueError(f"packaged rule(s) {', '.join(missing)} not found; reinstall aegis-guardrails")
    return [shipped[n] for n in names]


_TOP_LEVEL_KEY = re.compile(r"^([A-Za-z_][\w-]*)[ \t]*:")


def _declare_type(source: Path, rule_type: str) -> bytes:
    """The bytes of ``source`` with its frontmatter declaring ``type: <rule_type>`` and, when
    it names no files, ``target_paths: []``; the rest of the file is kept as it is."""
    text = source.read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(True)
    close = next((i for i, line in enumerate(lines[1:], 1) if line.rstrip("\r\n") == "---"), None)
    if not lines or lines[0].rstrip("\r\n") != "---" or close is None:
        raise ValueError(f"packaged rule {source.name} has no frontmatter; reinstall aegis-guardrails")
    keys: Dict[str, int] = {}
    for index in range(1, close):
        match = _TOP_LEVEL_KEY.match(lines[index])
        if match:
            keys.setdefault(match.group(1), index)
    added = [] if "target_paths" in keys else [f"target_paths: []{eol}"]
    if "type" in keys:
        lines[keys["type"]] = f"type: {rule_type}{eol}"
        at = keys["type"] + 1
    else:
        added.insert(0, f"type: {rule_type}{eol}")
        at = keys.get("id", 0) + 1
    lines[at:at] = added
    return "".join(lines).encode("utf-8")


def install_rules(rules_dir: Path, preset: str = "standard", dry_run: bool = False, force: bool = False,
                  skip: Sequence[str] = (), rule_type: Optional[str] = None) -> List[str]:
    """Copy the preset's packaged rules into ``rules_dir`` (flat); return the ids now there.

    An existing file is kept unless ``force``; a symlinked destination is never written
    through; ids in ``skip`` are left out. With ``rule_type`` each copy's frontmatter
    declares that type (and ``target_paths: []`` when it names none); without it the
    packaged bytes are copied as they are.
    """
    rules_dir = Path(rules_dir)
    present: List[str] = []
    for source in preset_rules(preset):
        name = source.stem
        if name in skip:
            continue
        dest = rules_dir / source.name
        if dest.is_symlink():
            continue
        if dest.exists() and not force:
            present.append(name)
            continue
        data = _declare_type(source, rule_type) if rule_type else source.read_bytes()
        if not dry_run:
            atomic_write_bytes(dest, data)
        present.append(name)
    return present


def seed_workspace_rules(root: Path, preset: str, dry_run: bool = False) -> Tuple[List[str], List[str]]:
    """Seed ``.aegis/rules/personas/`` with the preset; return (seeded, already present).

    A rule id that already exists in any type directory is left alone, so seeding never
    overwrites a rule and never creates a duplicate id (which would fail the scan closed).
    """
    from aegis_core.workspace.layout import WorkspaceLayout

    rules_dir = WorkspaceLayout(root).rules_dir
    target = rules_dir / SEED_TYPE_DIR
    for path in (rules_dir.parent, rules_dir, target):
        if path.is_symlink():
            raise InstallError(f"{path}: is a symlink; Aegis seeds rules only into a real directory "
                               "inside the workspace. Replace the link, then re-run.")
    existing = {p.stem for p in rules_dir.glob("*/*.md")} if rules_dir.is_dir() else set()
    names = [p.stem for p in preset_rules(preset)]
    present = [n for n in names if n in existing]
    seeded = install_rules(target, preset=preset, dry_run=dry_run, skip=present, rule_type=SEED_TYPE)
    return seeded, present


def _has_rules(root: Path) -> bool:
    from aegis_core.workspace.layout import WorkspaceLayout

    rules_dir = WorkspaceLayout(root).rules_dir
    return rules_dir.is_dir() and any(p.is_file() for p in rules_dir.glob("*/*.md"))


def seed_active_rules(root: Path, preset: str, new_workspace: bool, dry_run: bool = False) -> "Step":
    """Seed the active starters, as shipped, into their type directory of a new workspace.

    Only a workspace with no rule file yet gets them: a re-run (to add a host) must never
    put back a gate someone deleted, nor add one to a repository that already governs
    itself. A file already at the destination is kept.
    """
    from aegis_core.workspace.layout import WorkspaceLayout

    if preset in NO_ACTIVE_PRESETS:
        return Step(_ACTIVE_LABEL, "skipped", f"--rules {preset}: no active rule")
    if not new_workspace:
        return Step(_ACTIVE_LABEL, "unchanged",
                    "the workspace already has rules; active starters go only into a new one")
    directory = WorkspaceLayout(root).rules_dir / ACTIVE_TYPE_DIR
    seeded: List[str] = []
    kept: List[str] = []
    for name, source in packaged_active_rules().items():
        dest = directory / source.name
        if os.path.lexists(dest):
            kept.append(name)
            continue
        if not dry_run:
            atomic_write_bytes(dest, source.read_bytes())
        seeded.append(name)
    return Step(_ACTIVE_LABEL, "seeded" if seeded else "unchanged",
                ", ".join(f"{n} ({ACTIVE_STARTERS[n]})" for n in seeded) or "nothing new",
                names=seeded, kept=kept)


# ── Removed flags (H1 hard cut: one pointer line, exit 2) ────────────────────

class RemovedOption(argparse.Action):
    """A v3 flag: using it prints one line naming the replacement and exits 2."""

    def __init__(self, option_strings, dest, pointer: str = "", nargs=0, **kwargs):
        kwargs.update(help=argparse.SUPPRESS, default=argparse.SUPPRESS)
        super().__init__(option_strings, dest, nargs=nargs, **kwargs)
        self.pointer = pointer

    def __call__(self, parser, namespace, values, option_string=None):
        print(f"{parser.prog} {self.option_strings[0]} was removed in v4: {self.pointer}", file=sys.stderr)
        parser.exit(2)


def _host_option(value: str):
    try:
        return parse_hosts(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _host_help() -> str:
    """--host's help, from the host table: each plane with its surfaces and aliases."""
    planes = []
    for host in registrable_hosts():
        tag = ", experimental" if not host.verified else ""
        also = f"; also {', '.join(host.aliases)}" if host.aliases else ""
        planes.append(f"{host.id}{tag} ({', '.join(host.surfaces)}{also})")
    return ("Register the Aegis MCP server with these hosts, or 'auto' for the ones found on this machine "
            "(by CLI on PATH, config directory or desktop app). Without it, found hosts are only listed. A host "
            "is the config plane its surfaces share, so a surface name selects its host: " + "; ".join(planes))


def _with_surfaces(host_ids: Sequence[str]) -> str:
    from aegis_core import hosts as host_table

    return ", ".join(f"{h} ({', '.join(host_table.get(h).surfaces)})" for h in host_ids)


# ── The CI floor ─────────────────────────────────────────────────────────────

CI_WORKFLOW_LABEL = ".github/workflows/aegis.yml"
_RUNS_AEGIS_CHECK = re.compile(r"\baegis\s+check\b")
_WORKFLOW_READ_LIMIT = 1 << 20


def ci_workflow() -> str:
    """The GitHub Actions workflow init prints, and writes with ``--ci``: ``aegis check`` on
    every pull request, with the aegis version that wrote it (a newer release may check more)."""
    from aegis_cli import __version__

    return f"""\
# aegis check on every pull request. CI is the floor: git commit --no-verify skips the
# local pre-commit hook, so the same check runs here.
name: Aegis

on:
  pull_request:
  push:
    branches: [main, master]

permissions:
  contents: read

jobs:
  aegis-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0  # aegis check diffs the pull request against its base branch
          persist-credentials: false
      - uses: actions/setup-python@v7
        with:
          python-version: "3.12"
      - run: pip install aegis-guardrails=={__version__}
      - run: aegis check
"""


def _workflow_files(root: Path) -> List[Path]:
    """The GitHub Actions workflow files (``.github/workflows/*.yml|yaml``; GitHub reads no
    subdirectory there)."""
    directory = root / ".github" / "workflows"
    try:
        entries = sorted(directory.iterdir()) if directory.is_dir() else []
    except OSError:
        return []
    return [e for e in entries if e.suffix in (".yml", ".yaml") and e.is_file()]


def _runs_aegis_check(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            text = handle.read(_WORKFLOW_READ_LIMIT).decode("utf-8", "replace")
    except OSError:
        return False
    return bool(_RUNS_AEGIS_CHECK.search(text))


def _ci_step(root: Path, write: bool, dry_run: bool) -> "Step":
    """The CI workflow: with ``write`` (--ci) ``.github/workflows/aegis.yml`` is created
    unless a file is there; without it nothing is written, and the step says whether a
    workflow already runs aegis check (``present``) or init should print one (``suggested``,
    with the workflow files it saw as ``names``). Raises InstallError for a directory it
    cannot write through: a link, a file, or one resolving out of the repository."""
    workflows = root / ".github" / "workflows"
    if not write:
        files = _workflow_files(root)
        running = [f.relative_to(root).as_posix() for f in files if _runs_aegis_check(f)]
        if running:
            return Step(CI_WORKFLOW_LABEL, "present", f"{', '.join(running)} run{'s' if len(running) == 1 else ''} "
                                                      "aegis check")
        return Step(CI_WORKFLOW_LABEL, "suggested", "no GitHub Actions workflow runs aegis check; "
                                                    "aegis init --ci writes one",
                    names=[f.relative_to(root).as_posix() for f in files])
    inside = _real_key(root) + os.sep
    for directory in (root / ".github", workflows):
        label = directory.relative_to(root).as_posix()
        if directory.is_symlink():
            raise InstallError(f"{label}: is a symlink; aegis init --ci writes the workflow only into a real "
                               "directory inside the repository. Replace the link, or re-run without --ci.")
        if os.path.lexists(directory) and not directory.is_dir():
            raise InstallError(f"{label}: is not a directory; left unchanged. Move it aside, or re-run without --ci.")
        if directory.is_dir() and not _real_key(directory).startswith(inside):
            raise InstallError(f"{label}: resolves outside the repository; aegis init --ci writes the workflow only "
                               "inside it. Re-run without --ci.")
    dest = workflows / "aegis.yml"
    data = ci_workflow().encode("utf-8")
    if os.path.lexists(dest):
        try:
            same = not dest.is_symlink() and dest.is_file() and dest.read_bytes() == data
        except OSError:
            same = False
        return Step(CI_WORKFLOW_LABEL, "unchanged") if same else Step(
            CI_WORKFLOW_LABEL, "kept", "it exists; left as it is")
    if dry_run:
        _need_writable(workflows)
    else:
        atomic_write_bytes(dest, data)
    return Step(CI_WORKFLOW_LABEL, "created", "runs aegis check on every pull request")


def _report_ci(report: Report, actions: Sequence["Step"]) -> None:
    """After a real run: CI is the floor. The workflow written, or the one to add."""
    step = next((a for a in actions if a.target == CI_WORKFLOW_LABEL), None)
    floor = "CI is the floor: git commit --no-verify skips the pre-commit hook, so CI must run aegis check too."
    if step is None or step.result not in ("created", "suggested"):
        return
    if step.result == "created":
        report.say(f"  {floor} Review and commit {CI_WORKFLOW_LABEL}.")
        report.say()
        return
    lead = ("No GitHub Actions workflow here runs aegis check yet." if step.names
            else "This repository has no GitHub Actions workflow yet.")
    report.say(f"  {floor}")
    report.say(f"  {lead} Save this as {CI_WORKFLOW_LABEL}, or re-run aegis init with --ci to write it:")
    report.say()
    for line in ci_workflow().splitlines():
        report.say(f"      {line}".rstrip())
    report.say()


# ── The pre-commit hook ──────────────────────────────────────────────────────

def _within(path: Path, boundary: Path) -> bool:
    try:
        path.relative_to(boundary.resolve())
        return True
    except ValueError:
        return False


def _unwritable(directory: Path) -> Optional[str]:
    """Why no file can be created in ``directory`` (made with its parents when missing,
    so the nearest directory that exists decides); None when one can."""
    existing = Path(directory)
    while not os.path.lexists(existing) and existing.parent != existing:
        existing = existing.parent
    if existing.is_dir() and os.access(existing, os.W_OK | os.X_OK):
        return None
    return f"{existing} is not a writable directory"


@dataclass(frozen=True)
class _HookPlace:
    hooks_dir: Path
    hook: Path
    shared: bool  # outside the repository and its git directories
    where: str    # how a refusal names the hooks directory


def _hook_place(root: Path) -> Optional[_HookPlace]:
    """Where the pre-commit hook lives; None when there is no git repository."""
    from aegis_core.workspace.hooks import _find_git_dirs, resolve_git_hooks_dir

    hooks_dir = resolve_git_hooks_dir(root)
    if not hooks_dir:
        return None
    hooks_dir = Path(hooks_dir)
    git_dir, common_dir = _find_git_dirs(root)
    repository = (root, *(d for d in (git_dir, common_dir) if d is not None))
    shared = not any(_within(hooks_dir.resolve(), b) for b in repository)
    default = common_dir / "hooks" if common_dir is not None else None
    if default is not None and _real_key(default) == _real_key(hooks_dir):
        # No core.hooksPath: the repository's own hooks directory is a link out of it.
        where = f"{default} is a link to {hooks_dir.resolve()}"
    else:
        where = f"the hooks directory {hooks_dir} (core.hooksPath)"
    return _HookPlace(hooks_dir, hooks_dir / "pre-commit", shared, where)


def shared_hook_in_place(root: Path) -> Optional[Path]:
    """The pre-commit hook of a shared hooks directory (see hook_refusal) that already holds
    exactly the block install_hook would write, so installing it changes nothing: someone
    ran ``aegis hook install`` there on purpose. init leaves it as it is instead of refusing
    again (which left --no-hooks as the only way through) or rewriting a file other
    repositories run. None otherwise.
    """
    from aegis_cli.hooks.management import _replace_hook_block, generate_hook_block

    place = _hook_place(Path(root).resolve())
    if place is None or not place.shared:
        return None
    try:
        content = place.hook.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    # install_hook rewrites CRLF as LF, so a CRLF file is not one it would leave alone.
    if "\r" in content or _replace_hook_block(content, generate_hook_block()) != content:
        return None
    return place.hook


def hook_refusal(root: Path, *, removing: bool = False) -> Optional[str]:
    """Why the pre-commit hook cannot be installed (or, ``removing``, uninstalled) safely.

    install_hook and uninstall_hook print a refusal and return False, which a caller
    cannot tell from "not a git repository", or warn and report success; their dry runs
    never look at the file; and a hooks directory they cannot write fails them with a raw
    OSError. So init's and uninstall's check passes ask here first. None when the hook
    can be changed, or when there is no git repository.

    A hooks directory outside the repository and its git directories (``core.hooksPath``
    set to a team or dotfiles directory, often globally, or a ``.git/hooks`` linked to one)
    holds a hook every repository using it runs; install_hook would insert the Aegis block
    there, right after the shebang so it runs before the hook's own lines, pinned to this
    machine's aegis, so it is refused here and left to an explicit ``aegis hook install``
    (after which shared_hook_in_place lets init through).
    """
    from aegis_cli.hooks.management import _replace_hook_block

    root = Path(root).resolve()
    place = _hook_place(root)
    if place is None:
        return None
    hooks_dir, hook, shared = place.hooks_dir, place.hook, place.shared
    if shared and not removing:
        return (f"{place.where}, outside this repository, so its pre-commit hook may run in other "
                "repositories too; Aegis does not add its block there. To add it anyway, run: aegis hook install")
    verb = "removed" if removing else "installed"
    target, outside = hook, shared
    if hook.is_symlink():
        target = hook.resolve()
        if not target.exists():
            return None if removing else f"{hook} is a dangling symlink; to replace it, run: aegis hook install --force"
        outside = shared or not any(_within(target, b) for b in (root, hooks_dir))
        if outside and not removing:
            return (f"{hook} is a symlink to {target}, outside the repository; Aegis does not write through it. "
                    "To add the hook to that file anyway, run: aegis hook install --force")
    if not target.exists():
        reason = None if removing else _unwritable(hooks_dir)
        return f"{reason}, so the hook cannot be {verb}" if reason else None
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"{target} is not UTF-8 text; Aegis cannot edit it"
    except OSError as exc:
        return f"{target} cannot be read ({exc.strerror or exc})"
    if _AEGIS_HOOK_START not in content and _SOMA_HOOK_START not in content:
        reason = None if removing else _unwritable(target.parent)
        return f"{reason}, so the hook cannot be {verb}" if reason else None
    if shared:
        return (f"{hook} holds the Aegis hook, but {place.where}, outside this repository, and may serve other "
                "repositories; Aegis leaves it as it is. To remove the block anyway, run: aegis hook uninstall")
    if outside:
        return (f"{hook} is a symlink to {target}, outside the repository, and that file holds the Aegis hook; "
                "Aegis does not write through it. Remove the block from that file yourself, or run: "
                "aegis hook uninstall --force")
    if _replace_hook_block(content, "") is None:
        return f"{target} has an unterminated Aegis hook block; fix or remove it"
    # Removing may delete the hook file (and the file a link in the repository points to).
    reason = next(filter(None, (_unwritable(d) for d in (hook.parent, target.parent))), None)
    return f"{reason}, so the hook cannot be {verb}" if reason else None


# ── The run ──────────────────────────────────────────────────────────────────

@dataclass
class Step:
    """One init or uninstall step and what it did (or would do, in a dry run)."""

    target: str
    result: str
    detail: str = ""
    command: Optional[List[str]] = None
    names: Sequence[str] = ()
    kept: Sequence[str] = ()

    def as_dict(self) -> Dict[str, Any]:
        return {"target": self.target, "result": self.result, "detail": self.detail, "command": self.command}


class Report:
    """Human lines on stdout, or one JSON document at the end with --json."""

    def __init__(self, json_mode: bool, source: str) -> None:
        self.json_mode = json_mode
        self.source = source
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.muted = False  # the check pass before a real run stays quiet; the run reports

    def say(self, line: str = "") -> None:
        if not self.json_mode:
            print(line)

    def warn(self, line: str) -> None:
        if self.muted:
            return
        self.warnings.append(line)
        if not self.json_mode:
            sys.stdout.flush()  # keep the order of stdout and stderr lines in a pipe
            print(f"  ⚠️  {line}", file=sys.stderr)

    def error(self, line: str) -> None:
        self.errors.append(line)
        if not self.json_mode:
            sys.stdout.flush()  # keep the order of stdout and stderr lines in a pipe
            print(f"  ❌ {line}", file=sys.stderr)

    def finish(self, status: str, scope: Dict[str, Any], dry_run: bool, actions: Sequence[Step]) -> None:
        if not self.json_mode:
            return
        from aegis_cli import __version__

        print(json.dumps({
            "source": self.source,
            "aegis_version": __version__,
            "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scope": scope,
            "dry_run": dry_run,
            "status": status,
            "actions": [a.as_dict() for a in actions],
            "errors": self.errors,
            "warnings": self.warnings,
        }, indent=2))


def _config_hosts(root: Path, selected: List[str], dry_run: bool, report: Report) -> Step:
    """Add the selected hosts to ``.aegis/config.json`` (``{"v": 1}`` when none)."""
    from aegis_core.config import ConfigError, RepoConfig, update_repo_config
    from aegis_core.errors import PathTraversalError
    from aegis_core.workspace.layout import WorkspaceLayout

    layout = WorkspaceLayout(root)
    for path in (layout.aegis_dir, layout.config_file):
        if path.is_symlink():
            raise InstallError(f"{path}: is a symlink; aegis writes .aegis/ only as regular files inside "
                               "the workspace. Replace the link, then re-run.")
    unreadable: List[str] = []

    def change(data: Dict[str, Any]) -> None:
        current = data.get("hosts")
        if current is None and not selected:
            return
        if current is not None and not (isinstance(current, list) and all(isinstance(h, str) for h in current)):
            unreadable.append("'hosts' in .aegis/config.json is not a list of host ids; left as it is")
            return
        data["hosts"] = ordered_hosts(list(current or []) + selected)

    before = layout.config_file.read_bytes() if layout.config_file.is_file() else None
    try:
        if dry_run:
            current = RepoConfig.load(root)
            data: Dict[str, Any] = {"hosts": list(current.hosts)} if before is not None else {}
            change(data)
            hosts = data.get("hosts", [])
            result = "created" if before is None else (
                "unchanged" if list(current.hosts) == list(hosts) else "updated")
        else:
            hosts = update_repo_config(root, change).get("hosts", [])
            result = "created" if before is None else (
                "unchanged" if layout.config_file.read_bytes() == before else "updated")
    except PathTraversalError as exc:
        raise InstallError(str(exc)) from exc
    except ConfigError as exc:
        report.warn(f"{exc}; left unchanged. Fix it, then rerun aegis init.")
        return Step(CONFIG_LABEL, "kept", str(exc))
    for line in unreadable:
        report.warn(line)
    return Step(CONFIG_LABEL, result, f"hosts: {', '.join(hosts) if hosts else 'none'}")


@dataclass
class _Context:
    ws: Any
    root: Path
    home: Path
    selected: List[str]
    preset: str
    force: bool
    no_hooks: bool
    command: List[str]
    pin: Optional[str]
    path_env: Optional[str]
    report: Report
    skills: bool = False
    ci: bool = False


def _real_key(path: Path) -> str:
    return os.path.normcase(os.path.realpath(path))


def _check_repo_dirs(root: Path, dirs: Sequence[Path]) -> None:
    """Refuse, before the first write, a directory under .aegis/ that init writes into
    but cannot use: a link (it could point anywhere), a file, a junction resolving out of
    the workspace, or (when it is still to be made) no writable directory to make it in."""
    inside = _real_key(root) + os.sep
    for directory in dirs:
        if directory.is_symlink():
            raise InstallError(f"{directory}: is a symlink; Aegis keeps .aegis/ only as real directories inside "
                               "the workspace. Replace the link, then re-run.")
        if not os.path.lexists(directory):
            _need_writable(directory)
        elif not directory.is_dir():
            raise InstallError(f"{directory}: is not a directory; left unchanged. Move it aside, then re-run.")
        elif not _real_key(directory).startswith(inside):
            raise InstallError(f"{directory}: resolves outside the workspace; Aegis keeps .aegis/ only inside it. "
                               "Replace it with a real directory, then re-run.")


def _need_writable(directory: Path) -> None:
    reason = _unwritable(directory)
    if reason:
        where = "" if os.path.lexists(directory) else f"{directory} cannot be created: "
        raise InstallError(f"{where}{reason}; nothing can be written there. Fix its permissions, then re-run.")


def _claude_shim(ctx: _Context, dry_run: bool) -> Step:
    """The ``@AGENTS.md`` block in an existing CLAUDE.md; a link is never written through."""
    claude, agents = ctx.root / CLAUDE_FILE, ctx.root / AGENTS_FILE
    if not claude.is_symlink():
        return Step(CLAUDE_FILE, write_managed_block(
            claude, CLAUDE_SHIM_ID, CLAUDE_SHIM_TEXT, force=ctx.force, create=False, dry_run=dry_run))
    if _real_key(claude) == _real_key(agents):
        return Step(CLAUDE_FILE, "linked", "a link to AGENTS.md, so Claude Code reads the bootstrap as it is")
    ctx.report.warn(f"{claude} is a symlink to {os.path.realpath(claude)}; Aegis never writes through a link, so "
                    "it was left as it is. For Claude Code to read the Aegis bootstrap, add an @AGENTS.md import "
                    "to that file, or make CLAUDE.md a link to AGENTS.md.")
    return Step(CLAUDE_FILE, "skipped", "a symlink, never written through")


def _skills_steps(ctx: _Context, dry_run: bool) -> List[Step]:
    """``--skills``: the packaged skills copied for the configured and selected hosts, as
    ``aegis skills sync`` copies them. A refusal (a link, a file of the wrong kind) stops
    init like any other step; a file the user owns or edited is kept, with a warning."""
    from aegis_cli.skills_sync import summary, sync_skills
    from aegis_core.config import ConfigError, RepoConfig

    try:
        configured = list(RepoConfig.load(ctx.root).hosts)
    except ConfigError:
        configured = []  # _config_hosts has already warned about the file
    result = sync_skills(ctx.root, ordered_hosts(configured + ctx.selected), dry_run=dry_run, trigger="init")
    if not result.targets:
        return [Step("skills", "skipped", "no selected host reads project skills; "
                                          "add --host claude-code, codex-cli or antigravity")]
    problems = [e.detail for t in result.targets for e in t.entries if e.result in ("refused", "failed")]
    problems += result.errors
    if problems:
        raise InstallError(f"skills: {problems[0]}. Fix it, or re-run without --skills.")
    for warning in result.warnings:
        ctx.report.warn(warning)
    steps = []
    for target in result.targets:
        for entry in target.entries:
            if entry.result == "skipped":
                ctx.report.warn(f"{entry.path}: {entry.detail}")
        counts = target.counts
        written = any(counts[name] for name in ("created", "updated", "overwritten"))
        label = "" if target.verified else ", unverified"
        steps.append(Step(target.dir, "synced" if written else "unchanged",
                          f"{', '.join(target.hosts)}{label}: {summary(counts)}"))
    return steps


def _steps(ctx: _Context, dry_run: bool, actions: Optional[List[Step]] = None) -> List[Step]:
    """Run every init step; with ``dry_run`` only check and plan. Raises InstallError.

    Each finished step is appended to ``actions`` as it completes, so a run that fails
    part way still says what it had already written.
    """
    from aegis_core.ast.detect import detect_project_languages, provision_ast_driver_slots
    from aegis_core.bootstrap import BOOTSTRAP_ID, bootstrap_text
    from aegis_core.errors import PathTraversalError, WorkspaceBareRepoError
    from aegis_core.workspace.hooks import resolve_git_hooks_dir
    from aegis_core.workspace.layout import WorkspaceLayout
    from aegis_core.workspace.scaffold import ensure_runtime_gitignore

    report, root = ctx.report, ctx.root
    actions = [] if actions is None else actions
    layout = WorkspaceLayout(root)
    personas = layout.rules_dir / SEED_TYPE_DIR
    new_workspace = not _has_rules(root)  # before anything is seeded
    try:
        planned = ctx.ws.scaffold(minimal=(ctx.preset == "minimal"), dry_run=True)
        missing = [d for d in planned if not os.path.lexists(d)]
        if dry_run:
            # The real run creates these directories first, so only this pass can see them.
            _check_repo_dirs(root, [layout.aegis_dir, layout.rules_dir, *planned, personas])
            _need_writable(layout.state_dir)  # the workspace lock lives there
        else:
            ctx.ws.scaffold(minimal=(ctx.preset == "minimal"), dry_run=False)
    except WorkspaceBareRepoError as exc:
        raise InstallError(str(exc)) from exc
    if missing:
        actions.append(Step(SCAFFOLD_LABEL, "created", ", ".join(d.relative_to(root).as_posix() for d in missing)))
    actions.append(_config_hosts(root, ctx.selected, dry_run, report))
    if dry_run and actions[-1].result in ("created", "updated"):
        _need_writable(layout.aegis_dir)

    gitignore = ensure_runtime_gitignore(ctx.ws.aegis_dir, dry_run=dry_run)
    if gitignore == "symlink":
        report.warn(".aegis/.gitignore is a symlink; not modified. Add Aegis runtime state to it yourself.")
    elif gitignore == "dry-run":
        _need_writable(layout.aegis_dir)
    actions.append(Step(GITIGNORE_LABEL, gitignore))

    try:
        seeded, present = seed_workspace_rules(root, ctx.preset, dry_run=dry_run)
    except ValueError as exc:
        raise InstallError(str(exc)) from exc
    if dry_run and seeded:
        _need_writable(personas)
    actions.append(Step(f"{RULES_RELDIR}/{SEED_TYPE_DIR}", "seeded" if seeded else "unchanged",
                           f"preset {ctx.preset}: {', '.join(seeded) or 'nothing new'}",
                           names=seeded, kept=present))
    try:
        active = seed_active_rules(root, ctx.preset, new_workspace, dry_run=dry_run)
    except ValueError as exc:
        raise InstallError(str(exc)) from exc
    if dry_run and active.result == "seeded":
        _need_writable(layout.rules_dir / ACTIVE_TYPE_DIR)
    actions.append(active)

    languages = detect_project_languages(root)
    try:
        slots, _written = provision_ast_driver_slots(root, languages, dry_run=dry_run)
    except PathTraversalError as exc:
        raise InstallError(str(exc)) from exc
    drivers = sorted(k[len("ast_driver_"):] for k in slots if k.startswith("ast_driver_"))
    actions.append(Step("ast drivers", "configured" if drivers else "none", ", ".join(drivers)))

    agents = root / AGENTS_FILE
    if agents.is_symlink():
        raise InstallError(
            f"{agents}: is a symlink to {os.path.realpath(agents)}; Aegis never writes through a link. Make "
            f"{AGENTS_FILE} a regular file, then re-run. If it links to {CLAUDE_FILE}, swap them: move "
            f"{CLAUDE_FILE} to {AGENTS_FILE} and make {CLAUDE_FILE} the link to {AGENTS_FILE}, which Aegis "
            "supports.")
    actions.append(Step(AGENTS_FILE, write_managed_block(
        agents, BOOTSTRAP_ID, bootstrap_text(), force=ctx.force, dry_run=dry_run)))
    actions.append(_claude_shim(ctx, dry_run))
    if ctx.skills:
        actions.extend(_skills_steps(ctx, dry_run))
    actions.append(_ci_step(root, ctx.ci, dry_run))

    if not ctx.no_hooks:
        in_place = shared_hook_in_place(root)
        if in_place is not None:
            actions.append(Step("pre-commit hook", "unchanged",
                                f"{in_place} already runs the Aegis hook (a shared hooks directory); left as it is"))
        else:
            refusal = hook_refusal(root)
            if refusal:
                raise InstallError(f"pre-commit hook: {refusal}. Or re-run with --no-hooks to set up everything else.")
            hooked = install_hook(root, dry_run=dry_run)
            if not hooked and resolve_git_hooks_dir(root):
                raise InstallError("the pre-commit hook could not be installed (see above); left unchanged")
            actions.append(Step("pre-commit hook", "installed" if hooked else "skipped (not a git repository)"))

    actions.append(Step(REGISTRY_LABEL, register_workspace(ctx.home, root, ctx.selected, dry_run=dry_run)))
    for host in ctx.selected:
        done = register_host(host, home=ctx.home, command=ctx.command, pin=ctx.pin, path=ctx.path_env,
                             dry_run=dry_run)
        actions.append(Step(host, done.result, done.detail, done.command))
    return actions


_ICONS = {"failed": "❌", "manual": "👉", "kept": "⚠️ ", "skipped": "⚠️ "}
# Results that changed nothing on disk (what a failed run reports as already written).
_NO_CHANGE = {"unchanged", "absent", "none", "kept", "skipped", "linked", "would_run", "manual", "failed",
              "dry-run", "skipped (not a git repository)", "present", "suggested"}
_NEXT_RULE = "    Next: add a rule for your own code with aegis rule create (aegis rule create --help)"


def _print_active(report: Report, action: Step, dry_run: bool, preset: str) -> None:
    """The active starter: what it enforces, or that there is none; then the next step."""
    if action.result == "skipped":
        report.say(f"  No active rule (--rules {preset}): aegis check enforces no rule until one names files.")
    elif action.names or action.kept:
        report.say(f"  Active rule in {action.target}/:")
        for name in action.names:
            report.say(f"    {'[DRY-RUN]' if dry_run else '✅'} {name}: {ACTIVE_STARTERS[name]}; "
                       "aegis check and the pre-commit hook enforce it")
        for name in action.kept:
            report.say(f"    [SKIP] {name} (a file with this name exists)")
    else:
        return  # a workspace that already had rules: nothing was seeded, nothing to say
    if not dry_run:
        report.say(_NEXT_RULE)


def _print_ci(report: Report, action: Step, dry_run: bool) -> None:
    if action.result == "present":
        report.say(f"  ✅ CI: {action.detail}")
    elif action.result == "created":
        report.say(f"  ✅ {action.target}: {'would create' if dry_run else 'created'} ({action.detail})")
    elif action.result == "kept":
        report.say(f"  {_ICONS['kept']} {action.target}: kept ({action.detail})")
    elif action.result == "unchanged":
        report.say(f"  ✅ {action.target}: unchanged")
    # "suggested": the workflow is printed after a real run (_report_ci)


def _print_actions(report: Report, actions: Sequence[Step], dry_run: bool, preset: str) -> None:
    for action in actions:
        if action.target == _ACTIVE_LABEL:
            _print_active(report, action, dry_run, preset)
            continue
        if action.target == CI_WORKFLOW_LABEL:
            _print_ci(report, action, dry_run)
            continue
        if action.target.startswith(RULES_RELDIR + "/"):
            report.say(f"  Starter rules (preset={preset}) in {action.target}/:")
            for name in action.names:
                report.say(f"    {'[DRY-RUN]' if dry_run else '✅'} {name}")
            for name in action.kept:
                report.say(f"    [SKIP] {name} (a rule with this id exists)")
            if action.names:
                report.say("    They apply to no file until you set their target_paths (aegis status lists them).")
            continue
        if action.result == "absent":
            continue  # CLAUDE.md: Aegis never creates one
        if action.target == "ast drivers":
            verb = "Would configure" if dry_run else "Configured"
            for ext in action.detail.split(", ") if action.detail else []:
                report.say(f"    ✨ {verb} AST driver (.{ext}): packaged {ext} driver")
            continue
        if action.target == "pre-commit hook" and action.result == "unchanged":
            report.say(f"    🪝 Pre-commit hook: {action.detail}")
            continue
        if action.target in ("pre-commit hook", SCAFFOLD_LABEL):
            continue  # the hook is printed by _report_hook; the directories are in JSON only
        icon = _ICONS.get(action.result, "✅")
        if action.result == "manual":
            report.say(f"  {icon} {action.target}: {action.detail}; run it yourself:")
            report.say(f"       {display_command(action.command or [])}")
        elif action.command:
            result = "would run" if action.result == "would_run" else action.result
            report.say(f"  {icon} {action.target}: {result} ({display_command(action.command)})")
        else:
            detail = f" ({action.detail})" if action.detail else ""
            report.say(f"  {icon} {action.target}: {action.result}{detail}")


def report_partial(report: Report, exc: Exception, actions: Sequence[Step], done: str) -> None:
    """Report a failure in the middle of a real run with what it had already changed."""
    if isinstance(exc, OSError):
        where = f"{exc.filename}: " if exc.filename else ""
        report.error(f"{where}{exc.strerror or exc}; stopped there.")
    else:
        report.error(str(exc))
    changed = [a.target for a in actions if a.result not in _NO_CHANGE]
    if changed:
        report.error(f"Already {done}: {', '.join(changed)}. Fix the cause, then re-run (it keeps what is there).")
    else:
        report.error(f"Nothing was {done}.")


def _print_card(report: Report, root: Path) -> None:
    """The day-0 card (aegis_core.card), as `aegis check --card` prints it: what this
    repository looks like to Aegis now that it is set up. Advisory: init never fails for it."""
    if report.json_mode:
        return
    from aegis_cli import sanitize_display

    try:
        from aegis_core import card

        lines = card.build(root).text_lines()
    except Exception as exc:
        report.warn(f"the day-0 card could not be built: {type(exc).__name__}: {exc}")
        return
    for line in lines:
        report.say(sanitize_display(f"  {line}", max_len=max(len(line) + 2, 80)))
    report.say()


def run_init(args: argparse.Namespace) -> int:
    """Main init flow. Returns the exit code (0 ok, 1 refused or failed, 2 usage)."""
    from aegis_core.ast.detect import detect_project_languages
    from aegis_core.workspace.base import Workspace

    json_mode = bool(getattr(args, "json", False))
    report = Report(json_mode, "aegis init")
    ws = getattr(args, "ws", None) or Workspace.for_init(
        getattr(args, "workspace", None) or getattr(args, "_project_root", None) or Path.cwd())
    root = ws.root
    dry_run = bool(getattr(args, "dry_run", False))
    yes = bool(getattr(args, "yes", False))
    preset = getattr(args, "rules", None) or "standard"
    home = Path.home()
    path_env = os.environ.get("PATH")

    found = detection_evidence(home, path_env)
    detected = list(found)
    host_arg = getattr(args, "host", None)
    if isinstance(host_arg, str):
        host_arg = parse_hosts(host_arg)
    selected: List[str] = list(detected) if host_arg == "auto" else list(host_arg or [])
    scope = {"workspace": str(root), "hosts": selected, "detected": detected}

    if json_mode and not (yes or dry_run):
        print("aegis init --json needs --yes or --dry-run (it cannot prompt)", file=sys.stderr)
        return 2
    if is_denied_root(root, home):
        report.error(f"refusing to set up {root}: your home directory and a filesystem root are never "
                     "a workspace (ADR 0005 AD-4). Run aegis init in a repository.")
        report.finish("refused", scope, dry_run, [])
        return 1

    report.say()
    report.say("  🛡️ Aegis Guardrails — Workspace Setup")
    report.say()
    report.say(f"  Workspace: {root}")
    languages = detect_project_languages(root)
    if languages:
        report.say(f"  Detected language(s): {', '.join(k.title() for k in sorted(languages))}")
    else:
        report.say("  Project type: unknown (rules are language-agnostic)")
    if selected:
        report.say(f"  Hosts: {_with_surfaces(selected)}")
    else:
        report.say("  Hosts: none selected (only the repository is set up)")
        if detected and host_arg is None:
            report.say("  Found on this machine: "
                       f"{', '.join(f'{h} ({_home_label(v, home)})' for h, v in found.items())}. "
                       "To register Aegis with them:")
            report.say(f"       aegis init --host {','.join(detected)}")
    report.say()
    from aegis_core import hosts as host_table

    for host_id in selected:
        spec = host_table.get(host_id)
        if not spec.verified:
            report.warn(f"{host_id} is an experimental host. {' '.join(spec.notes)}")

    ctx = _Context(ws=ws, root=root, home=home, selected=selected, preset=preset,
                   force=bool(getattr(args, "force", False)), no_hooks=_no_hooks(args),
                   command=mcp_command(path_env), pin=str(root) if getattr(args, "pin", False) else None,
                   path_env=path_env, report=report, skills=bool(getattr(args, "skills", False)),
                   ci=bool(getattr(args, "ci", False)))

    # Every step is checked first; a refusal stops init before anything is written.
    report.muted = not dry_run
    try:
        plan = _steps(ctx, dry_run=True)
    except InstallError as exc:
        report.muted = False
        report.error(str(exc))
        report.error("Nothing was written.")
        report.finish("refused", scope, dry_run, [])
        return 1

    report.muted = False
    if dry_run:
        _print_actions(report, plan, True, preset)
        if any(a.target == "pre-commit hook" and a.result == "installed" for a in plan):
            report.say("    🪝 Would install pre-commit hook")
        report.say()
        report.say("  Dry run complete. No files were created.")
        report.finish("ok", scope, True, plan)
        return 0

    if not yes:
        report.say("  Will do:")
        _print_actions(report, plan, True, preset)
        try:
            answer = input("  Proceed? [Y/n] ").strip().lower()
        except EOFError:
            # Not a decline: stdin is closed (a script that forgot --yes) and nothing was done.
            report.say()
            report.error("no answer to the prompt (end of input); nothing was written. "
                         "Re-run with --yes to skip the prompt.")
            report.finish("aborted", scope, False, plan)
            return 1
        except KeyboardInterrupt:
            report.say()
            report.say("  Aborted.")
            report.finish("aborted", scope, False, plan)
            return 130
        if answer and answer not in ("y", "yes"):
            report.say("  Aborted.")
            report.finish("aborted", scope, False, plan)
            return 0
        report.say()

    actions: List[Step] = []
    try:
        _steps(ctx, dry_run=False, actions=actions)
    except (InstallError, OSError) as exc:
        # The check pass refuses everything it can see, so only a change between the check
        # and the write (a file edited meanwhile, a disk error) gets here.
        report_partial(report, exc, actions, "written")
        report.finish("failed", scope, False, actions)
        return 1
    _print_actions(report, actions, False, preset)
    _report_hook(report, root, actions)

    failed = [a for a in actions if a.result == "failed"]
    for action in failed:
        report.error(f"{action.target}: registration failed ({action.detail}). Run it yourself: "
                     f"{display_command(action.command or [])}")
    manual = sum(1 for a in actions if a.result == "manual")
    report.say()
    if failed:
        report.say("  Done, with errors (see above).")
    elif manual:
        # The host CLI is not installed here; nothing is governed until the user runs it.
        report.say(f"  Done, but {manual} host{'s are' if manual > 1 else ' is'} not registered until you run the "
                   f"command{'s' if manual > 1 else ''} above.")
    elif ctx.selected:
        report.say("  Done! Your next agent session will be governed.")
    else:
        report.say("  Done! No agent host was registered; to add one: aegis init --host HOST[,HOST]")
    report.say()
    _print_card(report, root)
    report.say("  After a session, run: aegis status")
    report.say()
    _report_ci(report, actions)
    if not json_mode:
        try:
            from aegis_cli.pathcheck import build_hint

            hint = build_hint()
            if hint:
                print(hint)
                print()
        except (OSError, RuntimeError):
            pass
    report.finish("failed" if failed else "ok", scope, False, actions)
    return 1 if failed else 0


def _home_label(evidence: str, home: Path) -> str:
    """``evidence`` (a path that found a host) as ``~/...`` when it is under ``home``."""
    if evidence.startswith("~/"):
        return evidence
    try:
        return "~/" + Path(evidence).relative_to(home).as_posix()
    except ValueError:
        return evidence


def _no_hooks(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "no_hooks", False)) or not getattr(args, "hooks", True)


def _report_hook(report: Report, root: Path, actions: Sequence[Step]) -> None:
    if not any(a.target == "pre-commit hook" and a.result == "installed" for a in actions):
        return
    st = hook_status(root)
    report.say(f"    🪝 Pre-commit hook installed ({st['hook_file']})")
    if st["hooks_dir_in_work_tree"]:
        print(work_tree_warning(st["hook_file"]), file=sys.stderr)


class InitCommand(AegisCommand):
    """Command to initialize governance for a project."""

    name = "init"
    category = CommandCategory.SETUP
    help = "Set up governance for this project and register it with your agent hosts"
    description = (
        "Set up .aegis/ (config, starter rules, .gitignore), the Aegis block in AGENTS.md "
        "(and an @AGENTS.md block in an existing CLAUDE.md), the git pre-commit hook, and this "
        "workspace's entry in ~/.aegis/workspaces.json {\"v\": 1, \"workspaces\": [{root, added_at, "
        "added_by, hosts}]}, which only aegis init and aegis uninstall write. Hosts named with "
        "--host get the 'aegis' MCP server (codex-cli: codex mcp add; claude-code: claude mcp add "
        "--scope user; antigravity: ~/.gemini/config/mcp_config.json; kiro: ~/.kiro/settings/mcp.json). "
        "A new workspace also gets one active rule, the no-eval invariant; --ci writes the CI workflow "
        ".github/workflows/aegis.yml, which init otherwise only prints."
    )

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--host",
            type=_host_option,
            default=None,
            metavar="HOST[,HOST]|auto",
            help=_host_help(),
        )
        parser.add_argument(
            "--rules",
            choices=list(RULE_PRESETS),
            default="standard",
            help="Starter rules: guidance seeded into .aegis/rules/personas/ (minimal 2, standard 5, full every "
                 "shipped one), which applies to no file until you set its target_paths; a new workspace also gets "
                 "one active rule, the no-eval invariant in .aegis/rules/invariants/ (bans eval and exec in "
                 "**/*.py). none-active seeds the standard guidance without it (default: standard)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Check and show every step without writing anything or running a host CLI",
        )
        parser.add_argument(
            "--yes",
            "-y",
            action="store_true",
            help="Skip the confirmation prompt",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Replace Aegis blocks in AGENTS.md/CLAUDE.md even if they were edited by hand",
        )
        parser.add_argument(
            "--pin",
            action="store_true",
            help="Pin the host registrations to this workspace (AEGIS_WORKSPACE)",
        )
        parser.add_argument(
            "--no-hooks",
            action="store_true",
            help="Skip installing the git pre-commit hook",
        )
        parser.add_argument(
            "--skills",
            action="store_true",
            help="Also copy the packaged skills into the hosts' project skills folders (.claude/skills, "
                 ".agents/skills), as aegis skills sync does",
        )
        parser.add_argument(
            "--ci",
            action="store_true",
            help="Also write .github/workflows/aegis.yml, a GitHub Actions workflow that runs aegis check on every "
                 "pull request (CI is the floor: git commit --no-verify skips the pre-commit hook). Without it, "
                 "init prints that workflow when no workflow runs aegis check",
        )
        parser.add_argument("--platform", action=RemovedOption, nargs="?", pointer="use aegis init --host")
        parser.add_argument("--mcp", action=RemovedOption,
                            pointer="use aegis init --host (no project MCP file is written)")
        parser.add_argument("--local", action=RemovedOption,
                            pointer="rules live in .aegis/rules; use aegis init")

    def execute(self, args: argparse.Namespace) -> int:
        return run_init(args)
