"""``human_gate``: the trust tier and the approvals an agent cannot produce (v4.3 spec §2.2).

Local evidence is a label: a same-uid agent can edit anything Aegis writes. What it cannot do
is act as GitHub's enforcement or sign with a key it cannot use, so the tier says which of
those a repository really has:

- **A, separation of duties**: the default branch requires a pull request, an approving review,
  code-owner review and status checks; CODEOWNERS covers the governance set
  (``aegis_core.governance``); and the identity that asked is not an admin who could edit the
  ruleset.
- **B, solo, signed**: required status checks on the default branch, plus ``allowed_signers`` on
  that branch and a signing key whose custody is not a plain, readable file. An approval is a
  signed empty commit ``Aegis-Approve: <governance tree hash>`` (``aegis approve``), checked
  against the BASE branch's ``allowed_signers``, so a key added on the pull request's own branch
  proves nothing.
- **C, self-attested**: neither; detection and audit only, and every report says so.

``detect_tier`` only reads: ``gh api`` GETs through an injectable runner (the user's own ``gh``;
no ``gh`` means tier C), plain git plumbing, and the user-scope git config. Nothing here writes
a key or a repository setting; ``create_ruleset`` is the one gh write and its caller asks a
person first. The signing key, the signing program and the allowed-signers file are always
taken from the user-scope config and passed with ``-c``, which beats the repository's own
config: a clone cannot name the program git runs to sign or to verify.

An approval verifies one commit: a good ``G`` signature of a key in the BASE ``allowed_signers``
(``git log --format=%G?``), exactly one ``Aegis-Approve`` trailer equal to the governance tree
hash of the state being approved, and no ``Aegis-Accept:`` line anywhere in the message (that
trailer is reserved for a later release, v4.4 requirement 5, and the verifier refuses it so no
approval can be minted that carries it). The hash covers the governance files at a revision
(path, mode and object id), so any later governance change voids an earlier approval.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import quote

from aegis_core import gitsafe, governance, pathlookup
from aegis_core._version import __version__
from aegis_core.errors import AegisError
from aegis_core.storage import atomic_write_bytes
from aegis_core.workspace.layout import AEGIS_DIRNAME, RULES_RELDIR

__all__ = [
    "ALLOWED_SIGNERS",
    "Approval",
    "COVERAGE_SAMPLES",
    "GhResult",
    "HumanGateError",
    "KeyCustody",
    "RULESET_NAME",
    "SCHEMA",
    "SOURCE",
    "TierReport",
    "approval_message",
    "build_ruleset",
    "check_key_custody",
    "codeowners_coverage",
    "codeowners_lines",
    "create_ruleset",
    "default_gh_runner",
    "detect_tier",
    "find_approval",
    "governance_tree_hash",
    "ruleset_exists",
    "signed_empty_commit",
    "signers_setup",
    "signing_config",
    "verify_approval",
    "workflow_contexts",
]

SCHEMA = "aegis.human_gate/v1"
SOURCE = "aegis human_gate"
#: Where the keys allowed to approve are listed, at the top of the BASE branch.
ALLOWED_SIGNERS = "allowed_signers"
RULESET_NAME = "aegis-human-gate"
GH_TIMEOUT_SECONDS = 10.0
SIGN_TIMEOUT_SECONDS = 300.0
HASH_DOMAIN = b"aegis-governance-tree/v1\n"
MAX_SCANNED_COMMITS = 500

_LABELS = {"A": "separation of duties", "B": "solo, signed", "C": "self-attested"}
_STATEMENTS = {
    "A": "governance changes need a review by someone other than their author",
    "B": "governance changes need a signature from a key listed in allowed_signers on the base branch",
    "C": "detection and audit only: nothing here is enforced against the agent",
}
#: Paths CODEOWNERS must cover for tier A: one per governance pattern (aegis_core.governance).
COVERAGE_SAMPLES: Tuple[str, ...] = (
    f"{RULES_RELDIR}/trap/sample.md", f"{AEGIS_DIRNAME}/config.json", f"{AEGIS_DIRNAME}/team.json",
    f"{AEGIS_DIRNAME}/baseline.json", "allowed_signers", ".github/workflows/ci.yml", "conftest.py", "pytest.ini",
    ".pytest.ini", "pytest.toml", ".pytest.toml", "tox.ini", "setup.cfg", "pyproject.toml", "sitecustomize.py",
    "evil.pth", "Makefile",
)
_CODEOWNERS_LOCATIONS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


class HumanGateError(AegisError):
    """git or the signing program cannot answer, or an input cannot be trusted."""


class GhResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


#: ``runner(argv, stdin=None, cwd=None)``: run ``gh <argv>``; None when gh is not installed.
GhRunner = Callable[..., Optional[GhResult]]


def default_gh_runner(argv: Sequence[str], stdin: Optional[bytes] = None, cwd: Any = None) -> Optional[GhResult]:
    """Run the user's ``gh`` (an absolute PATH entry outside ``cwd``), never prompting. None when
    there is none. ``{owner}``, ``{repo}`` and ``{branch}`` in an ``api`` endpoint are filled by
    gh from the repository in ``cwd``."""
    exe = pathlookup.which("gh", outside=cwd)
    if exe is None:
        return None
    env = dict(os.environ)
    env.update({"GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1"})
    try:
        proc = subprocess.run([exe, *argv], input=stdin, capture_output=True, env=env,
                              cwd=None if cwd is None else str(cwd), timeout=GH_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        return GhResult(124, "", f"gh timed out after {GH_TIMEOUT_SECONDS:g}s")
    except OSError as exc:
        return GhResult(126, "", f"cannot run gh: {exc}")
    return GhResult(proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── CODEOWNERS ───────────────────────────────────────────────────────────────

_OWNER = re.compile(r"\A(?:@[A-Za-z0-9][A-Za-z0-9-]*(?:/[A-Za-z0-9._-]+)?|[^@\s]+@[^@\s]+\.[^@\s]+)\Z")
_MAX_CODEOWNERS_LINES = 5000
_MAX_PATTERN = 300


def _parse_codeowners(text: str) -> List[Tuple[str, Tuple[str, ...]]]:
    entries: List[Tuple[str, Tuple[str, ...]]] = []
    for line in text.splitlines()[:_MAX_CODEOWNERS_LINES]:
        tokens = line.strip().split()
        if not tokens or tokens[0].startswith("#"):
            continue
        owners: List[str] = []
        for token in tokens[1:]:
            if token.startswith("#"):
                break
            if _OWNER.match(token):
                owners.append(token)
        entries.append((tokens[0], tuple(owners)))
    return entries


def _segment_match(pattern: str, text: str) -> bool:
    """``*`` and ``?`` inside one path segment, matched without backtracking blowup."""
    p = t = 0
    star = -1
    mark = 0
    while t < len(text):
        if p < len(pattern) and (pattern[p] == "?" or pattern[p] == text[t]) and pattern[p] != "*":
            p += 1
            t += 1
        elif p < len(pattern) and pattern[p] == "*":
            star, mark = p, t
            p += 1
        elif star >= 0:
            p = star + 1
            mark += 1
            t = mark
        else:
            return False
    while p < len(pattern) and pattern[p] == "*":
        p += 1
    return p == len(pattern)


def _prefix_ends(segments: List[str], parts: List[str], start: int) -> List[int]:
    """Every index ``segments`` can end at, matched against ``parts`` from ``start``."""
    ends = {start} if not segments else set()
    reach = {(0, start)}
    seen = set()
    while reach:
        si, pi = reach.pop()
        if (si, pi) in seen:
            continue
        seen.add((si, pi))
        if si == len(segments):
            ends.add(pi)
            continue
        seg = segments[si]
        if seg == "**":
            for end in range(pi, len(parts) + 1):
                reach.add((si + 1, end))
        elif pi < len(parts) and _segment_match(seg.replace("**", "*"), parts[pi]):
            reach.add((si + 1, pi + 1))
    return sorted(ends)


def _codeowners_match(pattern: str, path: str) -> bool:
    if not pattern or len(pattern) > _MAX_PATTERN or pattern[0] == "!" or any(c in pattern for c in "[]\\"):
        return False
    directory = pattern.endswith("/")
    core = pattern.strip("/")
    if not core:
        return False
    anchored = pattern.startswith("/") or "/" in core
    segments = core.split("/")
    parts = path.split("/")
    starts = [0] if anchored else range(len(parts))
    for start in starts:
        for end in _prefix_ends(segments, parts, start):
            if end == len(parts):
                if not directory:  # the path itself matched; "dir/" names directories only
                    return True
            elif end > start and directory:  # "dir/" owns what is inside it; "dir/*" does not reach below
                return True
    return False


def codeowners_coverage(text: str, location: str = "CODEOWNERS") -> Tuple[List[str], List[str]]:
    """(covered, uncovered) representative governance paths under CODEOWNERS ``text``.

    ``location`` is where the CODEOWNERS file itself lives (it is in the governance set). The
    last matching entry wins, as on GitHub, and an entry with no valid owner leaves its files
    unprotected. A pattern GitHub would not read (a ``[range]``, an escape, a negation) matches
    nothing here, so an unreadable entry never counts as protection.
    """
    entries = _parse_codeowners(text)
    covered: List[str] = []
    uncovered: List[str] = []
    for path in (*COVERAGE_SAMPLES, location):
        owners: Tuple[str, ...] = ()
        for pattern, found in entries:
            if _codeowners_match(pattern, path):
                owners = found
        (covered if owners else uncovered).append(path)
    return covered, uncovered


def codeowners_lines(owner: str = "@OWNER") -> List[str]:
    """The CODEOWNERS entries that cover the governance set, owned by ``owner``."""
    paths = [
        f"/{RULES_RELDIR}/", f"/{AEGIS_DIRNAME}/config.json", f"/{AEGIS_DIRNAME}/team.json",
        f"/{AEGIS_DIRNAME}/baseline.json", "/allowed_signers", "/CODEOWNERS", "/.github/CODEOWNERS",
        "/.github/workflows/", "conftest.py", "pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml", "tox.ini",
        "setup.cfg", "pyproject.toml", "sitecustomize.py", "*.pth", "Makefile",
    ]
    return [f"{path} {owner}" for path in paths]


# ── signing-key custody ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class KeyCustody:
    """How the user's signing key is held. ``degrades``: tier B cannot rest on it."""

    status: str  # hardware | passphrase | agent | plain_file | unknown | unsupported | none
    detail: str
    degrades: bool
    key: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "detail": self.detail, "degrades": self.degrades, "key": self.key}


def _user_config(root: Path, key: str) -> Optional[str]:
    """``key`` from the user's or the system's git config; never the repository's."""
    for scope in ("--global", "--system"):
        try:
            res = gitsafe.run(["config", scope, "--get", key], root)
        except gitsafe.GitError:
            return None
        if res.returncode == 0:
            value = os.fsdecode(res.stdout).strip()
            if value:
                return value
    return None


def signing_config(root: Any) -> Dict[str, Optional[str]]:
    """The user-scope signing settings: ``format`` (git's default openpgp when unset) and ``key``."""
    root = Path(root)
    return {"format": (_user_config(root, "gpg.format") or "openpgp").lower(), "key": _user_config(root, "user.signingkey")}


def _literal_key(value: str) -> Optional[str]:
    if value.startswith("key::"):
        return value[len("key::"):]
    if value.startswith(("ssh-", "sk-", "ecdsa-")):
        return value
    return None


def _wire_string(blob: bytes, offset: int) -> Tuple[bytes, int]:
    (size,) = struct.unpack_from(">I", blob, offset)
    start = offset + 4
    if size > len(blob) - start:
        raise ValueError("truncated")
    return blob[start:start + size], start + size


def _private_key_protection(path: Path) -> str:
    """plain | encrypted | hardware | unknown | unreadable, from the private key file's header."""
    try:
        with open(path, "rb") as handle:
            data = handle.read(65536)
    except OSError:
        return "unreadable"
    if b"-----BEGIN OPENSSH PRIVATE KEY-----" in data:
        body = data.split(b"-----BEGIN OPENSSH PRIVATE KEY-----", 1)[1].split(b"-----END", 1)[0]
        try:
            blob = base64.b64decode(b"".join(body.split()))
            if not blob.startswith(b"openssh-key-v1\x00"):
                return "unknown"
            cipher, at = _wire_string(blob, len(b"openssh-key-v1\x00"))
            _kdf, at = _wire_string(blob, at)
            _opts, at = _wire_string(blob, at)
            at += 4  # number of keys
            public, _ = _wire_string(blob, at)
            key_type, _ = _wire_string(public, 0)
        except (ValueError, struct.error):
            return "unknown"
        if key_type.startswith(b"sk-"):
            return "hardware"
        return "plain" if cipher == b"none" else "encrypted"
    if b"-----BEGIN ENCRYPTED PRIVATE KEY-----" in data or b"Proc-Type: 4,ENCRYPTED" in data:
        return "encrypted"
    if b"PRIVATE KEY-----" in data:
        return "plain"
    return "unknown"


def check_key_custody(root: Any) -> KeyCustody:
    """Classify the user's signing key (v4.3 §2.2 "Key custody check").

    A private key that is a readable file with no passphrase is ``plain_file``: the agent runs as
    the same user and signs with it, so a signature proves nothing and tier B degrades to C. A
    security-key type (``sk-``) is ``hardware`` (touch required) and an encrypted private key is
    ``passphrase``. A public key whose private half is not a file here is held by an agent
    (``agent``): its confirmation policy is not visible from here, so it is reported as
    unverified, not as a failure. Only SSH signing can be verified against ``allowed_signers``.
    """
    root = Path(root)
    config = signing_config(root)
    value = config["key"]
    if not value:
        return KeyCustody("none", "no user.signingkey in the user-level git config", True)
    if config["format"] != "ssh":
        return KeyCustody("unsupported", f"gpg.format is {config['format']!r}: approvals are SSH signatures "
                          "checked against allowed_signers (git config --global gpg.format ssh)", True)
    literal = _literal_key(value)
    if literal is not None:
        kind = literal.split()[0] if literal.split() else ""
        if kind.startswith("sk-"):
            return KeyCustody("hardware", "a security key (touch required)", False, kind)
        return KeyCustody("agent", "the private key is held by an ssh-agent; whether it asks before signing is "
                          "unverified from here", False, kind)
    path = Path(os.path.expanduser(value))
    is_public = path.name.endswith(".pub")
    public = path if is_public else Path(str(path) + ".pub")
    private = Path(str(path)[:-len(".pub")]) if is_public else path
    try:
        pub_text = public.read_text(encoding="utf-8", errors="replace") if public.is_file() else ""
    except OSError:
        pub_text = ""
    name = private.name
    if pub_text.strip().startswith("sk-"):
        return KeyCustody("hardware", "a security key (touch required)", False, name)
    if not private.is_file():
        if is_public:
            return KeyCustody("agent", "only the public key is on disk; the private key is held by an ssh-agent "
                              "and whether it asks before signing is unverified from here", False, name)
        return KeyCustody("unknown", f"the signing key file {name} was not found", False, name)
    protection = _private_key_protection(private)
    if protection == "hardware":
        return KeyCustody("hardware", "a security key handle (touch required)", False, name)
    if protection == "encrypted":
        return KeyCustody("passphrase", "the private key is passphrase-protected", False, name)
    if protection == "plain":
        return KeyCustody("plain_file", f"the signing key {name} is a plain file with no passphrase, readable by this "
                          "user: an agent running as you can sign with it, so a signature proves nothing", True, name)
    return KeyCustody("unknown", f"the signing key file {name} could not be classified", False, name)


# ── tier detection ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TierReport:
    """The detected tier and the evidence it rests on."""

    tier: str
    reasons: Tuple[str, ...] = ()
    caveats: Tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)
    scope: Mapping[str, Any] = field(default_factory=dict)
    checked_at: str = field(default_factory=_utc_now)

    @property
    def label(self) -> str:
        return _LABELS[self.tier]

    @property
    def statement(self) -> str:
        return _STATEMENTS[self.tier]

    def text_lines(self) -> List[str]:
        lines = [f"Trust tier (human_gate): {self.tier} ({self.label}): {self.statement}"]
        lines += [f"  - {reason}" for reason in self.reasons]
        lines += [f"  ! {caveat}" for caveat in self.caveats]
        return lines

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA,
            "source": SOURCE,
            "aegis_version": __version__,
            "checked_at": self.checked_at,
            "scope": dict(self.scope),
            "tier": self.tier,
            "label": self.label,
            "statement": self.statement,
            "reasons": list(self.reasons),
            "caveats": list(self.caveats),
            "evidence": json.loads(json.dumps(self.evidence)),
        }


def _gh_json(runner: GhRunner, endpoint: str, cwd: Path) -> Tuple[Any, Optional[str]]:
    """(parsed JSON, None) or (None, why not) for one ``gh api`` GET."""
    result = runner(["api", "--method", "GET", endpoint], None, cwd)
    if result is None:
        return None, "gh is not installed"
    if result.returncode != 0:
        detail = " ".join((result.stderr or result.stdout).split())[:200]
        return None, f"gh api {endpoint} failed: {detail or 'exit ' + str(result.returncode)}"
    try:
        return json.loads(result.stdout), None
    except ValueError:
        return None, f"gh api {endpoint} did not return JSON"


def _signer_keys(text: Optional[bytes]) -> int:
    if not text:
        return 0
    count = 0
    for line in text.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and re.search(r"\b(?:ssh-|ecdsa-|sk-)[A-Za-z0-9@.-]* [A-Za-z0-9+/=]{20,}", line):
            count += 1
    return count


def _ruleset_facts(rules: Any) -> Dict[str, Any]:
    approvals, owners, contexts, has_pr = 0, False, [], False
    for rule in rules if isinstance(rules, list) else []:
        if not isinstance(rule, dict):
            continue
        params = rule.get("parameters") if isinstance(rule.get("parameters"), dict) else {}
        if rule.get("type") == "pull_request":
            has_pr = True
            count = params.get("required_approving_review_count")
            approvals = max(approvals, count if isinstance(count, int) and not isinstance(count, bool) else 0)
            owners = owners or params.get("require_code_owner_review") is True
        elif rule.get("type") == "required_status_checks":
            for check in params.get("required_status_checks") or []:
                if isinstance(check, dict) and isinstance(check.get("context"), str) and check["context"] not in contexts:
                    contexts.append(check["context"])
    return {"pull_request": has_pr, "required_approving_review_count": approvals,
            "require_code_owner_review": owners, "required_status_checks": contexts}


def detect_tier(root: Any, gh: Optional[GhRunner] = None, environ: Optional[Mapping[str, str]] = None) -> TierReport:
    """Read-only tier detection for the repository holding ``root`` (v4.3 spec §2.2).

    ``gh`` is the runner (default ``default_gh_runner``); without a usable gh the answer is C
    with the reason. Never raises for a missing tool, a failing API call or an unreadable file:
    each is a reason the tier is not higher.
    """
    root = Path(root)
    runner: GhRunner = gh if gh is not None else default_gh_runner
    top = gitsafe.toplevel(root)
    evidence: Dict[str, Any] = {"gh": {"available": None, "error": None}, "repo": None, "rules": None,
                                "codeowners": None, "allowed_signers": None, "key_custody": None, "identity": None}
    scope: Dict[str, Any] = {"machine": "local", "workspace": str(top or root), "repository": None, "base": None}
    if top is None:
        return TierReport("C", ("not inside a git repository: nothing to detect",), (), evidence, scope)

    reasons: List[str] = []
    caveats: List[str] = []
    repo_info, why = _gh_json(runner, "repos/{owner}/{repo}", top)
    facts: Optional[Dict[str, Any]] = None
    default_branch: Optional[str] = None
    admin: Optional[bool] = None
    if why is not None or not isinstance(repo_info, dict):
        why = why or "gh api repos/{owner}/{repo} did not return an object"
        evidence["gh"] = {"available": why != "gh is not installed", "error": why}
        reasons.append(f"GitHub settings could not be read: {why}")
    else:
        evidence["gh"] = {"available": True, "error": None}
        default_branch = repo_info.get("default_branch") if isinstance(repo_info.get("default_branch"), str) else None
        perms = repo_info.get("permissions") if isinstance(repo_info.get("permissions"), dict) else {}
        admin = perms.get("admin") if isinstance(perms.get("admin"), bool) else None
        full = repo_info.get("full_name") if isinstance(repo_info.get("full_name"), str) else None
        scope["repository"] = full
        evidence["repo"] = {"full_name": full, "default_branch": default_branch}
        evidence["identity"] = {"admin": admin}
        if default_branch:
            rules, why = _gh_json(runner, "repos/{owner}/{repo}/rules/branches/" + quote(default_branch, safe=""), top)
            if why is None:
                facts = _ruleset_facts(rules)
                evidence["rules"] = facts
            else:
                reasons.append(f"the default branch's rules could not be read: {why}")
        else:
            reasons.append("the repository's default branch is unknown")

    base = None
    for candidate in ([f"origin/{default_branch}", default_branch] if default_branch else []):
        if gitsafe.resolve_commit(top, candidate):
            base = candidate
            break
    if base is None:
        base = gitsafe.resolve_base_ref(top)
    scope["base"] = base

    codeowners: Dict[str, Any] = {"present": False, "path": None, "covered": [], "uncovered": list(COVERAGE_SAMPLES)}
    signers: Dict[str, Any] = {"present": False, "keys": 0}
    if base is not None:
        for location in _CODEOWNERS_LOCATIONS:
            blob = _blob(top, base, location)
            if blob is not None:
                covered, uncovered = codeowners_coverage(blob.decode("utf-8", "replace"), location)
                codeowners = {"present": True, "path": location, "covered": covered, "uncovered": uncovered}
                break
        blob = _blob(top, base, ALLOWED_SIGNERS)
        signers = {"present": blob is not None, "keys": _signer_keys(blob)}
    evidence["codeowners"] = codeowners
    evidence["allowed_signers"] = signers
    custody = check_key_custody(top)
    evidence["key_custody"] = custody.as_dict()

    checks = facts["required_status_checks"] if facts else []
    a_missing: List[str] = []
    if facts is None:
        a_missing.append("the default branch's ruleset was not read")
    else:
        if facts["required_approving_review_count"] < 1:
            a_missing.append("the default branch does not require an approving review")
        if not facts["require_code_owner_review"]:
            a_missing.append("the default branch does not require code-owner review")
        if not checks:
            a_missing.append("the default branch has no required status checks")
    if not codeowners["present"]:
        a_missing.append("no CODEOWNERS file on the base branch")
    elif codeowners["uncovered"]:
        a_missing.append(f"CODEOWNERS leaves {len(codeowners['uncovered'])} governance path(s) without an owner")
    if admin is True:
        a_missing.append("the gh identity doctor used is a repository admin, who can edit the ruleset "
                         "(an agent needs its own non-admin identity)")
    elif admin is None:
        a_missing.append("whether the gh identity is an admin is unknown")

    b_missing: List[str] = []
    if facts is None:
        b_missing.append("the default branch's ruleset was not read")
    elif not checks:
        b_missing.append("the default branch has no required status checks")
    if signers["keys"] < 1:
        b_missing.append(f"{ALLOWED_SIGNERS} on the base branch lists no signing key")
    if custody.degrades:
        b_missing.append(custody.detail if custody.status == "plain_file" else f"signing key: {custody.detail}")

    if not a_missing:
        tier, why_not = "A", []
    elif not b_missing:
        tier, why_not = "B", a_missing
    else:
        tier, why_not = "C", reasons + b_missing + [f"not tier A: {m}" for m in a_missing if m not in b_missing]
    if tier == "B":
        why_not = [f"not tier A: {m}" for m in why_not]
    if tier != "C":
        if admin is True:
            caveats.append("the gh identity doctor used is a repository admin: an agent holding that token can edit "
                           "the ruleset, so this tier holds only while that token is withheld from the agent")
        if custody.status in ("agent", "unknown"):
            caveats.append(custody.detail)
        caveats.append("a ruleset can name bypass actors, which this endpoint does not show; classic branch "
                       "protection is not read at all")
        if facts is not None and facts["required_status_checks"]:
            caveats.append("which required checks run Aegis, and that they have no path filter, is not visible from here")
    return TierReport(tier, tuple(why_not), tuple(caveats), evidence, scope)


def _blob(top: Path, rev: str, path: str) -> Optional[bytes]:
    try:
        return gitsafe.read_blob(top, rev, path)
    except gitsafe.GitError:
        return None


# ── the governance tree hash and approvals ───────────────────────────────────

def _top(root: Any) -> Path:
    top = gitsafe.toplevel(Path(root))
    if top is None:
        raise HumanGateError(f"{root} is not inside a git work tree")
    return top


def governance_tree_hash(root: Any, rev: str = "HEAD") -> str:
    """sha256 over the governance files of ``rev`` (mode, object id and path of each, sorted).

    Any change to a governance file, an addition or a removal moves it, so an approval of one
    hash covers exactly one governance state. Raises HumanGateError when ``rev`` does not resolve.
    """
    top = _top(root)
    commit = gitsafe.resolve_commit(top, rev)
    if not commit:
        raise HumanGateError(f"cannot resolve {rev!r} to a commit in {top}")
    try:
        res = gitsafe.run(["ls-tree", "-r", "-z", "--full-tree", commit], top, timeout=60.0)
    except gitsafe.GitError as exc:
        raise HumanGateError(str(exc)) from exc
    if res.returncode != 0:
        raise HumanGateError(f"git ls-tree failed for {rev}")
    records: List[Tuple[bytes, bytes]] = []
    for entry in res.stdout.split(b"\0"):
        meta, _, raw_path = entry.partition(b"\t")
        fields = meta.split()
        if len(fields) != 3 or not raw_path:
            continue
        if governance.category_of(os.fsdecode(raw_path)):
            records.append((raw_path, fields[0] + b" " + fields[2]))
    digest = hashlib.sha256(HASH_DOMAIN)
    for raw_path, meta in sorted(records):
        digest.update(meta + b" " + raw_path + b"\n")
    return digest.hexdigest()


class Approval(NamedTuple):
    """The verdict on one commit: ``valid``, a stable ``code`` and a ``reason`` for people."""

    valid: bool
    code: str
    reason: str
    commit: str
    signer: Optional[str] = None

    def as_dict(self, workspace: Any = None) -> Dict[str, Any]:
        return {"schema": SCHEMA, "source": SOURCE, "aegis_version": __version__, "checked_at": _utc_now(),
                "scope": {"machine": "local", "workspace": None if workspace is None else str(workspace),
                          "commit": self.commit},
                "valid": self.valid, "code": self.code, "reason": self.reason, "signer": self.signer}


_ACCEPT_LINE = re.compile(r"^[ \t]*aegis-accept[ \t]*:", re.IGNORECASE | re.MULTILINE)
_APPROVE_LINE = re.compile(r"^[ \t]*aegis-approve[ \t]*:[ \t]*(\S*)[ \t]*$", re.IGNORECASE | re.MULTILINE)


def approval_message(digest: str) -> str:
    return f"chore: approve governance state\n\nAegis-Approve: {digest}\n"


def _ssh_keygen() -> str:
    found = pathlookup.which("ssh-keygen")
    if not found:
        raise HumanGateError("ssh-keygen is not installed or not on PATH; SSH signatures cannot be made or checked")
    return found


def _no(code: str, reason: str, commit: str) -> Approval:
    return Approval(False, code, reason, commit)


def verify_approval(root: Any, commit: str, governance_hash: str, base_ref: str) -> Approval:
    """Whether ``commit`` is a human approval of the governance state ``governance_hash``.

    All of: no ``Aegis-Accept:`` line in the message; exactly one ``Aegis-Approve:`` line whose
    value is ``governance_hash``; and a good signature (``%G?`` is ``G``) by a key listed in
    ``allowed_signers`` as committed at the tip of ``base_ref`` (so a key revoked there stays
    revoked), never the commit's own copy.
    """
    try:
        top = _top(root)
        oid = gitsafe.resolve_commit(top, commit)
        base = gitsafe.resolve_commit(top, base_ref)
        if not oid or not base:
            return _no("unresolved", f"cannot resolve {commit!r} or the base {base_ref!r}", str(commit))
        raw = gitsafe.run(["cat-file", "commit", oid], top)
        if raw.returncode != 0:
            return _no("unresolved", f"cannot read commit {oid}", oid)
        message = raw.stdout.decode("utf-8", "replace").partition("\n\n")[2]
        if _ACCEPT_LINE.search(message):
            return _no("accept_reserved", "the message carries an Aegis-Accept line, which is reserved", oid)
        values = _APPROVE_LINE.findall(message)
        if not values:
            return _no("no_trailer", "no Aegis-Approve trailer", oid)
        if len(values) > 1:
            return _no("multiple_trailers", "more than one Aegis-Approve trailer", oid)
        if values[0].lower() != governance_hash.lower():
            return _no("hash_mismatch", "the approved governance hash is not this governance state", oid)
        signers = gitsafe.read_blob(top, base, ALLOWED_SIGNERS)
        if _signer_keys(signers) < 1:
            return _no("no_allowed_signers", f"{ALLOWED_SIGNERS} on the base branch lists no key", oid)
        status, fingerprint = _signature(top, oid, signers or b"")
    except gitsafe.GitError as exc:
        return _no("unresolved", str(exc), str(commit))
    except HumanGateError as exc:
        return _no("unverifiable", str(exc), str(commit))
    if status == "G":
        return Approval(True, "ok", "good signature by a key in the base allowed_signers", oid, fingerprint)
    if status == "N":
        return _no("unsigned", "the commit is not signed", oid)
    if status == "U":  # a good signature, but by a key (or principal) the base does not list
        return _no("untrusted_signature", "the signing key is not in the base allowed_signers", oid)
    if status == "E":
        return _no("unverifiable", "git could not check the signature", oid)
    return _no("bad_signature", f"the signature does not verify (git reports {status!r})", oid)


def _signature(top: Path, oid: str, signers: bytes) -> Tuple[str, Optional[str]]:
    program = _ssh_keygen()
    directory = Path(tempfile.mkdtemp(prefix="aegis-signers-"))
    try:
        os.chmod(directory, 0o700)
        path = directory / "allowed_signers"
        atomic_write_bytes(path, signers, mode=0o600)
        res = gitsafe.run(
            ["-c", "gpg.format=ssh", "-c", f"gpg.ssh.allowedSignersFile={path}", "-c", f"gpg.ssh.program={program}",
             "log", "-1", "--format=%G?%n%GF", oid], top)
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    if res.returncode != 0:
        raise HumanGateError(f"git log could not check the signature of {oid}")
    lines = res.stdout.decode("utf-8", "replace").splitlines()
    status = lines[0].strip() if lines else "N"
    fingerprint = lines[1].strip() if len(lines) > 1 and lines[1].strip() else None
    return status, fingerprint


def find_approval(root: Any, head: str, base_ref: str, governance_hash: Optional[str] = None) -> Optional[Approval]:
    """The newest valid approval among the commits ``merge-base(base_ref, head)..head``, or None.

    ``governance_hash`` defaults to the governance state at ``head``.
    """
    top = _top(root)
    tip = gitsafe.resolve_commit(top, head)
    base = gitsafe.merge_base(top, base_ref, head)
    if not tip or not base:
        return None
    digest = governance_hash or governance_tree_hash(top, tip)
    res = gitsafe.run(["rev-list", f"--max-count={MAX_SCANNED_COMMITS}", f"{base}..{tip}"], top)
    if res.returncode != 0:
        return None
    for oid in res.stdout.decode("ascii", "replace").split():
        verdict = verify_approval(top, oid, digest, base_ref)
        if verdict.valid:
            return verdict
    return None


def signed_empty_commit(root: Any, message: str) -> str:
    """Make a signed empty commit on HEAD and return its id.

    The key, the format and the signing program come from the user-scope config only and are
    passed with ``-c``, so the repository's config cannot swap the program git runs. Hooks are
    off (gitsafe). The key is used, never created. Raises HumanGateError with git's own words
    when signing fails.
    """
    top = _top(root)
    config = signing_config(top)
    if config["format"] != "ssh" or not config["key"]:
        raise HumanGateError("approvals are SSH signatures: set git config --global gpg.format ssh and "
                             "git config --global user.signingkey <key>")
    key = config["key"] or ""
    if not _literal_key(key):
        key = os.path.expanduser(key)
    res = gitsafe.run(
        ["-c", "gpg.format=ssh", "-c", f"user.signingkey={key}", "-c", f"gpg.ssh.program={_ssh_keygen()}",
         "-c", "commit.gpgsign=true", "commit", "-S", "--allow-empty", "--no-verify", "-m", message],
        top, timeout=SIGN_TIMEOUT_SECONDS)
    if res.returncode != 0:
        detail = " ".join((res.stderr or res.stdout).decode("utf-8", "replace").split())[:300]
        raise HumanGateError(f"git could not make the signed commit: {detail}")
    commit = gitsafe.head_commit(top)
    if not commit:
        raise HumanGateError("the signed commit was made but HEAD cannot be read")
    return commit


# ── the ruleset (doctor --github) ────────────────────────────────────────────

def build_ruleset(tier: str, contexts: Iterable[str]) -> Dict[str, Any]:
    """The repository ruleset body for ``POST /repos/{owner}/{repo}/rulesets``.

    Tier A requires one approving review and code-owner review; tier B requires only the pull
    request and the checks (a solo developer cannot approve their own pull request). Neither has
    a bypass actor.
    """
    if tier not in ("A", "B"):
        raise ValueError(f"tier must be 'A' or 'B', got {tier!r}")
    reviewed = tier == "A"
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "bypass_actors": [],
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "pull_request", "parameters": {
                "required_approving_review_count": 1 if reviewed else 0,
                "dismiss_stale_reviews_on_push": True,
                "require_code_owner_review": reviewed,
                "require_last_push_approval": reviewed,
                "required_review_thread_resolution": False,
            }},
            {"type": "required_status_checks", "parameters": {
                "strict_required_status_checks_policy": False,
                "required_status_checks": [{"context": c} for c in contexts],
            }},
        ],
    }


_JOB_ID = re.compile(r"^  ([A-Za-z0-9_-]+):[ \t]*(?:#.*)?$")
_JOB_NAME = re.compile(r"""^    name:[ \t]*(?:"([^"]*)"|'([^']*)'|([^#\n]*?))[ \t]*(?:#.*)?$""")


def workflow_contexts(root: Any) -> List[str]:
    """The job names (``name:``, else the id) in ``.github/workflows``: the status-check contexts
    a ruleset can require. Read from the files, in file order; [] when there are none."""
    directory = Path(root) / ".github" / "workflows"
    contexts: List[str] = []
    try:
        files = sorted(p for p in directory.iterdir() if p.suffix in (".yml", ".yaml") and p.is_file())
    except OSError:
        return contexts
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:5000]
        except OSError:
            continue
        in_jobs, job, named = False, None, False
        for line in lines + ["x:"]:
            if line.startswith("jobs:"):
                in_jobs = True
                continue
            if in_jobs and line and not line[0].isspace() and not line.startswith("#"):
                in_jobs = False
            if not in_jobs:
                continue
            found = _JOB_ID.match(line)
            if found:
                job, named = found.group(1), False
                contexts.append(job)
                continue
            named_as = _JOB_NAME.match(line)
            if named_as and job and not named:
                value = next((g for g in named_as.groups() if g), "")
                if value and "${{" not in value:
                    contexts[-1] = value
                named = True
    return contexts


def ruleset_exists(root: Any, gh: Optional[GhRunner] = None) -> bool:
    """Whether a ruleset named ``RULESET_NAME`` already exists. Raises HumanGateError when gh
    cannot say."""
    runner: GhRunner = gh if gh is not None else default_gh_runner
    listing, why = _gh_json(runner, "repos/{owner}/{repo}/rulesets", Path(root))
    if why is not None or not isinstance(listing, list):
        raise HumanGateError(why or "gh api rulesets did not return a list")
    return any(isinstance(r, dict) and r.get("name") == RULESET_NAME for r in listing)


def create_ruleset(root: Any, ruleset: Mapping[str, Any], gh: Optional[GhRunner] = None) -> Dict[str, Any]:
    """POST ``ruleset`` through gh. The only write this module makes to GitHub: callers ask a
    person first. Raises HumanGateError when gh is missing or refuses."""
    runner: GhRunner = gh if gh is not None else default_gh_runner
    body = json.dumps(ruleset).encode("utf-8")
    result = runner(["api", "--method", "POST", "repos/{owner}/{repo}/rulesets", "--input", "-"], body, Path(root))
    if result is None:
        raise HumanGateError("gh is not installed")
    if result.returncode != 0:
        raise HumanGateError(f"gh could not create the ruleset: {' '.join(result.stderr.split())[:300]}")
    try:
        created = json.loads(result.stdout)
    except ValueError:
        created = {}
    return created if isinstance(created, dict) else {}


def signers_setup() -> List[str]:
    """How to set up tier B signing (printed by ``doctor --github``; nothing here runs them)."""
    return [
        "# 1. A signing key the agent cannot use: a hardware key (touch required) or a passphrase-protected key.",
        "ssh-keygen -t ed25519-sk -f ~/.ssh/aegis_approval      # or: ssh-keygen -t ed25519 (set a passphrase)",
        "# 2. Tell git to sign with it (user-level config; a repository's config is never used for approvals).",
        "git config --global gpg.format ssh",
        "git config --global user.signingkey ~/.ssh/aegis_approval.pub",
        f"# 3. List the public key in {ALLOWED_SIGNERS} at the top of the default branch, through a reviewed pull request:",
        f'#    you@example.com namespaces="git" <contents of ~/.ssh/aegis_approval.pub>',
        "# 4. When a pull request changes governance files, review it, then run: aegis approve",
    ]
