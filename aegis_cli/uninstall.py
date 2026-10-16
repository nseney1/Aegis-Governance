"""aegis uninstall — undo `aegis init` for this workspace on this machine.

Removes the git pre-commit hook block, the Aegis managed blocks (the AGENTS.md
bootstrap, the CLAUDE.md ``@AGENTS.md`` import), this workspace's entry in
``~/.aegis/workspaces.json`` and the hosts' ``aegis`` and legacy ``soma`` MCP
registrations. It never deletes ``.aegis/`` (rules, config, ledger): those are the
repository's. Hosts default to the ones this workspace was registered with; a host
another registered workspace still lists keeps its registration unless named with
``--host``. Every step is checked first: a refusal changes nothing.

A CLAUDE.md or AGENTS.md that is a link is never written through: it has nothing of
Aegis to remove unless the file it points to holds that file's Aegis block, which is
then refused. An AGENTS.md that CLAUDE.md links to is emptied, not deleted, so the link
does not dangle.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import List, Optional

from aegis_cli.base import CommandCategory, AegisCommand
from aegis_cli.init import (
    AGENTS_FILE,
    CLAUDE_FILE,
    CLAUDE_SHIM_ID,
    RemovedOption,
    Step,
    Report,
    report_partial,
    hook_refusal,
)
from aegis_cli.install_hosts import (
    REGISTRY_LABEL,
    InstallError,
    display_command,
    find_workspace,
    has_block_marker,
    parse_hosts,
    read_registry,
    remove_managed_block,
    unregister_host,
    unregister_workspace,
    workspace_hosts,
)

__all__ = ["run_uninstall", "UninstallCommand"]


def _host_ids(value: str) -> List[str]:
    try:
        hosts = parse_hosts(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None
    if hosts == "auto":
        raise argparse.ArgumentTypeError("uninstall names hosts; 'auto' is for aegis init")
    return list(hosts)


def _recorded_hosts(root: Path, home: Path, report: Report) -> List[str]:
    """The hosts init registered this workspace with: its registry entry, else config.json."""
    entry = find_workspace(read_registry(home), root)
    if entry is not None:
        return workspace_hosts(entry)
    from aegis_core.config import ConfigError, RepoConfig

    try:
        return [h for h in RepoConfig.load(root).hosts if h]
    except ConfigError as exc:
        report.warn(f"{exc}; no host taken from it")
        return []


def _links_to(link: Path, target: Path) -> bool:
    return link.is_symlink() and (os.path.normcase(os.path.realpath(link))
                                  == os.path.normcase(os.path.realpath(target)))


def _through_link(link: Path, block_id: str) -> Step:
    """A linked AGENTS.md or CLAUDE.md: init never wrote through it, so there is nothing
    to remove unless its target holds the block anyway, which is refused (not skipped)."""
    if has_block_marker(link, block_id):
        target = os.path.realpath(link)
        raise InstallError(f"{link}: is a symlink to {target}, which holds the Aegis {block_id!r} block; "
                           f"Aegis never writes through a link. Remove the block from {target} yourself, then re-run.")
    return Step(link.name, "absent", "a symlink with nothing of Aegis in it")


def _bootstrap(root: Path, force: bool, dry_run: bool) -> Step:
    from aegis_core.bootstrap import BOOTSTRAP_ID

    agents = root / AGENTS_FILE
    if agents.is_symlink():
        return _through_link(agents, BOOTSTRAP_ID)
    return Step(AGENTS_FILE, remove_managed_block(agents, BOOTSTRAP_ID, force=force, dry_run=dry_run,
                                                  delete_if_empty=not _links_to(root / CLAUDE_FILE, agents)))


def _claude_shim(root: Path, force: bool, dry_run: bool) -> Step:
    claude = root / CLAUDE_FILE
    if claude.is_symlink():
        return _through_link(claude, CLAUDE_SHIM_ID)
    return Step(CLAUDE_FILE, remove_managed_block(claude, CLAUDE_SHIM_ID, force=force, dry_run=dry_run))


def _steps(root: Path, home: Path, explicit: Optional[List[str]], force: bool, dry_run: bool,
           report: Report, actions: Optional[List[Step]] = None) -> List[Step]:
    """Every uninstall step; with ``dry_run`` only check and plan. Raises InstallError.

    Each finished step is appended to ``actions`` as it completes, so a run that fails
    part way still says what it had already removed.
    """
    from aegis_cli.hooks import uninstall_hook

    actions = [] if actions is None else actions
    hosts = explicit if explicit is not None else _recorded_hosts(root, home, report)

    refusal = hook_refusal(root, removing=True)
    if refusal:
        raise InstallError(f"pre-commit hook: {refusal}.")
    removed = uninstall_hook(project_root=root, dry_run=dry_run)
    actions.append(Step("pre-commit hook", "removed" if removed else "absent"))
    actions.append(_bootstrap(root, force, dry_run))
    actions.append(_claude_shim(root, force, dry_run))

    status, remaining = unregister_workspace(home, root, dry_run=dry_run)
    actions.append(Step(REGISTRY_LABEL, status))
    path_env = os.environ.get("PATH")
    for host in hosts:
        users = [e["root"] for e in remaining if host in workspace_hosts(e)]
        if users and explicit is None:
            actions.append(Step(host, "kept", f"still used by {len(users)} other registered workspace(s)"))
            continue
        if users:
            report.warn(f"{users[0]} still lists {host}; it loses Aegis too until you re-run aegis init there")
        done = unregister_host(host, home=home, path=path_env, dry_run=dry_run)
        actions.append(Step(host, done.result, done.detail, done.command))
    return actions


def run_uninstall(args: argparse.Namespace) -> int:
    """Uninstall flow. Returns the exit code (0 ok, 1 refused)."""
    json_mode = bool(getattr(args, "json", False))
    report = Report(json_mode, "aegis uninstall")
    ws = getattr(args, "ws", None)
    root = Path(ws.root if ws is not None else (getattr(args, "_project_root", None) or Path.cwd())).resolve()
    home = Path.home()
    dry_run = bool(getattr(args, "dry_run", False))
    force = bool(getattr(args, "force", False))
    explicit = getattr(args, "host", None)
    scope = {"workspace": str(root), "hosts": []}

    # Every step is checked first; a refusal stops uninstall before anything changes.
    report.muted = not dry_run
    try:
        plan = _steps(root, home, explicit, force, True, report)
    except InstallError as exc:
        report.muted = False
        report.error(str(exc))
        report.error("Nothing was changed.")
        report.finish("refused", scope, dry_run, [])
        return 1
    report.muted = False
    scope["hosts"] = [a.target for a in plan if a.target not in
                      ("pre-commit hook", AGENTS_FILE, CLAUDE_FILE, REGISTRY_LABEL)]
    actions = plan
    if not dry_run:
        actions = []
        try:
            _steps(root, home, explicit, force, False, report, actions)
        except (InstallError, OSError) as exc:
            # The check pass refuses everything it can see, so only a change between the
            # check and the write (a file edited meanwhile, a disk error) gets here.
            report_partial(report, exc, actions, "changed")
            report.finish("failed", scope, False, actions)
            return 1

    for action in actions:
        result = "would run" if action.result == "would_run" else action.result
        if action.result == "manual":
            report.say(f"  👉 {action.target}: {action.detail}; run it yourself:")
            report.say(f"       {display_command(action.command or [])}")
        elif action.command:
            report.say(f"  ✅ {action.target}: {result} ({display_command(action.command)})")
        else:
            detail = f" ({action.detail})" if action.detail else ""
            report.say(f"  ✅ {action.target}: {result}{detail}")
    report.say("  .aegis/ was kept (rules, config and ledger belong to the repository).")
    if dry_run:
        report.say("  Dry run: nothing was changed.")
    report.finish("ok", scope, dry_run, actions)
    return 0


class UninstallCommand(AegisCommand):
    """Command to uninstall Aegis from this workspace and this machine's hosts."""

    name = "uninstall"
    category = CommandCategory.SETUP
    help = "Remove Aegis from this workspace's hosts, AGENTS.md/CLAUDE.md and git hook (keeps .aegis/)"
    description = (
        "Remove the git pre-commit hook block, the Aegis blocks in AGENTS.md and CLAUDE.md, this "
        "workspace's entry in ~/.aegis/workspaces.json and the Aegis MCP registration "
        "(including the v3 name) of the hosts it was registered with. A host that another registered workspace "
        "still lists keeps its registration unless named with --host. Never deletes .aegis/."
    )

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--host",
            type=_host_ids,
            default=None,
            metavar="HOST[,HOST]",
            help="Unregister these hosts even if another workspace uses them "
                 "(default: the hosts this workspace was registered with)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be removed without changing anything",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Also remove Aegis blocks that were edited by hand",
        )
        parser.add_argument("--platform", "-p", action=RemovedOption, nargs="?",
                            pointer="use aegis uninstall --host")
        parser.add_argument("--local", action=RemovedOption, pointer="use aegis uninstall")
        parser.add_argument("--purge", action=RemovedOption,
                            pointer="aegis uninstall never deletes .aegis/; remove it yourself (git rm -r .aegis)")

    def execute(self, args: argparse.Namespace) -> int:
        return run_uninstall(args)
