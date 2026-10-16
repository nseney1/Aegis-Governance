"""aegis doctor — workspace health, the host matrix and backed-up cleanup (host-matrix §3.9-3.10).

A read run changes nothing: it reads files, runs ``codex mcp get aegis --json`` (the only
host CLI it starts: Codex keeps its registrations in TOML, which stdlib-only Aegis does not
parse), and never syncs, checks or initializes. The one network access is the trust tier's
read-only ``gh api`` GETs through the user's own ``gh`` (no ``gh`` means tier C). Claude Code
is read from ``~/.claude.json`` instead of ``claude mcp list``, which starts every configured
server.

Each host gets one state, the first of these that applies:

- ``missing_binary``: none of its binaries is in an absolute PATH entry outside the
  workspace (one found only inside it, or only through an empty or relative entry, is
  listed in ``binary.ignored`` with the reason ``binary_in_workspace`` or
  ``binary_on_relative_path``, and makes the host's installation unknown), and none of
  its desktop apps is installed (``app``: an IDE or desktop app puts nothing on PATH);
- ``unregistered``: its config has no ``aegis`` server, or the registered command is gone;
- ``auth_unknown``: doctor cannot confirm the host will load ``aegis`` or read its
  bootstrap (its CLI failed or timed out, its config cannot be parsed, the registration
  waits on an approval doctor cannot see, the registered command is a relative path or is
  found only where doctor does not look, a host that sends no workspace depends on an
  unreadable registry, or a CLAUDE.md-family file above the workspace, which doctor does
  not read, decides whether Claude Code reads AGENTS.md; the user's own
  ``~/.claude/CLAUDE.md``, which Claude Code loads as user memory, never does);
- ``policy_gap``: ``aegis`` loads, but this repository's policy does not fully reach the
  host (no or broken bootstrap, a CLAUDE.md, CLAUDE.local.md, .claude/CLAUDE.md or
  AGENTS.override.md shadowing AGENTS.md, a file the host truncates, an unregistered
  workspace for a host without roots, a disabled entry or one Claude Code turns off for
  the project in ``disabledMcpServers``, another host's identity, or an unsafe
  registration: a command that is not absolute, or that runs ``-m`` or ``-c`` without
  ``-I`` and so imports from the project directory the host starts it in);
- ``ok``: none of the above.

``--json`` prints one ``aegis.doctor/v1`` document: ``schema``, ``source``, ``aegis_version``,
``checked_at`` (UTC), ``scope``, ``stale`` and ``unknown`` (fields doctor could not
determine), ``checks_ok`` (no blocking check failed; it says nothing about the hosts),
``checks``, ``hosts`` (each with ``state``, ``reasons``, the matrix facts,
``enforcement_level`` and ``trust_tier``, the repository's human_gate tier), ``enforcement_tiers``,
``human_gate`` (the tier, the evidence it rests on and why it is not higher), ``state_modes``
(how many entries of the shared state are looser than 0700/0600; a count, never names),
``findings``, and with ``--fix`` the ``fixes`` it applied and its ``backup_dir``.

The trust tier (``aegis_core.human_gate``, v4.3 §2.2) is printed on every report: A, separation
of duties; B, solo with signed approvals; C, self-attested. ``--github`` prints what A and B
need: the exact ruleset JSON, the CODEOWNERS lines and the signing setup. ``--github --apply
--tier A|B`` creates that ruleset through ``gh api``, and only after an interactive y/N at a
terminal: ``--yes`` and ``--json`` never apply, and a ruleset of the same name is never
touched. ``--release SHA`` (aegis_core.release_verify) asks ``gh attestation verify`` whether the
CI verdict job attested that exact commit, pinning repository, workflow, digest and ref; a gh
that is missing or older than 2.93.0 prints ``UNVERIFIED (gh >= 2.93.0 required)`` and exits
non-zero, and at tier C the report says "attestation present, but the workflow is agent-editable"
and exits non-zero too (the release claim needs tier A or B).

Each row lists the ``surfaces`` its config plane covers (CLI, IDE extension, desktop app).
A row whose host table entry is unverified (``verified_row`` false: Cursor, Copilot, Kiro,
Windsurf) is also ``experimental``, and the text names it so: its registration file is the
one the vendor documents, not yet checked on a real install.
Without ``hosts`` in .aegis/config.json the matrix is every verified host plus each
experimental one found on this machine (by binary, config path or app). A host found
here whose agent reads AGENTS.md, while AGENTS.md carries the bootstrap and the host has
no ``aegis`` registration, is the ``bootstrap_without_tools`` warning: the bootstrap
tells that agent to call tools it does not have (fix: ``aegis init --host <id>``).

``enforcement_level`` is the strongest tier known to be in force for the host here:
``local_floor``, ``advisory``, ``none`` (an ungoverned workspace, a host not installed,
or no route by which aegis or its bootstrap reaches the agent) or ``unknown`` (a fact
that decides it cannot be read, such as a host binary found only inside the workspace).
The home directory is never a governed workspace: its ``.aegis/`` is the user plane, so
run from there doctor checks no project rules, state or AST drivers.

Each host row also has ``hooks`` (v4.1 §2): the Aegis PreToolUse entries in the files the
host reads hooks from (user, project and, for Claude Code, local settings), whether each
runs an executable ``aegis``, and the tier such an entry gives with its evidence label
(Claude Code and Codex blocking are documented, DOC; Antigravity's exit-1 block is LIVE).
Presence never claims enforcement: no entry changes ``state`` or ``enforcement_level``, and
the best-effort tier is ``unknown`` while any is registered, since doctor cannot see a host
run it (nor Codex's /hooks approval). An entry that is not the one ``aegis hook install``
writes (matcher, type, command form with its host, or timeout) is ``modified`` and claims no
tier. Duplicates, modified entries, host files that do not parse, entries
whose ``aegis`` is gone and v3 leftovers (``soma hook ...`` or a removed ``aegis hook``
phase, in any hook file or the stale v3 Antigravity plugin) are findings; ``--fix`` removes
the leftovers with the ``remove_list_items`` action (or deletes a plugin file that holds
nothing else).
Strings taken from files or host output are printed without control sequences, and
doctor starts only host CLIs found in absolute PATH entries outside the workspace
(aegis_core.pathlookup). It never starts the MCP server or a registered command: the MCP
launcher check compares what each host registered with what ``aegis init --host`` would
register from this install.

``--fix`` changes only what a finding reported as fixable, after confirmation (``--yes``
skips it). Every file is first copied to ``~/.aegis/backups/<UTC stamp>/`` with a manifest;
writes are atomic; a symlink, a hard link or a file that changed since the check is never
written. It never edits shell rc files (D17) and never writes TOML.
"""
from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from aegis_cli.base import CommandCategory, AegisCommand
from aegis_core import human_gate
from aegis_core.pathlookup import INSIDE_FENCE, Hit, only_skipped, which

__all__ = ["run_doctor", "DoctorCommand", "probe_mcp_launcher", "SCHEMA", "V3_SHIPPED_RULE_SHA256"]

SCHEMA = "aegis.doctor/v1"
SOURCE = "aegis doctor"
SERVER = "aegis"
# The v3 server name; v4 registers only "aegis" and doctor --fix removes this one.
LEGACY_SERVER = "soma"
EXIT_USAGE = 2


def _check_python_version() -> bool:
    """Check Python >= 3.9."""
    ok = sys.version_info >= (3, 9)
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if ok:
        print(f"  ✅ Python {ver} (≥ 3.9)")
    else:
        print(f"  ❌ Python {ver} (requires ≥ 3.9)")
    return ok


def _check_zero_dependencies() -> bool:
    """Verify that the frontmatter engine is operational with zero dependencies."""
    from aegis_core.yaml_engine.frontmatter import parse_frontmatter

    test_fm = "---\nid: test\ntype: invariant\n---\n"
    ok = parse_frontmatter(test_fm) == {"id": "test", "type": "invariant"}
    if ok:
        print("  ✅ zero-dependency runtime operational (pure standard library)")
    else:
        print("  ❌ frontmatter engine validation failed")
    return ok


def _is_home(root: Path) -> bool:
    """Whether ``root`` is the home directory, whose ``.aegis/`` is the user plane."""
    from aegis_core.workspace.layout import UserLayout

    layout = UserLayout.current()
    key = _root_key(root)
    return layout is not None and key is not None and key == _root_key(layout.home)


def _setup_command(root: Path) -> str:
    """What sets governance up here: ``aegis migrate`` while an unmigrated v3 workspace is
    here (``aegis init`` would leave its rules unserved, and the check would then pass on
    none of them), else ``aegis init``."""
    from aegis_core.errors import WorkspaceError
    from aegis_core.workspace.discovery import refuse_unmigrated_v3

    try:
        refuse_unmigrated_v3(root)
    except WorkspaceError:
        return "aegis migrate"
    return "aegis init"


def _setup_fix(root: Path, purpose: str) -> str:
    if _setup_command(root) == "aegis migrate":
        return "Fix: Run 'aegis migrate' to see how this v3 workspace converts, then 'aegis migrate --apply'."
    return f"Fix: Run 'aegis init' to {purpose}."


def _check_rules(project_root: Path) -> bool:
    """The workspace serves at least one rule and every rule file loads."""
    from aegis_core.rules import load_rules
    from aegis_core.workspace.layout import UserLayout, WorkspaceLayout

    if _is_home(project_root):
        print(f"  ❌ Rules: {project_root} is your home directory, never a workspace: "
              f"{UserLayout(Path(project_root)).rules_dir} is your user rule layer, which every workspace adds to its own")
        print("    Fix: run aegis doctor inside a repository.")
        return False
    rules_dir = WorkspaceLayout(Path(project_root)).rules_dir
    if not rules_dir.is_dir():
        print(f"  ❌ No rules directory ({rules_dir})")
        print("    " + _setup_fix(project_root, "install starter rules"))
        return False
    try:
        ruleset = load_rules(project_root)
    except Exception as exc:  # an unreadable tree fails closed, here as in scan
        print(f"  ❌ Rules cannot be loaded from {rules_dir}: {exc}")
        return False
    if ruleset.errors:
        first = ruleset.errors[0]
        print(f"  ❌ {len(ruleset.errors)} rule file(s) cannot be served, e.g. {first.path}: {first.error}")
        print("    Fix: correct them; 'aegis check' fails closed until they load.")
        return False
    if not ruleset.served:
        print(f"  ❌ No rules are served from {rules_dir}")
        print("    " + _setup_fix(project_root, "install starter rules"))
        return False
    print(f"  ✅ Rules: {len(ruleset.served)} served from {rules_dir}")
    return True


def _check_state_dir(project_root: Path | None = None) -> Optional[bool]:
    """Check .aegis/state/ (ledger, lock) exists and is writable, or can be created (read-only check)."""
    from aegis_core.workspace.layout import WorkspaceLayout

    root = Path(project_root or Path.cwd()).resolve()
    if _is_home(root):
        print(f"  ℹ️  State directory: not checked: {root} is your home directory, whose .aegis/ is your "
              "user layer; a workspace keeps its state in its own .aegis/state")
        return None
    state = WorkspaceLayout(root).state_dir
    if state.is_dir():
        if os.access(str(state), os.W_OK):
            print(f"  ✅ State directory writable ({state})")
            return True
        print(f"  ❌ State directory not writable ({state})")
        print(f"    Fix: Verify write permissions on {state}.")
        return False
    parent = state.parent
    if parent.is_dir() and os.access(str(parent), os.W_OK):
        print(f"  ✅ State directory can be created ({state})")
        return True
    print(f"  ❌ State directory does not exist ({state})")
    print("    " + _setup_fix(root, "create workspace directories"))
    return False


def _check_cli_resolvable(project_root: Optional[Path] = None) -> bool:
    """Check that the 'aegis' CLI the bootstrap sends agents to is on PATH.

    Only absolute PATH entries count (aegis_core.pathlookup): an empty or relative entry
    resolves against the directory a shell starts in, where a cloned repository can plant
    an ``aegis``. Doctor runs nothing here, so an absolute entry inside the workspace (a
    project virtualenv the user put on PATH) counts, and the line says where it is.
    """
    root = Path(project_root or Path.cwd()).resolve()
    path = which("aegis")
    if path:
        inside = which("aegis", outside=root) != path
        print(f"  ✅ aegis CLI resolvable ({path}{', inside the workspace' if inside else ''})")
        return True
    print("  ❌ aegis CLI not found on PATH")
    for hit in only_skipped("aegis", base=root):
        print(f"    {hit.path} is reached only through the relative PATH entry {hit.entry!r}, which "
              "resolves against the current directory: not counted")
    from aegis_cli.pathcheck import build_hint
    hint = build_hint()
    if hint:
        print("\n".join("    " + line for line in hint.splitlines()))
    return False


# ── Programs doctor starts ───────────────────────────────────────────────────

def _child_env() -> Dict[str, str]:
    """The environment of a program doctor starts.

    On Windows a ``.cmd`` or ``.bat`` shim (npm's ``codex.cmd``) runs under cmd.exe,
    which looks for the programs it calls (``node``) in the current directory first:
    the repository, for the codex probe. This variable turns that search off.
    """
    env = dict(os.environ)
    if sys.platform == "win32":
        env["NoDefaultCurrentDirectoryInExePath"] = "1"
    return env


def _clean(text: Any, limit: int = 512) -> str:
    """A string from a file or a host's output, safe to print: no escape or control sequences."""
    from aegis_cli import sanitize_display

    return sanitize_display(str(text), max_len=limit)


# ── MCP launcher ─────────────────────────────────────────────────────────────

# A registered command, as doctor compares it: (host id, argv as the host config holds it).
Registered = Tuple[str, Sequence[str]]


def _same_command(a: Sequence[str], b: Sequence[str]) -> bool:
    if len(a) != len(b) or not a:
        return False
    return os.path.normcase(a[0]) == os.path.normcase(b[0]) and list(a[1:]) == list(b[1:])


def _launcher_problem(argv: Sequence[str], current: Sequence[str]) -> Optional[str]:
    """Why a registered launcher is wrong, or None. Nothing is run."""
    from aegis_cli.install_hosts import MCP_RUNNER, display_command, launch_risk

    shown = display_command(argv) if argv else "an empty command"
    risk = launch_risk(argv)
    if risk:
        return f"starts `{shown}`, an unsafe registration: {risk}"
    if not (os.path.isfile(argv[0]) and (os.name == "nt" or os.access(argv[0], os.X_OK))):
        return f"starts {argv[0]}, which does not exist"
    if len(argv) == 5 and argv[1:4] == ["-I", "-c", MCP_RUNNER] \
            and not os.path.isfile(os.path.join(argv[4], "aegis_mcp", "server.py")):
        return f"starts {argv[0]} with no aegis_mcp in {argv[4]}: that install is gone"
    if not _same_command(argv, current):
        return f"starts {shown}, not this install's {display_command(current)}"
    return None


def probe_mcp_launcher(path_env: Optional[str] = None, registered: Sequence[Registered] = (),
                       scripts_dirs: Optional[Sequence[str]] = None) -> Tuple[List[str], List[Tuple[str, str]]]:
    """The command `aegis init --host` registers from this install (install_hosts.mcp_command
    under ``path_env``), and each ``registered`` host whose command is unsafe (launch_risk),
    gone, or another install's, with the reason.

    Doctor runs neither: the registered argv comes from a host's config file, and
    starting the server would prove nothing a host does not do at its next session.
    """
    from aegis_cli.install_hosts import mcp_command

    # None reaches mcp_command as it does from init: $PATH, or the OS default path when unset.
    current = mcp_command(path_env, scripts_dirs)
    problems = []
    for host_id, argv in registered:
        why = _launcher_problem(list(argv), current)
        if why:
            problems.append((host_id, why))
    return current, problems


def _where(hit: Hit, fence: Any) -> str:
    """Where a program ``only_skipped`` passed over is, and why it was passed over;
    ``fence`` names what it was inside."""
    if hit.reason == INSIDE_FENCE:
        return f"{hit.path}, inside {fence}"
    return f"{hit.path}, through the relative PATH entry {hit.entry!r}"


def _check_mcp_launcher(path_env: Optional[str] = None, workspace: Optional[Path] = None,
                        registered: Sequence[Registered] = (),
                        scripts_dirs: Optional[Sequence[str]] = None) -> bool:
    """Advisory: the MCP launcher this install registers, and whether each host's matches."""
    from aegis_cli.install_hosts import MCP_SCRIPT, display_command

    current, problems = probe_mcp_launcher(path_env, registered, scripts_dirs)
    where = ""
    if len(current) == 1 and workspace is not None:
        # The script's directory, not the script: a version manager's link resolves elsewhere.
        key, fence = _root_key(Path(current[0]).parent), _root_key(workspace)
        if key and fence and (key == fence or key.startswith(fence.rstrip(os.sep) + os.sep)):
            where = ", inside the workspace"
    if len(current) == 1:
        print(f"  {'⚠️ ' if problems else '✅'} MCP launcher: {current[0]}{where} (what aegis init --host registers)")
    else:
        print(f"  {'⚠️ ' if problems else '✅'} MCP launcher: no {MCP_SCRIPT} script found, so aegis init --host "
              f"registers this interpreter in isolated mode: {display_command(current)}")
    for host_id, why in problems:
        print(f"      {host_id} {why}. Fix: re-run aegis init --host {host_id}")
    ok_hosts = [h for h, _ in registered if h not in {p for p, _ in problems}]
    if ok_hosts:
        print(f"      registered for {', '.join(ok_hosts)}")
    return not problems


def _missing_ast_extensions(ws_root: Path) -> List[str]:
    """Detected source extensions with no AST driver configured (what --fix provisions).

    An unreadable config gives none: the AST check reports it, and --fix will not
    write over a file it cannot parse.
    """
    from aegis_core.ast.detect import detect_project_languages
    from aegis_core.skills.slots import SlotRegistry, SlotResolutionError

    if _is_home(ws_root):
        return []
    langs = {k: v for k, v in detect_project_languages(ws_root).items() if k != "python"}
    configured: set = set()
    try:
        registries = (SlotRegistry.load(ws_root), SlotRegistry.load_user(ws_root))
    except SlotResolutionError:
        return []
    for registry in registries:
        for name in registry.to_dict():
            if name == "ast_driver":
                configured.add("default")
            elif name.startswith("ast_driver_"):
                configured.add(f".{name[len('ast_driver_'):]}")
    if "default" in configured:
        return []
    return sorted({ext for info in langs.values() for ext in info.get("extensions", []) if ext not in configured})


def _check_ast_drivers(project_root: Path | None = None, fix: bool = False) -> Optional[bool]:
    """Check the AST drivers this workspace uses and that their executables resolve.

    A repository opts in to a packaged driver in .aegis/config.json; driver commands
    come only from ~/.aegis/config.json (D10).
    """
    import shlex
    from aegis_core.errors import PathTraversalError
    from aegis_core.skills.slots import SlotRegistry, SlotResolutionError
    from aegis_core.ast.detect import detect_project_languages, provision_ast_driver_slots
    from aegis_core.ast.runner import resolve_driver_executable

    ws_root = Path(project_root or Path.cwd())
    if _is_home(ws_root):
        # Never walk the home directory for sources, nor write a repository's driver
        # opt-in into ~/.aegis/config.json, which is the user scope.
        print(f"  ℹ️  AST drivers: not checked: {ws_root} is your home directory, whose .aegis/ is your user layer")
        return None
    detected_langs = detect_project_languages(ws_root)
    non_py_langs = {k: v for k, v in detected_langs.items() if k != "python"}

    def _configured() -> dict[str, str]:
        drivers: dict[str, str] = {}
        for registry in (SlotRegistry.load(ws_root), SlotRegistry.load_user(ws_root)):
            for slot_name, slot_val in registry.to_dict().items():
                if slot_name == "ast_driver":
                    drivers["default"] = str(slot_val)
                elif slot_name.startswith("ast_driver_"):
                    drivers[f".{slot_name[len('ast_driver_'):]}"] = str(slot_val)
        return drivers

    try:
        ast_drivers = _configured()
    except SlotResolutionError as exc:
        print(f"  ❌ AST drivers: {exc}")
        return False

    missing = sorted({
        ext
        for l_info in non_py_langs.values()
        for ext in l_info.get("extensions", [])
        if ext not in ast_drivers and "default" not in ast_drivers
    })
    if missing:
        if fix:
            try:
                _slots, written = provision_ast_driver_slots(ws_root, detected_langs)
            except PathTraversalError as exc:
                print(f"  ❌ AST drivers: {exc}")
                return False
            if written:
                print(f"  ✅ Fixed: enabled the packaged AST drivers in .aegis/config.json for {', '.join(missing)}")
                ast_drivers = _configured()
        else:
            print(f"  ⚠️  AST drivers: unconfigured driver for detected source extension(s): {', '.join(missing)}. Run 'aegis doctor --fix' to provision.")
            return False

    if not ast_drivers:
        print("  ✅ AST drivers: native Python stdlib (in-process)")
        return True

    all_resolvable = True
    for ext, cmd in sorted(ast_drivers.items()):
        parts = (
            shlex.split(cmd)
            if os.name != "nt"
            else [p.strip('"') for p in shlex.split(cmd, posix=False)]
        )
        if not parts:
            continue
        bin_name = parts[0]
        # As the driver runs: absolute PATH entries outside the workspace, a relative path
        # joined to the workspace root (aegis_core.ast.runner).
        found = resolve_driver_executable(bin_name, workspace=ws_root)
        hits = [] if found else only_skipped(bin_name, outside=ws_root, base=ws_root)
        if found:
            print(f"  ✅ AST driver ({ext}): {bin_name} resolvable ({found})")
        elif hits:
            print(f"  ⚠️  AST driver ({ext}): executable '{bin_name}' is found only at "
                  f"{_where(hits[0], 'the workspace')}, where aegis never runs it")
            all_resolvable = False
        else:
            print(f"  ⚠️  AST driver ({ext}): executable '{bin_name}' not found on PATH")
            all_resolvable = False

    return all_resolvable


# ── Pre-commit hook ──────────────────────────────────────────────────────────

def _check_precommit_hook(project_root: Path | None = None) -> bool | None:
    """True for a current, runnable hook block; False for an older one or one whose
    pinned interpreter or aegis path is gone; None if absent.

    Blocks before the current format resolved aegis through PATH, $VIRTUAL_ENV
    or the repository's .venv, so repository code could run on commit.
    """
    from aegis_cli.hooks.management import hook_status

    st = hook_status(project_root)
    if not st["managed_by_aegis"]:
        return None
    if st["status"] == "installed":
        gone = [p["path"] for p in (st["interpreter"], st["aegis_path"]) if p and not p["exists"]]
        if gone:
            print(f"  ❌ Pre-commit hook ({st['hook_file']}) pins {gone[0]}, which no longer exists,\n"
                  "      so every commit fails closed. Re-run `aegis hook install` to re-pin it.")
            return False
        if st.get("reachable", True) is False:
            print(f"  ❌ Pre-commit hook ({st['hook_file']}) is installed but never runs: "
                  f"{st.get('unreachable_reason') or 'git does not reach the Aegis block'}.\n"
                  "      Run `aegis hook status` for the fix.")
            return False
        print(f"  ✅ Pre-commit hook is current ({st['hook_file']})")
        return True
    print(f"  ❌ Pre-commit hook uses an old block (format {st['format_version']}, {st['hook_file']}).\n"
          "      It can run an aegis found on PATH or in the repository instead of\n"
          "      the one you installed. Re-run `aegis hook install` to refresh it.")
    return False


# ── Host plane: context ──────────────────────────────────────────────────────

# Codex's own answer when no server has that name. Any other failure leaves the
# registration unknown: a CLI that crashed has not said "absent".
_CODEX_ABSENT = re.compile(r"no mcp server named\s+['\"]?aegis['\"]?\s+found", re.IGNORECASE)
_PROBE_TIMEOUT = 10.0
# Hosts that silently keep only the start of an over-budget instruction file: Codex at
# its 32 KiB project_doc_max_bytes, Antigravity at 24,000 bytes per file (host-matrix
# §1-§2, verified 2026-10-15). A block that ends within the budget still arrives; for
# the other hosts the budget is advice.
_TRUNCATES_TAIL = frozenset({"codex-cli", "antigravity"})
# Hosts that send no MCP roots and attest no workspace: the registry is how the server
# finds the repository (host-matrix §2, §3.6).
_REGISTRY_BOUND = frozenset({"antigravity"})
# Hosts that read AGENTS.override.md instead of AGENTS.md at the same level.
_READS_AGENTS_OVERRIDE = frozenset({"codex-cli"})
_FIX_HINT = "aegis doctor --fix"
_LEGACY_ENTRY = f"stale v3 '{LEGACY_SERVER}' MCP server"


def _run_host_cli(argv: Sequence[str], cwd: str, timeout: float) -> "subprocess.CompletedProcess[str]":
    """The one place doctor starts a host CLI: an argv (no shell), no stdin, bounded in time."""
    return subprocess.run(list(argv), cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, errors="replace", timeout=timeout, env=_child_env())


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _aegis_version() -> str:
    from aegis_core._version import __version__
    return __version__


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class _File:
    """One file as doctor read it, with the facts --fix needs to decide whether it may write."""

    path: Path
    raw: Optional[bytes] = None
    is_link: bool = False
    error: Optional[str] = None
    refusal: Optional[str] = None  # why --fix will not write it
    data: Any = None

    @property
    def exists(self) -> bool:
        return self.raw is not None or self.is_link or self.error is not None


def _write_refusal(path: Path, st: os.stat_result) -> Optional[str]:
    if stat.S_ISLNK(st.st_mode):
        return "it is a symlink, and Aegis never writes through a link"
    if not stat.S_ISREG(st.st_mode):
        return "it is not a regular file"
    if st.st_nlink > 1:
        return "it has another hard link, and replacing it would split the link"
    if not (st.st_mode & 0o222) or not os.access(str(path), os.W_OK):
        return "it is read-only"
    return None


def _read_file(path: Path) -> _File:
    entry = _File(path)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return entry
    except OSError as exc:
        entry.error = f"cannot be read ({exc.strerror or exc})"
        return entry
    entry.is_link = stat.S_ISLNK(st.st_mode)
    entry.refusal = _write_refusal(path, st)
    if entry.is_link and not path.is_file():
        entry.error = "is a symlink to no regular file"
        return entry
    if not entry.is_link and not stat.S_ISREG(st.st_mode):
        entry.error = "is not a regular file"
        return entry
    try:
        with open(path, "rb") as fh:
            entry.raw = fh.read()
    except OSError as exc:
        entry.error = f"cannot be read ({exc.strerror or exc})"
    return entry


def _strict_pairs(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def _parse_json(entry: _File) -> _File:
    if entry.raw is None or entry.error:
        return entry
    try:
        text = entry.raw.decode("utf-8")
        if text.startswith("\ufeff"):
            raise ValueError("starts with a byte-order mark")
        entry.data = json.loads(text, object_pairs_hook=_strict_pairs, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        entry.error = f"is not valid JSON ({str(exc)[:120]})"
        return entry
    except RecursionError:
        # A file nested past the parser's depth (a cloned repository's .mcp.json can be)
        # is as unreadable as a malformed one; it must not abort the whole report.
        entry.error = "is not valid JSON (nested too deeply to parse)"
        return entry
    if not isinstance(entry.data, dict):
        entry.error = "is not a JSON object"
        entry.data = None
    return entry


@dataclass
class _Ctx:
    """What one doctor run looks at; files are read once."""

    root: Path
    governed: bool
    home: Optional[Path]
    environ: Mapping[str, str]
    selected: Tuple[Any, ...]
    selection: str
    is_home: bool = False
    # What sets this workspace up: aegis migrate while an unmigrated v3 workspace is here.
    setup: str = "aegis init"
    _cache: Dict[Tuple[str, bool], _File] = field(default_factory=dict)

    @property
    def path_env(self) -> str:
        return self.environ.get("PATH", "")

    def which(self, name: str) -> Optional[str]:
        return which(name, self.path_env, outside=self.root)

    def passed_over(self, name: str) -> List[Hit]:
        """Where ``name`` is when ``which`` refused every place: a relative or empty PATH
        entry (resolved against the workspace, where a host would start) or an absolute
        entry inside it. Never run."""
        return only_skipped(name, self.path_env, outside=self.root, base=self.root)

    def file(self, path: Path, as_json: bool = False) -> _File:
        key = (os.path.abspath(str(path)), as_json)
        if key not in self._cache:
            entry = _read_file(Path(path))
            self._cache[key] = _parse_json(entry) if as_json else entry
        return self._cache[key]

    def label(self, path: Path) -> str:
        """``~/x`` for a file under the home directory (as the docs name them), else the path."""
        if self.home is not None:
            try:
                return "~/" + Path(path).relative_to(self.home).as_posix()
            except ValueError:
                pass
        return str(path)


def _claude_dir(ctx: _Ctx) -> Optional[Path]:
    custom = ctx.environ.get("CLAUDE_CONFIG_DIR")
    if custom:
        return Path(custom)
    return ctx.home / ".claude" if ctx.home else None


def _claude_config(ctx: _Ctx) -> Optional[Path]:
    # Claude Code keeps its user and local MCP scopes in .claude.json: in the home
    # directory, or in CLAUDE_CONFIG_DIR when that is set.
    custom = ctx.environ.get("CLAUDE_CONFIG_DIR")
    if custom:
        return Path(custom) / ".claude.json"
    return ctx.home / ".claude.json" if ctx.home else None


def _desktop_configs(ctx: _Ctx) -> List[Path]:
    """Every claude_desktop_config.json location: v3 wrote ~/.config/Claude on every OS."""
    if ctx.home is None:
        return []
    found = [ctx.home / ".config" / "Claude" / "claude_desktop_config.json"]
    if sys.platform == "darwin":
        found.append(ctx.home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")
    elif os.name == "nt":
        appdata = ctx.environ.get("APPDATA")
        if appdata:
            found.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
    else:
        xdg = ctx.environ.get("XDG_CONFIG_HOME", "")
        if xdg and os.path.isabs(xdg):
            found.append(Path(xdg) / "Claude" / "claude_desktop_config.json")
    unique: Dict[str, Path] = {}
    for path in found:
        unique.setdefault(os.path.normcase(os.path.abspath(str(path))), path)
    return list(unique.values())


def _platform() -> str:
    """``sys.platform``, read in one place so a test can emulate another OS's app folders."""
    return sys.platform


def _app(spec: Any, ctx: _Ctx) -> Optional[str]:
    """The installed desktop app of ``spec`` (an app bundle is a directory), or None."""
    from aegis_core import hosts

    if ctx.home is None:
        return None
    return next((app for app in hosts.app_paths(spec, ctx.home, ctx.environ, _platform()) if os.path.isdir(app)),
                None)


def _plane_found(spec: Any, ctx: _Ctx) -> Optional[str]:
    """What shows ``spec``'s config plane is on this machine, for people: a binary doctor
    would run, a config path in the home directory or a desktop app; None when nothing does."""
    for name in spec.binaries:
        found = ctx.which(name)
        if found:
            return ctx.label(Path(found))
    if ctx.home is not None:
        for spec_path in spec.config_paths:
            rel = spec_path[2:] if spec_path.startswith("~/") else spec_path
            if os.path.exists(ctx.home.joinpath(*rel.split("/"))):
                return spec_path
    app = _app(spec, ctx)
    return ctx.label(Path(app)) if app else None


def _host_json_path(spec: Any, ctx: _Ctx) -> Optional[Path]:
    reg = spec.registration
    if reg is None or reg.kind != "json_file" or ctx.home is None:
        return None
    rel = reg.path[2:] if reg.path.startswith("~/") else reg.path
    return ctx.home.joinpath(*rel.split("/"))


# ── Host plane: registration probes ─────────────────────────────────────────

def _registration(status: str, source: str, **facts: Any) -> Dict[str, Any]:
    reg = {"status": status, "source": source, "scope": None, "command": None, "command_exists": None,
           "enabled": None, "approval": None, "detail": None, "aegis_client": None}
    reg.update(facts)
    return reg


def _entry_facts(entry: Any, ctx: _Ctx) -> Dict[str, Any]:
    """Command, AEGIS_CLIENT and enabled flag of one MCP server entry.

    The strings come from files a repository can write (a project .mcp.json), so the
    command is reported without control sequences; the existence check uses it as
    written, and AEGIS_CLIENT stays raw for the identity decision (``_identity`` cleans
    what it reports), since the server sees the raw value.
    """
    facts: Dict[str, Any] = {}
    if not isinstance(entry, dict):
        return facts
    command = entry.get("command")
    if isinstance(command, str) and command:
        args = entry.get("args") if isinstance(entry.get("args"), list) else []
        facts["command"] = [_clean(command)] + [_clean(a) for a in args]
        facts["command_exists"] = _command_exists(command, ctx)
    env = entry.get("env")
    if isinstance(env, dict) and isinstance(env.get("AEGIS_CLIENT"), str):
        facts["aegis_client"] = env["AEGIS_CLIENT"]
    if isinstance(entry.get("disabled"), bool):
        facts["enabled"] = not entry["disabled"]
    if isinstance(entry.get("enabled"), bool):
        facts["enabled"] = entry["enabled"]
    return facts


def _command_exists(command: str, ctx: _Ctx) -> Optional[bool]:
    """Whether the registered command exists; None when doctor cannot tell.

    A relative path with a directory part resolves against the directory the host starts
    the server in, which doctor does not know. A bare name found only through an empty or
    relative PATH entry, or in an absolute entry inside the workspace, is one the host
    may run but doctor does not count.
    """
    if os.path.isabs(command):
        return os.path.isfile(command) and (os.name == "nt" or os.access(command, os.X_OK))
    if os.sep in command or (os.altsep and os.altsep in command):
        return None
    if ctx.which(command) is not None:
        return True
    return None if ctx.passed_over(command) else False


def _probe_codex(spec: Any, binary: Optional[str], ctx: _Ctx) -> Dict[str, Any]:
    source = "codex mcp get aegis --json"
    if binary is None:
        detail = ("the only codex on PATH is inside the workspace or behind a relative PATH entry, "
                  "and doctor does not run it" if ctx.passed_over("codex") else "codex is not on PATH")
        return _registration("unavailable", source, detail=detail)
    try:
        # From the workspace: Codex answers with the config it would use here (user
        # config plus a trusted project's own).
        proc = _run_host_cli([binary, "mcp", "get", SERVER, "--json"], cwd=str(ctx.root), timeout=_PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return _registration("unknown", source, detail=f"codex did not answer within {_PROBE_TIMEOUT:g}s")
    except OSError as exc:
        return _registration("unknown", source, detail=f"codex could not be started ({exc.strerror or exc})")
    if proc.returncode != 0:
        said = ((proc.stderr or "") + (proc.stdout or "")).strip()
        if _CODEX_ABSENT.search(said):
            return _registration("absent", source)
        first = _clean(said.splitlines()[0], 200) if said else "no output"
        return _registration("unknown", source, detail=f"codex exited {proc.returncode}: {first}")
    try:
        data = json.loads(proc.stdout)
    except (ValueError, RecursionError):  # RecursionError: nested past the parser's depth
        return _registration("unknown", source, detail="codex printed no JSON")
    if not isinstance(data, dict) or data.get("name") != SERVER:
        return _registration("unknown", source, detail="codex answered about another server")
    transport = data.get("transport") if isinstance(data.get("transport"), dict) else {}
    facts = _entry_facts(transport, ctx)
    if isinstance(data.get("enabled"), bool):
        facts["enabled"] = data["enabled"]
    return _registration("registered", source, scope="effective", **facts)


def _claude_project_keys(ctx: _Ctx) -> List[str]:
    keys = [str(ctx.root), ctx.root.as_posix()]
    return list(dict.fromkeys(keys))


def _probe_claude(spec: Any, binary: Optional[str], ctx: _Ctx) -> Dict[str, Any]:
    path = _claude_config(ctx)
    if path is None:
        return _registration("unknown", "~/.claude.json", detail="no home directory")
    source = ctx.label(path)
    cfg = ctx.file(path, as_json=True)
    if cfg.error:
        return _registration("unknown", source, detail=f"{source} {cfg.error}")
    data = cfg.data or {}
    projects = data.get("projects") if isinstance(data.get("projects"), dict) else {}
    key = next((k for k in _claude_project_keys(ctx) if isinstance(projects.get(k), dict)), None)
    project = projects[key] if key is not None else {}

    def facts_of(entry: Any) -> Dict[str, Any]:
        facts = _entry_facts(entry, ctx)
        # Claude Code turns off any server this project lists, whatever its scope
        # (user, local or .mcp.json): "turned off; turn it on in /mcp".
        if SERVER in _names(project.get("disabledMcpServers")):
            facts["enabled"] = False
            facts["detail"] = (f"Claude Code turns aegis off in this project: {source} lists it in "
                               f"projects[{key}].disabledMcpServers; turn it on in Claude Code's /mcp")
        return facts

    local = _server_entry(project)
    user = _server_entry(data)
    if local is not None:
        return _registration("registered", source, scope="local", **facts_of(local))
    if user is not None:
        return _registration("registered", source, scope="user", **facts_of(user))
    dot_mcp = ctx.file(ctx.root / ".mcp.json", as_json=True)
    shared = _server_entry(dot_mcp.data) if not dot_mcp.error else None
    if shared is not None:
        # A project .mcp.json server runs only after the user approves it; that answer
        # lives in settings files doctor does not read, unless .claude.json records it.
        approved = _names(project.get("enabledMcpjsonServers"))
        denied = _names(project.get("disabledMcpjsonServers"))
        approval = ("approved" if SERVER in approved or project.get("enableAllProjectMcpServers") is True
                    else "denied" if SERVER in denied else "unknown")
        facts = facts_of(shared)
        if approval == "denied":
            facts["enabled"] = False
        return _registration("registered", ctx.label(ctx.root / ".mcp.json"), scope="project",
                             approval=approval, **facts)
    return _registration("absent", source)


def _names(value: Any) -> List[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _server_entry(data: Any, name: str = SERVER) -> Optional[Any]:
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers"), dict):
        return None
    return data["mcpServers"].get(name)


def _probe_json_host(spec: Any, binary: Optional[str], ctx: _Ctx) -> Dict[str, Any]:
    path = _host_json_path(spec, ctx)
    if path is None:
        return _registration("unknown", spec.registration.path, detail="no home directory")
    source = ctx.label(path)
    cfg = ctx.file(path, as_json=True)
    if cfg.error:
        return _registration("unknown", source, detail=f"{source} {cfg.error}")
    servers = (cfg.data or {}).get(spec.registration.key)
    entry = servers.get(SERVER) if isinstance(servers, dict) else None
    if entry is None:
        return _registration("absent", source)
    return _registration("registered", source, scope="user", **_entry_facts(entry, ctx))


_PROBES: Dict[str, Callable[[Any, Optional[str], _Ctx], Dict[str, Any]]] = {
    "codex-cli": _probe_codex,
    "claude-code": _probe_claude,
}


def _probe(spec: Any, binary: Optional[str], ctx: _Ctx) -> Dict[str, Any]:
    if spec.id in _PROBES:
        return _PROBES[spec.id](spec, binary, ctx)
    if spec.registration is not None and spec.registration.kind == "json_file":
        return _probe_json_host(spec, binary, ctx)
    return _registration("unavailable", "-", detail=f"doctor has no check for {spec.display_name}")


# ── Host plane: instruction files ───────────────────────────────────────────

_BLOCK_BEGIN = re.compile(r"^<!-- aegis:begin id=(\S+) v=(\S+) sha=(\S+) -->[ \t]*$")
_BLOCK_END = re.compile(r"^<!-- aegis:end id=(\S+) -->[ \t]*$")
_HEX12 = re.compile(r"^[0-9a-f]{12}$")
# An import path runs to the next whitespace, so @AGENTS.md.bak names another file. A
# relative import resolves next to the file holding it: from .claude/ it is ../AGENTS.md.
_IMPORTS_AGENTS = re.compile(r"(?<![\w@/.\-])@(?:\./)?AGENTS\.md(?=\s|$)")
_IMPORTS_PARENT_AGENTS = re.compile(r"(?<![\w@/.\-])@\.\./AGENTS\.md(?=\s|$)")
# What Claude Code loads as project memory from the directory it starts in and from every
# parent. Any one of them turns off its native AGENTS.md reading (host research digest:
# "only when no CLAUDE.md or CLAUDE.local.md exists in cwd or any ancestor"; the binary's
# candidate list also has .claude/CLAUDE.md).
_CLAUDE_FAMILY = ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_CODE_SPAN = re.compile(r"(`+).+?\1")
_INDENTED_CODE = re.compile(r"^(?: {4}|\t)")
_BOM = "\ufeff"


def _fence_step(fence: Optional[Tuple[str, int]], line: str) -> Optional[Tuple[str, int]]:
    """The fenced-code state after ``line``: None outside a fence, else (fence char, length)."""
    match = _FENCE.match(line)
    if fence is None:
        return (match.group(1)[0], len(match.group(1))) if match else None
    closes = (match is not None and match.group(1)[0] == fence[0] and len(match.group(1)) >= fence[1]
              and not line[match.end():].strip())
    return None if closes else fence


def _prose(text: str) -> str:
    """``text`` without fenced or indented code blocks and inline code spans, where
    Claude Code evaluates no ``@`` import.

    An indented block starts after a blank line (or at the top) and cannot interrupt a
    paragraph. List context is not tracked, so an import indented inside a list item
    after a blank line counts as code: doctor may then under-report it, never over-report.
    """
    out, fence, blank_before, indented = [], None, True, False
    for line in text.splitlines():
        inside = fence is not None
        fence = _fence_step(fence, line)
        if inside or fence is not None:
            blank_before, indented = False, False
            continue
        if not line.strip():
            blank_before = True
            continue
        if _INDENTED_CODE.match(line) and (blank_before or indented):
            indented, blank_before = True, False
            continue
        indented, blank_before = False, False
        out.append(_CODE_SPAN.sub(" ", line))
    return "\n".join(out)


@dataclass
class _ClaudeFile:
    """One CLAUDE.md-family file in the workspace, as Claude Code would load it."""

    name: str  # relative to the workspace, with forward slashes
    path: Path
    size: int
    imports_agents: bool
    # It and AGENTS.md are one file (a link either way): Claude Code reads AGENTS.md.
    is_agents: bool
    link_target: Optional[str]  # where it points when it is a symlink


@dataclass
class _Instructions:
    agents_bytes: Optional[int] = None
    bootstrap: str = "not_read"  # current outdated hand_edited malformed missing not_read
    block_end: Optional[int] = None  # bytes up to the end of the closing marker line
    claude: List[_ClaudeFile] = field(default_factory=list)  # in the workspace, _CLAUDE_FAMILY order
    # CLAUDE.md-family files in the workspace's parent directories, except the user memory
    # file: they count, but doctor reads no file outside the workspace, so whether one
    # imports this AGENTS.md is unknown.
    claude_outside: List[Path] = field(default_factory=list)
    override: bool = False


def _bootstrap_state(text: str) -> Tuple[str, Optional[int]]:
    from aegis_core.bootstrap import BOOTSTRAP_ID, bootstrap_text

    # aegis init keeps a byte-order mark it finds, so the block can start right after one.
    bom = text.startswith(_BOM)
    lines = text[1:].splitlines(True) if bom else text.splitlines(True)
    begins, ends, offset, end_at = [], [], len(_BOM.encode("utf-8")) if bom else 0, None
    for index, line in enumerate(lines):
        offset += len(line.encode("utf-8"))
        bare = line.rstrip("\r\n")
        begin = _BLOCK_BEGIN.match(bare)
        if begin and begin.group(1) == BOOTSTRAP_ID:
            begins.append((index, begin.group(2), begin.group(3)))
        end = _BLOCK_END.match(bare)
        if end and end.group(1) == BOOTSTRAP_ID:
            ends.append(index)
            end_at = offset
    if not begins and not ends:
        return "missing", None
    if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0][0]:
        return "malformed", None
    start, version, sha = begins[0]
    if version != "1" or not _HEX12.match(sha):
        return "malformed", None
    body = "".join(lines[start + 1:ends[0]]).replace("\r\n", "\n")
    if _sha256(body.encode("utf-8"))[:12] != sha:
        return "hand_edited", end_at
    return ("current" if body == bootstrap_text() else "outdated"), end_at


def _instructions(ctx: _Ctx) -> _Instructions:
    info = _Instructions()
    if not ctx.governed:
        return info
    agents = ctx.file(ctx.root / "AGENTS.md")
    if agents.raw is not None:
        info.agents_bytes = len(agents.raw)
        text = agents.raw.decode("utf-8", errors="replace")
        info.bootstrap, info.block_end = _bootstrap_state(text)
    else:
        info.bootstrap = "missing"
    for name in _CLAUDE_FAMILY:
        entry = ctx.file(ctx.root.joinpath(*name.split("/")))
        if entry.raw is None:
            continue
        imports = _IMPORTS_PARENT_AGENTS if name.startswith(".claude/") else _IMPORTS_AGENTS
        same = False
        if agents.raw is not None:
            try:
                same = os.path.samefile(str(entry.path), str(agents.path))
            except OSError:
                same = False
        info.claude.append(_ClaudeFile(
            name=name, path=entry.path, size=len(entry.raw),
            imports_agents=bool(imports.search(_prose(entry.raw.decode("utf-8", errors="replace")))),
            is_agents=same, link_target=os.path.realpath(str(entry.path)) if entry.is_link else None))
    # Claude Code loads <config dir>/CLAUDE.md (~/.claude/CLAUDE.md) as user memory and
    # leaves exactly that path out of the walk that decides whether AGENTS.md is read
    # (claude 2.1.301: the walk's processed paths start as {managed, user} memory).
    # The match is by spelling. Under a symlinked home the ancestors of the resolved root
    # spell that file differently, and whether Claude Code still skips it there is
    # unverified, so it counts and the reach stays unknown rather than claimed.
    claude_dir = _claude_dir(ctx)
    user_memory = _path_key(claude_dir / "CLAUDE.md") if claude_dir is not None else None
    candidates = (d.joinpath(*name.split("/")) for d in ctx.root.parents for name in _CLAUDE_FAMILY)
    info.claude_outside = [p for p in candidates if _path_key(p) != user_memory and _present(p)]
    info.override = (ctx.root / "AGENTS.override.md").exists()
    return info


def _path_key(path: Path) -> str:
    """``path`` as written, made absolute and case-folded where the OS folds case."""
    return os.path.normcase(os.path.abspath(str(path)))


def _present(path: Path) -> bool:
    """Whether a file is there, without reading it; True when that cannot be told, so an
    unreadable parent directory never lets doctor claim the bootstrap through."""
    try:
        return stat.S_ISREG(os.stat(path).st_mode)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except (OSError, ValueError):
        return True


def _claude_reads_agents(info: _Instructions) -> bool:
    return any(f.is_agents or f.imports_agents for f in info.claude)


def _claude_names(info: _Instructions) -> str:
    names = [f.name for f in info.claude]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _claude_import_advice(info: _Instructions) -> str:
    """How to make Claude Code read AGENTS.md. aegis init adds the import only to a
    CLAUDE.md at the root, and never writes through a link."""
    root = next((f for f in info.claude if f.name == "CLAUDE.md"), None)
    if root is not None and root.link_target is not None:
        return (f"CLAUDE.md is a link to {root.link_target}, which aegis init never writes through: "
                "add an @AGENTS.md line to that file, or make CLAUDE.md a link to AGENTS.md")
    if root is not None:
        return "run aegis init to add the import"
    first = info.claude[0]
    line = "@../AGENTS.md" if first.name.startswith(".claude/") else "@AGENTS.md"
    return f"add the line {line} to {first.name} (aegis init adds it only to a CLAUDE.md at the root)"


def _budget(spec: Any, info: _Instructions) -> Dict[str, Any]:
    budget = spec.budget_bytes
    if spec.instructions == "agents_md_unless_claude_md" and info.claude:
        # Claude Code loads every one of them; AGENTS.md too when one imports it, once.
        whole = any(f.is_agents for f in info.claude)
        imported = not whole and any(f.imports_agents for f in info.claude)
        size = sum(f.size for f in info.claude) + ((info.agents_bytes or 0) if imported else 0)
        name = " + ".join(f.name + (" (= AGENTS.md)" if f.is_agents else "") for f in info.claude)
        name += " + AGENTS.md" if imported else ""
    elif spec.instructions in ("agents_md", "agents_md_unless_claude_md"):
        size, name = info.agents_bytes, "AGENTS.md"
    else:
        size, name = None, None
    within = None if size is None or budget is None else size <= budget
    return {"file": name, "bytes": size, "budget_bytes": budget, "within": within}


def _bootstrap_reaches(spec: Any, info: _Instructions) -> Optional[bool]:
    if info.bootstrap == "not_read" or spec.instructions in ("gemini_md", "none"):
        return None
    if info.bootstrap not in ("current", "outdated"):
        return False
    if spec.id in _READS_AGENTS_OVERRIDE and info.override:
        return False
    if spec.instructions == "agents_md_unless_claude_md":
        if _claude_reads_agents(info):
            return True
        if info.claude:
            return False
        if info.claude_outside:
            return None  # no native read; an import in a file doctor does not read is unknown
    return True


def _registered_roots(ctx: _Ctx) -> Tuple[Optional[set], List[int]]:
    """(normalized roots in ~/.aegis/workspaces.json, indexes of the entries skipped).

    The roots are empty when the file is absent and None when it cannot be read. An
    entry is skipped, as the server's registry reader skips it, unless it is an object
    whose ``root`` is an absolute path that resolves: a relative root would otherwise be
    resolved against doctor's own cwd, and a NUL byte makes resolving raise.
    """
    if ctx.home is None:
        return None, []
    from aegis_core.workspace.layout import UserLayout

    reg = ctx.file(UserLayout(ctx.home).workspaces_file, as_json=True)
    if not reg.exists:
        return set(), []
    if reg.error or reg.data.get("v") != 1 or not isinstance(reg.data.get("workspaces"), list):
        return None, []
    roots, skipped = set(), []
    for index, entry in enumerate(reg.data["workspaces"]):
        raw = entry.get("root") if isinstance(entry, dict) else None
        key = _root_key(raw) if isinstance(raw, str) and os.path.isabs(raw) else None
        if key is None:
            skipped.append(index)
        else:
            roots.add(key)
    return roots, skipped


def _root_key(root: Any) -> Optional[str]:
    """``root`` resolved and case-folded for comparison, or None when it cannot be resolved.

    A NUL byte is refused here, not left to realpath: realpath raises on it everywhere
    except Windows Python 3.12+, where it returns the path as given (gh-106242)."""
    text = str(root)
    if "\x00" in text:
        return None
    try:
        return os.path.normcase(os.path.realpath(text))
    except (OSError, ValueError):
        return None


# ── Host plane: one row per host ────────────────────────────────────────────

def _identity(spec: Any, reg: Dict[str, Any]) -> Dict[str, Any]:
    client = reg.get("aegis_client")
    if reg["status"] != "registered":
        return {"status": "unknown", "aegis_client": None}
    if client == spec.id:
        return {"status": "explicit", "aegis_client": client}
    if not client:
        known = bool(spec.client_names or spec.client_prefixes)
        return {"status": "client_info" if known else "unknown", "aegis_client": None}
    if set(client) == {"*"}:
        return {"status": "unknown", "aegis_client": None}
    return {"status": "mismatch", "aegis_client": _clean(client, 128)}


def _any(*facts: Optional[bool]) -> Optional[bool]:
    """Three-valued or: True if one fact holds, None if none holds but one is unknown."""
    return True if True in facts else (None if None in facts else False)


def _all(*facts: Optional[bool]) -> Optional[bool]:
    """Three-valued and: False if one fact fails, None if none fails but one is unknown."""
    return False if False in facts else (None if None in facts else True)


def _mcp_loads(reg: Dict[str, Any]) -> Optional[bool]:
    """Whether the host starts the aegis server: None when doctor cannot tell."""
    if reg["status"] == "absent":
        return False
    if reg["status"] != "registered":
        return None
    if reg["command_exists"] is False or reg["enabled"] is False or reg["approval"] == "denied":
        return False
    if reg["command_exists"] is None or reg["approval"] == "unknown":
        return None
    return True


def _advisory(spec: Any, ctx: _Ctx, installed: Optional[bool], reg: Dict[str, Any], bootstrap: Optional[bool],
              workspace_registered: Optional[bool]) -> Optional[bool]:
    """Whether the advisory tier reaches this host here; None when a deciding fact is unknown.

    It needs rules to serve (a governed workspace), the host on this machine
    (``installed`` is None when its only binary sits inside the workspace) and a route
    to its agent: the server loading in the host, or the bootstrap arriving whole
    (``bootstrap`` is False when the host cuts it). A host that sends no workspace finds
    the repository only through the registry, and its bootstrap sends the agent to that
    server, so it needs this workspace registered as well.
    """
    if not ctx.governed or installed is False:
        return False
    route = _any(_mcp_loads(reg), False if spec.instructions == "none" else bootstrap)
    if spec.id in _REGISTRY_BOUND:
        route = _all(workspace_registered, route)
    return _all(installed, route)


def _level(advisory: Optional[bool], floor: str, governed: bool, installed: Optional[bool]) -> str:
    """The strongest tier known to be in force for one host (AD-8), never a guess.

    Nothing is enforced on a host in an ungoverned workspace or on a host that is not
    installed; whether one whose only binary doctor will not run (inside the workspace, or
    behind an empty or relative PATH entry) is installed is unknown. The local floor
    holds for every commit made through git.
    """
    if not governed or installed is False:
        return "none"
    if installed is None:
        return "unknown"
    if floor == "active":
        return "local_floor"
    if advisory is True:
        return "advisory"
    if advisory is None or floor == "unknown":
        return "unknown"
    return "none"


def _host_row(spec: Any, ctx: _Ctx, info: _Instructions, roots: Optional[set], floor: str) -> Dict[str, Any]:
    from aegis_cli.install_hosts import launch_risk

    binary = next((found for found in (ctx.which(name) for name in spec.binaries) if found), None)
    passed = [] if binary else [hit for name in spec.binaries for hit in ctx.passed_over(name)]
    ignored = list(dict.fromkeys(hit.path for hit in passed))
    # An IDE or desktop app of the plane puts no binary on PATH; its bundle is the evidence.
    app = None if binary else _app(spec, ctx)
    # Installed: True, False, or None when the only binary is one doctor will not run.
    installed: Optional[bool] = True if binary or app else (None if passed else False)
    reg = _probe(spec, binary, ctx)
    identity = _identity(spec, reg)
    reasons: List[Dict[str, str]] = []
    unknown: List[str] = []

    def add(code: str, message: str) -> None:
        reasons.append({"code": code, "message": _clean(message, 1024)})

    names = " or ".join(f"`{b}`" for b in spec.binaries) or "a binary"
    if passed and not app:
        unknown.append("binary")
    fenced = next((hit for hit in passed if hit.reason == INSIDE_FENCE), None) if not app else None
    relative = next((hit for hit in passed if hit.reason != INSIDE_FENCE), None) if not app else None
    if fenced is not None:
        add("binary_in_workspace", f"{names} found only at {fenced.path}, inside the workspace: doctor does not "
                                   "run programs from the repository, so it cannot tell whether the host is installed")
    if relative is not None:
        add("binary_on_relative_path", f"{names} found only at {relative.path}, through the relative PATH entry "
                                       f"{relative.entry!r}, which resolves against the directory a program starts in "
                                       "(here the workspace): doctor does not run it, so it cannot tell whether the "
                                       "host is installed")
    if binary is None and not passed and not app:
        add("missing_binary", f"no {names} on PATH")
    status = reg["status"]
    if status == "absent":
        add("not_registered", f"aegis is not registered with {spec.display_name}: run aegis init --host {spec.id}")
    elif status in ("unknown", "unavailable"):
        unknown.append("registration")
        # An installed host doctor cannot ask is never "ok": unknown is not absent either.
        if status == "unknown" or installed:
            add("registration_unverifiable", f"cannot tell whether {spec.display_name} loads aegis: {reg['detail']}")
    else:
        if reg["command_exists"] is False:
            add("command_missing", f"the registered command {reg['command'][0]} does not exist: "
                                   f"run aegis init --host {spec.id}")
        elif reg["command_exists"] is None:
            unknown.append("command_exists")
            if reg["command"]:
                cmd = reg["command"][0]
                why = (f"is a relative path, which {spec.display_name} resolves against the directory it starts "
                       "the server in" if os.sep in cmd or (os.altsep and os.altsep in cmd) else
                       "is found only through an empty or relative PATH entry or inside the workspace, where "
                       "doctor does not look")
                add("command_unverifiable", f"the registered command {cmd} {why}, so doctor cannot tell whether "
                                            f"it exists: run aegis init --host {spec.id} to register an absolute path")
        risk = launch_risk(reg["command"]) if reg["command"] else None
        if risk:
            add("unsafe_registration", f"the registered command {reg['command'][0]} is an unsafe registration: "
                                       f"{risk}: run aegis init --host {spec.id}")
        if reg["approval"] == "unknown":
            add("approval_unknown", "aegis is registered only in this project's .mcp.json, which Claude Code "
                                    "runs after an approval doctor cannot see")
        if reg["enabled"] is False:
            add("registration_disabled", reg["detail"] or f"the aegis entry is disabled in {reg['source']}")
        if identity["status"] == "mismatch":
            add("identity_mismatch", f"the registration says AEGIS_CLIENT={identity['aegis_client']}, so the "
                                     f"server would act as that host: run aegis init --host {spec.id}")
        elif identity["status"] == "unknown":
            unknown.append("identity")

    budget = _budget(spec, info)
    reaches = _bootstrap_reaches(spec, info)
    # The host keeps too little of its instruction file for the bootstrap to arrive whole.
    cut = (budget["within"] is False and info.bootstrap != "missing" and spec.id in _TRUNCATES_TAIL
           and (info.block_end or 0) > budget["budget_bytes"])
    workspace_registered = None if roots is None else _root_key(ctx.root) in roots
    if roots is None:
        unknown.append("workspace_registered")
    if not ctx.governed and ctx.is_home:
        add("workspace_not_governed", f"{ctx.root} is your home directory: its .aegis/ is your user layer, "
                                      "never a governed workspace. Run aegis doctor inside a repository")
    elif not ctx.governed:
        add("workspace_not_governed", f"{ctx.root} has no .aegis/: run {ctx.setup} there")
    else:
        if info.bootstrap in ("missing", "hand_edited", "malformed"):
            add("bootstrap_" + info.bootstrap, {
                "missing": "AGENTS.md has no Aegis bootstrap block: run aegis init",
                "hand_edited": "the Aegis block in AGENTS.md was edited by hand: run aegis init --force",
                "malformed": "the Aegis block markers in AGENTS.md are broken: fix them, then run aegis init",
            }[info.bootstrap])
        if spec.instructions == "agents_md_unless_claude_md" and info.claude and not _claude_reads_agents(info):
            verb = "exists" if len(info.claude) == 1 else "exist"
            add("claude_md_shadows_agents_md", f"{_claude_names(info)} {verb} without @AGENTS.md, so Claude Code "
                                               f"does not read AGENTS.md: {_claude_import_advice(info)}")
        elif spec.instructions == "agents_md_unless_claude_md" and reaches is None and info.claude_outside:
            unknown.append("bootstrap")
            add("claude_md_outside_workspace",
                f"{info.claude_outside[0]} is outside the workspace: Claude Code does not read AGENTS.md "
                "natively when a CLAUDE.md, CLAUDE.local.md or .claude/CLAUDE.md is in the directory it starts "
                "in or a parent, and doctor reads no file outside the workspace, so it cannot tell whether "
                "AGENTS.md reaches Claude Code: add a CLAUDE.md holding the line @AGENTS.md to the workspace")
        if spec.id in _READS_AGENTS_OVERRIDE and info.override:
            add("agents_override_shadows_agents_md", "AGENTS.override.md replaces AGENTS.md for Codex")
        if cut:
            add("over_budget", f"{budget['file']} is {budget['bytes']} bytes; {spec.display_name} reads "
                               f"{budget['budget_bytes']} and the Aegis block may not reach it")
        if spec.id in _REGISTRY_BOUND and workspace_registered is False:
            add("workspace_unregistered", f"{spec.display_name} sends no workspace, so aegis finds this "
                                          f"repository only through ~/.aegis/workspaces.json: run aegis init")
        elif spec.id in _REGISTRY_BOUND and workspace_registered is None:
            add("workspace_registry_unknown", f"{spec.display_name} sends no workspace and "
                                              "~/.aegis/workspaces.json cannot be read, so doctor cannot tell "
                                              "whether aegis finds this repository")

    codes = {r["code"] for r in reasons}
    if codes & {"missing_binary", "binary_in_workspace", "binary_on_relative_path"}:
        state = "missing_binary"
    elif codes & {"not_registered", "command_missing"}:
        state = "unregistered"
    elif codes & {"registration_unverifiable", "approval_unknown", "workspace_registry_unknown",
                   "claude_md_outside_workspace", "command_unverifiable"}:
        state = "auth_unknown"
    elif codes:
        state = "policy_gap"
    else:
        state = "ok"

    advisory = _advisory(spec, ctx, installed, reg, False if cut else reaches, workspace_registered)
    level = _level(advisory, floor, ctx.governed, installed)
    # The PreToolUse hooks never change ``state`` or ``level``: their presence in a file is
    # not proof that the host runs them (presence never claims enforcement).
    hooks = _hook_row(spec, ctx)
    if hooks["status"] == "unknown":
        unknown.append("hooks")
    shown = {k: v for k, v in reg.items() if k != "aegis_client"}
    return {
        "id": spec.id,
        "display_name": spec.display_name,
        "verified_row": spec.verified,
        "experimental": not spec.verified,
        "surfaces": list(spec.surfaces),
        "state": state,
        "reasons": reasons,
        "binary": {"found": binary is not None, "path": binary, "names": list(spec.binaries), "ignored": ignored},
        "app": app,
        "registration": shown,
        "identity": identity,
        "workspace_registered": workspace_registered,
        "bootstrap": {"file": "AGENTS.md", "status": info.bootstrap, "reaches_host": reaches,
                      "stale": info.bootstrap == "outdated"},
        "budget": budget,
        "enforcement_level": level,
        "advisory": advisory,
        "hooks": hooks,
        "trust_tier": None,
        "trust_tier_status": "unavailable",  # _diagnose fills both from the repository's human_gate tier
        "stale": False,
        "unknown": unknown,
    }


# ── Host plane: PreToolUse hooks (v4.1 §2 Doctor) ──────────────────────────

_HOOK_SCOPE_FILES = {"claude-code": (("local", (".claude", "settings.local.json")),)}
# A token after which the shell starts a new command (a v3 entry may be `cd x && soma hook ...`).
_COMMAND_STARTERS = frozenset({"&&", "||", "|", ";", "&", "!", "(", "{", "then", "do", "else", "exec"})
_V3_PLUGIN = (".gemini", "config", "plugins", "governance", "hooks.json")


def _hook_files(host_id: str, ctx: _Ctx) -> List[Tuple[str, Path]]:
    """(scope, path) of each file ``host_id`` reads hooks from here: the user and project
    files ``aegis hook install`` writes, plus Claude Code's local settings."""
    from aegis_cli.hooks import registrar

    found: List[Tuple[str, Path]] = []
    for scope in registrar.SCOPES:
        path = registrar.hook_file(host_id, scope, home=ctx.home, root=ctx.root, environ=ctx.environ)
        if path is not None:
            found.append((scope, path))
    found.extend((scope, ctx.root.joinpath(*rel)) for scope, rel in _HOOK_SCOPE_FILES.get(host_id, ()))
    unique: Dict[str, Tuple[str, Path]] = {}
    for scope, path in found:  # in the home directory the project file is the user file
        unique.setdefault(os.path.normcase(os.path.abspath(str(path))), (scope, path))
    return list(unique.values())


def _runnable(path: Optional[str]) -> bool:
    return bool(path) and os.path.isfile(path) and (os.name == "nt" or os.access(path, os.X_OK))


def _hook_row(spec: Any, ctx: _Ctx) -> Dict[str, Any]:
    """Whether an Aegis PreToolUse entry for ``spec`` is in a file the host reads, and the
    tier it would give. ``status``: registered, absent, duplicate (more than one entry),
    broken (its aegis is missing), modified (not the entry install writes, so no tier is
    claimed), unknown (a host file cannot be read), unavailable (the host cannot run the
    hook here) or none (a host without Aegis hooks)."""
    from aegis_cli.hooks import registrar

    row: Dict[str, Any] = {"status": "none", "tier": None, "evidence": None, "trust": None, "detail": None,
                           "entries": [], "files": []}
    if spec.id not in registrar.HOOK_HOSTS:
        return row
    for scope, path in _hook_files(spec.id, ctx):
        entry = ctx.file(path, as_json=True)
        item = {"scope": scope, "path": str(path), "status": "absent", "error": None}
        row["files"].append(item)
        if not entry.exists:
            continue
        if entry.error:
            item.update(status="invalid", error=entry.error)
            continue
        try:
            located = registrar.aegis_handlers(spec.id, entry.data, path, strict=True)
        except registrar.ShapeError as exc:
            item.update(status="invalid", error=f"is not in the shape {spec.display_name} reads "
                                                f"('{exc.where}' must be {exc.what})")
            continue
        item["status"] = "ok"
        for keys, group_index, _handler_index, handler in located:
            groups: Any = entry.data
            for key in keys:
                groups = groups[key]
            aegis = registrar.handler_aegis(handler)
            row["entries"].append({"scope": scope, "path": str(path), "aegis": aegis, "executable": _runnable(aegis),
                                   "modified": not registrar.matches_install(spec.id, groups[group_index], handler)})
    entries = row["entries"]
    invalid = [f for f in row["files"] if f["status"] == "invalid"]
    why = registrar.unavailable_reason(spec.id, ctx.which("aegis"))
    if why:
        row.update(status=registrar.UNAVAILABLE, tier=registrar.UNAVAILABLE, detail=why)
        return row
    if len(entries) > 1:
        status = "duplicate"
    elif entries:
        status = "broken" if not entries[0]["executable"] else "modified" if entries[0]["modified"] else "registered"
    else:
        status = "unknown" if invalid else "absent"
    row.update(status=status, tier=registrar.TIERS[spec.id], evidence=registrar.EVIDENCE[spec.id])
    if status == "unknown":
        row["detail"] = f"{ctx.label(Path(invalid[0]['path']))} {invalid[0]['error']}"
    if entries and spec.id == "codex-cli":
        row["trust"] = registrar.TRUST_UNCHECKED
    return row


def _hook_findings(ctx: _Ctx, rows: List[Dict[str, Any]]) -> List[_Finding]:
    found: List[_Finding] = []
    for row in rows:
        hooks, name, host_id = row["hooks"], row["display_name"], row["id"]
        for item in hooks["files"]:
            if item["status"] == "invalid":
                path = Path(item["path"])
                found.append(_Finding("hook_file_invalid", path,
                                      f"{ctx.label(path)} {item['error']}, so {name} may skip every hook in it, and "
                                      f"aegis hook install --host {host_id} will not edit it: fix the file"))
        entries = hooks["entries"]
        if len(entries) > 1:
            where = ", ".join(f"{ctx.label(Path(e['path']))} ({e['scope']})" for e in entries)
            times = "twice" if len(entries) == 2 else f"{len(entries)} times"
            found.append(_Finding("duplicate_hook", Path(entries[1]["path"]),
                                  f"{name} has {len(entries)} Aegis PreToolUse hook entries ({where}), so it runs "
                                  f"the handler {times} per tool call: keep one (aegis hook uninstall --host "
                                  f"{host_id} --scope user|project removes one scope's)"))
        for e in entries:
            path = Path(e["path"])
            fix = (f"remove it from that file, then run aegis hook install --host {host_id}" if e["scope"] == "local"
                   else f"run aegis hook install --host {host_id}" + (" --scope project" if e["scope"] == "project"
                                                                        else ""))
            if not e["executable"]:
                found.append(_Finding("hook_aegis_missing", path,
                                      f"{ctx.label(path)}: the Aegis hook runs {e['aegis']}, which is missing or not "
                                      f"executable, so {name} gets no Aegis check from it (it fails open): {fix}"))
            elif e["modified"]:
                found.append(_Finding("hook_entry_modified", path,
                                      f"{ctx.label(path)}: the Aegis hook entry is not the entry aegis hook install "
                                      "writes (its matcher, type, command, arguments or timeout differ), so "
                                      f"{name} may not run it as its tier says: {fix}"))
    return found + _legacy_hook_findings(ctx)


def _removed_host_phases() -> frozenset:
    """The `aegis hook <phase>` commands v3 host configs called and v4 removed (cli.py's table)."""
    from aegis_cli.cli import _HOST_HOOK, REMOVED_COMMANDS

    return frozenset(name.partition(" ")[2] for name, pointer in REMOVED_COMMANDS.items()
                     if name.startswith("hook ") and pointer == _HOST_HOOK)


def _program_name(token: str) -> str:
    name = re.split(r"[\\/]", token)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _is_legacy_handler(handler: Any, phases: frozenset) -> bool:
    """Whether a hook handler calls the v3 CLI's hooks or a removed `aegis hook` phase,
    as the program of any command in its (shell) command line."""
    if not isinstance(handler, dict) or not isinstance(handler.get("command"), str):
        return False
    command, args = handler["command"], handler.get("args")
    if isinstance(args, list) and args and all(isinstance(a, str) for a in args):
        tokens = [command] + args
    else:
        from aegis_cli.hooks.registrar import command_tokens

        tokens = command_tokens(command)
    starts = True
    for index, token in enumerate(tokens[:-1]):
        if starts and tokens[index + 1] == "hook":
            program = _program_name(token)
            if program == LEGACY_SERVER:
                return True
            if program == "aegis" and index + 2 < len(tokens) and tokens[index + 2].rstrip(";&|") in phases:
                return True
        starts = token in _COMMAND_STARTERS or token.endswith((";", "&", "|"))
    return False


ListItem = Tuple[Tuple[Any, ...], int]


def _legacy_items(host_id: str, data: Dict[str, Any], phases: frozenset) -> Tuple[List[ListItem], int, int]:
    """(where the v3 entries are, handlers in the file, v3 handlers). A group whose handlers
    are all v3 goes whole; otherwise only its v3 handlers go. Every event counts, not only
    PreToolUse: v3 hooked PreInvocation and Stop too."""
    if host_id == "antigravity":
        containers = [name for name, value in data.items() if isinstance(value, dict)]
    else:
        containers = ["hooks"] if isinstance(data.get("hooks"), dict) else []
    items: List[ListItem] = []
    total = legacy = 0
    for name in containers:
        for event, listed in data[name].items():
            if not isinstance(listed, list):
                continue
            for index, item in enumerate(listed):
                inner = item.get("hooks") if isinstance(item, dict) else None
                if isinstance(inner, list):
                    old = [j for j, h in enumerate(inner) if _is_legacy_handler(h, phases)]
                    total += len(inner)
                    legacy += len(old)
                    if old and len(old) == len(inner):
                        items.append(((name, event), index))
                    else:
                        items.extend(((name, event, index, "hooks"), j) for j in old)
                elif isinstance(item, dict):
                    total += 1
                    if _is_legacy_handler(item, phases):
                        legacy += 1
                        items.append(((name, event), index))
    return items, total, legacy


def _list_location(path: Tuple[Any, ...], index: int) -> str:
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else ("." if out else "") + _clean(part)
    return f"{out}[{index}]"


def _legacy_hook_findings(ctx: _Ctx) -> List[_Finding]:
    """v3 hook entries in every hook file of every hook host (selected or not), and the
    stale v3 Antigravity plugin."""
    from aegis_cli.hooks import registrar

    files: Dict[str, Tuple[str, Path, bool]] = {}
    for host_id in registrar.HOOK_HOSTS:
        for _scope, path in _hook_files(host_id, ctx):
            files.setdefault(os.path.normcase(os.path.abspath(str(path))), (host_id, path, False))
    if ctx.home is not None:
        plugin = ctx.home.joinpath(*_V3_PLUGIN)
        files.setdefault(os.path.normcase(os.path.abspath(str(plugin))), ("antigravity", plugin, True))
    phases = _removed_host_phases()
    found: List[_Finding] = []
    for host_id, path, is_plugin in files.values():
        entry = ctx.file(path, as_json=True)
        if entry.raw is None or entry.error or not isinstance(entry.data, dict):
            continue
        items, total, legacy = _legacy_items(host_id, entry.data, phases)
        if not items:
            continue
        where = ", ".join(_list_location(p, i) for p, i in items)
        calls = f"call {LEGACY_SERVER} hook or a removed aegis hook phase"
        if is_plugin:
            code, message = "legacy_hook_plugin", f"{ctx.label(path)}: the stale v3 Antigravity plugin's hooks {calls}"
        else:
            code, message = "legacy_hook_entry", f"{ctx.label(path)}: v3 hook entries {calls}"
        message += f" ({where})"
        action = None
        if entry.refusal:
            message += f"; --fix will not change it: {entry.refusal}"
        elif is_plugin and legacy == total:
            action = _Action(path, "delete_file", _sha256(entry.raw), f"delete the file (it holds only v3 hooks, {where})")
            message += f"; nothing else is in it, so --fix deletes the file. Fix: {_FIX_HINT}"
        else:
            action = _Action(path, "remove_list_items", _sha256(entry.raw), f"remove the v3 hook entries ({where})",
                             items=tuple(items))
            message += f". Fix: {_FIX_HINT}"
        found.append(_Finding(code, path, message, location=where, action=action))
    return found


# ── Enforcement tiers (AD-8) ────────────────────────────────────────────────

def _floor_status(root: Path) -> Tuple[str, Optional[str]]:
    """The local floor's status, and why an installed, current hook never runs. The floor
    is active only for a hook that is installed, current and reached by git (hook_status
    ``reachable``; a status without the key predates it and counts as reachable)."""
    from aegis_cli.hooks import management

    try:
        st = management.hook_status(root)
    except Exception:
        return "unknown", None
    if st.get("status") == "no_git_repository":
        return "unavailable", None
    if not st.get("managed_by_aegis"):
        return "inactive", None
    if st.get("status") != "installed":
        return "outdated", None
    gone = [p for p in (st.get("interpreter"), st.get("aegis_path")) if p and not p.get("exists")]
    if gone:
        return "outdated", None
    if st.get("reachable", True) is False:
        return "inactive", _clean(st.get("unreachable_reason") or "git does not reach the Aegis block", 1024)
    return "active", None


_TIER_TEXT = {
    "advisory": ("Advisory", "AGENTS.md bootstrap, MCP instructions, JIT rules"),
    "best_effort": ("Best-effort", "per-host pre-tool hooks"),
    "local_floor": ("Local floor", "git pre-commit runs aegis check --hook (--no-verify bypasses it)"),
    "authoritative": ("Authoritative", "CI runs aegis check on the exact SHA; a human merges"),
}


def _tiers(rows: List[Dict[str, Any]], floor: str, governed: bool, unreached: Optional[str] = None,
           setup: str = "aegis init") -> List[Dict[str, Any]]:
    ids = [r["id"] for r in rows]
    reached = [r["id"] for r in rows if r["advisory"] is True]
    unsure = [r["id"] for r in rows if r["advisory"] is None]
    if ids and len(reached) == len(ids):
        advisory = "active"
    else:
        advisory = "partial" if reached else ("unknown" if unsure else "inactive")
    reach = f"reaches {', '.join(reached) or 'no selected host'}"
    if unsure:
        reach += f"; unknown for {', '.join(unsure)}"
    floor_detail = {
        "active": "the Aegis pre-commit hook is installed and current",
        "inactive": "no Aegis pre-commit hook: run aegis hook install",
        "outdated": "the Aegis pre-commit hook is outdated: run aegis hook install",
        "unavailable": "not a git repository",
        "unknown": "the git hooks directory could not be read",
    }[floor]
    if unreached:
        floor_detail = f"the Aegis pre-commit hook is installed but never runs: {unreached}; see aegis hook status"
    if not governed and floor != "unavailable":
        # A hook here, installed or not, has no rules to check: the floor is not in force.
        floor, floor_detail = "inactive", f"no .aegis/ here, so a pre-commit hook has nothing to enforce: run {setup}"
    return [
        {"tier": "advisory", "mechanism": _TIER_TEXT["advisory"][1], "hosts": ids, "status": advisory,
         "detail": reach},
        _best_effort(rows, governed, setup),
        {"tier": "local_floor", "mechanism": _TIER_TEXT["local_floor"][1], "hosts": ids, "status": floor,
         "detail": floor_detail},
        {"tier": "authoritative", "mechanism": _TIER_TEXT["authoritative"][1], "hosts": [], "status": "unavailable",
         "detail": "not checked: aegis doctor does not read CI runs; the trust tier says what GitHub enforces"},
    ]


def _hook_tier_text(host_id: str, hooks: Dict[str, Any]) -> str:
    text = f"{host_id}: {hooks['tier']} [{hooks['evidence']}]"
    return text + (f", {hooks['trust']}" if hooks["trust"] else "")


def _best_effort(rows: List[Dict[str, Any]], governed: bool, setup: str) -> Dict[str, Any]:
    """The per-host hook tier. Doctor reads files only, so a registered hook makes the tier
    ``unknown``, never active: whether a host runs it is out of doctor's sight."""
    tier = {"tier": "best_effort", "mechanism": _TIER_TEXT["best_effort"][1], "hosts": []}
    hooks = {row["id"]: row["hooks"] for row in rows}
    capable = [h for h, v in hooks.items() if v["status"] not in ("unavailable", "none")]
    hooked = [h for h in capable if hooks[h]["status"] in ("registered", "duplicate")]
    if not capable:
        reasons = "; ".join(v["detail"] for v in hooks.values() if v["detail"]) or "no selected host has Aegis hooks"
        return dict(tier, status="unavailable", detail=reasons)
    if not governed:
        return dict(tier, status="inactive",
                    detail=f"no .aegis/ here, so a registered hook passes every call: run {setup}")
    if hooked:
        said = "; ".join(_hook_tier_text(h, hooks[h]) for h in hooked)
        return dict(tier, hosts=hooked, status="unknown",
                    detail=f"registered for {said}. Doctor reads the host files only and cannot confirm that a host "
                           "runs them; each fails open when Aegis errors")
    unreadable = [h for h in capable if hooks[h]["status"] == "unknown"]
    if unreadable:
        return dict(tier, status="unknown",
                    detail=f"cannot tell for {', '.join(unreadable)}: a hook file cannot be read (see the warnings)")
    modified = [h for h in capable if hooks[h]["status"] == "modified"]
    if modified:
        return dict(tier, status="unknown",
                    detail=f"cannot tell for {', '.join(modified)}: its Aegis hook entry is not the one aegis hook "
                           "install writes (see the warnings)")
    absent = [h for h in capable if hooks[h]["status"] == "absent"]
    broken = [h for h in capable if hooks[h]["status"] == "broken"]
    parts = [f"no Aegis PreToolUse hook registered for {', '.join(absent)}"] if absent else []
    if broken:
        parts.append(f"the Aegis hook of {', '.join(broken)} runs a missing aegis")
    return dict(tier, status="inactive", detail="; ".join(parts) + ": run aegis hook install --host <host>")


# ── Findings ────────────────────────────────────────────────────────────────

@dataclass
class _Action:
    """One reported change --fix may make to one file."""

    path: Path
    kind: str  # remove_keys | remove_lines | remove_list_items | delete_file | enable_packaged_ast_drivers
    sha256: Optional[str]
    describe: str
    keys: Tuple[Tuple[str, ...], ...] = ()
    lines: Tuple[Tuple[int, int], ...] = ()
    # remove_list_items: (key path to a JSON list, index in it); the file is unchanged since
    # the check (sha256), so the indexes still name the entries doctor reported.
    items: Tuple[Tuple[Tuple[Any, ...], int], ...] = ()


@dataclass
class _Finding:
    code: str
    path: Path
    message: str
    location: Optional[str] = None
    severity: str = "warning"
    action: Optional[_Action] = None

    def __post_init__(self) -> None:
        # Messages quote paths, keys and parser errors from files a repository can write.
        self.message = _clean(self.message, 4096)

    def as_dict(self) -> Dict[str, Any]:
        # A finding is fixable exactly when it carries the action --fix would take.
        return {"code": self.code, "severity": self.severity, "path": str(self.path), "location": self.location,
                "message": self.message, "fixable": self.action is not None}


def _location(keys: Tuple[str, ...]) -> str:
    """Where a key is, for people: the keys (project paths among them) without control sequences."""
    out = []
    for key in keys:
        if out and out[-1] == "projects":
            out[-1] = f"projects[{_clean(key)}]"
        else:
            out.append(_clean(key))
    return ".".join(out)


def _key_finding(ctx: _Ctx, entry: _File, code: str, keys: Tuple[str, ...], message: str,
                 fixable: bool = True, blocked: Optional[str] = None) -> _Finding:
    where = _location(keys)
    action = None
    text = f"{ctx.label(entry.path)}: {message} ({where})"
    if not fixable:
        text += f"; {blocked}" if blocked else ""
    elif entry.refusal:
        text += f"; --fix will not change it: {entry.refusal}"
    else:
        action = _Action(entry.path, "remove_keys", _sha256(entry.raw or b""), f"remove {where}", keys=(keys,))
        text += f". Fix: {_FIX_HINT}"
    return _Finding(code, entry.path, text, location=where, action=action)


def _mcp_findings(ctx: _Ctx, claude_user: bool) -> List[_Finding]:
    found: List[_Finding] = []
    files: List[Tuple[Path, str]] = []
    if ctx.home is not None:
        files.append((ctx.home / ".mcp.json", "dot_mcp"))
    files.append((ctx.root / ".mcp.json", "dot_mcp"))
    claude_cfg = _claude_config(ctx)
    if claude_cfg is not None:
        files.append((claude_cfg, "claude"))
    files.extend((p, "desktop") for p in _desktop_configs(ctx))
    for spec in ctx.selected:
        path = _host_json_path(spec, ctx)
        if path is not None:
            files.append((path, "host"))
    seen = set()
    no_user = "keep it until aegis init --host claude-code registers aegis for your user"
    for path, kind in files:
        key = os.path.normcase(os.path.abspath(str(path)))
        if key in seen:
            continue
        seen.add(key)
        entry = ctx.file(path, as_json=True)
        if not entry.exists:
            continue
        if entry.error:
            found.append(_Finding("unreadable_config", path, f"{ctx.label(path)} {entry.error}; doctor did not "
                                  "read it and --fix will not change it"))
            continue
        data = entry.data or {}
        servers = data.get("mcpServers") if isinstance(data.get("mcpServers"), dict) else {}
        if LEGACY_SERVER in servers:
            found.append(_key_finding(ctx, entry, "legacy_mcp_entry", ("mcpServers", LEGACY_SERVER),
                                      _LEGACY_ENTRY))
        if SERVER in servers and kind == "dot_mcp":
            found.append(_key_finding(ctx, entry, "misplaced_mcp_entry", ("mcpServers", SERVER),
                                      "Aegis v4 registers 'aegis' per user, never in a .mcp.json file",
                                      fixable=claude_user, blocked=no_user))
        if SERVER in servers and kind == "desktop":
            found.append(_key_finding(ctx, entry, "desktop_mcp_entry", ("mcpServers", SERVER),
                                      "Claude Desktop is identity only in v4 (H4); its 'aegis' entry moves out"))
        if kind == "claude" and isinstance(data.get("projects"), dict):
            for name, project in data["projects"].items():
                psrv = project.get("mcpServers") if isinstance(project, dict) else None
                if not isinstance(psrv, dict):
                    continue
                if LEGACY_SERVER in psrv:
                    found.append(_key_finding(ctx, entry, "legacy_mcp_entry",
                                              ("projects", name, "mcpServers", LEGACY_SERVER),
                                              _LEGACY_ENTRY))
                if SERVER in psrv and claude_user:
                    found.append(_key_finding(ctx, entry, "misplaced_mcp_entry",
                                              ("projects", name, "mcpServers", SERVER),
                                              "a local-scope 'aegis' entry shadows your user registration"))
    return found


_LEGACY_MARKER = re.compile(r"^<!-- (SOMA|AEGIS):(START|END) -->[ \t]*$")


def _legacy_ranges(text: str) -> Tuple[List[Tuple[int, int]], bool]:
    """(line ranges of well-formed SOMA/AEGIS START..END blocks, markers are balanced).

    Markers shown inside a fenced code block are text, not a block. Inside an open block
    the content is v3's own (rule text with its fences), so only its END marker counts.
    """
    ranges, open_at, fence = [], None, None
    for index, line in enumerate(text.splitlines(True)):
        bare = line.rstrip("\r\n")
        if index == 0 and bare.startswith(_BOM):
            bare = bare[1:]
        if open_at is None:
            inside = fence is not None
            fence = _fence_step(fence, bare)
            if inside or fence is not None:
                continue
        match = _LEGACY_MARKER.match(bare)
        if not match:
            continue
        kind, edge = match.groups()
        if edge == "START":
            if open_at is not None:
                return ranges, False
            open_at = (index, kind)
        else:
            if open_at is None or open_at[1] != kind:
                return ranges, False
            ranges.append((open_at[0], index))
            open_at = None
    return ranges, open_at is None


def _instruction_files(ctx: _Ctx) -> List[Path]:
    files = [ctx.root / name for name in ("CLAUDE.md", "AGENTS.md", "GEMINI.md")]
    claude_dir = _claude_dir(ctx)
    if claude_dir is not None:
        files.append(claude_dir / "CLAUDE.md")
    if ctx.home is not None:
        codex_home = ctx.environ.get("CODEX_HOME")
        files.append((Path(codex_home) if codex_home else ctx.home / ".codex") / "AGENTS.md")
        files.append(ctx.home / ".gemini" / "GEMINI.md")
    return files


def _legacy_block_findings(ctx: _Ctx) -> List[_Finding]:
    found = []
    for path in _instruction_files(ctx):
        entry = ctx.file(path)
        if entry.raw is None:
            continue
        try:
            text = entry.raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        ranges, balanced = _legacy_ranges(text)
        if not ranges and balanced:
            continue
        label = ctx.label(path)
        where = ", ".join(f"lines {a + 1}-{b + 1}" for a, b in ranges) or None
        if not balanced:
            found.append(_Finding("legacy_block", path, f"{label}: unbalanced SOMA/AEGIS START/END markers; "
                                  "remove the old block by hand (--fix will not guess)", location=where))
            continue
        message = f"{label}: legacy Aegis/Soma rules block ({where})"
        action = None
        if entry.refusal:
            message += f"; --fix will not change it: {entry.refusal}"
        elif _without_lines(entry.raw, ranges) is None:
            # An emptied CLAUDE.md would still keep Claude Code from reading AGENTS.md, so
            # the file goes; the plan the user confirms says so.
            action = _Action(path, "delete_file", _sha256(entry.raw),
                             f"delete the file (it holds only the legacy block, {where})")
            message += f"; nothing else is in the file, so --fix deletes the file. Fix: {_FIX_HINT}"
        else:
            action = _Action(path, "remove_lines", _sha256(entry.raw), f"remove the legacy block ({where})",
                             lines=tuple(ranges))
            message += f". Fix: {_FIX_HINT}"
        found.append(_Finding("legacy_block", path, message, location=where, action=action))
    return found


def _budget_findings(ctx: _Ctx, info: _Instructions) -> List[_Finding]:
    found = []
    budgets = {s.id: s.budget_bytes for s in ctx.selected if s.budget_bytes}
    agent_hosts = [s for s in ctx.selected if s.budget_bytes and s.instructions in ("agents_md", "agents_md_unless_claude_md")]
    if info.agents_bytes is not None:
        over = [s.id for s in agent_hosts if info.agents_bytes > s.budget_bytes]
        if over:
            found.append(_Finding("instructions_over_budget", ctx.root / "AGENTS.md",
                                  f"AGENTS.md is {info.agents_bytes} bytes, over the budget of {', '.join(over)}; "
                                  "move text out of it (rules belong in .aegis/rules/)"))
    claude_budget = budgets.get("claude-code")
    if claude_budget:
        claude_dir = _claude_dir(ctx)
        for path in [ctx.root / "CLAUDE.md"] + ([claude_dir / "CLAUDE.md"] if claude_dir else []):
            entry = ctx.file(path)
            if entry.raw is not None and len(entry.raw) > claude_budget:
                found.append(_Finding("instructions_over_budget", path,
                                      f"{ctx.label(path)} is {len(entry.raw)} bytes, over Claude Code's "
                                      f"{claude_budget}; inlined v3 rules belong in .aegis/rules/, served by aegis_scan"))
    return found


def _workspace_findings(ctx: _Ctx, info: _Instructions) -> List[_Finding]:
    found = []
    if info.claude and not _claude_reads_agents(info):
        where = next((f for f in info.claude if f.name == "CLAUDE.md"), info.claude[0])
        verb = "does" if len(info.claude) == 1 else "do"
        found.append(_Finding("claude_md_without_agents_import", where.path,
                              f"{_claude_names(info)} {verb} not import @AGENTS.md, so Claude Code skips AGENTS.md; "
                              f"{_claude_import_advice(info)}"))
    if info.override:
        found.append(_Finding("agents_override", ctx.root / "AGENTS.override.md",
                              "AGENTS.override.md replaces AGENTS.md for Codex; move its text into AGENTS.md"))
    if info.bootstrap == "outdated":
        found.append(_Finding("bootstrap_outdated", ctx.root / "AGENTS.md",
                              "the Aegis block in AGENTS.md is from another aegis version: run aegis init",
                              severity="info"))
    return found


def _bootstrap_tool_findings(ctx: _Ctx, info: _Instructions, rows: List[Dict[str, Any]]) -> List[_Finding]:
    """Hosts found on this machine whose agent reads the bootstrap in AGENTS.md, which
    tells it to call aegis_scan, while the host has no ``aegis`` server: the field case of
    an IDE that read AGENTS.md but had no tools. Any registrable host counts, selected or
    not; a registration doctor cannot read is unknown, never absent, so it is not one."""
    from aegis_core import hosts

    if not ctx.governed or info.bootstrap not in ("current", "outdated"):
        return []
    by_id = {row["id"]: row for row in rows}
    found = []
    for spec in hosts.all_hosts(phase=1):
        if spec.registration is None or spec.retired or _bootstrap_reaches(spec, info) is not True:
            continue
        evidence = _plane_found(spec, ctx)
        if evidence is None:
            continue
        row = by_id.get(spec.id)
        if row is not None:
            status = row["registration"]["status"]
        else:
            binary = next((b for b in (ctx.which(name) for name in spec.binaries) if b), None)
            status = _probe(spec, binary, ctx)["status"]
        if status != "absent":
            continue
        found.append(_Finding(
            "bootstrap_without_tools", ctx.root / "AGENTS.md",
            f"AGENTS.md carries the Aegis bootstrap, which tells {spec.display_name}'s agent to call the aegis "
            f"tools, but {spec.display_name} (found: {evidence}) has no Aegis MCP server: "
            f"run aegis init --host {spec.id}"))
    return found


def _worktree_ledger_findings(ctx: _Ctx) -> List[_Finding]:
    """Rows in a worktree's own ledger that the shared ledger (v4.2) does not hold: Aegis
    no longer reads them, so rules show less evidence until aegis migrate --apply merges them."""
    if ctx.is_home:
        return []
    from aegis_core import migrate
    from aegis_core.workspace.layout import WorkspaceLayout

    pending = migrate.pending_worktree_rows(ctx.root)
    if not pending:
        return []
    return [_Finding("worktree_ledger_pending", WorkspaceLayout(ctx.root).ledger_file,
                     f"{pending} outcome row(s) in per-worktree ledgers are not in the shared ledger, so rule "
                     "evidence is understated: run aegis migrate to see the merge, then aegis migrate --apply")]


def _upgrade_findings(ctx: _Ctx) -> List[_Finding]:
    """v3 state here that v4 never reads (discovery.unmigrated_state): status, scan and sync
    refuse such a workspace, and doctor, which still runs in it, must not call it healthy.
    The home directory's .aegis/ is the user plane, which aegis migrate never converts."""
    if ctx.is_home:
        return []
    from aegis_core.workspace import discovery

    # The helper comes with the commands that refuse; a build without it has neither.
    pending = getattr(discovery, "unmigrated_state", None)
    found = list(pending(ctx.root)) if pending is not None else []
    if not found:
        return []
    return [_Finding("unmigrated_v3_state", ctx.root / found[0],
                     f"unmigrated v3 state: {', '.join(found)}. Aegis v4 does not read it, and aegis status, "
                     "scan and sync refuse to run until it is converted: run aegis migrate to see the "
                     "conversion, then aegis migrate --apply")]


def _home_rules_finding(ctx: _Ctx) -> List[_Finding]:
    if ctx.home is None:
        return []
    from aegis_core.workspace.layout import UserLayout

    rules = UserLayout(ctx.home).rules_dir
    if not rules.is_dir() or rules.is_symlink() or any(rules.rglob("*.md")):
        return []
    return [_Finding("home_rules_dir", rules,
                     f"{ctx.label(rules)} is empty; v3.3 created it when an MCP server started in your home "
                     "directory. v4 reads it as your personal read-only rule layer: remove it if you keep no "
                     "rules there (doctor --fix leaves directories alone)", severity="info")]


#: sha256 of every rules/*.md and rules/.oracles/*.md file shipped in the v3.0.0-v3.3.0
#: wheels, which v3's Gemini and Kiro adapters copied byte for byte into
#: ~/.gemini/config/rules and ~/.kiro/steering. Computed from the release tags with
#: ``git show vX:rules/<file> | sha256sum``. A copy is removed only on an exact match;
#: names and content are never compared (defense #39).
V3_SHIPPED_RULE_SHA256 = frozenset({
    "acab95f21fc4eb254337fc84fe87dbcd8b059173fb56fe520f385224e27825a2",  # .oracles/architectural-tenets
    "af94c7153052c7488e0e67d86e780a74fdf106caf45da65244cc9fb9643130ba",  # .oracles/atomic-workstream-protocol
    "3d605fdfe36b2fbef771776c43c079dffbda2a593e71cb5f04175e23807fe9a2",  # .oracles/documentation
    "03a9e189a1c72f6178d9c1c5eb139fca008db810cd14eddc56400b014b9ce4db",  # .oracles/feature-specs
    "e5bc5f348d4e2cdf93457471c60b239ab6d64f2420e349f368e4995396c2afc5",  # .oracles/git-workflow
    "ca215d78f371e0f7aa4ad562a22be47db42e639d0cb28797dc7971157db0ddd8",  # .oracles/optional-import-guard (3.0)
    "63a857db70e56ceabda0fd07412f8924b128e227ec94b63d839497ef73b7152b",  # .oracles/optional-import-guard (3.1+)
    "ded22d86c5f47a0a13f64f9da99d543d276ddf830017b6a63f1c5a6e78b5c021",  # .oracles/polyglot-standards
    "337cee795219e24354a7850acebb9d79e6266e595ca7d31e4598d0d21b9e82f4",  # .oracles/tdd-protocol (3.0)
    "d33b2a6ebd2dc7c81ac3b98c060e52c38bb80baaf6362a3aea22900463af74c8",  # .oracles/tdd-protocol (3.1+)
    "863c28d335a31e48a1aef27c83b32dcab881029b3eb07a955e0b8eadd5d198e8",  # .oracles/testing
    "12d8813c7b251bc310e8122305c6ee7778fe01483dd4103691b26000a3369354",  # META (3.0)
    "4879bfb58b4a5bd3344e0278c815ce33b90ae746f694f6b82b52e87e80938582",  # META (3.1+)
    "f7ec0a8f721b64f8d37b5f259e64c86470d98a00dd3e535e68b4ab33813d486c",  # ci-green-before-release
    "20b2f3294ef1e9ceb23c4714c3d1ed95cd89f6828dd57230099da9e62fd43ecc",  # core-change-protocol (3.0)
    "8b85634178a5e121581ca98687c490c55c37a0dae4a36950866631fa215f2dcd",  # core-change-protocol (3.1+)
    "4b1656771eab2a652e0b41f221be1f5712565493506295edd3de06be44978e0c",  # cost-optimization (3.0)
    "db76ddf60f833f0b0070e0a811cdcd101e02ccc204956d6c62609e929ae13955",  # cost-optimization (3.1+)
    "25600eecc61dbd447e67ae9d43255425efbcf94195930b8c8ca11c771d26add5",  # desktop-automation
    "91fdf925befe794b662d882a069fe7035c5acf731e413d961b9e1c83d6432447",  # destructive-ops
    "2473444c146b5d36d0edefd74347e0175e76a355536ab5d5df51514b69ba7ed1",  # gitflow-review-gate (3.0)
    "18357403da55489f326c15dad044ded615badaea7b77f37aeb7757f163bdbb3a",  # gitflow-review-gate (3.1+)
    "2be52fdd2f290e1cbd81600e35d8198bc6766b5c827c0d1b240ce060470984fc",  # no-pre-existing-excuse (3.0)
    "5187404be379aca6b0cb0ec62436054ebfcad320c264a34ef95e271a42c95767",  # no-pre-existing-excuse (3.1+)
    "27b596123c2a88dea15b82a846e07215774e0b1dfdc2c3b67f2336b89d3fad3b",  # providence (3.0)
    "6417ece31939ece9e3f6fec52413d4f8c329fbf38be8c104b01b2f28ee0a5fe6",  # providence (3.1+)
    "04946d5d7b525f24284ae51f2d958f8b5fcc4d3ed891e391ceec71f5dd5ddd0f",  # subagent-delegation (3.0)
    "5d54ce9b04be9572698749908558800cbf2d8acdffc15e7b7a651fbf6f39488f",  # subagent-delegation (3.1+)
})


def _v3_copy_findings(ctx: _Ctx) -> List[_Finding]:
    if ctx.home is None:
        return []
    found = []
    for base in (ctx.home / ".gemini" / "config" / "rules", ctx.home / ".kiro" / "steering"):
        for directory in (base, base / ".oracles"):
            if not directory.is_dir() or directory.is_symlink():
                continue
            for path in sorted(directory.glob("*.md")):
                entry = ctx.file(path)
                if entry.is_link or entry.raw is None or _sha256(entry.raw) not in V3_SHIPPED_RULE_SHA256:
                    continue
                message = f"{ctx.label(path)}: an unedited copy of a rule Aegis v3 shipped"
                action = None
                if entry.refusal:
                    message += f"; --fix will not change it: {entry.refusal}"
                else:
                    action = _Action(path, "delete_file", _sha256(entry.raw), "delete the v3 rule copy")
                    message += f". Fix: {_FIX_HINT}"
                found.append(_Finding("v3_rule_copy", path, message, action=action))
    return found


# ── The diagnosis ───────────────────────────────────────────────────────────

def _selection(root: Path, governed: bool, ctx: _Ctx) -> Tuple[Tuple[Any, ...], str, List[_Finding]]:
    from aegis_core import hosts
    from aegis_core.config import ConfigError, RepoConfig
    from aegis_core.workspace.layout import WorkspaceLayout

    config = WorkspaceLayout(root).config_file
    # An experimental row joins the default matrix only where its plane is on this machine.
    default = tuple(h for h in hosts.all_hosts(phase=1) if h.registration is not None
                    and (h.verified or _plane_found(h, ctx) is not None))
    if not governed:
        return default, "default", []
    try:
        chosen = RepoConfig.load(root).hosts
    except ConfigError as exc:
        return default, "default", [_Finding("unreadable_config", config, str(exc))]
    if not chosen:
        return default, "default", []
    known = {h.id: h for h in hosts.HOSTS if h.registration is not None}
    table = {h.id: h for h in hosts.HOSTS}
    named = list(dict.fromkeys(chosen))
    retired = [h for h in named if h in table and table[h].retired]
    unknown = [h for h in named if h not in known and h not in retired]
    notes = [_Finding("retired_host", config, f"{config.name} selects {h!r}, a retired host: {table[h].retired}",
                      severity="info") for h in retired]
    if unknown:
        notes.append(_Finding("unknown_host", config,
                              f"{config.name} selects {', '.join(repr(h) for h in unknown)}, which doctor "
                              "cannot check", severity="info"))
    picked = tuple(h for h in hosts.HOSTS if h.id in set(chosen) and h.id in known)
    return picked, "config", notes


@dataclass
class _Diagnosis:
    ctx: _Ctx
    rows: List[Dict[str, Any]]
    tiers: List[Dict[str, Any]]
    findings: List[_Finding]
    trust: Any = None  # the human_gate TierReport
    modes: Any = None  # the shared state's StateModes, or None when it cannot be read


def _diagnose(root: Path, environ: Optional[Mapping[str, str]] = None) -> _Diagnosis:
    from aegis_core.workspace.layout import UserLayout, is_aegis_workspace

    environ = os.environ if environ is None else environ
    layout = UserLayout.current()
    # The home directory's .aegis/ is the user plane (~/.aegis), never a workspace.
    is_home = _is_home(root)
    governed = is_aegis_workspace(root) and not is_home
    ctx = _Ctx(root=root, governed=governed, home=layout.home if layout else None, environ=environ,
               selected=(), selection="default", is_home=is_home,
               setup="aegis init" if governed or is_home else _setup_command(root))
    ctx.selected, ctx.selection, notes = _selection(root, governed, ctx)
    selected = ctx.selected
    info = _instructions(ctx)
    roots, skipped = _registered_roots(ctx)
    floor, unreached = _floor_status(root)
    rows = [_host_row(spec, ctx, info, roots, floor) for spec in selected]
    claude_user = _claude_user_registered(ctx)
    findings = (notes + _upgrade_findings(ctx) + _worktree_ledger_findings(ctx) + _workspace_findings(ctx, info) + _mcp_findings(ctx, claude_user)
                + _legacy_block_findings(ctx) + _budget_findings(ctx, info) + _home_rules_finding(ctx)
                + _v3_copy_findings(ctx) + _hook_findings(ctx, rows) + _bootstrap_tool_findings(ctx, info, rows))
    if roots is None and ctx.home is not None:
        findings.append(_Finding("unreadable_config", UserLayout(ctx.home).workspaces_file,
                                 "~/.aegis/workspaces.json cannot be read as a v1 registry; doctor "
                                 "reports workspace registration as unknown"))
    for index in skipped:
        findings.append(_Finding("registry_entry_skipped", UserLayout(ctx.home).workspaces_file,
                                 f"~/.aegis/workspaces.json: entry {index} has no absolute 'root' that resolves; "
                                 "aegis skips it (run aegis init in that workspace to register it again)",
                                 location=f"workspaces[{index}]"))
    trust = human_gate.detect_tier(root)
    for row in rows:
        row["trust_tier"], row["trust_tier_status"] = trust.tier, "detected"
    return _Diagnosis(ctx, rows, _tiers(rows, floor, governed, unreached, ctx.setup), findings, trust,
                      _state_modes(root))


def _state_modes(root: Path) -> Any:
    from aegis_core import storage
    from aegis_core.errors import AegisError

    try:
        return storage.shared_state_modes(root)
    except (AegisError, OSError):
        return None


def _claude_user_registered(ctx: _Ctx) -> bool:
    path = _claude_config(ctx)
    if path is None:
        return False
    cfg = ctx.file(path, as_json=True)
    return not cfg.error and _server_entry(cfg.data) is not None


# ── --fix ───────────────────────────────────────────────────────────────────

class _Refused(Exception):
    """A fix that must not be applied; the message says why."""


def _stdin_is_tty() -> bool:
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def _confirm(prompt: str) -> bool:
    """Ask on the terminal; anything but y/yes is no. Without a terminal the answer is no."""
    if not _stdin_is_tty():
        print("stdin is not a terminal, so nothing was applied: re-run with --yes to apply these changes.")
        return False
    try:
        answer = input(prompt)
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def _backup_root(home: Path) -> Path:
    from aegis_core.workspace.layout import UserLayout

    layout = UserLayout(home)
    for path in (layout.aegis_dir, layout.backups_dir):
        if path.is_symlink():
            raise _Refused(f"{path} is a symlink; Aegis keeps backups only in a real directory")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    target = layout.backups_dir / stamp
    target.mkdir(parents=True, mode=0o700)
    return target


def _current_bytes(path: Path, expected: Optional[str]) -> Optional[bytes]:
    """The file's bytes if it is still the regular, single-link file doctor checked."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        if expected is None:
            return None
        raise _Refused("it no longer exists")
    refusal = _write_refusal(path, st)
    if refusal:
        raise _Refused(refusal)
    with open(path, "rb") as fh:
        data = fh.read()
    if expected is not None and _sha256(data) != expected:
        raise _Refused("it changed since the check; re-run aegis doctor")
    return data


def _dump_like(original: bytes, data: Dict[str, Any]) -> bytes:
    """``data`` serialized the way ``original`` was: its indent, line endings and final newline."""
    text = original.decode("utf-8")
    match = re.search(r"\n([ \t]+)\"", text)
    indent: Any
    if match:
        indent = match.group(1) if "\t" in match.group(1) else len(match.group(1))
    else:
        indent = 2 if "\n" in text.strip() else None
    out = json.dumps(data, indent=indent, ensure_ascii=False)
    if "\r\n" in text:
        out = out.replace("\n", "\r\n")
    if text.endswith(("\n", "\r\n")):
        out += "\r\n" if "\r\n" in text else "\n"
    return out.encode("utf-8")


def _without_keys(raw: bytes, keys: Sequence[Tuple[str, ...]]) -> bytes:
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs, parse_constant=_reject_constant)
    for path in keys:
        node = data
        for part in path[:-1]:
            node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, dict) or path[-1] not in node:
            raise _Refused(f"{_location(path)} is no longer there")
        del node[path[-1]]
    return _dump_like(raw, data)


def _without_lines(raw: bytes, ranges: Sequence[Tuple[int, int]]) -> Optional[bytes]:
    """The bytes with the line ranges removed, or None when nothing but whitespace is left.

    A byte-order mark stays at the start of the file even when its first line goes.
    """
    text = raw.decode("utf-8")
    bom = _BOM if text.startswith(_BOM) else ""
    lines = text[len(bom):].splitlines(True)
    drop = {i for a, b in ranges for i in range(a, b + 1)}
    kept = "".join(line for i, line in enumerate(lines) if i not in drop)
    return (bom + kept).encode("utf-8") if kept.strip(" \t\r\n") else None


def _without_list_items(raw: bytes, items: Sequence[Tuple[Tuple[Any, ...], int]]) -> bytes:
    """The JSON with the listed entries removed from their lists. ``raw`` is byte-identical
    to what doctor checked (sha256), so every path resolves; every list is found before any
    entry goes, so removing one never shifts another's index."""
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs, parse_constant=_reject_constant)
    targets: Dict[int, Tuple[list, set]] = {}
    for path, index in items:
        node: Any = data
        for part in path:
            node = node[part]
        targets.setdefault(id(node), (node, set()))[1].add(index)
    for node, indexes in targets.values():
        for index in sorted(indexes, reverse=True):
            del node[index]
    return _dump_like(raw, data)


@dataclass
class _Change:
    path: Path
    kind: str
    sha256: Optional[str]
    describe: List[str] = field(default_factory=list)
    keys: List[Tuple[str, ...]] = field(default_factory=list)
    lines: List[Tuple[int, int]] = field(default_factory=list)
    items: List[Tuple[Tuple[Any, ...], int]] = field(default_factory=list)


def _plan(findings: List[_Finding], ast_missing: List[str], root: Path) -> List[_Change]:
    changes: Dict[str, _Change] = {}
    for finding in findings:
        action = finding.action
        if action is None:
            continue
        key = os.path.normcase(os.path.abspath(str(action.path)))
        change = changes.setdefault(key, _Change(action.path, action.kind, action.sha256))
        change.describe.append(action.describe)
        change.keys.extend(action.keys)
        change.lines.extend(action.lines)
        change.items.extend(action.items)
    plan = list(changes.values())
    if ast_missing:
        from aegis_core.workspace.layout import WorkspaceLayout

        plan.append(_Change(WorkspaceLayout(root).config_file, "enable_packaged_ast_drivers", None,
                            [f"enable the packaged AST drivers for {', '.join(ast_missing)}"]))
    return plan


def _apply(plan: List[_Change], home: Optional[Path], root: Path) -> Tuple[List[Dict[str, Any]], Optional[Path]]:
    from aegis_core.storage import atomic_write_bytes

    results: List[Dict[str, Any]] = []

    def result(change: _Change, status: str, action: str, reason: Optional[str] = None) -> None:
        results.append({"action": action, "path": str(change.path), "status": status,
                        "changes": list(change.describe), "reason": None if reason is None else _clean(reason, 1024)})

    if home is None:
        for change in plan:
            result(change, "failed", change.kind, "no home directory for ~/.aegis/backups")
        return results, None
    try:
        backup = _backup_root(home)
    except (_Refused, OSError) as exc:
        for change in plan:
            result(change, "failed", change.kind, f"no backup could be made: {exc}")
        return results, None

    manifest: List[Dict[str, Any]] = []
    for index, change in enumerate(plan, 1):
        action = change.kind
        try:
            current = _current_bytes(change.path, change.sha256)
            if current is not None:
                name = f"{index:02d}-{change.path.name}"
                # Owner-only whatever the original's bits: a backup of ~/.claude.json holds tokens.
                atomic_write_bytes(backup / name, current, mode=0o600)
                manifest.append({"path": str(change.path), "backup": name, "sha256": _sha256(current),
                                 "action": action})
                _write_manifest(backup, manifest)
            if change.kind == "remove_keys":
                atomic_bytes = _without_keys(current, change.keys)
                _current_bytes(change.path, change.sha256)  # compare before replace
                atomic_write_bytes(change.path, atomic_bytes)
            elif change.kind == "remove_list_items":
                edited = _without_list_items(current, change.items)
                _current_bytes(change.path, change.sha256)
                atomic_write_bytes(change.path, edited)
            elif change.kind == "remove_lines":
                kept = _without_lines(current, change.lines)
                if kept is None:  # the plan said "edit"; deleting would be a change nobody confirmed
                    raise _Refused("only the legacy block would be left; re-run aegis doctor")
                _current_bytes(change.path, change.sha256)
                atomic_write_bytes(change.path, kept)
            elif change.kind == "delete_file":
                _current_bytes(change.path, change.sha256)
                os.unlink(change.path)
            elif change.kind == "enable_packaged_ast_drivers":
                from aegis_core.ast.detect import detect_project_languages, provision_ast_driver_slots

                provision_ast_driver_slots(root, detect_project_languages(root))
        except _Refused as exc:
            result(change, "skipped", action, str(exc))
            continue
        except Exception as exc:  # report and keep going: other files are independent
            result(change, "failed", action, str(exc))
            continue
        result(change, "applied", action)
    return results, backup


def _write_manifest(backup: Path, files: List[Dict[str, Any]]) -> None:
    from aegis_core.storage import atomic_write_bytes

    doc = {"schema": "aegis.doctor.backup/v1", "created_at": _utc_now(), "aegis_version": _aegis_version(),
           "files": files}
    atomic_write_bytes(backup / "manifest.json", (json.dumps(doc, indent=2) + "\n").encode("utf-8"), mode=0o600)


# ── Output ──────────────────────────────────────────────────────────────────

_CHECKS: Tuple[Tuple[str, bool], ...] = (
    # (id, failing it fails the run); advisory checks only warn.
    ("python_version", True), ("zero_dependencies", True), ("rules", True), ("state_dir", True),
    ("cli_on_path", True), ("precommit_hook", True), ("ast_drivers", False), ("mcp_launcher", False),
)


def _registered_launchers(rows: List[Dict[str, Any]]) -> List[Registered]:
    """The command each host has registered, where doctor could read it."""
    return [(row["id"], row["registration"]["command"]) for row in rows
            if row["registration"]["status"] == "registered" and row["registration"]["command"]]


def _run_checks(root: Path, fix_ast: bool, only: Optional[Sequence[str]] = None,
                registered: Sequence[Registered] = ()) -> List[Dict[str, Any]]:
    calls: Dict[str, Callable[[], Optional[bool]]] = {
        "python_version": _check_python_version,
        "zero_dependencies": _check_zero_dependencies,
        "rules": lambda: _check_rules(root),
        "state_dir": lambda: _check_state_dir(root),
        "cli_on_path": lambda: _check_cli_resolvable(root),
        "precommit_hook": lambda: _check_precommit_hook(root),
        "ast_drivers": lambda: _check_ast_drivers(root, fix=fix_ast),
        "mcp_launcher": lambda: _check_mcp_launcher(workspace=root, registered=registered),
    }
    out = []
    for check_id, blocking in _CHECKS:
        if only is not None and check_id not in only:
            continue
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = calls[check_id]()
        status = "skip" if ok is None else ("pass" if ok else ("fail" if blocking else "warn"))
        # The lines quote rule file names, loader errors and paths a repository chooses:
        # cleaned here, at the one place every check's output passes.
        text = "".join(_clean(line, 4096) + "\n" for line in buf.getvalue().splitlines())
        out.append({"id": check_id, "status": status, "text": text,
                    "detail": [line.strip() for line in text.splitlines() if line.strip()]})
    return out


def _summary(checks: List[Dict[str, Any]], findings: List[_Finding]) -> Dict[str, int]:
    counted = [c for c in checks if c["status"] != "skip"]
    warn_checks = sum(c["status"] == "warn" for c in counted)
    return {"passed": sum(c["status"] == "pass" for c in counted),
            "warnings": warn_checks + sum(f.severity == "warning" for f in findings),
            "failed": sum(c["status"] == "fail" for c in counted), "total": len(counted)}


def _payload(diag: _Diagnosis, checks: List[Dict[str, Any]]) -> Dict[str, Any]:
    ctx = diag.ctx
    summary = _summary(checks, diag.findings)
    unknown = [f"{r['id']}.{field}" for r in diag.rows for field in r["unknown"]]
    hosts = [{k: v for k, v in row.items() if k != "advisory"} for row in diag.rows]
    return {
        "schema": SCHEMA,
        "source": SOURCE,
        "aegis_version": _aegis_version(),
        "checked_at": _utc_now(),
        "scope": {"machine": "local", "workspace": str(ctx.root), "workspace_governed": ctx.governed,
                  "hosts": [s.id for s in ctx.selected], "host_selection": ctx.selection},
        "stale": False,
        "unknown": unknown,
        # Only the checks: a run whose hosts are all unregistered can pass them. The hosts'
        # verdicts are their own ``state`` and ``enforcement_level``.
        "checks_ok": summary["failed"] == 0,
        "summary": summary,
        "checks": [{k: v for k, v in c.items() if k != "text"} for c in checks],
        "hosts": hosts,
        "enforcement_tiers": diag.tiers,
        "human_gate": diag.trust.as_dict() if diag.trust is not None else None,
        "state_modes": diag.modes.as_dict() if diag.modes is not None else None,
        "findings": [f.as_dict() for f in diag.findings],
    }


_ICON = {"ok": "✅", "missing_binary": "➖", "unregistered": "❌", "auth_unknown": "❔", "policy_gap": "⚠️ "}


def _print_hosts(diag: _Diagnosis) -> None:
    ctx = diag.ctx
    how = "from .aegis/config.json" if ctx.selection == "config" else "every supported host; aegis init --host picks yours"
    print(f"\nHosts ({how}):")
    for row in diag.rows:
        reg, boot, budget = row["registration"], row["bootstrap"], row["budget"]
        label = " [experimental]" if row["experimental"] else ""
        print(f"  {_ICON[row['state']]} {row['display_name']} ({row['id']}){label}: {row['state']}")
        if row["experimental"]:
            print("      experimental documented by the vendor, not yet checked on a real install "
                  "(verified after 3 clean runs)")
        if row["surfaces"]:
            print(f"      surfaces     {', '.join(row['surfaces'])}")
        binary = row["binary"]
        where = binary["path"] or ("found only where doctor runs nothing (see below)" if binary["ignored"]
                                   else "not on PATH")
        print(f"      binary       {where}")
        if row["app"]:
            print(f"      app          {_clean(ctx.label(Path(row['app'])), 4096)}")
        registered = {"registered": f"yes, {reg['scope']} scope", "absent": "no", "unknown": "unknown",
                      "unavailable": "not checked"}[reg["status"]]
        print(f"      registered   {registered} ({_clean(reg['source'], 4096)})")
        if reg["command"]:
            exists = {True: "exists", False: "MISSING", None: "unknown"}[reg["command_exists"]]
            print(f"      command      {reg['command'][0]} ({exists})")
        ident = row["identity"]
        if reg["status"] == "registered":
            print(f"      identity     {ident['status']}" + (f" (AEGIS_CLIENT={ident['aegis_client']})"
                                                             if ident["aegis_client"] else ""))
        ws = {True: "registered", False: "not registered", None: "unknown"}[row["workspace_registered"]]
        print(f"      workspace    {ws} in ~/.aegis/workspaces.json")
        print(f"      bootstrap    {boot['file']}: {boot['status']}")
        if budget["bytes"] is not None:
            limit = (f"of {budget['budget_bytes']} bytes" if budget["budget_bytes"] is not None
                     else "bytes (no documented limit)")
            print(f"      budget       {budget['file']} {budget['bytes']} {limit}")
        print(f"      hooks        {_clean(_hooks_line(row, ctx), 4096)}")
        print(f"      enforcement  {row['enforcement_level'].replace('_', ' ')}")
        for reason in row["reasons"]:
            if reason["code"] != "missing_binary":
                print(f"      → {reason['message']}")


def _hooks_line(row: Dict[str, Any], ctx: _Ctx) -> str:
    hooks, status = row["hooks"], row["hooks"]["status"]
    entries = hooks["entries"]
    if status == "registered":
        e = entries[0]
        text = (f"registered ({e['scope']} scope, {ctx.label(Path(e['path']))}); if {row['display_name']} runs it: "
                f"{hooks['tier']} [{hooks['evidence']}]")
        return text + (f"; {hooks['trust']}" if hooks["trust"] else "")
    if status == "absent":
        return f"not registered: aegis hook install --host {row['id']}"
    if status == "duplicate":
        return f"{len(entries)} Aegis entries ({', '.join(e['scope'] for e in entries)}): keep one"
    if status == "broken":
        return f"registered, but {entries[0]['aegis']} is missing or not executable (fails open)"
    if status == "modified":
        e = entries[0]
        return (f"registered but modified ({e['scope']} scope, {ctx.label(Path(e['path']))}): not the entry aegis "
                "hook install writes, so no tier is claimed")
    if status in ("unknown", "unavailable"):
        return f"{status}: {hooks['detail']}"
    return "none"


def _print_tiers(diag: _Diagnosis) -> None:
    from aegis_cli.hooks import registrar

    print("\nEnforcement tiers (AD-8):")
    for tier in diag.tiers:
        name, mechanism = _TIER_TEXT[tier["tier"]]
        hosts = ", ".join(tier["hosts"]) or "-"
        print(f"  {name:<14} {tier['status']:<12} {mechanism}")
        print(f"  {'':<14} {'':<12} hosts: {hosts}; {tier['detail']}")
        if tier["tier"] == "best_effort":
            print(f"  {'':<14} {'':<12} known gaps (guardrails, not a security boundary):")
            for gap in registrar.KNOWN_GAPS:
                print(f"  {'':<14} {'':<12}   - {gap}")


def _print_trust(diag: _Diagnosis) -> None:
    print("")
    for line in diag.trust.text_lines():
        print(_clean(line, 4096))
    modes = diag.modes
    if modes is not None and modes.supported and modes.looser:
        print(f"  Shared state: {modes.looser} of {modes.checked} entries are looser than 0700/0600 "
              "(aegis migrate --apply tightens them).")


def _print_findings(findings: List[_Finding]) -> None:
    if not findings:
        return
    print("\nWarnings:")
    for finding in findings:
        icon = "ℹ️ " if finding.severity == "info" else "⚠️ "
        print(f"  {icon} {finding.message}")


def _print_plan(plan: List[_Change], home: Optional[Path]) -> None:
    from aegis_core.workspace.layout import UserLayout

    where = f"{UserLayout(home).backups_dir}{os.sep}<UTC stamp>" if home else "the Aegis backups directory"
    print(f"\nPlanned changes (each file is backed up to {_clean(where, 4096)} first):")
    for index, change in enumerate(plan, 1):
        print(f"  {index}. {_clean(change.path, 4096)}: {_clean('; '.join(change.describe), 4096)}")


def _print_results(results: List[Dict[str, Any]], backup: Optional[Path]) -> None:
    print("")
    for item in results:
        icon = {"applied": "✅", "skipped": "⚠️ ", "failed": "❌"}[item["status"]]
        line = f"  {icon} {_clean(item['path'], 4096)}: {_clean('; '.join(item['changes']), 4096)}"
        if item["reason"]:
            line += f" ({item['status']}: {item['reason']})"
        print(line)
    if backup is not None:
        print(f"\nBackups: {_clean(backup, 4096)}")


# ── --github: what the trust tiers need, and --apply ────────────────────────

_PLACEHOLDER_CHECK = "aegis"


def _github_plan(root: Path, report: Any) -> Dict[str, Any]:
    found = human_gate.workflow_contexts(root)
    contexts = found or [_PLACEHOLDER_CHECK]
    owner = (report.evidence.get("repo") or {}).get("full_name") or ""
    handle = "@" + owner.split("/")[0] if "/" in owner else "@OWNER"
    return {
        "required_checks": contexts,
        "required_checks_from_workflows": bool(found),
        "ruleset": {"A": human_gate.build_ruleset("A", contexts), "B": human_gate.build_ruleset("B", contexts)},
        "codeowners": human_gate.codeowners_lines(handle),
        "signing_setup": human_gate.signers_setup(),
    }


def _print_github(plan: Dict[str, Any], report: Any) -> None:
    print("aegis doctor --github: what the trust tiers need (read-only; nothing below has been applied)\n")
    for line in report.text_lines():
        print(_clean(line, 4096))
    checks = ", ".join(plan["required_checks"])
    if plan["required_checks_from_workflows"]:
        print(f"\nRequired status checks (the jobs in .github/workflows; keep the ones that must pass): {checks}")
    else:
        print(f"\nNo workflow jobs found: the rulesets below name a placeholder check {checks!r}; replace it with "
              "your Aegis job, and --apply refuses until a workflow exists.")
    for tier, title in (("B", "solo, signed: pull request + required checks, approvals are `aegis approve` signatures"),
                        ("A", "separation of duties: one approving review + code-owner review + required checks")):
        print(f"\nRuleset, tier {tier} ({title}):")
        print(json.dumps(plan["ruleset"][tier], indent=2))
    print("\nCODEOWNERS lines (commit to the default branch; replace the owner with your reviewer):")
    for line in plan["codeowners"]:
        print(f"  {line}")
    print("\nSigning setup for tier B (nothing here is run for you):")
    for line in plan["signing_setup"]:
        print(f"  {line}")
    print("\nCreate the ruleset: aegis doctor --github --apply --tier A|B (asks at a terminal first).")


def _run_github(root: Path, use_json: bool, apply: bool, tier: Optional[str]) -> int:
    report = human_gate.detect_tier(root)
    plan = _github_plan(root, report)
    status = "printed"
    result: Optional[Dict[str, Any]] = None
    if apply:
        if not _stdin_is_tty():
            print("aegis doctor: --apply changes repository settings, so it only runs at a terminal with an "
                  "interactive y/N answer (--yes does not apply); nothing was changed.", file=sys.stderr)
            return 1
        if not plan["required_checks_from_workflows"]:
            print("aegis doctor: no workflow jobs found in .github/workflows to require; add the Aegis workflow "
                  "first. Nothing was changed.", file=sys.stderr)
            return 1
        try:
            exists = human_gate.ruleset_exists(root)
        except human_gate.HumanGateError as exc:
            print(f"aegis doctor: cannot read the repository's rulesets: {_clean(exc, 1000)}. Nothing was changed.",
                  file=sys.stderr)
            return 1
        if exists:
            print(f"aegis doctor: a ruleset named {human_gate.RULESET_NAME!r} already exists; edit it on GitHub "
                  "(--apply only ever creates). Nothing was changed.", file=sys.stderr)
            return 1
        body = plan["ruleset"][tier or "B"]
        print(json.dumps(body, indent=2))
        if not _confirm(f"Create this ruleset on the default branch (tier {tier})? [y/N] "):
            print("No changes made.")
            return 1
        try:
            result = human_gate.create_ruleset(root, body)
        except human_gate.HumanGateError as exc:
            print(f"aegis doctor: {_clean(exc, 1000)}", file=sys.stderr)
            return 1
        status = "applied"
        print(f"Created ruleset {human_gate.RULESET_NAME!r}. Re-run aegis doctor to see the tier.")
    if use_json:
        print(json.dumps({
            "schema": SCHEMA, "source": SOURCE, "aegis_version": _aegis_version(), "checked_at": _utc_now(),
            "scope": {"machine": "local", "workspace": str(root), "mode": "github"},
            "stale": False, "unknown": [], "status": status, "human_gate": report.as_dict(), "github": plan,
            "created": result,
        }, indent=2))
    elif not apply:
        _print_github(plan, report)
    return 0


# ── --release: was this commit green, by a signed attestation ───────────────

def _run_release(root: Path, sha: str, use_json: bool) -> int:
    from aegis_core import release_verify

    report = release_verify.verify_release(root, sha)
    if use_json:
        print(json.dumps(report.as_dict(root), indent=2))
    else:
        for line in report.text_lines():
            print(_clean(line, 4096))
    return 0 if report.verified else 1


# ── Entry point ─────────────────────────────────────────────────────────────

def _usage_error(message: str) -> int:
    print(f"aegis doctor: {message}", file=sys.stderr)
    return EXIT_USAGE


def _resolve_root(args: argparse.Namespace) -> Path:
    from aegis_core.workspace.base import Workspace

    ws = getattr(args, "ws", None)
    if ws is not None:
        return Path(ws.root)
    raw = getattr(args, "workspace", None) or getattr(args, "_project_root", None)
    return Path(Workspace.resolve(raw).root)


def _run_drivers_only(root: Path, use_json: bool, fix: bool, yes: bool) -> int:
    results: List[Dict[str, Any]] = []
    backup: Optional[Path] = None
    declined = False
    text = io.StringIO()
    with contextlib.redirect_stdout(text) if use_json else contextlib.nullcontext():
        if not use_json:
            print(f"aegis doctor — AST driver health check ({_clean(root, 4096)}):\n")
        plan = _plan([], _missing_ast_extensions(root), root) if fix else []
        if plan:
            _print_plan(plan, _home())
            if yes or _confirm(f"Apply these {len(plan)} changes? [y/N] "):
                results, backup = _apply(plan, _home(), root)
                _print_results(results, backup)
            else:
                declined = True
                print("No changes made.")
        (check,) = [c for c in _run_checks(root, fix_ast=False, only=("ast_drivers",))]
        if not use_json:
            print(check["text"], end="")
    failed = check["status"] != "pass" or declined or any(r["status"] != "applied" for r in results)
    if use_json:
        payload = {"schema": SCHEMA, "source": SOURCE, "aegis_version": _aegis_version(), "checked_at": _utc_now(),
                   "scope": {"machine": "local", "workspace": str(root), "checks": ["ast_drivers"]},
                   "stale": False, "unknown": [], "checks_ok": check["status"] == "pass",
                   "checks": [{k: v for k, v in check.items() if k != "text"}]}
        if fix:
            payload["fixes"] = results
            payload["backup_dir"] = str(backup) if backup else None
        print(json.dumps(payload, indent=2))
    return 1 if failed else 0


def _home() -> Optional[Path]:
    from aegis_core.workspace.layout import UserLayout

    layout = UserLayout.current()
    return layout.home if layout else None


def run_doctor(args: argparse.Namespace) -> int:
    """Run the health checks and the host matrix; with --fix, repair what they reported.

    Exit 0 when no blocking check failed (and every planned fix was applied), 1 otherwise,
    2 for a usage error.
    """
    use_json = bool(getattr(args, "json", False))
    fix = bool(getattr(args, "fix", False))
    yes = bool(getattr(args, "yes", False))
    if yes and bool(getattr(args, "apply", False)):
        return _usage_error("--yes does not apply to --github --apply: changing repository settings always asks "
                            "at a terminal")
    if yes and not fix:
        return _usage_error("--yes only applies to --fix")
    if use_json and fix and not yes:
        return _usage_error("--json --fix needs --yes (there is no prompt in JSON mode)")
    github = bool(getattr(args, "github", False))
    apply = bool(getattr(args, "apply", False))
    tier = getattr(args, "tier", None)
    if apply and not github:
        return _usage_error("--apply only applies to --github")
    if tier and not apply:
        return _usage_error("--tier only applies to --github --apply")
    if github and (fix or getattr(args, "drivers", False)):
        return _usage_error("--github cannot be combined with --fix or --drivers")
    if apply and use_json:
        return _usage_error("--github --apply asks at a terminal, so it cannot run with --json")
    if apply and tier not in ("A", "B"):
        return _usage_error("--github --apply needs --tier A or --tier B")
    release = getattr(args, "release", None)
    if release is not None:
        others = [flag for flag, given in (("--fix", fix), ("--yes", yes), ("--github", github),
                                           ("--drivers", bool(getattr(args, "drivers", False)))) if given]
        if others:
            return _usage_error(f"--release does not combine with {', '.join(others)}: it only reads")
        if not str(release).strip():
            return _usage_error("--release needs a commit")
    root = _resolve_root(args)

    if release is not None:
        return _run_release(root, str(release).strip(), use_json)

    if github:
        return _run_github(root, use_json, apply, tier)

    if getattr(args, "drivers", False):
        return _run_drivers_only(root, use_json, fix, yes)

    diag = _diagnose(root)
    plan = _plan(diag.findings, _missing_ast_extensions(root), root) if fix else []
    results: List[Dict[str, Any]] = []
    backup: Optional[Path] = None
    declined = False
    text = io.StringIO()
    with contextlib.redirect_stdout(text) if use_json else contextlib.nullcontext():
        if not use_json:
            print(f"aegis doctor — running health checks ({_clean(root, 4096)}):\n")
        checks = _run_checks(root, fix_ast=False, registered=_registered_launchers(diag.rows))
        if not use_json:
            for check in checks:
                print(check["text"], end="")
            _print_hosts(diag)
            _print_tiers(diag)
            _print_trust(diag)
            _print_findings(diag.findings)
        if fix:
            if not plan:
                print("\nNothing to fix.")
            else:
                _print_plan(plan, diag.ctx.home)
                if yes or _confirm(f"Apply these {len(plan)} changes? [y/N] "):
                    results, backup = _apply(plan, diag.ctx.home, root)
                    _print_results(results, backup)
                else:
                    declined = True
                    print("No changes made.")

    payload = _payload(diag, checks)
    failed = payload["summary"]["failed"] > 0 or declined or any(r["status"] != "applied" for r in results)
    if use_json:
        if fix:
            payload["fixes"] = results
            payload["backup_dir"] = str(backup) if backup else None
        print(json.dumps(payload, indent=2))
        return 1 if failed else 0

    s = payload["summary"]
    warn_label = "warning" if s["warnings"] == 1 else "warnings"
    print(f"\n{s['passed']}/{s['total']} checks passed ({s['passed']} passed, {s['warnings']} {warn_label}, "
          f"{s['failed']} failed).")
    return 1 if failed else 0


class DoctorCommand(AegisCommand):
    """Command for system health and governance audit."""

    name = "doctor"
    category = CommandCategory.SETUP
    help = "System health and governance audit"
    description = (
        "Read-only health checks, the host matrix (binary, registration, identity, workspace, "
        "bootstrap, budget per host) and the enforcement tiers in force here. --fix changes only "
        "what doctor reported (stale v3 and misplaced MCP entries, v3 hook entries, legacy rule "
        "blocks, unedited v3 rule copies, missing packaged AST drivers), after confirmation, backing each file up "
        "to ~/.aegis/backups/<UTC stamp>/ first."
    )

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Repair what doctor reported, after confirmation; every file is backed up first",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="With --fix: apply without asking (required with --json or without a terminal)",
        )
        parser.add_argument(
            "--drivers",
            action="store_true",
            help="Run only AST driver and language detection health check",
        )
        parser.add_argument(
            "--github",
            action="store_true",
            help="Print what trust tiers A and B need: the ruleset JSON, CODEOWNERS lines and signing setup",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="With --github --tier: create the ruleset through gh, only after a y/N at a terminal",
        )
        parser.add_argument(
            "--release",
            metavar="SHA",
            default=None,
            help="Verify that the CI verdict job attested this commit (gh attestation verify, gh >= 2.93.0; "
            "otherwise UNVERIFIED and a non-zero exit)",
        )
        parser.add_argument(
            "--tier",
            choices=("A", "B"),
            help="With --github --apply: which ruleset to create (A: reviews; B: solo, signed approvals)",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_doctor(args)
