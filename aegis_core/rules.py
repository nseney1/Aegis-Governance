"""The one rule loader (ADR 0005 AD-3 L1, defense #19, v4.3 spec §10.3).

``load_rules(workspace)`` is how every part of Aegis reads rules: aegis scan, aegis
check, status, sync, list, lifecycle and the SDK. It is a projection of
``rule_inventory.inventory_rules`` (the race-detecting byte snapshot, which stays the
fingerprint), so it never reads a rule file twice and never follows a link.

One policy, applied everywhere:

- A rule is ``.aegis/rules/<type dir>/<id>.md``, where the directory is one of the six
  of ``taxonomy.RULE_TYPES``. Its id is the file stem; its type is its directory.
- ``README.md`` and anything under a hidden directory (``.archive``) are skipped.
- A markdown file anywhere else under ``.aegis/rules`` is never served. If it looks
  like a rule (a ``type``, ``target_paths`` or ``forbid_ast`` key, or frontmatter that
  cannot be read) it is an error record, so a rule left in a v3 directory such as
  ``walls/`` cannot silently stop applying; anything else is reported as ignored.
- A file that cannot be decoded or parsed, whose frontmatter ``id`` or ``type``
  disagrees with its name or directory, whose id another rule also uses, or that sets
  an unknown enforcement-relevant key (``paths``, ``target_path``, ``enforce``, ...)
  becomes a record carrying ``error``. Callers that serve rules (scan, check) fail
  closed on error records; listing callers show them. Nothing is dropped silently.
- Derived counters (``fitness``, ``triggers: 12``, ...) are not rule content: they are
  removed from ``meta`` and listed in ``legacy_counters`` (``aegis migrate`` strips them).
- A rule with ``expired_at`` is loaded but not served (``Rule.expired``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
import threading
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

from aegis_core.rule_inventory import RuleInventory, RuleInventoryEntry, inventory_rules
from aegis_core.taxonomy import DIR_RULE_TYPES, RULE_TYPES
from aegis_core.workspace.layout import RULES_RELDIR
from aegis_core.yaml_engine.frontmatter import split_frontmatter
from aegis_core.yaml_engine.parser import AegisYAMLError, parse_yaml_subset

__all__ = [
    "DERIVED_KEYS",
    "ENFORCEMENT_KEYS",
    "VALID_ENFORCEMENT",
    "Ignored",
    "Rule",
    "RuleCache",
    "RuleSet",
    "is_derived",
    "load_rules",
    "lf_digest",
    "workspace_root",
]

VALID_ENFORCEMENT = ("advisory", "mechanical", "gate")

# Keys that decide what a rule enforces and where.
ENFORCEMENT_KEYS = frozenset({"type", "enforcement", "target_paths", "forbid_ast", "expired_at"})
# A key outside ENFORCEMENT_KEYS whose name carries one of these looks like an attempt to
# set where or how a rule applies (a misspelling, or an alias v3 tolerated such as
# `paths`); serving the rule without it would apply it in the wrong place.
_ENFORCEMENT_STEMS = ("target", "path", "glob", "enforc", "forbid")
# Enforcement keys v4 no longer reads (D14).
_RETIRED_ENFORCEMENT_KEYS = frozenset({"ast_triggers", "planned_symbols"})

# Frontmatter keys derived from the ledger; rule files never carry them (v4.3 §10.2).
DERIVED_KEYS = frozenset({
    "fitness", "triggers", "true_positives", "false_positives", "last_trigger_date",
    "last_triggered", "score", "fitness_score", "tp", "fp", "tp_rate", "fp_rate",
})
_TIMESTAMP_KEYS = frozenset({"last_trigger_date", "last_triggered"})
_RULE_SIGNAL_KEYS = ("type", "target_paths", "forbid_ast")
_NO_FRONTMATTER = "no frontmatter metadata"
_UNTERMINATED = "unterminated YAML frontmatter (no closing --- line)"


def is_derived(key: str, value: Any) -> bool:
    """Whether ``key: value`` is a ledger-derived counter. Only counter-shaped values count:
    ``triggers: [documentation_edit]`` is a rule's list of trigger keywords, and stays."""
    if key not in DERIVED_KEYS:
        return False
    if key == "fitness":
        return isinstance(value, (dict, int, float)) or value is None
    if key in _TIMESTAMP_KEYS:
        return value is None or isinstance(value, str) or hasattr(value, "isoformat")
    if isinstance(value, bool):
        return False
    if value is None or isinstance(value, (int, float)):
        return True
    try:
        float(str(value))
        return True
    except ValueError:
        return False


def lf_digest(content: bytes) -> str:
    """sha256 of ``content`` with CRLF normalized to LF: the same rule hashes the same on
    a Windows checkout (core.autocrlf) and a Linux one."""
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


@dataclass(frozen=True)
class Rule:
    """One rule file as loaded. ``error`` is set when it cannot be served as written."""

    id: str
    path: str  # workspace-relative POSIX path
    type: Optional[str]  # from its directory; None outside a rule type directory
    meta: Mapping[str, Any]  # frontmatter without derived counters
    body: str
    digest: str  # lf_digest of the file bytes
    error: Optional[str] = None
    legacy_counters: Tuple[str, ...] = ()
    raw: bytes = field(default=b"", repr=False, compare=False)

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def expired(self) -> bool:
        return bool(self.meta.get("expired_at"))

    @property
    def served(self) -> bool:
        """Loaded cleanly and not expired: scan and check apply it."""
        return self.ok and not self.expired

    @property
    def target_paths(self) -> Tuple[str, ...]:
        value = self.meta.get("target_paths")
        if isinstance(value, str):
            return (value,)
        if isinstance(value, (list, tuple)):
            return tuple(p for p in value if isinstance(p, str))
        return ()

    @property
    def enforcement(self) -> str:
        value = self.meta.get("enforcement")
        return value if isinstance(value, str) and value else "advisory"

    @property
    def mandatory(self) -> bool:
        """Gates and invariants by type, and any rule that declares ``enforcement: gate``."""
        spec = RULE_TYPES.get(self.type or "")
        return bool(spec and spec.mandatory) or self.enforcement == "gate"

    def as_dict(self) -> Dict[str, Any]:
        """The frontmatter plus ``type``, ``_name``/``_path`` (and ``_error``), as list payloads show it."""
        data: Dict[str, Any] = dict(self.meta)
        if self.type is not None:
            data["type"] = self.type  # its directory: a rule need not repeat it in frontmatter
        data["_name"] = self.id
        data["_path"] = self.path
        if self.error is not None:
            data["_error"] = self.error
        return data


@dataclass(frozen=True)
class Ignored:
    """A markdown file under ``.aegis/rules`` that is not a rule, and why."""

    path: str
    reason: str


@dataclass(frozen=True)
class RuleSet:
    """Every rule record of a workspace, plus the files that are not rules."""

    rules: Tuple[Rule, ...]
    ignored: Tuple[Ignored, ...] = ()
    fingerprint: str = ""

    def __iter__(self) -> Iterator[Rule]:
        return iter(self.rules)

    def __len__(self) -> int:
        return len(self.rules)

    @property
    def errors(self) -> Tuple[Rule, ...]:
        return tuple(r for r in self.rules if not r.ok)

    @property
    def served(self) -> Tuple[Rule, ...]:
        return tuple(r for r in self.rules if r.served)

    @property
    def needs_migrate(self) -> Tuple[Rule, ...]:
        """Rules whose files still carry derived counters (``aegis migrate`` strips them)."""
        return tuple(r for r in self.rules if r.legacy_counters)

    def get(self, rule_id: str) -> Optional[Rule]:
        """The rule with ``rule_id`` that loaded cleanly, or None."""
        for rule in self.rules:
            if rule.ok and rule.id == rule_id:
                return rule
        return None


def workspace_root(workspace: Any) -> str:
    """The absolute root of ``workspace``: a path, a string or a Workspace."""
    if not isinstance(workspace, (str, os.PathLike)):
        workspace = workspace.root
    return os.path.abspath(os.fspath(workspace))


def _stem(relative: str) -> str:
    return os.path.splitext(relative.rsplit("/", 1)[-1])[0]


def _target_paths_error(value: Any) -> Optional[str]:
    if value is None or isinstance(value, str):
        return None
    if isinstance(value, list) and all(isinstance(p, str) for p in value):
        return None
    return "target_paths must be a glob pattern or a list of glob patterns"


def _unknown_enforcement_keys(meta: Mapping[str, Any]) -> List[str]:
    found = []
    for key in meta:
        if not isinstance(key, str) or key in ENFORCEMENT_KEYS or key in DERIVED_KEYS:
            continue
        norm = key.lower().replace("-", "_")
        if norm in _RETIRED_ENFORCEMENT_KEYS or any(stem in norm for stem in _ENFORCEMENT_STEMS):
            found.append(key)
    return sorted(found)


def _parse(entry: RuleInventoryEntry, rule_type: Optional[str], directory: str) -> Rule:
    relative = entry.relative_path
    stem = _stem(relative)
    digest = lf_digest(entry.content)

    def broken(message: str, meta: Optional[Mapping[str, Any]] = None) -> Rule:
        return Rule(stem, relative, rule_type, dict(meta or {}), "", digest, message, raw=entry.content)

    try:
        text = entry.content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return broken(f"invalid UTF-8: {exc}")
    status, fm_text, body = split_frontmatter(text)
    if status == "unterminated":
        return broken(_UNTERMINATED)
    if status == "none" or not (fm_text or "").strip():
        return broken(_NO_FRONTMATTER)
    try:
        meta = parse_yaml_subset(fm_text.strip())
    except (AegisYAMLError, RecursionError) as exc:
        return broken(f"malformed YAML frontmatter: {exc}")
    if not isinstance(meta, dict) or not meta:
        return broken(_NO_FRONTMATTER)

    counters = tuple(sorted(k for k, v in meta.items() if is_derived(k, v)))
    clean = {k: v for k, v in meta.items() if k not in counters}
    problems: List[str] = []
    declared_id = clean.get("id")
    if declared_id is not None and declared_id != stem:
        problems.append(f"id {declared_id!r} does not match the file name {stem!r}")
    declared_type = clean.get("type")
    if rule_type is not None and declared_type is not None and declared_type != rule_type:
        problems.append(f"type {declared_type!r} does not match its directory {directory!r} ({rule_type})")
    enforcement = clean.get("enforcement")
    if enforcement is not None and enforcement not in VALID_ENFORCEMENT:
        problems.append(f"unknown enforcement {enforcement!r} (expected one of {', '.join(VALID_ENFORCEMENT)})")
    paths_error = _target_paths_error(clean.get("target_paths"))
    if paths_error:
        problems.append(paths_error)
    unknown = _unknown_enforcement_keys(clean)
    if unknown:
        problems.append(
            f"unknown enforcement-relevant key(s) {', '.join(repr(k) for k in unknown)} "
            f"(known: {', '.join(sorted(ENFORCEMENT_KEYS))})"
        )
    return Rule(
        id=stem,
        path=relative,
        type=rule_type,
        meta=clean,
        body=body.strip(),
        digest=digest,
        error="; ".join(problems) or None,
        legacy_counters=counters,
        raw=entry.content,
    )


def _outside_type_dir(entry: RuleInventoryEntry, parts: List[str]) -> Tuple[Optional[Rule], Optional[Ignored]]:
    """A markdown file under .aegis/rules but not directly in a rule type directory."""
    if len(parts) == 1:
        where = "it is not in a rule type directory"
    elif parts[0] in DIR_RULE_TYPES:
        where = f"rules are not loaded from subdirectories of {parts[0]}/"
    else:
        where = f"{parts[0]}/ is not a rule type directory"
    rule = _parse(entry, None, parts[0])
    # Frontmatter that cannot be read may hold any key, so it counts as a rule; a file
    # with no frontmatter at all is a note.
    unreadable = not rule.ok and rule.error != _NO_FRONTMATTER
    looks_like_rule = unreadable or any(key in rule.meta for key in _RULE_SIGNAL_KEYS)
    if looks_like_rule:
        dirs = ", ".join(sorted(DIR_RULE_TYPES))
        message = (
            f"not served: {where} (expected {RULES_RELDIR}/<{dirs}>/<id>.md; "
            "aegis migrate converts v3 layouts)"
        )
        if not rule.ok:
            message = f"{message}; {rule.error}"
        return Rule(rule.id, rule.path, None, rule.meta, rule.body, rule.digest, message, rule.legacy_counters, rule.raw), None
    return None, Ignored(entry.relative_path, f"not a rule: {where}")


def load_rules(workspace: Any, inventory: Optional[RuleInventory] = None) -> RuleSet:
    """Load every rule of ``workspace`` (a path or a Workspace).

    Raises RuleInventoryError when the rules tree cannot be read safely (a symlink, an
    unreadable directory, a file changed mid-read): no partial set is ever returned.
    """
    root = workspace_root(workspace)
    snapshot = inventory if inventory is not None else inventory_rules(root)
    prefix = RULES_RELDIR + "/"
    loaded: List[Rule] = []
    ignored: List[Ignored] = []
    for entry in snapshot.entries:
        relative = entry.relative_path
        if not relative.startswith(prefix):
            continue
        parts = relative[len(prefix):].split("/")
        if parts[-1].lower() == "readme.md" or any(p.startswith(".") for p in parts):
            continue
        rule_type = DIR_RULE_TYPES.get(parts[0]) if len(parts) == 2 else None
        if rule_type is None:
            rule, skipped = _outside_type_dir(entry, parts)
            if rule is not None:
                loaded.append(rule)
            if skipped is not None:
                ignored.append(skipped)
            continue
        loaded.append(_parse(entry, rule_type, parts[0]))

    by_id: Dict[str, List[int]] = {}
    for index, rule in enumerate(loaded):
        by_id.setdefault(rule.id, []).append(index)
    for rule_id, indexes in by_id.items():
        if len(indexes) < 2:
            continue
        paths = [loaded[i].path for i in indexes]
        for i in indexes:
            rule = loaded[i]
            others = ", ".join(p for p in paths if p != rule.path)
            message = f"duplicate rule id {rule_id!r} (also {others})"
            if rule.error:
                message = f"{message}; {rule.error}"
            loaded[i] = Rule(rule.id, rule.path, rule.type, rule.meta, rule.body, rule.digest, message,
                             rule.legacy_counters, rule.raw)
    return RuleSet(tuple(loaded), tuple(ignored), snapshot.fingerprint)


class RuleCache:
    """Parsed rules per workspace, reused while the inventory fingerprint is unchanged.

    The inventory (the byte snapshot) is taken on every call, so an edit is always seen;
    only parsing is skipped. A rule is never excluded here: what load_rules returns, the
    cache returns.
    """

    _MAX_WORKSPACES = 8

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: Dict[str, Tuple[str, RuleSet]] = {}

    def get(self, workspace: Any) -> RuleSet:
        key = workspace_root(workspace)
        snapshot = inventory_rules(key)
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None and cached[0] == snapshot.fingerprint:
                return cached[1]
        ruleset = load_rules(key, inventory=snapshot)
        with self._lock:
            if key not in self._entries and len(self._entries) >= self._MAX_WORKSPACES:
                self._entries.pop(next(iter(self._entries)))
            self._entries[key] = (snapshot.fingerprint, ruleset)
        return ruleset

    def invalidate(self) -> None:
        with self._lock:
            self._entries.clear()
