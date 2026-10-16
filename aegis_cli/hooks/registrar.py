"""`aegis hook install --host <h>` / `aegis hook uninstall --host <h>`: register the
per-host PreToolUse hook (v4.1 spec §2 Registration, AD-8 honest tiers).

Each host gets one PreToolUse group that runs ``aegis hook run pre-tool --host <h>``:

- **Claude Code** (exec form, no shell; Claude Code >= 2.1.139, DOC):
  ``~/.claude/settings.json`` (``$CLAUDE_CONFIG_DIR/settings.json``) or, with
  ``--scope project``, ``<repo>/.claude/settings.json``. No ``permissions.deny`` entries:
  the hook parses commands, which deny rules cannot.
- **Codex CLI** (run through ``$SHELL -lc``, DOC): ``~/.codex/hooks.json``
  (``$CODEX_HOME/hooks.json``) or ``<repo>/.codex/hooks.json``, plus
  ``~/.codex/rules/aegis.rules`` (``prefix_rule(... decision="forbidden")``, generated from
  :data:`aegis_core.command_safety.BLOCK_SET`; ``default.rules`` is never touched). The
  entry is byte-stable across re-installs with the same ``aegis``: Codex's trust hash
  covers the handler, and a changed hook is skipped silently until re-trusted in /hooks.
- **Antigravity** (shell, LIVE): group ``aegis`` in ``~/.gemini/config/hooks.json`` or
  ``<repo>/.agents/hooks.json``. The wrapper maps the handler's 75 to agy's blocking 1 and
  every other code (a crash, 126, 127, a missing binary) to 0, and keeps stdout empty.
  agy hooks are ``unavailable`` on Windows (its hook shell is UNVERIFIED there).

Every write follows the host-plane contract of :mod:`aegis_cli.install_hosts`: no
symlinked or multiply-linked file is written, unparseable JSON is refused, the old bytes
go to ``~/.aegis/backups/<UTC stamp>/<scope>/`` first (both scopes' files share a name, and
the Codex rules file is a user file), the replacement is atomic and is re-read
afterwards (a broken Claude settings file silently drops all its hooks, DOC). Aegis
entries are identified by their command (an absolute ``aegis`` followed by ``hook run``),
never by position, and a host never gets an Aegis entry at both scopes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shlex
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from aegis_cli import install_hosts as plane
from aegis_cli.install_hosts import InstallError
from aegis_core import hosts as host_table
from aegis_core.storage import atomic_write_bytes

__all__ = [
    "AEGIS_PATH_CHARSET",
    "CODEX_RULES_HEADER",
    "EVIDENCE",
    "HOOK_HOSTS",
    "HOOK_TIMEOUT_S",
    "KNOWN_GAPS",
    "SCOPES",
    "TIERS",
    "TRUST_UNCHECKED",
    "UNAVAILABLE",
    "HookResult",
    "ShapeError",
    "UsageError",
    "aegis_command",
    "aegis_handlers",
    "codex_rules_file",
    "codex_rules_text",
    "handler_aegis",
    "hook_file",
    "hook_group",
    "install",
    "is_aegis_handler",
    "run_host_install",
    "run_host_uninstall",
    "uninstall",
    "unavailable_reason",
]

HOOK_HOSTS = ("claude-code", "codex-cli", "antigravity")
SCOPES = ("user", "project")
HOOK_TIMEOUT_S = 10
EVENT = "PreToolUse"
AGY_GROUP = "aegis"
MATCHERS = {
    "claude-code": "Bash|PowerShell|Monitor|Write|Edit|NotebookEdit",
    "codex-cli": "Bash|apply_patch",
    "antigravity": "run_command|write_to_file|replace_file_content|multi_replace_file_content",
}
#: What a shell form may contain of the aegis path: no quoting games (spec §2).
AEGIS_PATH_CHARSET = re.compile(r"[A-Za-z0-9._/+-]+")
_CHARSET_TEXT = "[A-Za-z0-9._/+-]+"
UNAVAILABLE = "unavailable"
#: The tier each registration provides, as doctor prints it. Presence is not enforcement.
TIERS = {
    "claude-code": "blocking (documented; fails open on error)",
    "codex-cli": "blocking once trusted in /hooks (documented; fails open)",
    "antigravity": "blocks destructive commands (live); scan gate records only",
}
#: Where each tier claim comes from (LIVE probed, DOC documented, UNVERIFIED neither).
EVIDENCE = {"claude-code": "DOC", "codex-cli": "DOC", "antigravity": "LIVE"}
KNOWN_GAPS = (
    "Edits made through shell commands never reach the edit gate on any host.",
    "Codex write_stdin into an interactive shell has no PreToolUse payload, and the Codex Bash payload "
    "carries no working directory.",
    "Antigravity manage_task with send_input types into a background terminal past run_command.",
    "Aegis never emits an 'ask' decision (it fails open on Codex and soft-denies in agy headless runs).",
    "The hooks fail open on any Aegis error: they are guardrails, not a security boundary.",
)
#: What doctor says of a Codex entry: trust lives in Codex's own state, not in a file Aegis reads.
TRUST_UNCHECKED = "needs approval in /hooks (cannot be checked)"
CODEX_TRUST_STEP = (
    "Codex runs a new or changed hook only after you trust it: open Codex and approve the aegis hook in "
    "/hooks (doctor cannot check this). Until then Codex skips it silently. codex exec has no documented "
    "trust path besides --dangerously-bypass-hook-trust on each run.")
CODEX_RULES_HEADER = ("# aegis:codex-rules v=1 - generated by `aegis hook install --host codex-cli` from the "
                      "Aegis destructive-command block set.\n")
_AEGIS_NAMES = ("aegis", "aegis.exe")


class UsageError(Exception):
    """A host or scope `aegis hook install --host` does not take (exit 2)."""


class ShapeError(InstallError):
    """A hooks file that parses but is not in the shape its host reads."""

    def __init__(self, path: Path, where: str, what: str):
        self.where, self.what = where, what
        super().__init__(f"{path}: '{where}' must be {what}; left unchanged. Fix the file, then re-run.")


@dataclass
class HookResult:
    host: str
    scope: str
    path: Optional[Path]
    status: str  # added | updated | unchanged | removed | absent | unavailable
    detail: str = ""
    dry_run: bool = False
    backup_dir: Optional[Path] = None
    rules_path: Optional[Path] = None
    rules_status: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"host": self.host, "scope": self.scope, "path": None if self.path is None else str(self.path),
                "status": self.status, "detail": self.detail, "dry_run": self.dry_run,
                "backup_dir": None if self.backup_dir is None else str(self.backup_dir),
                "rules_path": None if self.rules_path is None else str(self.rules_path),
                "rules_status": self.rules_status,
                "tier": UNAVAILABLE if self.status == UNAVAILABLE else TIERS[self.host],
                "evidence": EVIDENCE[self.host], "warnings": list(self.warnings)}


# ── Where the files are ─────────────────────────────────────────────────────

def _windows() -> bool:
    return os.name == "nt"


def _env_dir(environ: Mapping[str, str], name: str) -> Optional[Path]:
    value = environ.get(name) or ""
    return Path(value) if value and os.path.isabs(value) else None


def _codex_home(home: Path, environ: Mapping[str, str]) -> Path:
    return _env_dir(environ, "CODEX_HOME") or home / ".codex"


def check_host(host: str) -> None:
    """Raise UsageError unless ``host`` takes a hook registration."""
    if host in HOOK_HOSTS:
        return
    try:
        spec = host_table.get(host)
    except KeyError:
        spec = None
    if spec is not None and spec.retired:
        raise UsageError(spec.retired)
    raise UsageError(f"--host {host!r} has no Aegis hooks; hook hosts: {', '.join(HOOK_HOSTS)}")


def hook_file(host: str, scope: str, *, home: Path, root: Optional[Path],
              environ: Mapping[str, str]) -> Optional[Path]:
    """The file that holds ``host``'s hooks at ``scope`` (None: project scope without a root)."""
    check_host(host)
    if scope == "project":
        if root is None:
            return None
        rel = {"claude-code": (".claude", "settings.json"), "codex-cli": (".codex", "hooks.json"),
               "antigravity": (".agents", "hooks.json")}[host]
        return Path(root).joinpath(*rel)
    if host == "claude-code":
        return (_env_dir(environ, "CLAUDE_CONFIG_DIR") or Path(home) / ".claude") / "settings.json"
    if host == "codex-cli":
        return _codex_home(Path(home), environ) / "hooks.json"
    return Path(home) / ".gemini" / "config" / "hooks.json"


def codex_rules_file(home: Path, environ: Mapping[str, str]) -> Path:
    return _codex_home(Path(home), environ) / "rules" / "aegis.rules"


# ── The aegis command ───────────────────────────────────────────────────────

def _scripts_dirs() -> List[str]:
    from aegis_cli import pathcheck

    return pathcheck.default_candidates()


def aegis_command(path: Optional[str] = None, scripts_dirs: Optional[Sequence[str]] = None,
                  outside: Optional[Union[str, Path]] = None) -> Optional[str]:
    """The absolute ``aegis`` a hook registration runs: the first in an absolute PATH entry
    outside ``outside`` (the repository, which could plant one), else the console script
    installed with this interpreter; None when neither exists."""
    from aegis_cli import pathcheck
    from aegis_core.pathlookup import which

    found = which("aegis", path, outside=outside)
    if found:
        return found
    dirs = _scripts_dirs() if scripts_dirs is None else list(scripts_dirs)
    directory = pathcheck.scripts_dir(dirs, cmd_name="aegis")
    if directory is None or not os.path.isabs(directory):
        return None
    for name in ("aegis.exe", "aegis") if _windows() else ("aegis",):
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and (_windows() or os.access(candidate, os.X_OK)):
            return candidate
    return None


def unavailable_reason(host: str, aegis: Optional[str] = None) -> Optional[str]:
    """Why ``host``'s hook cannot be registered on this machine, or None."""
    if host == "antigravity" and _windows():
        return ("Antigravity hooks are unavailable on Windows: the shell agy runs hooks with there is "
                "unverified, and a wrong guess would block every tool call")
    if host == "codex-cli" and _windows() and aegis is not None and not AEGIS_PATH_CHARSET.fullmatch(aegis):
        return (f"Codex hooks are unavailable here: Codex runs them through %COMSPEC% /C and the aegis path "
                f"{aegis} is outside {_CHARSET_TEXT}")
    return None


def _check_aegis(host: str, aegis: str) -> None:
    if not os.path.isabs(aegis) and not PureWindowsPath(aegis).is_absolute():
        raise InstallError(f"the aegis path {aegis!r} is not absolute; a hook must name an absolute aegis")
    if host != "claude-code" and not AEGIS_PATH_CHARSET.fullmatch(aegis):
        raise InstallError(
            f"the aegis path {aegis} has characters outside {_CHARSET_TEXT}; {host} runs its hooks through a "
            "shell and Aegis does not quote paths for it. Install aegis under a plain path, then re-run.")


# ── The registration forms ──────────────────────────────────────────────────

def _handler_command(host: str, aegis: str) -> str:
    base = f"{aegis} hook run pre-tool --host {host}"
    if host == "antigravity":
        return f"{base} >/dev/null; [ $? -eq 75 ] && exit 1; exit 0"
    return base


def hook_group(host: str, aegis: str) -> Dict[str, Any]:
    """The exact PreToolUse group ``aegis hook install --host`` writes for ``host``."""
    check_host(host)
    if host == "claude-code":
        handler: Dict[str, Any] = {"type": "command", "command": aegis,
                                   "args": ["hook", "run", "pre-tool", "--host", host], "timeout": HOOK_TIMEOUT_S}
    else:
        handler = {"type": "command", "command": _handler_command(host, aegis), "timeout": HOOK_TIMEOUT_S}
    return {"matcher": MATCHERS[host], "hooks": [handler]}


def _is_aegis_path(token: Any) -> bool:
    if not isinstance(token, str) or not token:
        return False
    absolute = os.path.isabs(token) or PureWindowsPath(token).is_absolute()
    name = PureWindowsPath(token).name if "\\" in token else os.path.basename(token)
    return absolute and name.lower() in _AEGIS_NAMES


def handler_aegis(handler: Any) -> Optional[str]:
    """The absolute ``aegis`` a hook handler runs as ``<aegis> hook run ...`` (exec or
    shell form), or None when the handler is not an Aegis entry."""
    if not isinstance(handler, dict):
        return None
    command, args = handler.get("command"), handler.get("args")
    if isinstance(args, list) and args:
        return command if _is_aegis_path(command) and args[:2] == ["hook", "run"] else None
    if not isinstance(command, str):
        return None
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    if len(tokens) >= 3 and _is_aegis_path(tokens[0]) and tokens[1:3] == ["hook", "run"]:
        return tokens[0]
    return None


def is_aegis_handler(handler: Any) -> bool:
    """Whether a hook handler runs ``<absolute aegis> hook run ...`` (exec or shell form)."""
    return handler_aegis(handler) is not None


#: (path of keys to a PreToolUse group list, group index, handler index, handler)
Located = Tuple[Tuple[str, ...], int, int, Dict[str, Any]]


def _event_lists(host: str, data: Dict[str, Any], path: Path, strict: bool) -> List[Tuple[Tuple[str, ...], list]]:
    """Every PreToolUse group list of a hooks file, with its key path. ``strict`` refuses a
    shape the host would not load (what install would write into); otherwise such parts are
    skipped."""
    out: List[Tuple[Tuple[str, ...], list]] = []

    def bad(where: str, what: str) -> None:
        if strict:
            raise ShapeError(path, where, what)

    if host == "antigravity":
        containers = [((name,), value) for name, value in data.items()]
    else:
        containers = [(("hooks",), data["hooks"])] if "hooks" in data else []
    for keys, container in containers:
        if not isinstance(container, dict):
            if host != "antigravity" or keys == (AGY_GROUP,):
                bad(keys[0], "a JSON object")
            continue
        groups = container.get(EVENT)
        if groups is None:
            continue
        where = ".".join(keys + (EVENT,))
        if not isinstance(groups, list) or not all(isinstance(g, dict) for g in groups):
            bad(where, "a list of objects")
            continue
        for g in groups:
            if "hooks" in g and not isinstance(g["hooks"], list):
                bad(where + "[].hooks", "a list")
                break
        else:
            out.append((keys + (EVENT,), groups))
    return out


def aegis_handlers(host: str, data: Any, path: Path = Path("."), strict: bool = False) -> List[Located]:
    """Every Aegis handler in a hooks file's PreToolUse lists (any group, any position)."""
    if not isinstance(data, dict):
        return []
    found: List[Located] = []
    for keys, groups in _event_lists(host, data, path, strict):
        for gi, group in enumerate(groups):
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                continue
            for hi, handler in enumerate(handlers):
                if is_aegis_handler(handler):
                    found.append((keys, gi, hi, handler))
    return found


def _remove_aegis(host: str, data: Dict[str, Any], path: Path) -> Tuple[int, Optional[Tuple[Tuple[str, ...], int]]]:
    """Drop every Aegis handler (and groups left empty); (count, where the first group was)."""
    count = 0
    first: Optional[Tuple[Tuple[str, ...], int]] = None
    for keys, groups in _event_lists(host, data, path, strict=True):
        kept: List[Any] = []
        for group in groups:
            handlers = group.get("hooks")
            if isinstance(handlers, list) and any(is_aegis_handler(h) for h in handlers):
                count += sum(1 for h in handlers if is_aegis_handler(h))
                rest = [h for h in handlers if not is_aegis_handler(h)]
                if rest:
                    kept.append(dict(group, hooks=rest))
                # A shared group keeps its index (another hook's Codex trust covers its
                # position too); Aegis's own group goes right after it.
                if first is None:
                    first = (keys, len(kept))
                continue
            kept.append(group)
        groups[:] = kept
    return count, first


def _container_path(host: str) -> Tuple[str, ...]:
    return (AGY_GROUP, EVENT) if host == "antigravity" else ("hooks", EVENT)


def _drop_empty(host: str, data: Dict[str, Any]) -> None:
    """Remove the containers Aegis's removal left empty; nothing else."""
    top = AGY_GROUP if host == "antigravity" else "hooks"
    names = list(data) if host == "antigravity" else [top]
    for name in names:
        container = data.get(name)
        if isinstance(container, dict) and container.get(EVENT) == []:
            del container[EVENT]
            if not container and (host != "antigravity" or name == AGY_GROUP):
                del data[name]


# ── Safe writes ─────────────────────────────────────────────────────────────

def _serialize(data: Dict[str, Any]) -> bytes:
    return plane._dump(data)


def _load(path: Path) -> Tuple[Optional[bytes], Dict[str, Any]]:
    return plane._load_json_object(path)


def _backup(path: Path, raw: bytes, backup: Path, dry_run: bool) -> None:
    copy = backup / path.name
    plane._writable_dir(copy, creating=True)
    if dry_run:
        return
    try:
        plane._private_dirs(backup)
        atomic_write_bytes(copy, raw, mode=0o600)
    except OSError as exc:
        raise InstallError(f"{path}: cannot back it up to {backup} ({exc.strerror or exc}); left unchanged") from exc


def _restore(path: Path, raw: Optional[bytes]) -> None:
    try:
        if raw is None:
            os.unlink(path)
        else:
            atomic_write_bytes(path, raw)
    except OSError:
        pass


def _write_json(path: Path, raw: Optional[bytes], data: Dict[str, Any], backup: Path, dry_run: bool,
                check: Any = None) -> None:
    """Back up, replace atomically, then re-read: a file that does not parse back to what
    was meant is replaced by its old bytes (or removed when it was new)."""
    payload = _serialize(data)
    plane._preflight(path, raw)
    if raw is not None:
        _backup(path, raw, backup, dry_run)
    if dry_run:
        return
    plane._replace(path, raw, payload)
    try:
        written = path.read_bytes()
        reread = json.loads(written.decode("utf-8"), object_pairs_hook=plane._reject_duplicates)
        ok = reread == data
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        ok = False
    if not ok:
        _restore(path, raw)
        raise InstallError(f"{path}: did not re-read as the JSON Aegis meant to write; the previous bytes were "
                           "put back. Report this, then re-run.")


def codex_rules_text() -> str:
    """``aegis.rules``: one forbidden ``prefix_rule`` per BLOCK_SET Codex prefix."""
    # Imported here: every aegis command builds the hook parser, which reads this module.
    from aegis_core import command_safety

    parts = [CODEX_RULES_HEADER, "# Do not edit: aegis rewrites it; aegis hook uninstall --host codex-cli removes it.\n"]
    for rule in command_safety.BLOCK_SET:
        for prefix in rule.codex_prefixes:
            pattern = json.dumps([list(p) if isinstance(p, tuple) else p for p in prefix])
            parts.append(
                "\nprefix_rule(\n"
                f"    pattern = {pattern},\n"
                '    decision = "forbidden",\n'
                f"    justification = {json.dumps('aegis: ' + rule.reason)},\n"
                ")\n")
    return "".join(parts)


def _rules_state(path: Path) -> Tuple[Optional[bytes], bool]:
    """(current bytes or None, whether Aegis wrote them); refuses links and specials."""
    raw = plane._read(path)
    return raw, raw is not None and raw.startswith(CODEX_RULES_HEADER.encode("utf-8"))


def _plan_rules(path: Path) -> Tuple[Optional[bytes], str]:
    raw, ours = _rules_state(path)
    want = codex_rules_text().encode("utf-8")
    if raw is not None and not ours:
        raise InstallError(f"{path}: exists and was not written by Aegis; left unchanged. Move it aside, then "
                           "re-run (Aegis never edits your own Codex rules).")
    if raw == want:
        return raw, "unchanged"
    plane._preflight(path, raw)
    return raw, "updated" if raw is not None else "added"


# ── Install / uninstall ─────────────────────────────────────────────────────

def _same_dir(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _other_scope_has_entry(host: str, scope: str, home: Path, root: Optional[Path],
                           environ: Mapping[str, str]) -> Optional[Path]:
    other = "project" if scope == "user" else "user"
    if other == "project" and (root is None or _same_dir(root, home)):
        return None
    path = hook_file(host, other, home=home, root=root, environ=environ)
    if path is None:
        return None
    try:
        _, data = _load(path)
    except InstallError as exc:
        raise InstallError(f"cannot tell whether {host} already has an Aegis hook at {other} scope: {exc}") from exc
    return path if aegis_handlers(host, data, path) else None


def install(host: str, scope: str = "user", *, home: Union[str, Path], root: Optional[Union[str, Path]],
            aegis: str, environ: Mapping[str, str], dry_run: bool = False) -> HookResult:
    """Register ``host``'s PreToolUse hook at ``scope``. Raises UsageError for a host
    without hooks or an unknown scope, InstallError when a file cannot be changed safely
    (nothing is written then)."""
    check_host(host)
    if scope not in SCOPES:
        raise UsageError(f"--scope must be one of {', '.join(SCOPES)}")
    home = Path(home)
    root = None if root is None else Path(root)
    why = unavailable_reason(host, aegis)
    if why:
        return HookResult(host, scope, None, UNAVAILABLE, why, dry_run)
    _check_aegis(host, aegis)
    if scope == "project" and (root is None or _same_dir(root, home)):
        raise InstallError("--scope project needs a repository: here the workspace is your home directory, "
                           "whose host files are the user scope")
    path = hook_file(host, scope, home=home, root=root, environ=environ)
    assert path is not None
    clash = _other_scope_has_entry(host, scope, home, root, environ)
    if clash is not None:
        other = "project" if scope == "user" else "user"
        raise InstallError(f"{host} already has an Aegis hook at {other} scope ({clash}); a second one would run "
                           f"the handler twice. Run aegis hook uninstall --host {host} --scope {other} first.")
    raw, data = _load(path)
    want = hook_group(host, aegis)
    located = aegis_handlers(host, data, path, strict=True)
    container = _container_path(host)
    current = _get_list(data, container)
    if (len(located) == 1 and located[0][0] == container and current is not None
            and current[located[0][1]] == want):
        status = "unchanged"
    else:
        count, first = _remove_aegis(host, data, path)
        status = "updated" if count else "added"
        groups = _ensure_list(data, container, path)
        index = first[1] if first is not None and first[0] == container else len(groups)
        groups.insert(index, want)
    rules_path = codex_rules_file(home, environ) if host == "codex-cli" else None
    rules_raw, rules_status = _plan_rules(rules_path) if rules_path is not None else (None, None)
    backup: Optional[Path] = None
    if status != "unchanged" or rules_status not in (None, "unchanged"):
        backup = plane.backup_dir(home)
    if status != "unchanged":
        _write_json(path, raw, data, backup / scope, dry_run)  # type: ignore[operator]
    if rules_path is not None and rules_status != "unchanged":
        if rules_raw is not None:
            _backup(rules_path, rules_raw, backup / "user", dry_run)  # type: ignore[operator]
        if not dry_run:
            plane._replace(rules_path, rules_raw, codex_rules_text().encode("utf-8"))
    used = backup if backup is not None and backup.exists() else None
    result = HookResult(host, scope, path, status, "", dry_run, used, rules_path, rules_status)
    if host == "codex-cli":
        result.warnings.append(CODEX_TRUST_STEP)
    if scope == "project":
        result.warnings.append(
            f"{path} is a repository file: once committed, your teammates' {host} will execute this hook "
            "(the aegis path in it is this machine's). Commit it only if that is intended.")
    return result


def _get_list(data: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[list]:
    node: Any = data
    for key in keys:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, list) else None


def _ensure_list(data: Dict[str, Any], keys: Tuple[str, ...], path: Path) -> list:
    node: Any = data
    for key in keys[:-1]:
        child = node.setdefault(key, {})
        if not isinstance(child, dict):
            raise InstallError(f"{path}: '{key}' must be a JSON object; left unchanged")
        node = child
    groups = node.setdefault(keys[-1], [])
    if not isinstance(groups, list):
        raise InstallError(f"{path}: '{'.'.join(keys)}' must be a list; left unchanged")
    return groups


def uninstall(host: str, scope: Optional[str] = None, *, home: Union[str, Path], root: Optional[Union[str, Path]],
              environ: Mapping[str, str], dry_run: bool = False) -> List[HookResult]:
    """Remove Aegis's hook entries for ``host`` at ``scope`` (both scopes when None), and
    for Codex the aegis.rules Aegis wrote. Everything else in the files stays."""
    check_host(host)
    if scope is not None and scope not in SCOPES:
        raise UsageError(f"--scope must be one of {', '.join(SCOPES)}")
    home = Path(home)
    root = None if root is None else Path(root)
    scopes = [scope] if scope else list(SCOPES)
    results: List[HookResult] = []
    backup: Optional[Path] = None
    for each in scopes:
        if each == "project" and (root is None or _same_dir(root, home)):
            if scope == "project":
                raise InstallError("--scope project needs a repository: here the workspace is your home directory")
            continue
        path = hook_file(host, each, home=home, root=root, environ=environ)
        assert path is not None
        raw, data = _load(path)
        status = "absent"
        if raw is not None and aegis_handlers(host, data, path, strict=True):
            _remove_aegis(host, data, path)
            _drop_empty(host, data)
            backup = backup or plane.backup_dir(home)
            _write_json(path, raw, data, backup / each, dry_run)
            status = "removed"
        results.append(HookResult(host, each, path, status, "", dry_run))
    if host == "codex-cli":
        rules = codex_rules_file(home, environ)
        raw, ours = _rules_state(rules)
        rules_status = "absent"
        if raw is not None and ours:
            plane._preflight(rules, raw)
            backup = backup or plane.backup_dir(home)
            _backup(rules, raw, backup / "user", dry_run)
            if not dry_run:
                plane._preflight(rules, raw)
                os.unlink(rules)
            rules_status = "removed"
        elif raw is not None:
            rules_status = "not_aegis"
        target = results[0] if results else None
        if target is not None:
            target.rules_path, target.rules_status = rules, rules_status
    used = backup if backup is not None and backup.exists() else None
    for result in results:
        result.backup_dir = used
    return results


# ── CLI ─────────────────────────────────────────────────────────────────────

def _envelope(command: str, host: str, scope: Optional[str], root: Optional[Path],
              results: List[HookResult]) -> Dict[str, Any]:
    from aegis_core._version import __version__

    return {"source": f"aegis hook {command}", "aegis_version": __version__,
            "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scope": {"host": host, "scope": scope, "workspace": None if root is None else str(root)},
            "results": [r.as_dict() for r in results]}


def _context(args: Any) -> Tuple[Path, Optional[Path]]:
    from aegis_core.workspace.layout import UserLayout

    layout = UserLayout.current()
    if layout is None:
        raise InstallError("no home directory: Aegis cannot find the host config files")
    ws = getattr(args, "ws", None)
    raw = getattr(ws, "root", None) or getattr(args, "_project_root", None) or getattr(args, "workspace", None)
    root = Path(raw).resolve() if raw else None
    return Path(layout.home), root


def _print_text(command: str, results: List[HookResult]) -> None:
    for r in results:
        where = r.path if r.path is not None else "-"
        verb = {"added": "added to", "updated": "updated in", "unchanged": "already current in",
                "removed": "removed from", "absent": "not found in"}.get(r.status)
        prefix = "(dry run) " if r.dry_run else ""
        if r.status == UNAVAILABLE:
            print(f"➖ {r.host}: hooks unavailable: {r.detail}")
            continue
        icon = "ℹ️ " if r.status in ("absent", "unchanged") else "✅"
        print(f"{icon} {prefix}{r.host}: the Aegis PreToolUse hook {verb} {where} ({r.scope} scope)")
        if r.rules_path is not None and r.rules_status:
            print(f"   Codex rules {r.rules_path}: {r.rules_status.replace('_', ' ')}")
        if command == "install":
            print(f"   tier: {TIERS[r.host]} [{EVIDENCE[r.host]}]; doctor cannot confirm the host runs it")
        if r.backup_dir is not None:
            print(f"   backup: {r.backup_dir}")
        for warning in r.warnings:
            if "teammates" in warning:
                print(f"⚠️  {warning}", file=sys.stderr)
            else:
                print(f"   Next: {warning}")


def _run(command: str, args: Any) -> int:
    host = str(getattr(args, "host", "") or "")
    scope = getattr(args, "scope", None)
    use_json = bool(getattr(args, "json", False))
    dry_run = bool(getattr(args, "dry_run", False))
    try:
        check_host(host)
        if scope is not None and scope not in SCOPES:
            raise UsageError(f"--scope must be one of {', '.join(SCOPES)}")
        home, root = _context(args)
        if command == "install":
            aegis = aegis_command(os.environ.get("PATH", ""), outside=root)
            if aegis is None:
                why = unavailable_reason(host)
                if why:
                    results = [HookResult(host, scope or "user", None, UNAVAILABLE, why, dry_run)]
                else:
                    raise InstallError("no absolute aegis command found (not on an absolute PATH entry outside the "
                                       "repository, nor beside this Python): install aegis, then re-run")
            else:
                results = [install(host, scope or "user", home=home, root=root, aegis=aegis, environ=os.environ,
                                   dry_run=dry_run)]
        else:
            results = uninstall(host, scope, home=home, root=root, environ=os.environ, dry_run=dry_run)
    except UsageError as exc:
        print(f"aegis hook {command}: {exc}", file=sys.stderr)
        return 2
    except InstallError as exc:
        print(f"❌ aegis hook {command} --host {host}: {exc}", file=sys.stderr)
        return 1
    if use_json:
        print(json.dumps(_envelope(command, host, scope or ("user" if command == "install" else None), root,
                                   results), indent=2))
        for r in results:
            for warning in r.warnings:
                if "teammates" in warning:
                    print(f"⚠️  {warning}", file=sys.stderr)
    else:
        _print_text(command, results)
    return 1 if any(r.status == UNAVAILABLE for r in results) else 0


def run_host_install(args: Any) -> int:
    """`aegis hook install --host <h> [--scope user|project] [--dry-run] [--json]`."""
    return _run("install", args)


def run_host_uninstall(args: Any) -> int:
    """`aegis hook uninstall --host <h> [--scope user|project] [--dry-run] [--json]`."""
    return _run("uninstall", args)
