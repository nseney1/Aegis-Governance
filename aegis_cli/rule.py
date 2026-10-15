"""aegis rule — Unified rule lifecycle management.

Subcommands:
  aegis rule list                 List active workspace rules and fitness scores
  aegis rule create               Create a rule (--hypothesis, optional --body-file)
  aegis rule promote <rule_id>    Promote a rule up lifecycle tiers
  aegis rule demote <rule_id>     Demote a rule down lifecycle tiers
  aegis rule archive [rule_id]    Archive decayed, extinct, or quarantined rules
  aegis rule clean                Prune leaked or redundant rules
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, List, Optional

from aegis_cli.base import CommandCategory, AegisCommand
from aegis_core.errors import WorkspaceNotFoundError
from aegis_core.lifecycle.creation import MAX_RULE_BODY_BYTES, validate_rule_body
from aegis_core.taxonomy import RULE_TYPE_DIRS
from aegis_core.workspace import Workspace
from aegis_core.workspace.discovery import _is_workspace_dir
from aegis_core.workspace.layout import WorkspaceLayout
from aegis_core.lifecycle import (
    promote_cell, demote_cell, prune_cells, find_cell_file,
    evaluate_promotions, evaluate_demotions, evaluate_cell_tiers,
)
from aegis_core.lifecycle.cleanse import (
    AEGIS_INTERNAL_PURGE_STEMS, UNIVERSAL_TENETS, _clean_claude_sections,
    clean_global_rules, collect_workspace_rules, format_cleanse_report, is_purge_candidate,
)

__all__ = [
    "run_rule", "RuleCommand", "run_promote", "run_demote", "_force_promote",
    "_force_demote", "clean_global_rules", "run_clean_rules", "UNIVERSAL_TENETS",
    "AEGIS_INTERNAL_PURGE_STEMS", "is_purge_candidate", "_clean_claude_sections",
]


def run_rule(args: argparse.Namespace) -> int:
    """Entrypoint for aegis rule subcommands."""
    action = getattr(args, "rule_action", None) or "list"
    handlers = {
        "list": _run_list, "create": _run_create, "promote": _run_promote,
        "demote": _run_demote, "archive": _run_archive, "clean": _run_clean,
    }
    if action not in handlers:
        print(f"Unknown rule subcommand: {action}", file=sys.stderr)
        return 1
    try:
        return handlers[action](args)
    except WorkspaceNotFoundError as exc:
        return _emit_error(args, str(exc))


def _emit_error(args: argparse.Namespace, msg: str) -> int:
    if getattr(args, "json", False):
        print(json.dumps({"status": "error", "error": msg}))
    else:
        print(f"Error: {msg}", file=sys.stderr)
    return 1


class _WorkspaceArg(argparse.Action):
    """Keep the operator's ``--workspace`` verbatim.

    ``cli.main`` replaces ``args.workspace`` with its own walked-up resolution
    before dispatch, which is how ``rule create`` once landed in ``$HOME``.
    """

    def __call__(self, parser, namespace, values, option_string=None):  # type: ignore[override]
        setattr(namespace, self.dest, values)
        setattr(namespace, "_rule_workspace_arg", values)


def _git_toplevel(start: Path) -> Path | None:
    for d in (start, *start.parents):
        if (d / ".git").exists():
            return d
    return None


def _home() -> Path | None:
    try:
        return Path.home().resolve()
    except (RuntimeError, KeyError, OSError):
        return None


def _not_a_workspace(directory: Path) -> WorkspaceNotFoundError:
    return WorkspaceNotFoundError(f"not an Aegis workspace (no .aegis/ in {directory}); run aegis init")


def _walk_up_to_workspace(start: Path) -> Path:
    """Discovery's start-path walk without its AEGIS_WORKSPACE/AEGIS_ROOT override:
    an explicit --workspace beats the environment, as it already does for create."""
    for d in (start, *start.parents):
        if _is_workspace_dir(str(d)):
            return d
    return start


def _resolve_workspace_root(args: argparse.Namespace, require_aegis: bool = False) -> Path:
    """Resolve the rule workspace. Never ``$HOME``, never above the git toplevel (H8).

    An explicit ``--workspace DIR`` is the start point, whichever position it
    was given in (``_workspace_arg`` is the raw global flag, when ``cli.main``
    keeps it). ``rule create`` (``require_aegis``) uses exactly DIR; the other
    actions walk up from DIR like cwd discovery does. Without DIR the root comes
    from ``cli.main``'s cwd discovery. Either way the root is then bounded by
    the start point's git toplevel, since discovery itself walks up without bounds.
    """
    explicit = getattr(args, "_rule_workspace_arg", None) or getattr(args, "_workspace_arg", None)
    if explicit:
        start = Path(explicit).expanduser().resolve()
        root = start if require_aegis else _walk_up_to_workspace(start)
    else:
        ws_obj = getattr(args, "ws", None)
        raw = getattr(args, "workspace", None) or getattr(args, "_project_root", None) or getattr(args, "_root", None)
        if ws_obj is None and raw:
            root = start = Path(raw).resolve()
        else:
            root = Path(ws_obj.root if ws_obj is not None else Workspace.resolve().root).resolve()
            start = Path.cwd().resolve()

    home = _home()
    if home is not None and root == home:
        if start == home:
            raise WorkspaceNotFoundError(
                f"not an Aegis workspace ({home} is the home directory; ~/.aegis is the user rule layer); "
                "run aegis init in a project"
            )
        raise _not_a_workspace(start)

    pinned = any(
        os.environ.get(var) and Path(os.environ[var]).resolve() == root
        for var in ("AEGIS_WORKSPACE", "AEGIS_ROOT")
    )
    if not pinned and root != start and root in start.parents:
        top = _git_toplevel(start)
        if top is not None and root in top.parents:
            raise _not_a_workspace(start)

    if require_aegis and not (root / ".aegis").is_dir():
        raise _not_a_workspace(root)
    return root


def _run_list(args: argparse.Namespace) -> int:
    """List active rules and fitness metrics."""
    root = _resolve_workspace_root(args)
    rules_dir = WorkspaceLayout(root).rules_dir
    if not rules_dir.is_dir():
        print(json.dumps([]) if getattr(args, "json", False) else "No rules directory found.")
        return 0

    rules = collect_workspace_rules(
        root, rules_dir, getattr(args, "type", None), getattr(args, "min_fitness", None)
    )
    if getattr(args, "json", False):
        print(json.dumps(rules, indent=2))
        return 0
    if not rules:
        print("No matching rules found.")
        return 0

    from aegis_cli.ui.table import Table
    from aegis_cli.ui.theme import OutputContext

    existing_ui = getattr(args, "ui", None)
    ui = existing_ui if isinstance(existing_ui, OutputContext) else OutputContext.from_env_and_args(args)
    tbl = Table(ctx=ui)
    for col in ("Rule ID", "Type", "Enforcement"):
        tbl.add_column(col, no_wrap=True)
    tbl.add_column("Fitness", justify="right", no_wrap=True)
    for r in rules:
        score_str = ui.color_fitness(float(r["score"])) if isinstance(r.get("score"), (int, float)) else "—"
        tbl.add_row(str(r["id"]), ui.color_rule_type(str(r["type"])), str(r["enforcement"]), score_str)

    print(f"Active Rules ({len(rules)} found):")
    for line in tbl.render(ui).splitlines():
        print(f"  {line}")
    return 0


def _emit_status(use_json: bool, payload: dict[str, Any], text: str, rc: int) -> int:
    print(json.dumps(payload) if use_json else text)
    return rc


def _resolve_rule_id(args: argparse.Namespace) -> str | None:
    return getattr(args, "rule", None) or getattr(args, "rule_id", None) or getattr(args, "cell", None) or getattr(args, "cell_id", None)


def _run_promote(args: argparse.Namespace) -> int:
    """Promote a rule up lifecycle tiers or evaluate promotion candidates."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    root = _resolve_workspace_root(args)
    rule_id = _resolve_rule_id(args)
    dry_run = getattr(args, "dry_run", False)
    use_json = getattr(args, "json", False)

    if getattr(args, "tier_check", False):
        res = evaluate_cell_tiers(root, execute=not dry_run)
        if use_json:
            print(json.dumps(res, indent=2))
        else:
            changes = res.get("changes", [])
            print(f"  Evaluated {res.get('evaluated', 0)} rules across enforcement tiers.")
            if not changes:
                print("  No tier changes required.")
            for c in changes:
                print(f"    {c['cell']}: {c['old_tier']} → {c['new_tier']} ({c['reason']})")
        return 0

    if not rule_id:
        candidates = evaluate_promotions(str(root))
        if use_json:
            print(json.dumps({"candidates": candidates}, indent=2, default=str))
        elif not candidates:
            print("  No promotion candidates found.")
        else:
            print(f"  Promotion Candidates ({len(candidates)}):\n")
            for c in candidates:
                print(f"    {c['cell_id']}: {c['from_type']} → {c['to_type']}\n      triggers={c['triggers']} tp_rate={c['tp_rate']:.0%} age={c['age_days']}d")
            print()
        return 0

    res = promote_cell(root, rule_id, force=True, dry_run=dry_run)
    status = res.get("status")
    if status == "not_found":
        msg = f"Rule '{rule_id}' not found in workspace"
        return _emit_status(use_json, {"error": msg}, f"  ❌ {msg}", 1)
    if status == "already_terminal":
        msg = f"Rule '{rule_id}' is already at terminal tier ('{res.get('current_type')}')"
        return _emit_status(use_json, {"info": msg}, f"  ℹ️  {msg}", 0)
    if status not in ("promoted", "dry_run"):
        msg = res.get("message") or f"Promotion of '{rule_id}' failed ({status})"
        return _emit_status(use_json, {"error": msg}, f"  ❌ {msg}", 1)

    from_t, to_t = res.get("from_type"), res.get("to_type")
    if dry_run:
        return _emit_status(use_json, {"action": "promote", "rule_id": rule_id, "from": from_t, "to": to_t, "dry_run": True}, f"  🔍 Would promote: {rule_id}: {from_t} → {to_t}", 0)
    return _emit_status(use_json, {"action": "promote", "rule_id": rule_id, "from": from_t, "to": to_t, "success": True}, f"  ✅ Promoted: {rule_id}: {from_t} → {to_t}", 0)


def _run_demote(args: argparse.Namespace) -> int:
    """Demote a rule down lifecycle tiers or evaluate demotion candidates."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    root = _resolve_workspace_root(args)
    rule_id = _resolve_rule_id(args)
    dry_run = getattr(args, "dry_run", False)
    use_json = getattr(args, "json", False)

    if not rule_id:
        candidates = evaluate_demotions(str(root))
        if use_json:
            print(json.dumps({"candidates": candidates}, indent=2, default=str))
        elif not candidates:
            print("  No demotion candidates found.")
        else:
            print(f"  ⚠️  Demotion Candidates ({len(candidates)}):\n")
            for c in candidates:
                detail = f"triggers={c['triggers']} fp_rate={c.get('fp_rate', 0):.0%}" if c.get("triggers", 0) > 0 else f"dormant for {c.get('age_days', 0)}d"
                print(f"    {c['cell_id']}: {c['from_type']} → {c['to_type']} ({c['reason']})\n      {detail}")
            print()
        return 0

    try:
        res = demote_cell(root, rule_id, dry_run=dry_run)
    except ValueError:
        msg = f"Cannot demote core rule: {rule_id}."
        return _emit_status(use_json, {"error": msg}, f"  ❌ {msg}", 1)
    except Exception as exc:
        msg = f"Demotion error: {exc}"
        return _emit_status(use_json, {"error": msg}, f"  ❌ {msg}", 1)

    status = res.get("status")
    if status == "not_found":
        msg = f"Rule '{rule_id}' not found in workspace"
        return _emit_status(use_json, {"error": msg}, f"  ❌ {msg}", 1)
    if status == "already_base":
        msg = f"Rule '{rule_id}' is already at base tier ('{res.get('current_type')}')"
        return _emit_status(use_json, {"error": msg}, f"  ⚠️  {msg}", 1)
    if status not in ("demoted", "dry_run"):
        msg = res.get("message") or f"Demotion of '{rule_id}' failed ({status})"
        return _emit_status(use_json, {"error": msg}, f"  ❌ {msg}", 1)

    from_t, to_t = res.get("from_type"), res.get("to_type")
    if dry_run:
        return _emit_status(use_json, {"action": "demote", "rule_id": rule_id, "from": from_t, "to": to_t, "dry_run": True}, f"  🔍 Would demote: {rule_id}: {from_t} → {to_t}", 0)
    return _emit_status(use_json, {"action": "demote", "rule_id": rule_id, "from": from_t, "to": to_t, "success": True}, f"  ✅ Demoted: {rule_id}: {from_t} → {to_t}", 0)


def _force_promote(project_root: Path, cell_id: str, dry_run: bool = False, use_json: bool = False) -> int:
    return _run_promote(argparse.Namespace(_project_root=project_root, rule_id=cell_id, dry_run=dry_run, json=use_json, force=True))


def _force_demote(project_root: Path, cell_id: str, dry_run: bool = False, use_json: bool = False) -> int:
    return _run_demote(argparse.Namespace(_project_root=project_root, rule_id=cell_id, dry_run=dry_run, json=use_json, force=True))


run_promote = _run_promote
run_demote = _run_demote


def _run_archive(args: argparse.Namespace) -> int:
    """Archive extinct or decayed rules."""
    root = _resolve_workspace_root(args)
    execute = not getattr(args, "dry_run", False) and getattr(args, "apply", True)
    return prune_cells(workspace=root, execute=execute)


def _run_clean(args: argparse.Namespace) -> int:
    """Clean redundant or leaked global rules."""
    dry_run = getattr(args, "dry_run", False)
    apply = getattr(args, "apply", False) or getattr(args, "force", False)
    force = apply and not dry_run
    q_dir = getattr(args, "quarantine_dir", "") or None
    res = clean_global_rules(dry_run=not force, force=force, quarantine_dir=q_dir)
    print(format_cleanse_report(res))
    return 0


run_clean_rules = _run_clean


def _split_csv_arg(raw: Any) -> list[str] | None:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip():
        return [item.strip() for item in raw.split(",") if item.strip()]
    return None


class _BodyFileError(Exception):
    pass


def _read_body_file(raw: str) -> str:
    """Read a rule body from PATH or stdin (``-``), never more than the size cap + 1 byte."""
    label = "<stdin>" if raw == "-" else raw
    limit = MAX_RULE_BODY_BYTES + 1
    try:
        if raw == "-":
            stream = getattr(sys.stdin, "buffer", None)
            data = stream.read(limit) if stream is not None else sys.stdin.read(limit).encode("utf-8")
        else:
            with open(raw, "rb") as fh:
                data = fh.read(limit)
    except OSError as exc:
        raise _BodyFileError(f"--body-file {label}: cannot read file ({exc.strerror or exc})") from exc
    if len(data) > MAX_RULE_BODY_BYTES:
        raise _BodyFileError(f"--body-file {label}: rule body exceeds 64 KiB ({MAX_RULE_BODY_BYTES} bytes)")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _BodyFileError(f"--body-file {label}: rule body is not valid UTF-8") from exc
    try:
        return validate_rule_body(text)
    except ValueError as exc:
        raise _BodyFileError(f"--body-file {label}: {exc}") from exc


def _run_create(args: argparse.Namespace) -> int:
    """Create a new governance rule in the workspace."""
    from aegis_core.lifecycle.creation import create_cell
    cell_type = getattr(args, "type", None) or getattr(args, "cell_type", None) or "trap"
    hypothesis = getattr(args, "hypothesis", "")
    if not hypothesis:
        print("Error: --hypothesis is required to create a rule.", file=sys.stderr)
        return 1
    root = _resolve_workspace_root(args, require_aegis=True)
    body = None
    body_file = getattr(args, "body_file", None)
    if body_file is not None:
        try:
            body = _read_body_file(body_file)
        except _BodyFileError as exc:
            return _emit_error(args, str(exc))
    rule_id = getattr(args, "id", None) or getattr(args, "cell_id", None) or None
    try:
        created = create_cell(
            cell_type=cell_type, hypothesis=hypothesis, prediction=getattr(args, "prediction", "") or "",
            falsification=getattr(args, "falsification", "") or "", weight=float(getattr(args, "weight", 1.0) or 1.0),
            tags=_split_csv_arg(getattr(args, "tags", None)), expiry_sessions=getattr(args, "expiry_sessions", 15),
            expiry_days=getattr(args, "expiry_days", 60), minimum_mode=getattr(args, "minimum_mode", "") or "",
            id_override=rule_id, effector=bool(getattr(args, "effector", False)), memory=bool(getattr(args, "memory", False)),
            target_paths=_split_csv_arg(getattr(args, "target_paths", None)), domain=getattr(args, "domain", "correctness") or "correctness",
            workspace=root, enforcement=getattr(args, "enforcement", None), body=body,
        )
    except Exception as exc:
        return _emit_error(args, str(exc))
    print(json.dumps({"status": "created", "path": str(created), "id": created.stem}, indent=2) if getattr(args, "json", False) else f"Created rule: {created}")
    return 0


class RuleCommand(AegisCommand):
    """Unified rule lifecycle management."""

    name = "rule"
    aliases = ()
    category = CommandCategory.LIFECYCLE
    help = "Manage rule lifecycle (list, create, promote, demote, archive, clean)"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        common = argparse.ArgumentParser(add_help=False)
        for flag in ("--plain", "--no-emoji", "--json"):
            common.add_argument(flag, action="store_true", default=argparse.SUPPRESS)
        common.add_argument("--format", choices=["text", "json", "mermaid"], default=argparse.SUPPRESS)
        common.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS)
        common.add_argument("-q", "--quiet", action="store_true", default=argparse.SUPPRESS)
        common.add_argument("--workspace", type=str, default=argparse.SUPPRESS, action=_WorkspaceArg)
        sub = parser.add_subparsers(dest="rule_action", metavar="ACTION")

        p_list = sub.add_parser("list", parents=[common], help="List active rules and fitness metrics")
        p_list.add_argument("--type", choices=list(RULE_TYPE_DIRS.keys()), help="Filter by rule type")
        p_list.add_argument("--min-fitness", type=float, help="Filter by minimum fitness score")

        p_create = sub.add_parser("create", parents=[common], help="Create a new governance rule")
        p_create.add_argument("-t", "--type", dest="type", default="trap", help="Rule type (trap, invariant, boundary, persona, contract)")
        p_create.add_argument("--hypothesis", default="", help="Testable rule hypothesis")
        p_create.add_argument("-p", "--prediction", default="", help="Expected outcome when hypothesis holds")
        p_create.add_argument("-f", "--falsification", default="", help="Criteria that falsify the rule")
        p_create.add_argument("-d", "--domain", default="correctness", help="Governance domain")
        p_create.add_argument("-e", "--enforcement", default=None, help="Enforcement tier (gate, advisory)")
        p_create.add_argument("-n", "--name", "--id", dest="id", default=None, help="Explicit rule ID stem")
        p_create.add_argument("--target-paths", dest="target_paths", default="", help="Comma-separated target path globs")
        p_create.add_argument("--tags", default="", help="Comma-separated tags")
        p_create.add_argument("-w", "--weight", type=float, default=1.0, help="Impact weight")
        p_create.add_argument("--expiry-sessions", dest="expiry_sessions", type=int, default=15, help="Session expiry")
        p_create.add_argument("--expiry-days", dest="expiry_days", type=int, default=60, help="Day expiry")
        p_create.add_argument("--minimum-mode", dest="minimum_mode", default="", help="Minimum review mode")
        p_create.add_argument("--effector", action="store_true", default=False, help="Create as effector cell")
        p_create.add_argument("--memory", action="store_true", default=False, help="Create as memory cell")
        p_create.add_argument("--body-file", dest="body_file", default=None, metavar="PATH",
                              help="Rule body (markdown after the frontmatter) from PATH, or '-' for stdin; max 64 KiB")

        p_prom = sub.add_parser("promote", parents=[common], help="Promote a rule up lifecycle tiers")
        p_prom.add_argument("rule_id", nargs="?", default=None, help="Rule identifier to promote")
        p_prom.add_argument("--rule", default=None, help="Rule identifier to promote")
        p_prom.add_argument("--reason", help="Audit explanation for promotion")
        p_prom.add_argument("--force", action="store_true", help="Bypass evidence threshold checks")
        p_prom.add_argument("--tier-check", action="store_true", help="Evaluate enforcement tier transitions")
        p_prom.add_argument("--dry-run", action="store_true", help="Preview promotion without moving files")

        p_dem = sub.add_parser("demote", parents=[common], help="Demote a rule down lifecycle tiers")
        p_dem.add_argument("rule_id", nargs="?", default=None, help="Rule identifier to demote")
        p_dem.add_argument("--rule", default=None, help="Rule identifier to demote")
        p_dem.add_argument("--reason", help="Audit explanation for demotion")
        p_dem.add_argument("--force", action="store_true", help="Force demotion")
        p_dem.add_argument("--dry-run", action="store_true", help="Preview demotion without moving files")

        p_arch = sub.add_parser("archive", parents=[common], help="Archive decayed or extinct rules")
        p_arch.add_argument("rule_id", nargs="?", help="Specific rule ID to archive")
        p_arch.add_argument("--dry-run", action="store_true", help="Preview rules to archive")
        p_arch.add_argument("--apply", action="store_true", default=True, help="Apply archive movements")

        p_clean = sub.add_parser("clean", parents=[common], help="Clean redundant or leaked rules")
        p_clean.add_argument("--dry-run", action="store_true", help="Show purge candidates without deleting")
        p_clean.add_argument("--apply", action="store_true", help="Apply cleanup deletions")

    def execute(self, args: argparse.Namespace) -> int:
        return run_rule(args)


if __name__ == "__main__":  # pragma: no cover
    from aegis_cli.cli import main
    sys.exit(main(["rule"] + sys.argv[1:]))


