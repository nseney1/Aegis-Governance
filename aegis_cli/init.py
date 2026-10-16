"""aegis init — set up governance for this repository and register it with your agent hosts.

The repository plane (committed): ``.aegis/config.json`` (``hosts``), ``.aegis/.gitignore``,
the starter rules under ``.aegis/rules/personas/``, the Aegis bootstrap block in
``AGENTS.md`` and, only when a ``CLAUDE.md`` already exists, an ``@AGENTS.md`` block in it
(host-matrix spec §3.2, §3.4). The user plane (this machine): the ``aegis`` MCP
registration of each selected host and the workspace entry in ``~/.aegis/workspaces.json``
(see :mod:`aegis_cli.install_hosts` for its schema). Plus the git pre-commit hook.

Host detection only proposes: hosts are registered only when named with ``--host``
(``--host auto`` takes the detected ones). Every step is checked before anything is
written, so a file Aegis cannot change safely stops init with nothing written.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.resources
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from aegis_cli.base import CommandCategory, AegisCommand
from aegis_cli.install_hosts import (
    REGISTRY_LABEL,
    InstallError,
    ordered_hosts,
    detect_hosts,
    display_command,
    is_denied_root,
    mcp_command,
    parse_hosts,
    register_host,
    register_workspace,
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
    "AGENTS_FILE",
    "CLAUDE_FILE",
    "CLAUDE_SHIM_ID",
    "CLAUDE_SHIM_TEXT",
    "InitCommand",
    "RULE_PRESETS",
    "RemovedOption",
    "Report",
    "Step",
    "install_rules",
    "packaged_rules",
    "preset_rules",
    "run_init",
    "seed_workspace_rules",
]

CONFIG_LABEL = f"{AEGIS_DIRNAME}/config.json"
GITIGNORE_LABEL = f"{AEGIS_DIRNAME}/.gitignore"
AGENTS_FILE = "AGENTS.md"
CLAUDE_FILE = "CLAUDE.md"
CLAUDE_SHIM_ID = "agents-import"
CLAUDE_SHIM_TEXT = "@AGENTS.md\n"

# ── Starter rules: one locator over the packaged rules/ (defense #20, D16) ───

RULE_PRESETS: Dict[str, Optional[Tuple[str, ...]]] = {
    "minimal": ("providence", "destructive-ops"),
    "standard": ("providence", "destructive-ops", "testing", "cost-optimization", "git-workflow"),
    "full": None,  # every shipped rule
}
# The shipped rules are process guidance (what to do, not where), so they are seeded as
# persona rules. They name no target_paths: `aegis status` lists them as untargeted until
# the repository decides which files each applies to.
SEED_TYPE_DIR = RULE_TYPES[RuleType.PERSONA].directory
_NOT_RULES = {"META.md", "README.md"}


def packaged_rules() -> Dict[str, Path]:
    """Every rule shipped in the ``rules`` package (``rules/*.md``, ``rules/.oracles/*.md``) by id."""
    base = Path(str(importlib.resources.files("rules")))
    found: Dict[str, Path] = {}
    for directory in (base, base / ".oracles"):
        if directory.is_dir():
            for path in sorted(directory.glob("*.md")):
                if path.is_file() and path.name not in _NOT_RULES:
                    found.setdefault(path.stem, path)
    return found


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


def install_rules(rules_dir: Path, preset: str = "standard", dry_run: bool = False, force: bool = False,
                  skip: Sequence[str] = ()) -> List[str]:
    """Copy the preset's packaged rules into ``rules_dir`` (flat); return the ids now there.

    An existing file is kept unless ``force``; a symlinked destination is never written
    through; ids in ``skip`` are left out.
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
        if not dry_run:
            atomic_write_bytes(dest, source.read_bytes())
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
    seeded = install_rules(target, preset=preset, dry_run=dry_run, skip=present)
    return seeded, present


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
            print(f"  ⚠️  {line}", file=sys.stderr)

    def error(self, line: str) -> None:
        self.errors.append(line)
        if not self.json_mode:
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


def _steps(ctx: _Context, dry_run: bool) -> List[Step]:
    """Run every init step; with ``dry_run`` only check and plan. Raises InstallError."""
    from aegis_core.ast.detect import detect_project_languages, provision_ast_driver_slots
    from aegis_core.bootstrap import BOOTSTRAP_ID, bootstrap_text
    from aegis_core.errors import PathTraversalError, WorkspaceBareRepoError
    from aegis_core.workspace.scaffold import ensure_runtime_gitignore

    report, root = ctx.report, ctx.root
    actions: List[Step] = []
    try:
        ctx.ws.scaffold(minimal=(ctx.preset == "minimal"), dry_run=dry_run)
    except WorkspaceBareRepoError as exc:
        raise InstallError(str(exc)) from exc
    actions.append(_config_hosts(root, ctx.selected, dry_run, report))

    gitignore = ensure_runtime_gitignore(ctx.ws.aegis_dir, dry_run=dry_run)
    if gitignore == "symlink":
        report.warn(".aegis/.gitignore is a symlink; not modified. Add Aegis runtime state to it yourself.")
    actions.append(Step(GITIGNORE_LABEL, gitignore))

    try:
        seeded, present = seed_workspace_rules(root, ctx.preset, dry_run=dry_run)
    except ValueError as exc:
        raise InstallError(str(exc)) from exc
    actions.append(Step(f"{RULES_RELDIR}/{SEED_TYPE_DIR}", "seeded" if seeded else "unchanged",
                           f"preset {ctx.preset}: {', '.join(seeded) or 'nothing new'}",
                           names=seeded, kept=present))

    languages = detect_project_languages(root)
    try:
        slots, _written = provision_ast_driver_slots(root, languages, dry_run=dry_run)
    except PathTraversalError as exc:
        raise InstallError(str(exc)) from exc
    drivers = sorted(k[len("ast_driver_"):] for k in slots if k.startswith("ast_driver_"))
    actions.append(Step("ast drivers", "configured" if drivers else "none", ", ".join(drivers)))

    actions.append(Step(AGENTS_FILE, write_managed_block(
        root / AGENTS_FILE, BOOTSTRAP_ID, bootstrap_text(), force=ctx.force, dry_run=dry_run)))
    actions.append(Step(CLAUDE_FILE, write_managed_block(
        root / CLAUDE_FILE, CLAUDE_SHIM_ID, CLAUDE_SHIM_TEXT, force=ctx.force, create=False, dry_run=dry_run)))

    if not ctx.no_hooks:
        hooked = install_hook(root, dry_run=dry_run)
        actions.append(Step("pre-commit hook", "installed" if hooked else "skipped (not a git repository)"))

    actions.append(Step(REGISTRY_LABEL, register_workspace(ctx.home, root, ctx.selected, dry_run=dry_run)))
    for host in ctx.selected:
        done = register_host(host, home=ctx.home, command=ctx.command, pin=ctx.pin, path=ctx.path_env,
                             dry_run=dry_run)
        actions.append(Step(host, done.result, done.detail, done.command))
    return actions


_ICONS = {"failed": "❌", "manual": "👉", "kept": "⚠️ "}


def _print_actions(report: Report, actions: Sequence[Step], dry_run: bool, preset: str) -> None:
    for action in actions:
        if action.target.startswith(RULES_RELDIR + "/"):
            report.say(f"  Starter rules (preset={preset}) in {action.target}/:")
            for name in action.names:
                report.say(f"    {'[DRY-RUN]' if dry_run else '✅'} {name}")
            for name in action.kept:
                report.say(f"    [SKIP] {name} (a rule with this id exists)")
            continue
        if action.result == "absent":
            continue  # CLAUDE.md: Aegis never creates one
        if action.target == "ast drivers":
            verb = "Would configure" if dry_run else "Configured"
            for ext in action.detail.split(", ") if action.detail else []:
                report.say(f"    ✨ {verb} AST driver (.{ext}): packaged {ext} driver")
            continue
        if action.target == "pre-commit hook":
            continue  # printed by _report_hook
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

    detected = detect_hosts(home, path_env)
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
        report.say(f"  Hosts: {', '.join(selected)}")
    else:
        report.say("  Hosts: none selected (only the repository is set up)")
        if detected and host_arg is None:
            report.say(f"  Detected on this machine: {', '.join(detected)}. To register Aegis with them:")
            report.say(f"       aegis init --host {','.join(detected)}")
    report.say()

    ctx = _Context(ws=ws, root=root, home=home, selected=selected, preset=preset,
                   force=bool(getattr(args, "force", False)), no_hooks=_no_hooks(args),
                   command=mcp_command(path_env), pin=str(root) if getattr(args, "pin", False) else None,
                   path_env=path_env, report=report)

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
        except (EOFError, KeyboardInterrupt):
            answer = "n"
            report.say()
        if answer and answer not in ("y", "yes"):
            report.say("  Aborted.")
            report.finish("aborted", scope, False, plan)
            return 0
        report.say()

    try:
        actions = _steps(ctx, dry_run=False)
    except InstallError as exc:
        # Only a file that changed between the check and the write gets here.
        report.error(str(exc))
        report.finish("failed", scope, False, [])
        return 1
    _print_actions(report, actions, False, preset)
    _report_hook(report, root, actions)

    failed = [a for a in actions if a.result == "failed"]
    for action in failed:
        report.error(f"{action.target}: registration failed ({action.detail}). Run it yourself: "
                     f"{display_command(action.command or [])}")
    report.say()
    if failed:
        report.say("  Done, with errors (see above).")
    elif ctx.selected:
        report.say("  Done! Your next agent session will be governed.")
    else:
        report.say("  Done! No agent host was registered; to add one: aegis init --host HOST[,HOST]")
    report.say()
    report.say("  After a session, run: aegis status")
    report.say()
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


def _no_hooks(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "no_hooks", False)) or not getattr(args, "hooks", True)


def _report_hook(report: Report, root: Path, actions: Sequence[Step]) -> None:
    if not any(a.target == "pre-commit hook" and a.result == "installed" for a in actions):
        return
    st = hook_status(root)
    report.say(f"    🪝 Pre-commit hook installed ({st['hook_file']})")
    if st["hooks_dir_in_work_tree"]:
        print(work_tree_warning(st["hook_file"]), file=sys.stderr)


# ── Doctor seam ──────────────────────────────────────────────────────────────
# `aegis doctor` (aegis_cli/doctor.py, lane c3) still checks the v3 platform rules
# directory through these two names. They are kept, unexported, only until the
# host-matrix doctor replaces _check_platform/_check_rules; delete them with it.

_V3_MARKERS = (
    ("gemini", (".gemini",), ()),
    ("claude", (".claude",), ("CLAUDE.md",)),
    ("cursor", (".cursor",), (".cursorrules",)),
    ("copilot", (".github/copilot",), (".github/copilot-instructions.md",)),
    ("kiro", (".kiro",), ()),
)


def detect_platform(project_root: Path) -> str:
    """The first v3 platform whose marker is under ``project_root``, or ``unknown``."""
    root = Path(project_root)
    for name, dirs, files in _V3_MARKERS:
        if any((root / d).is_dir() for d in dirs) or any((root / f).is_file() for f in files):
            return name
    return "unknown"


def get_rules_dir(platform: str, home: Optional[Path] = None, project_root: Optional[Path] = None) -> Path:
    """The v3 global rules directory of ``platform``."""
    home = Path(home) if home is not None else Path.home()
    dirs = {
        "gemini": home / ".gemini" / "config" / "rules",
        "claude": home / ".claude",
        "cursor": home / ".cursor" / "rules",
        "copilot": Path(project_root or Path.cwd()) / ".github" / "copilot",
        "kiro": home / ".kiro" / "steering",
    }
    if platform not in dirs:
        raise ValueError(f"Unsupported platform: '{platform}'. Supported: {', '.join(sorted(dirs))}")
    return dirs[platform]


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
        "--scope user; antigravity: ~/.gemini/config/mcp_config.json)."
    )

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--host",
            type=_host_option,
            default=None,
            metavar="HOST[,HOST]|auto",
            help="Register the Aegis MCP server with these hosts (codex-cli, claude-code, antigravity), "
                 "or 'auto' for the ones detected on this machine. Without it, detected hosts are only listed.",
        )
        parser.add_argument(
            "--rules",
            choices=list(RULE_PRESETS),
            default="standard",
            help="Starter rules to seed into .aegis/rules/personas/ (default: standard)",
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
        parser.add_argument("--platform", action=RemovedOption, nargs="?", pointer="use aegis init --host")
        parser.add_argument("--mcp", action=RemovedOption,
                            pointer="use aegis init --host (no project MCP file is written)")
        parser.add_argument("--local", action=RemovedOption,
                            pointer="rules live in .aegis/rules; use aegis init")

    def execute(self, args: argparse.Namespace) -> int:
        return run_init(args)
