"""aegis check — the verification gate for AI coding agent changes.

  aegis check [FILES...]              Layer 1: workspace checkpoint plus call_graph,
                                      import_guard and forbid_ast on FILES (default: files
                                      changed against HEAD, staged, or the branch base)
  aegis check --strict                also fail on checkpoint warnings
  aegis check --hook                  git pre-commit mode: Layer 1 only, never a model call
  aegis check --full --plan TEXT      add Layer 2: adversarial review by --llm-cmd
  aegis check --lane LANE [--base REF] [--paths GLOB...] [--base-policy]
                                      post-lane gate: containment and Python test
                                      integrity of the lane's commits (aegis_core.lane_gate)
  aegis check [--base REF]            with a baseline (.aegis/baseline.json), fail only on
                                      findings it does not hold; --base reads it from REF
  aegis check --write-baseline        record the current findings (aegis_core.baseline)
  aegis check --prune-baseline        drop the baseline entries whose findings are fixed
  aegis check --record [--tests] [--base REF] [--json]
                                      bind the work tree to a git tree, run Layer 1 (and the user-scope
                                      tests.command) on a snapshot of it, write one ledger check row
  aegis check --card [--json]         the day-0 card (aegis_core.card); changes nothing
  aegis check --partition --split NAME=GLOB[,GLOB...] --split NAME=...
                                      cross-lane call, def and import edges between planned
                                      lanes (aegis_core.partition); changes nothing

--lane, --partition, --card, --write-baseline, --prune-baseline and --record are modes of their own:
one at a time, and none takes FILES, --full or a plan.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from aegis_cli.base import AegisCommand, CommandCategory
from aegis_cli.verify import run_verify

__all__ = ["CheckCommand", "run_check"]


# Every other mode and the options a --record run would silently ignore.
_NOT_WITH_RECORD = (
    ("--lane", "lane", None), ("--partition", "partition", False), ("--card", "card", False),
    ("--write-baseline", "write_baseline", False), ("--prune-baseline", "prune_baseline", False),
    ("--hook", "hook", False), ("--full", "full", False), ("--strict", "strict", False),
    ("--dry-run", "dry_run", False), ("--plan", "plan", None), ("--plan-file", "plan_file", None),
    ("--llm-cmd", "llm_cmd", None), ("--paths", "paths", None), ("--base-policy", "base_policy", False),
    ("--split", "split", None), ("FILES", "files", None),
)


def _record_conflict(args: argparse.Namespace) -> str:
    for flag, attr, idle in _NOT_WITH_RECORD:
        value = getattr(args, attr, idle)
        if value not in (idle, [], ()) and value is not idle:
            return flag
    return ""


def _run_record(args: argparse.Namespace) -> int:
    """`aegis check --record [--tests]`: 0 recorded and passed, 1 failed or could not run, 2 usage."""
    from aegis_cli import sanitize_display
    from aegis_cli.verify import _resolve_git_cwd, _wants_json
    from aegis_core import baseline, checkrun

    clash = _record_conflict(args)
    if clash:
        print(f"Error: --record does not combine with {clash}: it checks the whole tree and records one row",
              file=sys.stderr)
        return 2
    root = _resolve_git_cwd(args)
    use_json = _wants_json(args)
    if not os.path.isdir(root):
        print(f"Error: workspace does not exist: {sanitize_display(root, max_len=len(root))}", file=sys.stderr)
        return 1
    outcome = checkrun.record(root, tests=bool(getattr(args, "tests", False)), base=getattr(args, "base", None))
    row = outcome.row or {}
    if use_json:
        document = baseline.envelope("aegis check --record", {"workspace": str(root), "tree": row.get("tree"),
                                                              "base": row.get("base")})
        document.update(status=outcome.status, witness=row.get("witness"), reason=outcome.reason, check=row or None,
                        tree=outcome.binding.as_dict() if outcome.binding else None)
        print(json.dumps(document, indent=2))
    elif outcome.status == "recorded":
        tests = row.get("tests")
        detail = f", tests {tests['passed']} passed, {tests['failed']} failed" if tests else ", Layer 1 only"
        print(f"recorded: tree {row['tree'][:12]} {'passed' if row['passed'] else 'FAILED'}{detail}"
              + ("; protected paths changed: no credit until approved" if row["protected_changed"] else ""))
    else:
        print(f"{outcome.status}: {sanitize_display(outcome.reason, max_len=300)}", file=sys.stderr)
    if outcome.status != "recorded":
        return 1
    return 0 if row.get("passed") else 1


def run_check(args: argparse.Namespace) -> int:
    """Execute `aegis check`."""
    if getattr(args, "record", False):
        return _run_record(args)
    if getattr(args, "tests", False):
        print("Error: --tests only applies with --record", file=sys.stderr)
        return 2
    return run_verify(args)


class CheckCommand(AegisCommand):
    """Unified verification gate for AI coding agent changes."""

    name = "check"
    category = CommandCategory.WORKFLOW
    help = "Verify changes: Layer 1 checks, plus a Layer 2 model review with --full"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "files",
            nargs="*",
            default=None,  # keeps the contract snapshot identical across argparse versions
            metavar="FILES",
            help="Files to check (default: changed against HEAD, staged, or against the branch base)",
        )
        parser.add_argument(
            "--hook",
            action="store_true",
            help="Git pre-commit mode: Layer 1 only, never a model call",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Fail on checkpoint warnings too (missing tests, hardcoded paths, stub tests...)",
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help="Add Layer 2: adversarial review of the change by the --llm-cmd model",
        )
        plan = parser.add_mutually_exclusive_group()
        plan.add_argument("--plan", metavar="TEXT", default=None, help="Task plan for Layer 2 (implies --full)")
        plan.add_argument(
            "--plan-file", metavar="PATH", default=None, help="File holding the task plan (implies --full)"
        )
        parser.add_argument(
            "--llm-cmd",
            metavar="CMD",
            default=None,
            help="Layer 2 model command, e.g. 'claude -p': gets the prompt on stdin, prints the reply. "
            "It runs in an empty temporary directory, never the repository, so give scripts absolute "
            "paths (default: $AEGIS_LLM_CMD; never read from repository files)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be checked without running anything",
        )
        parser.add_argument(
            "--record",
            action="store_true",
            help="Bind the work tree to a git tree, run Layer 1 on an exported snapshot of it and write one "
            "ledger check row (witness: aegis). A label, not proof: only CI on the landing commit confirms it. "
            "A tree git cannot see completely (assume-unchanged or skip-worktree files) is unbindable and "
            "writes no row; exit 0 only when the run passed",
        )
        parser.add_argument(
            "--tests",
            action="store_true",
            help="With --record: also run the test command from the user-scope config (tests.command in "
            "~/.aegis/config.json, default python -m pytest, never the repository's) in the snapshot with a "
            "fixed environment; exit 5 or zero passed tests is never evidence",
        )
        parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format")
        # One mode at a time. run_verify refuses every option a mode would otherwise ignore.
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--lane",
            metavar="LANE",
            default=None,
            help="Post-lane gate: check the lane's commits since merge-base(--base, HEAD) for containment "
            "(every changed path, deletions and both sides of a move included, inside the lane's globs) and "
            "Python test integrity (removed tests, added skips or xfails, pytest collection changes; assert "
            "weakening is not detected). Any finding fails. Self-attested from the live lease or --paths; "
            "witnessed with --base-policy. As a CI job it is advisory in v4.1, and a witness is only as strong "
            "as the protection on .github/** and on the base branch",
        )
        mode.add_argument(
            "--partition",
            action="store_true",
            help="Report the cross-lane call, def and import edges between lanes planned with --split (at least "
            "two), and the [FROZEN_SIGNATURES] of the functions that cross a lane boundary. Python, and Rust when "
            "its driver is enabled. A report: it changes nothing and exits 0 even when it finds edges",
        )
        mode.add_argument(
            "--card",
            action="store_true",
            help="Print the day-0 card: languages, AST drivers, rules by type, the Layer 1 pass rate on the "
            "files and the 5 files with the most findings (above 2000 files it samples, and says so). "
            "Changes nothing and never reads baseline.json; --json for the machine-readable form",
        )
        mode.add_argument(
            "--write-baseline",
            action="store_true",
            help="Record every current Layer 1 finding in .aegis/baseline.json, so that aegis check then fails "
            "only on new ones. Findings are fingerprinted by rule, path, matched line and its occurrence, not "
            "by line number. A failure that is not about a line (a rule that cannot load, a file that cannot "
            "be parsed) is listed and is never recorded",
        )
        mode.add_argument(
            "--prune-baseline",
            action="store_true",
            help="Drop the entries of .aegis/baseline.json whose findings are fixed (or whose file is gone). "
            "It never adds a finding, and it refuses to run while a check cannot run",
        )
        parser.add_argument(
            "--split",
            action="append",
            metavar="NAME=GLOB[,GLOB...]",
            default=None,
            help="With --partition: one planned lane and the globs of its files; give at least two. They match "
            "as rule target_paths do: a glob without '/' matches at any depth",
        )
        parser.add_argument(
            "--base",
            metavar="REF",
            default=None,
            help="With --lane: the base branch (default: origin/$GITHUB_BASE_REF, $GITHUB_BASE_REF, origin/main, "
            "main, origin/develop or develop). A shallow clone fails: fetch with fetch-depth 0. Without --lane: "
            "read .aegis/baseline.json from REF (label baseline: base@<sha>; absent there means empty: baseline: "
            "absent at base) and check what changed since REF; the working tree's baseline is then not consulted, "
            "and a REF that does not resolve is an error. Without --base the working tree's baseline is used and "
            "labelled self-attested: a candidate can edit its own. There is no CI detection",
        )
        parser.add_argument(
            "--paths",
            nargs="+",
            metavar="GLOB",
            default=None,
            help="With --lane: the lane's globs instead of its live lease (self-attested). They match as rule "
            "target_paths do: a glob without '/' matches at any depth, so CHANGELOG.md also admits "
            "docs/CHANGELOG.md. They never allow .aegis/** or .github/workflows/**",
        )
        parser.add_argument(
            "--base-policy",
            action="store_true",
            help="With --lane: take lanes.<lane> and shared from .aegis/team.json at the base tip, never the "
            "candidate; refuses --paths. Only then is the result 'witnessed: base policy', and only then may "
            ".aegis/** and .github/workflows/** change",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_check(args)


if __name__ == "__main__":  # pragma: no cover
    from aegis_cli.cli import main
    sys.exit(main(["check"] + sys.argv[1:]))
