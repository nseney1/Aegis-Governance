"""aegis doctor — workspace health, the host matrix and backed-up cleanup (host-matrix §3.9-3.10).

A read run changes nothing: it reads files, runs ``codex mcp get aegis --json`` (the only
host CLI it starts: Codex keeps its registrations in TOML, which stdlib-only Aegis does not
parse), and never syncs, checks, initializes or touches the network. Claude Code is read
from ``~/.claude.json`` instead of ``claude mcp list``, which starts every configured server.

Each host gets one state, the first of these that applies:

- ``missing_binary``: none of its binaries is on PATH;
- ``unregistered``: its config has no ``aegis`` server, or the registered command is gone;
- ``auth_unknown``: doctor cannot confirm the host will load ``aegis`` (its CLI failed or
  timed out, its config cannot be parsed, or the registration waits on an approval doctor
  cannot see);
- ``policy_gap``: ``aegis`` loads, but this repository's policy does not fully reach the
  host (no or broken bootstrap, a CLAUDE.md or AGENTS.override.md shadowing AGENTS.md, a
  file the host truncates, an unregistered workspace for a host without roots, a disabled
  entry, another host's identity);
- ``ok``: none of the above.

``--json`` prints one ``aegis.doctor/v1`` document: ``schema``, ``source``, ``aegis_version``,
``checked_at`` (UTC), ``scope``, ``stale`` and ``unknown`` (fields doctor could not
determine), ``checks``, ``hosts`` (each with ``state``, ``reasons``, the matrix facts,
``enforcement_level`` and ``trust_tier``, reserved as null until v4.3), ``enforcement_tiers``,
``findings``, and with ``--fix`` the ``fixes`` it applied and its ``backup_dir``.

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
import shutil
import stat
import subprocess
import sys
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from aegis_cli.base import CommandCategory, AegisCommand

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


def _check_rules(project_root: Path) -> bool:
    """The workspace serves at least one rule and every rule file loads."""
    from aegis_core.rules import load_rules
    from aegis_core.workspace.layout import WorkspaceLayout

    rules_dir = WorkspaceLayout(Path(project_root)).rules_dir
    if not rules_dir.is_dir():
        print(f"  ❌ No rules directory ({rules_dir})")
        print("    Fix: Run 'aegis init' to install starter rules.")
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
        print("    Fix: Run 'aegis init' to install starter rules.")
        return False
    print(f"  ✅ Rules: {len(ruleset.served)} served from {rules_dir}")
    return True


def _check_state_dir(project_root: Path | None = None) -> bool:
    """Check .aegis/state/ (ledger, lock) exists and is writable, or can be created (read-only check)."""
    from aegis_core.workspace.layout import WorkspaceLayout

    state = WorkspaceLayout(Path(project_root or Path.cwd()).resolve()).state_dir
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
    print("    Fix: Run 'aegis init' to create workspace directories.")
    return False


def _check_cli_resolvable() -> bool:
    """Check that 'aegis' CLI is on PATH."""
    path = shutil.which("aegis")
    if path:
        print(f"  ✅ aegis CLI resolvable ({path})")
        return True
    print("  ❌ aegis CLI not found on PATH")
    from aegis_cli.pathcheck import build_hint
    hint = build_hint()
    if hint:
        print("\n".join("    " + line for line in hint.splitlines()))
    return False


# ── MCP launcher ─────────────────────────────────────────────────────────────

# MCP configs start the server as `python3 -m aegis_mcp`. The import probe runs
# without -I so user site-packages count, but drops the implicit CWD entry so
# doctor never imports (executes) a aegis_mcp that happens to sit in the cwd.
_IMPORT_PROBE = "import sys; sys.path[:1] = [p for p in sys.path[:1] if p]; __import__('aegis_mcp')"


def probe_mcp_launcher(path_env: str | None = None,
                       timeout: float = 10.0) -> tuple[str, str]:
    """Resolve `python3` from PATH like an MCP host and classify it.

    Returns (status, detail); status is one of ok, missing, store_stub,
    broken, no_aegis_mcp.
    """
    path_env = os.environ.get("PATH", "") if path_env is None else path_env
    exe = shutil.which("python3", path=path_env)
    if not exe:
        return "missing", "python3 is not on PATH"

    def _run(argv: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run([exe, *argv], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, errors="replace",
                              timeout=timeout)

    try:
        proc = _run(["-I", "-S", "-c", "import sys; print(sys.version_info[0])"])
    except subprocess.TimeoutExpired:
        return "broken", f"{exe} timed out after {timeout:g}s"
    except OSError as exc:
        return "broken", f"{exe} could not be started: {exc}"
    out = proc.stdout.strip()
    # The App Installer stub exits 49, or prints a Store message and nothing
    # on stdout, instead of running Python.
    store_msg = "microsoft store" in (proc.stdout + proc.stderr).lower()
    if proc.returncode == 49 or (not out and store_msg):
        return "store_stub", exe
    if proc.returncode != 0 or out != "3":
        err = (proc.stderr.strip() or out)[:200]
        return "broken", f"{exe} exited {proc.returncode}: {err}"

    try:
        imp = _run(["-c", _IMPORT_PROBE])
    except subprocess.TimeoutExpired:
        return "broken", f"{exe} timed out after {timeout:g}s importing aegis_mcp"
    except OSError as exc:
        return "broken", f"{exe} could not be started: {exc}"
    if imp.returncode != 0:
        return "no_aegis_mcp", exe
    return "ok", exe


def _check_mcp_launcher(path_env: str | None = None) -> bool:
    """Advisory: report whether `python3 -m aegis_mcp` would start."""
    status, detail = probe_mcp_launcher(path_env)
    if status == "ok":
        print(f"  ✅ MCP launcher: python3 ({detail}) runs and imports aegis_mcp")
        return True
    if status == "missing":
        print("  ⚠️  MCP launcher: python3 not found on PATH. MCP configs start the\n"
              "      server with `python3 -m aegis_mcp`; install Python 3 from python.org\n"
              "      or put it on PATH (only needed if you use the MCP server).")
    elif status == "store_stub":
        print(f"  ⚠️  MCP launcher: {detail} is the Windows Store App Installer stub, not Python.\n"
              "      Fix: Settings > Apps > Advanced app settings > App execution aliases:\n"
              "      turn off python.exe and python3.exe, then install Python from python.org\n"
              "      (or make sure the real python3 comes first on PATH).")
    elif status == "no_aegis_mcp":
        print(f"  ⚠️  MCP launcher: {detail} runs but cannot import aegis_mcp.\n"
              f"      Install it for that interpreter: {detail} -m pip install --user aegis-guardrails")
    else:
        print(f"  ⚠️  MCP launcher: {detail}")
    return False


def _missing_ast_extensions(ws_root: Path) -> List[str]:
    """Detected source extensions with no AST driver configured (what --fix provisions).

    An unreadable config gives none: the AST check reports it, and --fix will not
    write over a file it cannot parse.
    """
    from aegis_core.ast.detect import detect_project_languages
    from aegis_core.skills.slots import SlotRegistry, SlotResolutionError

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


def _check_ast_drivers(project_root: Path | None = None, fix: bool = False) -> bool:
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
        found = resolve_driver_executable(bin_name)
        if found:
            print(f"  ✅ AST driver ({ext}): {bin_name} resolvable ({found})")
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
# Hosts that keep the start of an over-budget instruction file (Codex cuts at its
# project_doc_max_bytes) and hosts that may drop the whole file (Antigravity's
# per-file limit); for the others the budget is advice.
_TRUNCATES_TAIL = frozenset({"codex-cli"})
_DROPS_OVER_BUDGET = frozenset({"antigravity"})
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
                          text=True, errors="replace", timeout=timeout)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _aegis_version() -> str:
    from aegis_cli import __version__
    return str(__version__)


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
        if text.startswith("﻿"):
            raise ValueError("starts with a byte-order mark")
        entry.data = json.loads(text, object_pairs_hook=_strict_pairs, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        entry.error = f"is not valid JSON ({str(exc)[:120]})"
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
    _cache: Dict[Tuple[str, bool], _File] = field(default_factory=dict)

    @property
    def path_env(self) -> str:
        return self.environ.get("PATH", "")

    def which(self, name: str) -> Optional[str]:
        return shutil.which(name, path=self.path_env)

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
    """Command, AEGIS_CLIENT and enabled flag of one MCP server entry."""
    facts: Dict[str, Any] = {}
    if not isinstance(entry, dict):
        return facts
    command = entry.get("command")
    if isinstance(command, str) and command:
        args = entry.get("args") if isinstance(entry.get("args"), list) else []
        facts["command"] = [command] + [str(a) for a in args]
        facts["command_exists"] = _command_exists(command, ctx)
    env = entry.get("env")
    if isinstance(env, dict) and isinstance(env.get("AEGIS_CLIENT"), str):
        facts["aegis_client"] = env["AEGIS_CLIENT"]
    if isinstance(entry.get("disabled"), bool):
        facts["enabled"] = not entry["disabled"]
    if isinstance(entry.get("enabled"), bool):
        facts["enabled"] = entry["enabled"]
    return facts


def _command_exists(command: str, ctx: _Ctx) -> bool:
    if os.path.isabs(command):
        return os.path.isfile(command) and (os.name == "nt" or os.access(command, os.X_OK))
    return ctx.which(command) is not None


def _probe_codex(spec: Any, binary: Optional[str], ctx: _Ctx) -> Dict[str, Any]:
    source = "codex mcp get aegis --json"
    if binary is None:
        return _registration("unavailable", source, detail="codex is not on PATH")
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
        first = said.splitlines()[0][:200] if said else "no output"
        return _registration("unknown", source, detail=f"codex exited {proc.returncode}: {first}")
    try:
        data = json.loads(proc.stdout)
    except ValueError:
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
    project = next((projects[k] for k in _claude_project_keys(ctx) if isinstance(projects.get(k), dict)), {})
    local = _server_entry(project)
    user = _server_entry(data)
    if local is not None:
        return _registration("registered", source, scope="local", **_entry_facts(local, ctx))
    if user is not None:
        return _registration("registered", source, scope="user", **_entry_facts(user, ctx))
    dot_mcp = ctx.file(ctx.root / ".mcp.json", as_json=True)
    shared = _server_entry(dot_mcp.data) if not dot_mcp.error else None
    if shared is not None:
        # A project .mcp.json server runs only after the user approves it; that answer
        # lives in settings files doctor does not read, unless .claude.json records it.
        approved = _names(project.get("enabledMcpjsonServers"))
        denied = _names(project.get("disabledMcpjsonServers"))
        approval = ("approved" if SERVER in approved or project.get("enableAllProjectMcpServers") is True
                    else "denied" if SERVER in denied else "unknown")
        facts = _entry_facts(shared, ctx)
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
    return _registration("unavailable", "-", detail=f"doctor cannot check {spec.display_name} yet")


# ── Host plane: instruction files ───────────────────────────────────────────

_BLOCK_BEGIN = re.compile(r"^<!-- aegis:begin id=(\S+) v=(\S+) sha=(\S+) -->[ \t]*$")
_BLOCK_END = re.compile(r"^<!-- aegis:end id=(\S+) -->[ \t]*$")
_HEX12 = re.compile(r"^[0-9a-f]{12}$")
_IMPORTS_AGENTS = re.compile(r"(?<![\w@/.\-])@(?:\./)?AGENTS\.md\b")


@dataclass
class _Instructions:
    agents_bytes: Optional[int] = None
    bootstrap: str = "not_read"  # current outdated hand_edited malformed missing not_read
    block_end: Optional[int] = None  # bytes up to the end of the closing marker line
    claude_md: Optional[Path] = None
    claude_bytes: int = 0
    claude_imports_agents: bool = False
    override: bool = False


def _bootstrap_state(text: str) -> Tuple[str, Optional[int]]:
    from aegis_core.bootstrap import BOOTSTRAP_ID, bootstrap_text

    lines = text.splitlines(True)
    begins, ends, offset, end_at = [], [], 0, None
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
    claude = ctx.file(ctx.root / "CLAUDE.md")
    if claude.raw is not None:
        info.claude_md = claude.path
        info.claude_bytes = len(claude.raw)
        info.claude_imports_agents = bool(_IMPORTS_AGENTS.search(claude.raw.decode("utf-8", errors="replace")))
    info.override = (ctx.root / "AGENTS.override.md").exists()
    return info


def _budget(spec: Any, info: _Instructions) -> Dict[str, Any]:
    budget = spec.budget_bytes
    if spec.instructions == "agents_md_unless_claude_md" and info.claude_md is not None:
        size = info.claude_bytes + ((info.agents_bytes or 0) if info.claude_imports_agents else 0)
        name = "CLAUDE.md" + (" + AGENTS.md" if info.claude_imports_agents else "")
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
    if spec.instructions == "agents_md_unless_claude_md" and info.claude_md is not None:
        return info.claude_imports_agents
    return True


def _registered_roots(ctx: _Ctx) -> Optional[set]:
    """Normalized roots in ~/.aegis/workspaces.json; empty when absent, None when unreadable."""
    if ctx.home is None:
        return None
    from aegis_core.workspace.layout import UserLayout

    reg = ctx.file(UserLayout(ctx.home).workspaces_file, as_json=True)
    if not reg.exists:
        return set()
    if reg.error or reg.data.get("v") != 1 or not isinstance(reg.data.get("workspaces"), list):
        return None
    return {_root_key(e["root"]) for e in reg.data["workspaces"]
            if isinstance(e, dict) and isinstance(e.get("root"), str)}


def _root_key(root: Any) -> str:
    return os.path.normcase(os.path.realpath(str(root)))


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
    return {"status": "mismatch", "aegis_client": client}


def _host_row(spec: Any, ctx: _Ctx, info: _Instructions, roots: Optional[set], floor: str) -> Dict[str, Any]:
    binary = next((found for found in (ctx.which(name) for name in spec.binaries) if found), None)
    reg = _probe(spec, binary, ctx)
    identity = _identity(spec, reg)
    reasons: List[Dict[str, str]] = []
    unknown: List[str] = []

    def add(code: str, message: str) -> None:
        reasons.append({"code": code, "message": message})

    names = " or ".join(f"`{b}`" for b in spec.binaries) or "a binary"
    if binary is None:
        add("missing_binary", f"no {names} on PATH")
    status = reg["status"]
    if status == "absent":
        add("not_registered", f"aegis is not registered with {spec.display_name}: run aegis init --host {spec.id}")
    elif status in ("unknown", "unavailable"):
        unknown.append("registration")
        if status == "unknown":
            add("registration_unverifiable", f"cannot tell whether {spec.display_name} loads aegis: {reg['detail']}")
    else:
        if reg["command_exists"] is False:
            add("command_missing", f"the registered command {reg['command'][0]} does not exist: "
                                   f"run aegis init --host {spec.id}")
        elif reg["command_exists"] is None:
            unknown.append("command_exists")
        if reg["approval"] == "unknown":
            add("approval_unknown", "aegis is registered only in this project's .mcp.json, which Claude Code "
                                    "runs after an approval doctor cannot see")
        if reg["enabled"] is False:
            add("registration_disabled", f"the aegis entry is disabled in {reg['source']}")
        if identity["status"] == "mismatch":
            add("identity_mismatch", f"the registration says AEGIS_CLIENT={identity['aegis_client']}, so the "
                                     f"server would act as that host: run aegis init --host {spec.id}")
        elif identity["status"] == "unknown":
            unknown.append("identity")

    budget = _budget(spec, info)
    reaches = _bootstrap_reaches(spec, info)
    workspace_registered = None if roots is None else _root_key(ctx.root) in roots
    if roots is None:
        unknown.append("workspace_registered")
    if not ctx.governed:
        add("workspace_not_governed", f"{ctx.root} has no .aegis/: run aegis init there")
    else:
        if info.bootstrap in ("missing", "hand_edited", "malformed"):
            add("bootstrap_" + info.bootstrap, {
                "missing": "AGENTS.md has no Aegis bootstrap block: run aegis init",
                "hand_edited": "the Aegis block in AGENTS.md was edited by hand: run aegis init --force",
                "malformed": "the Aegis block markers in AGENTS.md are broken: fix them, then run aegis init",
            }[info.bootstrap])
        if spec.instructions == "agents_md_unless_claude_md" and info.claude_md is not None \
                and not info.claude_imports_agents:
            add("claude_md_shadows_agents_md", "CLAUDE.md exists without @AGENTS.md, so Claude Code does "
                                               "not read AGENTS.md: run aegis init to add the import")
        if spec.id in _READS_AGENTS_OVERRIDE and info.override:
            add("agents_override_shadows_agents_md", "AGENTS.override.md replaces AGENTS.md for Codex")
        if budget["within"] is False and info.bootstrap != "missing":
            cut = (spec.id in _DROPS_OVER_BUDGET
                   or (spec.id in _TRUNCATES_TAIL and (info.block_end or 0) > budget["budget_bytes"]))
            if cut:
                add("over_budget", f"{budget['file']} is {budget['bytes']} bytes; {spec.display_name} reads "
                                   f"{budget['budget_bytes']} and the Aegis block may not reach it")
        if spec.id in _REGISTRY_BOUND and workspace_registered is False:
            add("workspace_unregistered", f"{spec.display_name} sends no workspace, so aegis finds this "
                                          f"repository only through ~/.aegis/workspaces.json: run aegis init")

    codes = {r["code"] for r in reasons}
    if "missing_binary" in codes:
        state = "missing_binary"
    elif codes & {"not_registered", "command_missing"}:
        state = "unregistered"
    elif codes & {"registration_unverifiable", "approval_unknown"}:
        state = "auth_unknown"
    elif codes:
        state = "policy_gap"
    else:
        state = "ok"

    loads = (status == "registered" and reg["command_exists"] is not False and reg["enabled"] is not False
             and reg["approval"] in (None, "approved"))
    advisory = bool(loads or reaches)
    level = "local_floor" if floor == "active" else ("advisory" if advisory else "none")
    shown = {k: v for k, v in reg.items() if k != "aegis_client"}
    return {
        "id": spec.id,
        "display_name": spec.display_name,
        "verified_row": spec.verified,
        "state": state,
        "reasons": reasons,
        "binary": {"found": binary is not None, "path": binary, "names": list(spec.binaries)},
        "registration": shown,
        "identity": identity,
        "workspace_registered": workspace_registered,
        "bootstrap": {"file": "AGENTS.md", "status": info.bootstrap, "reaches_host": reaches,
                      "stale": info.bootstrap == "outdated"},
        "budget": budget,
        "enforcement_level": level,
        "advisory": advisory,
        "trust_tier": None,
        "trust_tier_status": "unavailable",
        "stale": False,
        "unknown": unknown,
    }


# ── Enforcement tiers (AD-8) ────────────────────────────────────────────────

def _floor_status(root: Path) -> str:
    from aegis_cli.hooks.management import hook_status

    try:
        st = hook_status(root)
    except Exception:
        return "unknown"
    if st.get("status") == "no_git_repository":
        return "unavailable"
    if not st.get("managed_by_aegis"):
        return "inactive"
    if st.get("status") != "installed":
        return "outdated"
    gone = [p for p in (st.get("interpreter"), st.get("aegis_path")) if p and not p.get("exists")]
    return "outdated" if gone else "active"


_TIER_TEXT = {
    "advisory": ("Advisory", "AGENTS.md bootstrap, MCP instructions, JIT rules"),
    "best_effort": ("Best-effort", "per-host pre-tool hooks"),
    "local_floor": ("Local floor", "git pre-commit runs aegis check --hook (--no-verify bypasses it)"),
    "authoritative": ("Authoritative", "CI runs aegis check on the exact SHA; a human merges"),
}


def _tiers(rows: List[Dict[str, Any]], floor: str) -> List[Dict[str, Any]]:
    ids = [r["id"] for r in rows]
    reached = [r["id"] for r in rows if r["advisory"]]
    advisory = "active" if ids and len(reached) == len(ids) else ("partial" if reached else "inactive")
    floor_detail = {
        "active": "the Aegis pre-commit hook is installed and current",
        "inactive": "no Aegis pre-commit hook: run aegis hook install",
        "outdated": "the Aegis pre-commit hook is outdated: run aegis hook install",
        "unavailable": "not a git repository",
        "unknown": "the git hooks directory could not be read",
    }[floor]
    return [
        {"tier": "advisory", "mechanism": _TIER_TEXT["advisory"][1], "hosts": ids, "status": advisory,
         "detail": f"reaches {', '.join(reached) or 'no selected host'}"},
        {"tier": "best_effort", "mechanism": _TIER_TEXT["best_effort"][1], "hosts": [], "status": "unavailable",
         "detail": "per-host hooks ship in v4.1 (Claude Code can block; Codex fails open)"},
        {"tier": "local_floor", "mechanism": _TIER_TEXT["local_floor"][1], "hosts": ids, "status": floor,
         "detail": floor_detail},
        {"tier": "authoritative", "mechanism": _TIER_TEXT["authoritative"][1], "hosts": [], "status": "unknown",
         "detail": "not checked: aegis doctor makes no network or GitHub calls"},
    ]


# ── Findings ────────────────────────────────────────────────────────────────

@dataclass
class _Action:
    """One reported change --fix may make to one file."""

    path: Path
    kind: str  # remove_keys | remove_lines | delete_file | enable_packaged_ast_drivers
    sha256: Optional[str]
    describe: str
    keys: Tuple[Tuple[str, ...], ...] = ()
    lines: Tuple[Tuple[int, int], ...] = ()


@dataclass
class _Finding:
    code: str
    path: Path
    message: str
    location: Optional[str] = None
    severity: str = "warning"
    action: Optional[_Action] = None

    @property
    def fixable(self) -> bool:
        return self.action is not None

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "path": str(self.path), "location": self.location,
                "message": self.message, "fixable": self.fixable}


def _location(keys: Tuple[str, ...]) -> str:
    out = []
    for key in keys:
        if out and out[-1] == "projects":
            out[-1] = f"projects[{key}]"
        else:
            out.append(key)
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
    """(line ranges of well-formed SOMA/AEGIS START..END blocks, markers are balanced)."""
    ranges, open_at = [], None
    for index, line in enumerate(text.splitlines(True)):
        match = _LEGACY_MARKER.match(line.rstrip("\r\n"))
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
    if info.claude_md is not None and not info.claude_imports_agents:
        found.append(_Finding("claude_md_without_agents_import", info.claude_md,
                              "CLAUDE.md does not import @AGENTS.md, so Claude Code skips AGENTS.md; "
                              "run aegis init to add the import block"))
    if info.override:
        found.append(_Finding("agents_override", ctx.root / "AGENTS.override.md",
                              "AGENTS.override.md replaces AGENTS.md for Codex; move its text into AGENTS.md"))
    if info.bootstrap == "outdated":
        found.append(_Finding("bootstrap_outdated", ctx.root / "AGENTS.md",
                              "the Aegis block in AGENTS.md is from another aegis version: run aegis init",
                              severity="info"))
    return found


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

def _selection(root: Path, governed: bool) -> Tuple[Tuple[Any, ...], str, List[_Finding]]:
    from aegis_core import hosts
    from aegis_core.config import ConfigError, RepoConfig

    default = tuple(h for h in hosts.all_hosts(phase=1) if h.registration is not None)
    if not governed:
        return default, "default", []
    try:
        chosen = RepoConfig.load(root).hosts
    except ConfigError as exc:
        return default, "default", [_Finding("unreadable_config", root / ".aegis" / "config.json", str(exc))]
    if not chosen:
        return default, "default", []
    known = {h.id: h for h in hosts.HOSTS if h.registration is not None}
    unknown = [h for h in chosen if h not in known]
    notes = [_Finding("unknown_host", root / ".aegis" / "config.json",
                      f".aegis/config.json selects {', '.join(repr(h) for h in unknown)}, which doctor "
                      "cannot check", severity="info")] if unknown else []
    picked = tuple(h for h in hosts.HOSTS if h.id in set(chosen) and h.id in known)
    return picked, "config", notes


@dataclass
class _Diagnosis:
    ctx: _Ctx
    rows: List[Dict[str, Any]]
    tiers: List[Dict[str, Any]]
    findings: List[_Finding]


def _diagnose(root: Path, environ: Optional[Mapping[str, str]] = None) -> _Diagnosis:
    from aegis_core.workspace.layout import UserLayout, is_aegis_workspace

    environ = os.environ if environ is None else environ
    layout = UserLayout.current()
    governed = is_aegis_workspace(root)
    selected, selection, notes = _selection(root, governed)
    ctx = _Ctx(root=root, governed=governed, home=layout.home if layout else None, environ=environ,
               selected=selected, selection=selection)
    info = _instructions(ctx)
    roots = _registered_roots(ctx)
    floor = _floor_status(root) if governed else "unavailable"
    rows = [_host_row(spec, ctx, info, roots, floor) for spec in selected]
    claude_user = _claude_user_registered(ctx)
    findings = (notes + _workspace_findings(ctx, info) + _mcp_findings(ctx, claude_user)
                + _legacy_block_findings(ctx) + _budget_findings(ctx, info) + _home_rules_finding(ctx)
                + _v3_copy_findings(ctx))
    if roots is None and ctx.home is not None:
        findings.append(_Finding("unreadable_config", UserLayout(ctx.home).workspaces_file,
                                 "~/.aegis/workspaces.json cannot be read as a v1 registry; doctor "
                                 "reports workspace registration as unknown"))
    return _Diagnosis(ctx, rows, _tiers(rows, floor), findings)


def _claude_user_registered(ctx: _Ctx) -> bool:
    path = _claude_config(ctx)
    if path is None:
        return False
    cfg = ctx.file(path, as_json=True)
    return not cfg.error and _server_entry(cfg.data) is not None


# ── --fix ───────────────────────────────────────────────────────────────────

class _Refused(Exception):
    """A fix that must not be applied; the message says why."""


def _confirm(prompt: str) -> bool:
    """Ask on the terminal; anything but y/yes is no. Without a terminal the answer is no."""
    try:
        interactive = sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):
        interactive = False
    if not interactive:
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
    text = original.decode("utf-8")
    match = re.search(r"\n( +)\"", text)
    indent = len(match.group(1)) if match else (2 if "\n" in text.strip() else None)
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
    """The bytes with the line ranges removed, or None when nothing but whitespace is left."""
    lines = raw.decode("utf-8").splitlines(True)
    drop = {i for a, b in ranges for i in range(a, b + 1)}
    kept = "".join(line for i, line in enumerate(lines) if i not in drop)
    return kept.encode("utf-8") if kept.strip(" \t\r\n﻿") else None


@dataclass
class _Change:
    path: Path
    kind: str
    sha256: Optional[str]
    describe: List[str] = field(default_factory=list)
    keys: List[Tuple[str, ...]] = field(default_factory=list)
    lines: List[Tuple[int, int]] = field(default_factory=list)


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
                        "changes": list(change.describe), "reason": reason})

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
                with open(backup / name, "xb") as fh:
                    fh.write(current)
                    fh.flush()
                    os.fsync(fh.fileno())
                manifest.append({"path": str(change.path), "backup": name, "sha256": _sha256(current),
                                 "action": action})
                _write_manifest(backup, manifest)
            if change.kind == "remove_keys":
                atomic_bytes = _without_keys(current, change.keys)
                _current_bytes(change.path, change.sha256)  # compare before replace
                atomic_write_bytes(change.path, atomic_bytes)
            elif change.kind == "remove_lines":
                kept = _without_lines(current, change.lines)
                _current_bytes(change.path, change.sha256)
                if kept is None:
                    os.unlink(change.path)
                    action = "delete_file"
                    change.describe.append("delete the file: nothing but the legacy block was in it")
                else:
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
    atomic_write_bytes(backup / "manifest.json", (json.dumps(doc, indent=2) + "\n").encode("utf-8"))


# ── Output ──────────────────────────────────────────────────────────────────

_CHECKS: Tuple[Tuple[str, bool], ...] = (
    # (id, failing it fails the run); advisory checks only warn.
    ("python_version", True), ("zero_dependencies", True), ("rules", True), ("state_dir", True),
    ("cli_on_path", True), ("precommit_hook", True), ("ast_drivers", False), ("mcp_launcher", False),
)


def _run_checks(root: Path, fix_ast: bool, only: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    from aegis_cli.ui.theme import strip_ansi

    calls: Dict[str, Callable[[], Optional[bool]]] = {
        "python_version": _check_python_version,
        "zero_dependencies": _check_zero_dependencies,
        "rules": lambda: _check_rules(root),
        "state_dir": lambda: _check_state_dir(root),
        "cli_on_path": _check_cli_resolvable,
        "precommit_hook": lambda: _check_precommit_hook(root),
        "ast_drivers": lambda: _check_ast_drivers(root, fix=fix_ast),
        "mcp_launcher": _check_mcp_launcher,
    }
    out = []
    for check_id, blocking in _CHECKS:
        if only is not None and check_id not in only:
            continue
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = calls[check_id]()
        status = "skip" if ok is None else ("pass" if ok else ("fail" if blocking else "warn"))
        out.append({"id": check_id, "status": status, "text": buf.getvalue(),
                    "detail": [strip_ansi(line.strip()) for line in buf.getvalue().splitlines() if line.strip()]})
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
        "ok": summary["failed"] == 0,
        "summary": summary,
        "checks": [{k: v for k, v in c.items() if k != "text"} for c in checks],
        "hosts": hosts,
        "enforcement_tiers": diag.tiers,
        "findings": [f.as_dict() for f in diag.findings],
    }


_ICON = {"ok": "✅", "missing_binary": "➖", "unregistered": "❌", "auth_unknown": "❔", "policy_gap": "⚠️ "}


def _print_hosts(diag: _Diagnosis) -> None:
    ctx = diag.ctx
    how = "from .aegis/config.json" if ctx.selection == "config" else "all v4.0 hosts; aegis init --host picks yours"
    print(f"\nHosts ({how}):")
    for row in diag.rows:
        reg, boot, budget = row["registration"], row["bootstrap"], row["budget"]
        print(f"  {_ICON[row['state']]} {row['display_name']} ({row['id']}): {row['state']}")
        print(f"      binary       {row['binary']['path'] or 'not on PATH'}")
        registered = {"registered": f"yes, {reg['scope']} scope", "absent": "no", "unknown": "unknown",
                      "unavailable": "not checked"}[reg["status"]]
        print(f"      registered   {registered} ({reg['source']})")
        if reg["command"]:
            exists = {True: "exists", False: "MISSING", None: "not checked"}[reg["command_exists"]]
            print(f"      command      {reg['command'][0]} ({exists})")
        ident = row["identity"]
        if reg["status"] == "registered":
            print(f"      identity     {ident['status']}" + (f" (AEGIS_CLIENT={ident['aegis_client']})"
                                                             if ident["aegis_client"] else ""))
        ws = {True: "registered", False: "not registered", None: "unknown"}[row["workspace_registered"]]
        print(f"      workspace    {ws} in ~/.aegis/workspaces.json")
        print(f"      bootstrap    {boot['file']}: {boot['status']}")
        if budget["bytes"] is not None:
            print(f"      budget       {budget['file']} {budget['bytes']} of {budget['budget_bytes']} bytes")
        print(f"      enforcement  {row['enforcement_level'].replace('_', ' ')}")
        for reason in row["reasons"]:
            if reason["code"] != "missing_binary":
                print(f"      → {reason['message']}")


def _print_tiers(diag: _Diagnosis) -> None:
    print("\nEnforcement tiers (AD-8):")
    for tier in diag.tiers:
        name, mechanism = _TIER_TEXT[tier["tier"]]
        hosts = ", ".join(tier["hosts"]) or "-"
        print(f"  {name:<14} {tier['status']:<12} {mechanism}")
        print(f"  {'':<14} {'':<12} hosts: {hosts}; {tier['detail']}")


def _print_findings(findings: List[_Finding]) -> None:
    if not findings:
        return
    print("\nWarnings:")
    for finding in findings:
        icon = "ℹ️ " if finding.severity == "info" else "⚠️ "
        print(f"  {icon} {finding.message}")


def _print_plan(plan: List[_Change], home: Optional[Path]) -> None:
    where = f"{home / '.aegis' / 'backups'}{os.sep}<UTC stamp>" if home else "~/.aegis/backups"
    print(f"\nPlanned changes (each file is backed up to {where} first):")
    for index, change in enumerate(plan, 1):
        print(f"  {index}. {change.path}: {'; '.join(change.describe)}")


def _print_results(results: List[Dict[str, Any]], backup: Optional[Path]) -> None:
    print("")
    for item in results:
        icon = {"applied": "✅", "skipped": "⚠️ ", "failed": "❌"}[item["status"]]
        line = f"  {icon} {item['path']}: {'; '.join(item['changes'])}"
        if item["reason"]:
            line += f" ({item['status']}: {item['reason']})"
        print(line)
    if backup is not None:
        print(f"\nBackups: {backup}")


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
            print(f"aegis doctor — AST driver health check ({root}):\n")
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
                   "stale": False, "unknown": [], "ok": not failed,
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
    if yes and not fix:
        return _usage_error("--yes only applies to --fix")
    if use_json and fix and not yes:
        return _usage_error("--json --fix needs --yes (there is no prompt in JSON mode)")
    root = _resolve_root(args)

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
            print(f"aegis doctor — running health checks ({root}):\n")
        checks = _run_checks(root, fix_ast=False)
        if not use_json:
            for check in checks:
                print(check["text"], end="")
            _print_hosts(diag)
            _print_tiers(diag)
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
        "what doctor reported (stale v3 and misplaced MCP entries, legacy rule blocks, unedited "
        "v3 rule copies, missing packaged AST drivers), after confirmation, backing each file up "
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

    def execute(self, args: argparse.Namespace) -> int:
        return run_doctor(args)
