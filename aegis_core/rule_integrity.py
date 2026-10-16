"""Rule integrity: git is the witness (v4.3 spec T3).

A same-uid agent can edit any file in the working tree, so the working tree's rules prove
nothing about what a human reviewed. What git holds at a reviewed commit does. This module
anchors every binding rule there.

**The anchor.** ``BASE`` is the first available of: the user-scope ``rules.base_ref``
(``~/.aegis/config.json``; never the repository's own config); ``git merge-base HEAD
refs/remotes/origin/HEAD``; ``HEAD``, labelled "local-head, not review-witnessed".

**Serving** (``effective``). A rule of rank 2 or more (``aegis_core.rules.rank_of``: an
invariant, or a rule declaring ``enforcement: gate``), with its rank read from the BASE
frontmatter, is served and enforced from its BASE blob. Where the working tree differs, the
stricter version wins and the other is never used: a version that weakens anything
``weakenings`` knows about loses outright, and so does one that merely rewrites text. A rule
that is new, changed, removed or broken on this branch is reported in ``unreviewed``
(id, title, kind of change) and is never mandatory and never gating. Rules of rank 1 are
served as they are. Outside git, or with no commit yet, nothing is anchored and the working
tree is served as before.

**The comparison** is of the policy view: the frontmatter without derived counters, plus the
body (``Rule.meta``, ``Rule.body``, ``Rule.type``), so a ledger-derived counter never makes a
rule look edited.

**The CI check** (``check_ci``) reads the net diff ``merge-base(base, head)..head`` over the
rank 2+ rules at that merge base and flags exactly the weakenings of spec T3: a deletion or an
archive with no same-id reappearance, a rank decrease, a loss of coverage of files that exist
(rename-aware), a ``forbid_ast`` pattern no longer subsumed (imports by dotted prefix, calls
and decorators by dotted suffix), a ``detect`` that is not an exact superset, any new or
unknown key (fail closed), and any change to ``applies_to`` on a rule of any rank; plus a
mandatory rule added past the scan's slot cap on a path other mandatory rules already cover.
``minimum_mode``, expiry and ``impact_weight`` are excluded. A weakening passes only with a
verified approval (``aegis_core.human_gate``); otherwise the check fails with itemized findings.

Everything here reads git objects through plumbing only (``ls-tree -r -z``, ``cat-file
--batch``, ``diff-tree``, ``merge-base``, ``rev-parse``) with the hardened environment of
``aegis_core.gitsafe``, and checks every blob's content against its object id.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from aegis_core import gitsafe
from aegis_core.errors import AegisError
from aegis_core.rule_inventory import RuleInventory, RuleInventoryEntry, inventory_rules
from aegis_core.rules import ENFORCEMENT_KEYS, Rule, RuleCache, RuleSet, VALID_ENFORCEMENT, load_rules, workspace_root
from aegis_core.workspace.layout import RULES_RELDIR, UserLayout

__all__ = [
    "BENIGN_KEYS",
    "BaseAnchor",
    "CiReport",
    "EXCLUDED_KEYS",
    "Effective",
    "IntegrityError",
    "LOCAL_HEAD_LABEL",
    "MANDATORY_SLOT_CAP",
    "Unreviewed",
    "Weakening",
    "check_ci",
    "effective",
    "effective_ruleset",
    "policy_view",
    "resolve_base",
    "weakenings",
]

SCHEMA = "aegis.rule_integrity/v1"
SOURCE = "aegis check --ci"
LOCAL_HEAD_LABEL = "local-head, not review-witnessed"

# Mandatory rules (gates, invariants, ``enforcement: gate``) may take at most this many of a
# scan's rule slots, so a few rules that declare themselves mandatory on ``**`` cannot starve
# every advisory rule (aegis_core.scan). Adding one past it is a governance change (T3).
MANDATORY_SLOT_CAP = 2

# Keys that change nothing a rule enforces, and that the spec excludes from the weakening
# list: loosening them is not loosening the rule (T3 "Excluded").
EXCLUDED_KEYS = frozenset({"minimum_mode", "impact_weight", "expiry_days", "expiry_sessions", "expired_at"})
# Descriptive keys no enforcement path reads. Any other key a branch adds or changes on a
# binding rule is unknown, and unknown fails closed.
BENIGN_KEYS = frozenset({
    "id", "name", "description", "domain", "hypothesis", "prediction", "falsification", "created", "tags",
    "lineage", "triggers", "persona_name", "origin", "expertise", "expertise_domain", "promotion_threshold",
    "demotion_threshold",
})
_CHECKED_KEYS = frozenset({"detect", "applies_to"})
_KNOWN_KEYS = ENFORCEMENT_KEYS | EXCLUDED_KEYS | BENIGN_KEYS | _CHECKED_KEYS
_FORBID_KINDS = ("imports", "calls", "decorators")
_ENFORCEMENT_ORDER = {name: index for index, name in enumerate(VALID_ENFORCEMENT)}

_USER_CONFIG_LIMIT = 64 * 1024
_GIT_TIMEOUT = 60.0
_MD = ".md"


class IntegrityError(AegisError):
    """The base cannot be read, or a blob does not hash to its object id: nothing is served
    or passed on a guess."""


# ── The anchor ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BaseAnchor:
    """The commit binding rules are read from, and how much a person can rely on it."""

    ref: str
    commit: str
    source: str  # "user-config" | "origin-head" | "local-head"
    witnessed: bool  # a reviewed branch tip (or one the user named); False for a local HEAD
    label: str

    def as_dict(self) -> Dict[str, Any]:
        return {"ref": self.ref, "commit": self.commit, "source": self.source, "witnessed": self.witnessed,
                "label": self.label}


def _within(path: Path, root: Path) -> bool:
    try:
        resolved, base = path.resolve(), root.resolve()
        return os.path.commonpath([str(resolved), str(base)]) == str(base)
    except (OSError, ValueError, RuntimeError):
        return False


def _user_base_ref(root: str) -> Optional[str]:
    """``rules.base_ref`` from ``~/.aegis/config.json``, or None. A file that lies inside the
    workspace is repository content, not user scope, and is not read."""
    layout = UserLayout.current()
    if layout is None:
        return None
    path = layout.config_file
    try:
        if not path.is_file() or _within(path, Path(root)):
            return None
        with open(path, "rb") as handle:
            raw = handle.read(_USER_CONFIG_LIMIT + 1)
        if len(raw) > _USER_CONFIG_LIMIT:
            return None
        data = json.loads(raw.decode("utf-8-sig"))
    except (OSError, ValueError):
        return None
    rules = data.get("rules") if isinstance(data, dict) else None
    ref = rules.get("base_ref") if isinstance(rules, dict) else None
    if isinstance(ref, str) and ref.strip() and not ref.strip().startswith("-"):
        return ref.strip()
    return None


def resolve_base(workspace: Any) -> Optional[BaseAnchor]:
    """The BASE anchor of ``workspace``, or None outside a git work tree / before the first commit."""
    root = workspace_root(workspace)
    top = gitsafe.toplevel(root)
    if top is None:
        return None
    ref = _user_base_ref(root)
    if ref:
        commit = gitsafe.resolve_commit(root, ref)
        if commit:
            return BaseAnchor(ref, commit, "user-config", True, f"rules.base_ref {ref} (user config)")
    reviewed = gitsafe.merge_base(root, "refs/remotes/origin/HEAD", "HEAD")
    if reviewed:
        return BaseAnchor("origin/HEAD", reviewed, "origin-head", True, "merge-base of HEAD and origin/HEAD")
    head = gitsafe.head_commit(root)
    if head:
        return BaseAnchor("HEAD", head, "local-head", False, LOCAL_HEAD_LABEL)
    return None


# ── Reading rules out of git ─────────────────────────────────────────────────

def _blob_oid(data: bytes, oid_length: int) -> str:
    digest = hashlib.sha256 if oid_length == 64 else hashlib.sha1
    return digest(b"blob %d\0" % len(data) + data).hexdigest()


def _run(cwd: str, args: Sequence[str], stdin: Optional[bytes] = None) -> bytes:
    try:
        res = gitsafe.run(list(args), cwd, timeout=_GIT_TIMEOUT, stdin=stdin)
    except gitsafe.GitError as exc:
        raise IntegrityError(str(exc)) from exc
    if res.returncode != 0:
        detail = " ".join(res.stderr.decode("utf-8", "replace").split())[:200]
        raise IntegrityError(f"git {args[0]} failed: {detail}")
    return res.stdout


def _rule_blobs(cwd: str, commit: str) -> Dict[str, str]:
    """``{path: oid}`` of every ``.md`` blob below ``.aegis/rules`` at ``commit``: one ``ls-tree -r -z``.
    Paths are relative to ``cwd`` (the workspace root), which is what the loader expects."""
    out = _run(cwd, ["ls-tree", "-r", "-z", commit, "--", RULES_RELDIR])
    found: Dict[str, str] = {}
    for record in out.split(b"\0"):
        meta, _, raw_path = record.partition(b"\t")
        fields = meta.split()
        if len(fields) != 3 or not raw_path:
            continue
        mode, kind, oid = (f.decode("ascii", "replace") for f in fields)
        path = os.fsdecode(raw_path)
        if kind != "blob" or mode == "120000" or not path.lower().endswith(_MD):
            continue  # a symlink or a submodule is never a rule
        found[path] = oid
    return found


def _read_blobs(cwd: str, oids: Iterable[str]) -> Dict[str, bytes]:
    """The content of each blob (one ``cat-file --batch``), each checked against its object id."""
    wanted = list(dict.fromkeys(oids))
    if not wanted:
        return {}
    out = _run(cwd, ["cat-file", "--batch"], stdin=("\n".join(wanted) + "\n").encode("ascii"))
    blobs: Dict[str, bytes] = {}
    position = 0
    for oid in wanted:
        end = out.find(b"\n", position)
        header = out[position:end].split() if end >= 0 else []
        if len(header) != 3 or header[0].decode("ascii", "replace") != oid or header[1] != b"blob" or not header[2].isdigit():
            raise IntegrityError(f"git cannot read object {oid}")
        size = int(header[2])
        data = out[end + 1:end + 1 + size]
        if len(data) != size or _blob_oid(data, len(oid)) != oid:
            raise IntegrityError(f"git returned content for {oid} that does not match the object id")
        blobs[oid] = data
        position = end + 1 + size + 1
    return blobs


def _fingerprint(entries: Sequence[RuleInventoryEntry]) -> str:
    aggregate = hashlib.sha256(b"aegis-rule-inventory-v1\0")
    for entry in entries:
        aggregate.update(entry.relative_path.encode("utf-8") + b"\0")
        aggregate.update(bytes.fromhex(entry.digest))
        aggregate.update(b"\0")
    return aggregate.hexdigest()


def _inventory_at(root: str, commit: str, working: Optional[RuleInventory] = None) -> RuleInventory:
    """The rules of ``commit`` as a loader inventory. A working-tree file whose bytes already
    hash to the committed object id is reused as is (the in-process oid compare); only the
    others are read with ``cat-file --batch``."""
    blobs = _rule_blobs(root, commit)
    present = {e.relative_path: e for e in working.entries} if working is not None else {}
    entries: List[RuleInventoryEntry] = []
    missing: List[Tuple[str, str]] = []
    for path, oid in sorted(blobs.items()):
        local = present.get(path)
        if local is not None and _blob_oid(local.content, len(oid)) == oid:
            entries.append(local)
        else:
            missing.append((path, oid))
    contents = _read_blobs(root, (oid for _path, oid in missing))
    for path, oid in missing:
        data = contents[oid]
        entries.append(RuleInventoryEntry(path, os.path.join(root, *path.split("/")), data,
                                          hashlib.sha256(data).hexdigest(), len(data)))
    entries.sort(key=lambda e: e.relative_path)
    return RuleInventory(tuple(entries), _fingerprint(entries))


def _tree_files(root: str, commit: str) -> List[str]:
    """Every file path of ``commit``'s tree (relative to the workspace root), sorted."""
    out = _run(root, ["ls-tree", "-r", "-z", "--name-only", commit])
    return sorted(os.fsdecode(p) for p in out.split(b"\0") if p)


# ── The policy view and the weakening analysis ───────────────────────────────

def policy_view(rule: Rule) -> Tuple[Any, Any, Any]:
    """What a rule says, without what the ledger derived: type, frontmatter and body."""
    # CRLF and LF checkouts of one rule (core.autocrlf) are the same policy.
    return (rule.type, dict(rule.meta), rule.body.replace("\r\n", "\n"))


def title_of(rule: Rule) -> str:
    """The rule's first markdown heading (else its id), one bounded line. It is branch-local
    text that reaches an agent, so control characters go and the length is capped."""
    for line in rule.body.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if line.lstrip().startswith("#") and stripped:
            text = stripped
            break
    else:
        text = rule.id
    cleaned = "".join(ch if ch.isprintable() else " " for ch in text)
    cleaned = " ".join(cleaned.split())
    return cleaned[:77] + "..." if len(cleaned) > 80 else cleaned


@dataclass(frozen=True)
class Weakening:
    """One way a head version of a rule binds less than its base version (or a governance
    change that needs the same approval)."""

    code: str  # deleted | rank | coverage | forbid_ast | detect | unknown_key | applies_to | mandatory_cap
    rule: str
    path: str
    message: str

    def as_dict(self) -> Dict[str, str]:
        return {"code": self.code, "rule": self.rule, "path": self.path, "message": self.message}


class _Tree:
    """What the coverage test needs to know about the files: those at the base tree (read
    lazily, one ``ls-tree``), the renames the diff found, and the files it deleted."""

    def __init__(self, root: Optional[str], commit: Optional[str], renames: Optional[Mapping[str, str]] = None,
                 deleted: Iterable[str] = ()) -> None:
        self._root, self._commit = root, commit
        self._files: Optional[List[str]] = None
        self.renames: Mapping[str, str] = renames or {}
        self.deleted = frozenset(deleted)

    @property
    def files(self) -> List[str]:
        if self._files is None:
            self._files = _tree_files(self._root, self._commit) if self._root and self._commit else []
        return self._files


def _dotted_covers(kind: str, broad: str, narrow: str) -> bool:
    """Whether the forbid_ast pattern ``broad`` matches everything ``narrow`` does."""
    if broad == narrow:
        return True
    if kind == "imports":
        return narrow.startswith(broad + ".")
    return narrow.endswith("." + broad)


def _forbid_patterns(spec: Any, kind: str) -> List[str]:
    from aegis_core.ast.schema import _normalize_ast_token

    values = spec.get(kind) if isinstance(spec, dict) else None
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return []
    return [t for t in (_normalize_ast_token(v) for v in values if isinstance(v, str)) if t]


def _forbid_findings(base: Rule, head: Rule) -> List[str]:
    before, after = base.meta.get("forbid_ast"), head.meta.get("forbid_ast")
    if before is None:
        return []
    if not isinstance(after, dict):
        return ["forbid_ast was removed"]
    lost: List[str] = []
    for kind in _FORBID_KINDS:
        kept = _forbid_patterns(after, kind)
        for pattern in _forbid_patterns(before, kind):
            if not any(_dotted_covers(kind, other, pattern) for other in kept):
                lost.append(f"{kind[:-1]} {pattern!r} is no longer forbidden")
    if isinstance(before, dict):
        for kind in sorted(k for k in before if k not in _FORBID_KINDS):
            # A forbid_ast option this version does not understand cannot be compared by
            # subsumption: it must be carried over unchanged or widened (an exact superset).
            if not _is_superset(before.get(kind), after.get(kind)):
                lost.append(f"forbid_ast option {kind!r} is not an exact superset")
    return lost


def _is_superset(before: Any, after: Any) -> bool:
    if before is None:
        return True
    if after is None:
        return False
    if isinstance(before, (list, tuple)) and isinstance(after, (list, tuple)):
        return all(item in after for item in before)
    return before == after


def _level(rule: Rule) -> Tuple[int, int]:
    return rule.rank, _ENFORCEMENT_ORDER.get(rule.enforcement, 0)


def _coverage_lost(base: Rule, head: Rule, tree: _Tree) -> List[str]:
    """Files that exist and that the base version of the rule reached and the head version no
    longer does (a file the diff renamed is judged at its new path; a deleted file is gone, not uncovered)."""
    lost: List[str] = []
    if base.target_paths == head.target_paths and base.skips_tests == head.skips_tests:
        candidates: Iterable[str] = list(tree.renames)  # an unchanged rule can only lose a file by a move
    else:
        candidates = tree.files
    for old in candidates:
        if old in tree.deleted and old not in tree.renames:
            continue
        new = tree.renames.get(old, old)
        if base.applies_to(old) and not head.applies_to(new):
            lost.append(new)
    return sorted(set(lost))


def _key_changes(base: Rule, head: Rule) -> List[str]:
    return sorted(
        str(key) for key, value in head.meta.items()
        if key not in _KNOWN_KEYS and not str(key).startswith("_") and base.meta.get(key, _MISSING) != value
    )


_MISSING = object()


def weakenings(base: Rule, head: Optional[Rule], tree: Optional[_Tree] = None) -> List[Weakening]:
    """Every way the ``head`` version of the rank 2+ rule ``base`` binds less (empty: it does not)."""
    if head is None or not head.ok:
        why = "the rule is gone from the branch" if head is None else f"the rule no longer loads: {head.error}"
        return [Weakening("deleted", base.id, base.path, f"{why} (a deletion or an archive, with no same-id rule in its place)")]
    found: List[Weakening] = []

    def add(code: str, message: str) -> None:
        found.append(Weakening(code, base.id, head.path, message))

    if _level(head)[0] < _level(base)[0] or _level(head)[1] < _level(base)[1]:
        add("rank", f"binds less: rank {base.rank} ({base.enforcement}) became rank {head.rank} ({head.enforcement})")
    for key in _key_changes(base, head):
        add("unknown_key", f"new or changed key {key!r} is not one Aegis knows, so it is treated as a weakening")
    for message in _forbid_findings(base, head):
        add("forbid_ast", message)
    if ("detect" in base.meta or "detect" in head.meta) and not _is_superset(base.meta.get("detect"), head.meta.get("detect")):
        add("detect", "detect is not an exact superset of the reviewed version")
    for path in _coverage_lost(base, head, tree or _Tree(None, None)):
        add("coverage", f"no longer applies to {path}, which the reviewed version covered")
    if base.meta.get("applies_to") != head.meta.get("applies_to"):
        add("applies_to", "applies_to changed")
    return found


def _stricter(base: Rule, head: Rule, tree: _Tree) -> bool:
    """Whether ``head`` differs from ``base`` only by being at least as strict in what is
    enforced (and in something enforced at all)."""
    if weakenings(base, head, tree):
        return False
    return any(base.meta.get(k) != head.meta.get(k) for k in ("target_paths", "forbid_ast", "enforcement")) \
        or base.type != head.type


# ── Serving: the effective rule set ──────────────────────────────────────────

@dataclass(frozen=True)
class Unreviewed:
    """A rule that differs on this branch from the reviewed base. Never mandatory, never gating."""

    id: str
    title: str
    change: str  # "new" | "changed" | "removed" | "broken"
    path: str = ""

    def as_dict(self) -> Dict[str, str]:
        return {"id": self.id, "title": self.title, "change": self.change}


@dataclass(frozen=True)
class Effective:
    """The rules that bind, the anchor they came from (None when nothing is anchored), and what
    this branch changed that nobody has reviewed."""

    ruleset: RuleSet
    anchor: Optional[BaseAnchor]
    unreviewed: Tuple[Unreviewed, ...] = ()


def _compose(root: str, head: RuleSet, base: RuleSet, anchor: BaseAnchor) -> Effective:
    base_all = {r.id: r for r in base.rules if r.ok}
    binding = {rule_id: r for rule_id, r in base_all.items() if r.rank >= 2}
    tree = _Tree(root, anchor.commit)
    served: List[Rule] = []
    unreviewed: List[Unreviewed] = []
    seen_ok = set()
    seen_any = set()
    for rule in head.rules:
        seen_any.add(rule.id)
        if not rule.ok:
            served.append(rule)  # a rule that cannot load stays an error: the scan fails closed on it
            continue
        seen_ok.add(rule.id)
        reviewed = binding.get(rule.id)
        if reviewed is None:
            if rule.rank < 2:
                served.append(rule)  # advisory rules are served as they are
            elif rule.id in base_all:
                served.append(base_all[rule.id])  # raised to mandatory on this branch: the base says advisory
                unreviewed.append(Unreviewed(rule.id, title_of(rule), "changed", rule.path))
            else:
                unreviewed.append(Unreviewed(rule.id, title_of(rule), "new", rule.path))
            continue
        if policy_view(reviewed) == policy_view(rule):
            served.append(rule)
        elif _stricter(reviewed, rule, tree):
            merged = replace(reviewed, type=rule.type, path=rule.path, meta={
                **reviewed.meta, **{k: rule.meta[k] for k in ("target_paths", "forbid_ast", "enforcement") if k in rule.meta}})
            served.append(merged)
            unreviewed.append(Unreviewed(rule.id, title_of(rule), "changed", rule.path))
        else:
            served.append(reviewed)
            unreviewed.append(Unreviewed(rule.id, title_of(rule), "changed", rule.path))
    for rule_id, reviewed in binding.items():
        if rule_id in seen_ok:
            continue
        served.append(reviewed)
        unreviewed.append(Unreviewed(rule_id, title_of(reviewed), "broken" if rule_id in seen_any else "removed", reviewed.path))
    ruleset = RuleSet(tuple(served), head.ignored, f"{head.fingerprint}@{anchor.commit}")
    return Effective(ruleset, anchor, tuple(unreviewed))


def effective(workspace: Any, cache: Optional[RuleCache] = None) -> Effective:
    """The rules of ``workspace`` as they bind: rank 2+ rules from the BASE commit.

    ``cache`` (the scan's) supplies the parsed working tree. Raises IntegrityError when the
    base is anchored but its rules cannot be read soundly, and RuleInventoryError when the
    working tree's rules cannot.
    """
    root = workspace_root(workspace)
    if cache is not None:
        inventory, head = cache.snapshot(root)
    else:
        inventory = inventory_rules(root)
        head = load_rules(root, inventory=inventory)
    anchor = resolve_base(root)
    if anchor is None:
        return Effective(head, None)
    base_inventory = _inventory_at(root, anchor.commit, inventory)
    if base_inventory.fingerprint == inventory.fingerprint:
        return Effective(head, anchor)
    return _compose(root, head, load_rules(root, inventory=base_inventory), anchor)


def effective_ruleset(workspace: Any, cache: Optional[RuleCache] = None) -> RuleSet:
    """``effective(...).ruleset``: what enforcement (aegis check) and serving apply."""
    return effective(workspace, cache).ruleset


# ── The CI weakening check ───────────────────────────────────────────────────

@dataclass(frozen=True)
class CiReport:
    base: str
    head: str
    merge_base: str
    rules_checked: int
    weakenings: Tuple[Weakening, ...]
    approval: Optional[Any]  # human_gate.Approval

    @property
    def passed(self) -> bool:
        return not self.weakenings or (self.approval is not None and self.approval.valid)

    def as_dict(self, workspace: Any = None) -> Dict[str, Any]:
        from datetime import datetime, timezone

        from aegis_core._version import __version__

        scope = {"machine": "local", "workspace": None if workspace is None else str(workspace), "mode": "ci",
                 "base": self.base, "head": self.head, "merge_base": self.merge_base}
        # The envelope every machine-readable output carries (the same head as aegis_core.baseline.envelope,
        # built here because this layer-1 module cannot import the layer-2 baseline).
        document: Dict[str, Any] = {"source": SOURCE, "aegis_version": __version__,
                                    "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "scope": scope}
        document.update(
            schema=SCHEMA,
            status="pass" if self.passed else "fail",
            rules_checked=self.rules_checked,
            weakenings=[w.as_dict() for w in self.weakenings],
            approval=None if self.approval is None else self.approval.as_dict(workspace),
        )
        return document


def _diff(root: str, base: str, head: str) -> Tuple[Dict[str, str], List[str]]:
    """(renames {old: new}, deleted paths) of ``base..head`` from ``diff-tree -r -M50%``."""
    out = _run(root, ["diff-tree", "-r", "-z", "--raw", "--no-commit-id", "-M50%", base, head])
    fields = out.split(b"\0")
    renames: Dict[str, str] = {}
    deleted: List[str] = []
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index].split()[-1].decode("ascii", "replace")[:1]
        if status in ("R", "C"):
            old, new = os.fsdecode(fields[index + 1]), os.fsdecode(fields[index + 2])
            if status == "R":
                renames[old] = new
            index += 3
        else:
            if status == "D":
                deleted.append(os.fsdecode(fields[index + 1]))
            index += 2
    return renames, deleted


def _cap_findings(head: RuleSet, base: RuleSet, files: Callable[[], List[str]]) -> List[Weakening]:
    already = {r.id for r in base.served if r.mandatory}
    mandatory = [r for r in head.served if r.mandatory]
    found: List[Weakening] = []
    for rule in sorted(mandatory, key=lambda r: r.id):
        if rule.id in already:
            continue
        for path in rule.matching_files(files()):
            # The reviewed mandatory rules already there, then the added ones that sort before this one:
            # of several added together, the first fill what room is left and the rest are over the cap.
            crowd = [o for o in mandatory if o.id != rule.id and o.applies_to(path) and (o.id in already or o.id < rule.id)]
            if len(crowd) + 1 > MANDATORY_SLOT_CAP:
                found.append(Weakening(
                    "mandatory_cap", rule.id, rule.path,
                    f"a mandatory rule added where {len(crowd)} already apply (to {path}); a scan gives mandatory rules "
                    f"at most {MANDATORY_SLOT_CAP} slots, so this one crowds out the others"))
                break
    return found


def check_ci(workspace: Any, base: str, head: str = "HEAD") -> CiReport:
    """The rank 2+ rule weakenings (and over-cap mandatory rules) in ``merge-base(base, head)..head``,
    and the approval, if any, that covers them. Raises IntegrityError when the range cannot be read."""
    from aegis_core import human_gate

    root = workspace_root(workspace)
    base_commit = gitsafe.resolve_commit(root, base)
    head_commit = gitsafe.resolve_commit(root, head)
    if not base_commit:
        raise IntegrityError(f"cannot resolve the base {base!r} to a commit (fetch it, or with a shallow clone fetch the full history)")
    if not head_commit:
        raise IntegrityError(f"cannot resolve the head {head!r} to a commit")
    merge = gitsafe.merge_base(root, base_commit, head_commit)
    if not merge:
        raise IntegrityError(f"{base!r} and {head!r} share no history (a shallow clone needs fetch-depth: 0)")
    base_rules = load_rules(root, inventory=_inventory_at(root, merge))
    head_rules = load_rules(root, inventory=_inventory_at(root, head_commit))
    renames, deleted = _diff(root, merge, head_commit)
    tree = _Tree(root, merge, renames, deleted)

    found: List[Weakening] = []
    checked = 0
    for rule in base_rules.rules:
        if rule.ok and rule.rank >= 2:
            checked += 1
            found += weakenings(rule, head_rules.get(rule.id), tree)
    reported = {(w.rule, w.code) for w in found}
    for rule in head_rules.rules:  # applies_to is watched on a rule of any rank, in the base or the head
        reviewed = base_rules.get(rule.id)
        if rule.ok and (rule.id, "applies_to") not in reported and \
                (reviewed.meta.get("applies_to") if reviewed else None) != rule.meta.get("applies_to"):
            found.append(Weakening("applies_to", rule.id, rule.path, "applies_to changed"))
    head_files: List[str] = []

    def files() -> List[str]:
        if not head_files:
            head_files.extend(_tree_files(root, head_commit))
        return head_files

    found += _cap_findings(head_rules, base_rules, files)
    approval = None
    if found:
        try:
            approval = human_gate.find_approval(root, head_commit, base_commit)
        except (human_gate.HumanGateError, gitsafe.GitError):
            approval = None
    return CiReport(base_commit, head_commit, merge, checked, tuple(found), approval)
