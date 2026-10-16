"""Human insights closed loop (v4.3 spec §3.5 T8, v4.4 spec §3.4 & §12.2).

Captures, redacts, clusters, and reviews human correction signals in user scope
(``~/.aegis/insights/<workspace-id>.jsonl``, mode ``0600``), keeping raw prompt
excerpts out of the repository working tree and out of agent-visible scan output:

- **Keyed pseudonymization (``link.key`` / ``session_hs``)**: ``~/.aegis/link.key`` holds
  32 random bytes (mode ``0600``, created ``O_CREAT | O_EXCL``). Host session identifiers
  are hashed with ``HMAC-SHA256(link_key, b"aegis-hs/v1\\x00" + host + b"\\x00" + id)[:32]``
  and stored as ``hs``; raw session identifiers are never written to disk.
- **Redaction and 300-char cap (``redact_insight_text``)**: strips PEM blocks, URL
  credentials, JWTs, AWS keys, VCS/API/vendor tokens, Bearer tokens, sensitive
  ``key=value`` pairs, email addresses, home directory usernames, IPv4 addresses, and
  high-entropy tokens with digits before truncating to at most 300 characters.
- **7-pattern correction-cue detector (``has_correction_cue``)**: gates opt-in
  ``UserPromptSubmit`` hook excerpts. Every prompt records a text-free ``heartbeat`` row
  for session-denominator accounting; only prompts matching a correction cue record a
  redacted ``W2`` insight excerpt.
- **Agent suggestions don't count (``capture_suggestion``)**: MCP ``aegis_capture_insight``
  records ``level="suggestion"``, which is excluded from clustering, rule matching,
  proposals, debits, and ``aegis_scan``. A suggestion upgrades to ``W2`` only when its
  redacted quote is a substring of a hook-captured prompt in the same ``hs`` session.
- **TF-IDF clustering & exposure-joined rule matching (``review_insights``)**: groups
  countable insights with stdlib TF-IDF cosine similarity, classifies each cluster against
  active rules (``exposed_and_ignored`` vs ``not_exposed``), proposals
  (``matches_proposal``), and archived rules (``matches_archived``), and enforces a
  cooldown on rejected clusters until ``>= 2`` new insights arrive.
- **Closed-template proposals (``write_proposal``) & recurrence alarm
  (``measure_recurrence``)**: writes proposals to ``.aegis/proposals/<id>.md`` (outside
  ``.aegis/rules/``, refusing verbatim hook/suggestion text) and measures post-activation
  recurrence over heartbeat-alive sessions per rule ``rev``.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path, PurePath
import re
import secrets
import stat
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from aegis_core import credit, gitsafe, human_gate
from aegis_core.errors import PathTraversalError
from aegis_core.match import first_match
from aegis_core.rules import Rule, load_rules
from aegis_core.scan_compliance import activity_path
from aegis_core.storage import (
    append_jsonl,
    atomic_write_text,
    fsync_dir,
    read_jsonl,
    workspace_relative,
)
from aegis_core.telemetry_engine import ledger
from aegis_core.workspace.layout import AEGIS_DIRNAME, UserLayout, WorkspaceLayout

__all__ = [
    "BURST_WINDOW_SECONDS",
    "DECISIONS",
    "INSIGHT_LEVELS",
    "INSIGHT_SCHEMA_VERSION",
    "KEY_SIZE",
    "MAX_EXCERPT_CHARS",
    "RECURRENCE_ALARM_COUNT",
    "REJECTION_RESURFACE_COUNT",
    "add_insight",
    "capture_suggestion",
    "create_link_key",
    "dirty_paths",
    "enable_host_hook",
    "has_correction_cue",
    "host_capture_status",
    "insight_workspace_id",
    "insights_path",
    "measure_recurrence",
    "read_insight_rows",
    "read_link_key",
    "record_decision",
    "record_hook_prompt",
    "redact_insight_text",
    "review_insights",
    "session_hs",
    "tfidf_cosine",
    "write_proposal",
]

KEY_SIZE = 32
_HS_DOMAIN = b"aegis-hs/v1"
INSIGHT_SCHEMA_VERSION = 1
MAX_EXCERPT_CHARS = 300
REJECTION_RESURFACE_COUNT = 2
RECURRENCE_ALARM_COUNT = 3
BURST_WINDOW_SECONDS = 300
INSIGHT_LEVELS = ("H", "cli", "W2", "hook", "suggestion")
COUNTABLE_LEVELS = frozenset({"H", "cli", "W2", "hook"})
DECISIONS = ("propose", "reject", "snooze", "merge-into-rule", "noise")

_O_BINARY = getattr(os, "O_BINARY", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime(_TS_FORMAT)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, _TS_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ── 1. Link key & session_hs (compatible with g1-label-foundation) ───────────

def _user_layout(home: Optional[Path] = None) -> Optional[UserLayout]:
    if home is not None:
        return UserLayout(Path(home))
    return UserLayout.current()


def _link_key_path(layout: UserLayout) -> Path:
    return layout.aegis_dir / "link.key"


def _ensure_private_dir(directory: Path) -> None:
    try:
        st: Optional[os.stat_result] = os.lstat(directory)
    except FileNotFoundError:
        st = None
    if st is not None:
        if stat.S_ISLNK(st.st_mode):
            raise PathTraversalError(
                f"refusing to use {directory}: it is a symlink", path=str(directory)
            )
        if not stat.S_ISDIR(st.st_mode):
            raise PathTraversalError(
                f"refusing to use {directory}: it is not a directory", path=str(directory)
            )
    else:
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if os.name == "posix":
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass


def create_link_key(home: Optional[Path] = None) -> Tuple[Path, bool]:
    """Ensure ``~/.aegis/link.key`` exists with 32 random bytes and mode ``0600``.

    Created with ``O_CREAT | O_EXCL`` so an existing key is never overwritten.
    Returns ``(path, True)`` when newly created and ``(path, False)`` when already present.
    """
    layout = _user_layout(home)
    if layout is None:
        raise OSError("cannot resolve home directory for link.key")
    aegis_dir = layout.aegis_dir
    _ensure_private_dir(aegis_dir)
    key_path = _link_key_path(layout)
    try:
        key_st: Optional[os.stat_result] = os.lstat(key_path)
    except FileNotFoundError:
        key_st = None
    if key_st is not None and stat.S_ISLNK(key_st.st_mode):
        raise PathTraversalError(
            f"refusing to use {key_path}: it is a symlink", path=str(key_path)
        )

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW | _O_BINARY | _O_CLOEXEC
    try:
        fd = os.open(str(key_path), flags, 0o600)
    except FileExistsError:
        st = os.lstat(key_path)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise PathTraversalError(
                f"refusing to use {key_path}: it is not a regular file", path=str(key_path)
            )
        if st.st_size != KEY_SIZE:
            raise ValueError(
                f"corrupt {key_path}: expected {KEY_SIZE} bytes, found {st.st_size}"
            )
        if os.name == "posix" and stat.S_IMODE(st.st_mode) != 0o600:
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass
        return key_path, False

    try:
        data = secrets.token_bytes(KEY_SIZE)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        if hasattr(os, "fchmod"):
            try:
                os.fchmod(fd, 0o600)
            except OSError:
                pass
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        try:
            os.unlink(key_path)
        except OSError:
            pass
        raise
    os.close(fd)
    if os.name == "posix":
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
    fsync_dir(aegis_dir)
    return key_path, True


def read_link_key(home: Optional[Path] = None) -> Optional[bytes]:
    """Read the 32-byte ``~/.aegis/link.key``, or ``None`` if absent or unreadable."""
    layout = _user_layout(home)
    if layout is None:
        return None
    key_path = _link_key_path(layout)
    try:
        st = os.lstat(key_path)
    except OSError:
        return None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        return None
    flags = os.O_RDONLY | _O_NOFOLLOW | _O_BINARY | _O_CLOEXEC
    try:
        fd = os.open(str(key_path), flags)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(KEY_SIZE + 1)
    except OSError:
        return None
    if len(data) != KEY_SIZE:
        return None
    return data


def _is_printable_ascii(text: str) -> bool:
    return all(0x20 <= ord(ch) <= 0x7E for ch in text)


def session_hs(
    host: str,
    value: str,
    link_key: Optional[bytes] = None,
    *,
    home: Optional[Path] = None,
) -> Optional[str]:
    """Compute the 32-hex pseudonymized ``hs`` for ``(host, value)``."""
    if not isinstance(host, str) or not host.strip():
        return None
    if not isinstance(value, str):
        return None
    clean = value.strip()
    if not (1 <= len(clean) <= 128) or not _is_printable_ascii(clean):
        return None
    key = link_key if link_key is not None else read_link_key(home)
    if key is None or len(key) != KEY_SIZE:
        return None
    msg = _HS_DOMAIN + b"\x00" + host.encode("utf-8") + b"\x00" + clean.encode("ascii")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:32]


def _ensure_hs(host: str, session: Optional[str], home: Optional[Path] = None) -> Optional[str]:
    if not isinstance(session, str) or not session.strip():
        return None
    key = read_link_key(home)
    if key is None:
        try:
            create_link_key(home)
            key = read_link_key(home)
        except (OSError, ValueError, PathTraversalError):
            return None
    return session_hs(host, session, key, home=home)


# ── 2. User-scope storage (~/.aegis/insights/<workspace-id>.jsonl) ───────────

def _fast_git_common_and_top(root: Path) -> Optional[Tuple[Path, Path]]:
    """Fast filesystem-only resolution of (common_dir, toplevel) without spawning git."""
    cur = Path(os.path.realpath(root))
    for candidate in (cur, *cur.parents):
        dot_git = candidate / ".git"
        try:
            st = os.lstat(dot_git)
        except OSError:
            continue
        if stat.S_ISDIR(st.st_mode):
            return dot_git, candidate
        if stat.S_ISREG(st.st_mode):
            try:
                raw = dot_git.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                break
            if raw.startswith("gitdir:"):
                gitdir_raw = raw[len("gitdir:") :].strip()
                gitdir = (candidate / gitdir_raw).resolve() if not os.path.isabs(gitdir_raw) else Path(gitdir_raw).resolve()
                commondir_file = gitdir / "commondir"
                if commondir_file.is_file():
                    try:
                        rel_common = commondir_file.read_text(encoding="utf-8", errors="replace").strip()
                        common = (gitdir / rel_common).resolve()
                        return common, candidate
                    except OSError:
                        pass
                return gitdir, candidate
    return None


def insight_workspace_id(workspace: Any) -> str:
    """Stable 16-hex identifier for ``workspace`` across worktrees of the same repo."""
    root = Path(os.fspath(workspace)).resolve()
    fast = _fast_git_common_and_top(root)
    if fast is not None:
        common, top = fast
        try:
            rel = os.path.relpath(
                os.path.normcase(os.path.realpath(root)),
                os.path.normcase(os.path.realpath(top)),
            ).replace(os.sep, "/")
        except ValueError:
            rel = "."
        canon = f"{Path(os.path.realpath(common)).as_posix()}\x00{rel}"
    else:
        common_fallback = gitsafe.common_dir(root)
        rel_fallback = workspace_relative(root) if common_fallback is not None else None
        if common_fallback is not None and rel_fallback is not None:
            canon = f"{Path(os.path.realpath(common_fallback)).as_posix()}\x00{rel_fallback}"
        else:
            canon = Path(os.path.realpath(root)).as_posix()
    return hashlib.sha256(canon.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def insights_path(workspace: Any, home: Optional[Path] = None) -> Path:
    """Path to ``~/.aegis/insights/<workspace-id>.jsonl`` in user scope."""
    layout = _user_layout(home)
    if layout is None:
        raise OSError("cannot resolve user home directory for insights storage")
    return layout.aegis_dir / "insights" / f"{insight_workspace_id(workspace)}.jsonl"


def _append_user_insights(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    if not rows:
        return
    _ensure_private_dir(path.parent.parent)
    _ensure_private_dir(path.parent)
    append_jsonl(path, rows)
    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def read_insight_rows(workspace: Any, home: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Read all valid rows from ``~/.aegis/insights/<workspace-id>.jsonl``."""
    try:
        path = insights_path(workspace, home=home)
    except OSError:
        return []
    return list(read_jsonl(path).rows)


# ── 3. Redaction & 300-char cap (from redaction2.py) ─────────────────────────

_SENSITIVE_KEYS = (
    r"(?:password|passwd|pwd|secret|token|api_?key|access_?key|private_?key|"
    r"client_?secret|auth|credential|authorization)"
)

_REDACT_PATTERNS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED_PEM]",
    ),
    (
        re.compile(r"\b([a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@/]+@"),
        r"\1[REDACTED]@",
    ),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b"),
        "[REDACTED_JWT]",
    ),
    (
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        "[REDACTED_AWS]",
    ),
    (
        re.compile(
            r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|"
            r"\bgithub_pat_[A-Za-z0-9_]{20,}\b|"
            r"\bglpat-[A-Za-z0-9_-]{16,}\b"
        ),
        "[REDACTED_VCS_TOKEN]",
    ),
    (
        re.compile(
            r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}\b|"
            r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}\b"
        ),
        "[REDACTED_API_KEY]",
    ),
    (
        re.compile(
            r"\bxox[abprs]-[A-Za-z0-9-]{20,}\b|"
            r"\bnpm_[A-Za-z0-9]{20,}\b|"
            r"\bAIza[A-Za-z0-9_-]{25,}\b|"
            r"\bpypi-[A-Za-z0-9_-]{20,}\b"
        ),
        "[REDACTED_TOKEN]",
    ),
    (
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
        "Bearer [REDACTED]",
    ),
    (
        re.compile(
            rf"(?i)(\b[A-Za-z0-9_]*{_SENSITIVE_KEYS}[A-Za-z0-9_]*[\"']?\s*(?:=|:|\bis\b)\s*[\"']?)([^\s\"',;]{4,})"
        ),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
    (
        re.compile(r"(?<=/home/)[^/\s]+|(?<=/Users/)[^/\s]+|(?<=C:\\Users\\)[^\\\s]+"),
        "~user",
    ),
    (
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        "[REDACTED_IP]",
    ),
)

_HEX_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_CANDIDATE_TOKEN_RE = re.compile(r"[A-Za-z0-9+_=-]{20,}")


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    counts = Counter(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _is_high_entropy_secret(tok: str) -> bool:
    if "REDACTED" in tok:
        return False
    if _HEX_RE.match(tok) or _UUID_RE.match(tok):
        return False
    has_digit = any(c.isdigit() for c in tok)
    if not has_digit:
        # Pure alphabetical / snake_case / CamelCase identifiers are never high-entropy secrets
        return False
    has_lower = any(c.islower() for c in tok)
    has_upper = any(c.isupper() for c in tok)
    classes = int(has_lower) + int(has_upper) + int(has_digit)
    if classes < 2:
        return False
    return _shannon_entropy(tok) >= 3.8


def redact_insight_text(text: str, max_len: int = MAX_EXCERPT_CHARS) -> str:
    """Redact secrets, credentials, PII, home paths, IPs, and high-entropy tokens,
    then cap length at ``max_len`` characters (default 300)."""
    if not isinstance(text, str) or not text:
        return ""
    out = text
    for pat, repl in _REDACT_PATTERNS:
        out = pat.sub(repl, out)

    def _replace_hient(match: re.Match[str]) -> str:
        tok = match.group(0)
        return "[REDACTED_HIENT]" if _is_high_entropy_secret(tok) else tok

    out = _CANDIDATE_TOKEN_RE.sub(_replace_hient, out)
    out = " ".join(out.split())
    if max_len > 0 and len(out) > max_len:
        sliced = out[:max_len]
        # Never slice a [REDACTED...] tag in half
        last_open = sliced.rfind("[REDACTED")
        if last_open != -1 and "]" not in sliced[last_open:]:
            sliced = sliced[:last_open].rstrip()
        out = sliced
    return out


# ── 4. Correction-cue detector (7 regexes from cue_eval.py) ──────────────────

_CUE_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(don'?t|do not|never|stop|no more|not acceptable|shouldn'?t|should not|must not|mustn'?t)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(again|already|i (said|told|asked|wanted)|last time|as i said|keep (doing|using|adding))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(wrong|incorrect|broke|broken|breaks|mistake|not what i)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(instead|rather than)\b", re.IGNORECASE),
    re.compile(r"^\s*(no|nope|nah)\b", re.IGNORECASE),
    re.compile(r"\bwhy (is|are|did|do) (there|you|this|we)\b", re.IGNORECASE),
    re.compile(r"\b(revert|undo)\b", re.IGNORECASE),
)


def has_correction_cue(text: str) -> bool:
    """True when ``text`` matches at least one of the 7 correction-cue patterns."""
    if not isinstance(text, str) or not text.strip():
        return False
    return any(pat.search(text) is not None for pat in _CUE_PATTERNS)


# ── 5. Workspace dirty paths & active rule revisions ─────────────────────────

def dirty_paths(workspace: Any) -> List[str]:
    """Modified, staged, or untracked workspace-relative POSIX paths from git status."""
    root = Path(os.fspath(workspace)).resolve()
    top = gitsafe.toplevel(root)
    if top is None:
        return []
    try:
        res = gitsafe.run(["status", "--porcelain", "-z", "-uall"], top, timeout=5.0)
    except gitsafe.GitError:
        return []
    if res.returncode != 0:
        return []
    found: Set[str] = set()
    entries = res.stdout.split(b"\0")
    idx = 0
    while idx < len(entries):
        entry = entries[idx]
        idx += 1
        if len(entry) < 4:
            continue
        status = entry[:2].decode("ascii", "replace")
        raw_path = entry[3:].decode("utf-8", "replace")
        if status.startswith("R") or status.startswith("C"):
            # In -z format, rename/copy has the destination first, followed by source in next NUL entry
            if idx < len(entries):
                idx += 1
        candidate = (top / raw_path).resolve()
        try:
            rel = candidate.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel.startswith(f"{AEGIS_DIRNAME}/state/"):
            continue
        found.add(rel)
    return sorted(found)


def _served_rule_revs(workspace: Any) -> Dict[str, str]:
    root = Path(os.fspath(workspace)).resolve()
    if not (root / AEGIS_DIRNAME / "rules").is_dir():
        return {}
    try:
        ruleset = load_rules(root)
    except Exception:
        return {}
    return {r.id: r.digest[:16] for r in ruleset.served}


def _has_human_approval(workspace: Any, commit: Optional[str], base_ref: Optional[str]) -> bool:
    root = Path(os.fspath(workspace)).resolve()
    top = gitsafe.toplevel(root)
    if top is None:
        return False
    try:
        base = base_ref or gitsafe.resolve_base_ref(top)
        if not base:
            return False
        if commit:
            digest = human_gate.governance_tree_hash(top, commit)
            verdict = human_gate.verify_approval(top, commit, digest, base)
            return verdict.valid
        verdict_opt = human_gate.find_approval(top, "HEAD", base)
        return bool(verdict_opt and verdict_opt.valid)
    except Exception:
        return False


# ── 6. Capture API: add_insight, capture_suggestion, record_hook_prompt ──────

def add_insight(
    workspace: Any,
    text: str,
    *,
    paths: Optional[Sequence[str]] = None,
    kind: Optional[str] = None,
    host: str = "cli",
    session: Optional[str] = None,
    commit: Optional[str] = None,
    base_ref: Optional[str] = None,
    home: Optional[Path] = None,
) -> Dict[str, Any]:
    """Record an explicit human insight (``level='cli'`` or ``'H'`` when human-gate approved)."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("insight text must be a non-empty string")
    redacted = redact_insight_text(text, max_len=MAX_EXCERPT_CHARS)
    if paths is not None and len(paths) > 0:
        norm_paths = sorted({PurePath(str(p)).as_posix() for p in paths if str(p).strip()})
        psrc = "explicit"
    else:
        norm_paths = dirty_paths(workspace)
        psrc = "dirty"

    level = "H" if _has_human_approval(workspace, commit, base_ref) else "cli"
    hs = _ensure_hs(host, session, home=home)
    row: Dict[str, Any] = {
        "v": INSIGHT_SCHEMA_VERSION,
        "ts": _utc_now(),
        "event": "insight",
        "id": f"ins-{secrets.token_hex(6)}",
        "level": level,
        "text": redacted,
        "paths": norm_paths,
        "psrc": psrc,
        "host": host or "cli",
    }
    if hs is not None:
        row["hs"] = hs
    if kind:
        row["kind"] = str(kind)
    revs = _served_rule_revs(workspace)
    if revs:
        row["revs"] = revs
    path = insights_path(workspace, home=home)
    _append_user_insights(path, [row])
    return row


def _matching_hook_insight(
    rows: Sequence[Mapping[str, Any]], hs: Optional[str], redacted_quote: str
) -> Optional[str]:
    if not hs or not redacted_quote or len(redacted_quote.strip()) < 4:
        return None
    needle = redacted_quote.strip().lower()
    for row in rows:
        if (
            row.get("event") == "insight"
            and row.get("level") in ("W2", "hook")
            and row.get("hs") == hs
            and isinstance(row.get("text"), str)
            and needle in row["text"].lower()
        ):
            return str(row.get("id") or "")
    return None


def capture_suggestion(
    workspace: Any,
    quote: str,
    paths: Optional[Sequence[str]] = None,
    *,
    host: str = "mcp",
    session: Optional[str] = None,
    home: Optional[Path] = None,
) -> Dict[str, Any]:
    """Capture an agent-reported insight via ``aegis_capture_insight``.

    Stored as ``level='suggestion'`` by default (never counted toward proposals or debits,
    never returned by ``aegis_scan``). Upgraded to ``level='W2'`` only when ``quote`` (or
    its redacted form) is a substring of a hook-captured prompt in the same ``hs`` session.
    """
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError("quote must be a non-empty string")
    redacted = redact_insight_text(quote, max_len=MAX_EXCERPT_CHARS)
    if paths is not None and len(paths) > 0:
        norm_paths = sorted({PurePath(str(p)).as_posix() for p in paths if str(p).strip()})
        psrc = "explicit"
    else:
        norm_paths = dirty_paths(workspace)
        psrc = "dirty"

    hs = _ensure_hs(host, session, home=home)
    existing = read_insight_rows(workspace, home=home)
    matched_hook_id = _matching_hook_insight(existing, hs, redacted)
    level = "W2" if matched_hook_id else "suggestion"

    row: Dict[str, Any] = {
        "v": INSIGHT_SCHEMA_VERSION,
        "ts": _utc_now(),
        "event": "insight",
        "id": f"ins-{secrets.token_hex(6)}",
        "level": level,
        "text": redacted,
        "paths": norm_paths,
        "psrc": psrc,
        "host": host or "mcp",
    }
    if hs is not None:
        row["hs"] = hs
    if matched_hook_id:
        row["confirmed_by"] = matched_hook_id
    revs = _served_rule_revs(workspace)
    if revs:
        row["revs"] = revs
    path = insights_path(workspace, home=home)
    _append_user_insights(path, [row])
    return row


def _extract_hook_fields(payload: Any) -> Tuple[str, Optional[str], Optional[str]]:
    if isinstance(payload, str):
        stripped = payload.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, Mapping):
                    payload = parsed
            except ValueError:
                pass
    if isinstance(payload, str):
        return payload, None, None
    if not isinstance(payload, Mapping):
        return "", None, None
    prompt = ""
    for key in ("prompt", "user_prompt", "text", "message", "input"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            prompt = val
            break
    session_id = None
    for key in ("session_id", "sessionId", "conversation_id", "conversationId", "session"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            session_id = val.strip()
            break
    cwd = None
    for key in ("cwd", "workspace", "working_directory", "project_dir"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            cwd = val.strip()
            break
    return prompt, session_id, cwd


def record_hook_prompt(
    workspace_or_host: Any,
    host_or_payload: Any,
    payload: Any = None,
    *,
    workspace: Any = None,
    excerpts: bool = True,
    session: Optional[str] = None,
    home: Optional[Path] = None,
) -> Dict[str, Any]:
    """Process a ``UserPromptSubmit`` hook event.

    Supports both ``record_hook_prompt(workspace, host, payload, ...)`` and
    ``record_hook_prompt(host, payload, *, workspace=...)``.
    Appends a text-free ``heartbeat`` row (once per ``(host, hs)`` session) on every
    prompt, and appends a redacted ``<= 300`` char ``W2`` insight row only when
    ``has_correction_cue(prompt)`` is True and ``excerpts`` is enabled.
    """
    if payload is None:
        host = str(workspace_or_host)
        actual_payload = host_or_payload
        actual_ws = workspace
    else:
        actual_ws = workspace_or_host
        host = str(host_or_payload)
        actual_payload = payload

    prompt_text, payload_session, payload_cwd = _extract_hook_fields(actual_payload)
    if actual_ws is None:
        from aegis_core.config import env_workspace
        actual_ws = payload_cwd or env_workspace() or os.getcwd()
    raw_session = session or payload_session
    hs = _ensure_hs(host, raw_session, home=home)

    path = insights_path(actual_ws, home=home)
    existing = read_insight_rows(actual_ws, home=home)
    revs = _served_rule_revs(actual_ws)
    now = _utc_now()
    to_write: List[Dict[str, Any]] = []

    has_hb = any(
        r.get("event") == "heartbeat"
        and r.get("host") == host
        and (hs is not None and r.get("hs") == hs)
        for r in existing
    )
    if not has_hb:
        hb: Dict[str, Any] = {
            "v": INSIGHT_SCHEMA_VERSION,
            "ts": now,
            "event": "heartbeat",
            "host": host,
        }
        if hs is not None:
            hb["hs"] = hs
        if revs:
            hb["revs"] = revs
        to_write.append(hb)

    cue_matched = has_correction_cue(prompt_text)
    insight_row: Optional[Dict[str, Any]] = None
    if cue_matched and excerpts:
        redacted = redact_insight_text(prompt_text, max_len=MAX_EXCERPT_CHARS)
        dirty = dirty_paths(actual_ws)
        insight_row = {
            "v": INSIGHT_SCHEMA_VERSION,
            "ts": now,
            "event": "insight",
            "id": f"ins-{secrets.token_hex(6)}",
            "level": "W2",
            "text": redacted,
            "paths": dirty,
            "psrc": "dirty",
            "host": host,
        }
        if hs is not None:
            insight_row["hs"] = hs
        if revs:
            insight_row["revs"] = revs
        to_write.append(insight_row)

    if to_write:
        _append_user_insights(path, to_write)

    if insight_row is not None:
        return insight_row
    return {
        "v": INSIGHT_SCHEMA_VERSION,
        "ts": now,
        "event": "heartbeat",
        "host": host,
        "hs": hs,
        "cue": cue_matched,
        "recorded": False,
    }


# ── 7. Stdlib TF-IDF, clustering, exposure join, and rule matching ───────────

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "to", "of", "in", "on", "at",
    "for", "with", "by", "from", "up", "about", "into", "over", "after", "is", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "don", "t",
    "not", "no", "never", "stop", "don't", "shouldn't", "mustn't", "should", "must", "can",
    "could", "would", "will", "just", "please", "you", "your", "i", "me", "my", "we", "our",
    "it", "its", "this", "that", "these", "those", "there", "here", "what", "which", "who",
    "why", "how", "when", "where", "again", "already", "said", "told", "asked", "wanted",
    "last", "time", "as", "keep", "doing", "using", "adding", "wrong", "incorrect", "broke",
    "broken", "breaks", "mistake", "instead", "rather", "than", "nope", "nah", "revert",
    "undo", "use", "always", "avoid", "make", "sure", "only", "any", "all", "every", "some",
    "rule", "trap", "prevent", "recurring", "defect", "modules", "module", "file", "files",
})
_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _stem(word: str) -> str:
    for suf in ("ing", "ed", "es", "s", "ly"):
        if word.endswith(suf) and len(word) > len(suf) + 2:
            return word[: -len(suf)]
    return word


def _tokenize(text: str) -> List[str]:
    if not isinstance(text, str):
        return []
    tokens = []
    for raw in _TOKEN_RE.findall(text.lower()):
        for part in raw.split("_"):
            if part and part not in _STOPWORDS and len(part) > 1:
                stemmed = _stem(part)
                if stemmed not in _STOPWORDS and len(stemmed) > 1:
                    tokens.append(stemmed)
    return tokens


def _tfidf_vectors(docs: Sequence[Sequence[str]]) -> List[Dict[str, float]]:
    n = len(docs)
    if n == 0:
        return []
    df: Counter[str] = Counter()
    for doc in docs:
        for term in set(doc):
            df[term] += 1
    vecs: List[Dict[str, float]] = []
    for doc in docs:
        tf = Counter(doc)
        vec: Dict[str, float] = {}
        for term, count in tf.items():
            vec[term] = (1.0 + math.log(count)) * (math.log((n + 1.0) / (df[term] + 1.0)) + 1.0)
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vecs.append({k: v / norm for k, v in vec.items()})
    return vecs


def _cosine(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(val * b.get(k, 0.0) for k, val in a.items())


def tfidf_cosine(text_a: str, text_b: str) -> float:
    """Pairwise TF-IDF cosine similarity between two strings."""
    toks_a, toks_b = _tokenize(text_a), _tokenize(text_b)
    if not toks_a or not toks_b:
        return 0.0
    vecs = _tfidf_vectors([toks_a, toks_b])
    return _cosine(vecs[0], vecs[1])


def _load_archived_rules(workspace: Any) -> List[Rule]:
    root = WorkspaceLayout(Path(os.fspath(workspace)).resolve())
    archive_dir = root.rules_dir / ".archive"
    if not archive_dir.is_dir():
        return []
    from aegis_core.yaml_engine.frontmatter import split_frontmatter
    from aegis_core.yaml_engine.parser import AegisYAMLError, parse_yaml_subset

    archived: List[Rule] = []
    for md in sorted(archive_dir.rglob("*.md")):
        if not md.is_file() or md.is_symlink():
            continue
        try:
            raw = md.read_bytes()
            text = raw.decode("utf-8")
            _status, fm, body = split_frontmatter(text)
            meta = parse_yaml_subset(fm) if fm else {}
            if not isinstance(meta, dict):
                meta = {}
        except (OSError, UnicodeDecodeError, AegisYAMLError):
            continue
        rule_id = str(meta.get("id") or md.stem)
        rel = md.relative_to(root.root).as_posix()
        digest = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
        archived.append(
            Rule(
                id=rule_id,
                path=rel,
                type=str(meta.get("type") or "trap"),
                meta=meta,
                body=body,
                digest=digest,
            )
        )
    return archived


def _load_proposals(workspace: Any) -> List[Rule]:
    root = WorkspaceLayout(Path(os.fspath(workspace)).resolve())
    prop_dir = root.aegis_dir / "proposals"
    if not prop_dir.is_dir():
        return []
    from aegis_core.yaml_engine.frontmatter import split_frontmatter
    from aegis_core.yaml_engine.parser import AegisYAMLError, parse_yaml_subset

    proposals: List[Rule] = []
    for md in sorted(prop_dir.glob("*.md")):
        if not md.is_file() or md.is_symlink():
            continue
        try:
            raw = md.read_bytes()
            text = raw.decode("utf-8")
            _status, fm, body = split_frontmatter(text)
            meta = parse_yaml_subset(fm) if fm else {}
            if not isinstance(meta, dict):
                meta = {}
        except (OSError, UnicodeDecodeError, AegisYAMLError):
            continue
        prop_id = str(meta.get("id") or md.stem)
        rel = md.relative_to(root.root).as_posix()
        digest = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
        proposals.append(
            Rule(
                id=prop_id,
                path=rel,
                type=str(meta.get("type") or "trap"),
                meta=meta,
                body=body,
                digest=digest,
            )
        )
    return proposals


def _rule_was_exposed(
    workspace: Any,
    rule: Rule,
    cluster_rows: Sequence[Mapping[str, Any]],
    home: Optional[Path] = None,
) -> bool:
    """True only when a real exposure record joins on workspace, host, session/hs, and rule rev."""
    root = Path(os.fspath(workspace)).resolve()
    ledger_rows = ledger.read(root).rows
    activity_rows = read_jsonl(activity_path(root)).rows
    link_key = read_link_key(home)

    # Map session -> hs for ledger and activity rows
    exposed_hs_for_rule: Set[Tuple[str, str]] = set()
    scan_hs_hosts: Set[Tuple[str, str]] = set()

    for act in activity_rows:
        if act.get("event") == "scan":
            act_host = str(act.get("host") or "")
            act_sess = str(act.get("session") or "")
            hs = session_hs(act_host, act_sess, link_key, home=home) if act_sess else None
            if hs:
                scan_hs_hosts.add((act_host, hs))

    for lrow in ledger_rows:
        if lrow.get("rule") != rule.id:
            continue
        meta = lrow.get("meta") if isinstance(lrow.get("meta"), Mapping) else {}
        row_rev = meta.get("rev")
        if isinstance(row_rev, str) and row_rev and not rule.digest.startswith(row_rev):
            continue
        lhost = str(lrow.get("host") or "")
        lsess = str(lrow.get("session") or "")
        if less_rules := credit.exposed_rules(root, lhost, lsess):
            if rule.id in less_rules:
                lhs = session_hs(lhost, lsess, link_key, home=home)
                if lhs:
                    exposed_hs_for_rule.add((lhost, lhs))
        lhs = session_hs(lhost, lsess, link_key, home=home) if lsess else None
        if lhs and ((lhost, lhs) in scan_hs_hosts or lrow.get("outcome") in ("trigger", "tp", "fp")):
            exposed_hs_for_rule.add((lhost, lhs))

    for ins in cluster_rows:
        ihost = str(ins.get("host") or "")
        ihs = str(ins.get("hs") or "")
        if ihost and ihs and (ihost, ihs) in exposed_hs_for_rule:
            return True
    return False


def _paths_overlap_rule(paths: Iterable[str], rule: Rule) -> bool:
    path_list = [p for p in paths if p]
    if not path_list:
        return True
    if not rule.target_paths:
        return True
    return any(rule.applies_to(p) or first_match(rule.target_paths, p) is not None for p in path_list)


def _cluster_signature_id(tokens: Sequence[str], matched_id: Optional[str]) -> str:
    if matched_id:
        return f"cluster-{matched_id}"
    top_terms = [t for t, _ in Counter(tokens).most_common(4)]
    seed = "-".join(sorted(top_terms)) if top_terms else "misc"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
    return f"cluster-{digest}"


def record_decision(
    workspace: Any,
    *,
    cluster_id: str,
    decision: str,
    insight_ids: Sequence[str],
    reason: Optional[str] = None,
    rule_id: Optional[str] = None,
    home: Optional[Path] = None,
) -> Dict[str, Any]:
    """Append an operator review decision (``propose``, ``reject``, ``snooze``, ``merge-into-rule``, ``noise``)."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {list(DECISIONS)}, got {decision!r}")
    if not isinstance(cluster_id, str) or not cluster_id.strip():
        raise ValueError("cluster_id must be a non-empty string")
    row: Dict[str, Any] = {
        "v": INSIGHT_SCHEMA_VERSION,
        "ts": _utc_now(),
        "event": "decision",
        "cluster_id": cluster_id.strip(),
        "decision": decision,
        "insight_ids": [str(i) for i in insight_ids if str(i).strip()],
    }
    if reason:
        row["reason"] = redact_insight_text(str(reason), max_len=MAX_EXCERPT_CHARS)
    if rule_id:
        row["rule_id"] = str(rule_id)
    path = insights_path(workspace, home=home)
    _append_user_insights(path, [row])
    return row


def review_insights(
    workspace: Any,
    *,
    home: Optional[Path] = None,
    include_suppressed: bool = False,
) -> Dict[str, Any]:
    """Cluster countable insights via stdlib TF-IDF cosine similarity and match against rules.

    - Agent suggestions (``level='suggestion'`` not confirmed by a hook prompt in the same
      ``hs`` session) are returned only in ``suggestions`` and never enter clusters or proposals.
    - Rejected clusters stay suppressed until ``>= 2`` new insights arrive after the rejection.
    """
    all_rows = read_insight_rows(workspace, home=home)
    noise_ids: Set[str] = set()
    rejections: List[Tuple[int, Dict[str, Any]]] = []

    for idx, row in enumerate(all_rows):
        if row.get("event") == "decision":
            dec = row.get("decision")
            ids = [str(x) for x in (row.get("insight_ids") or []) if x]
            if dec == "noise":
                noise_ids.update(ids)
            elif dec == "reject":
                rejections.append((idx, row))

    hook_rows = [
        r for r in all_rows if r.get("event") == "insight" and r.get("level") in ("W2", "hook")
    ]
    suggestions: List[Dict[str, Any]] = []
    countable: List[Tuple[int, Dict[str, Any]]] = []
    seen_hook_ids: Set[str] = set()

    for idx, row in enumerate(all_rows):
        if row.get("event") != "insight":
            continue
        ins_id = str(row.get("id") or f"row-{idx}")
        if ins_id in noise_ids:
            continue
        level = row.get("level")
        if level == "suggestion":
            matched_hook = _matching_hook_insight(hook_rows, row.get("hs"), str(row.get("text") or ""))
            if not matched_hook:
                suggestions.append(row)
                continue
            # Confirmed by a hook prompt in the same session; avoid double-counting if the hook row is already present
            if matched_hook in seen_hook_ids:
                continue
        if level in COUNTABLE_LEVELS or level == "suggestion":
            if level in ("W2", "hook") and ins_id:
                seen_hook_ids.add(ins_id)
            countable.append((idx, row))

    if not countable:
        return {
            "clusters": [],
            "suggestions": suggestions,
            "suppressed_clusters": [],
            "neighbours": {},
        }

    # Load active rules, proposals, and archived rules for corpus TF-IDF + matching
    root = Path(os.fspath(workspace)).resolve()
    active_rules = list(load_rules(root).served) if (root / AEGIS_DIRNAME / "rules").is_dir() else []
    proposals = _load_proposals(root)
    archived_rules = _load_archived_rules(root)

    ins_tokens = [_tokenize(str(r.get("text") or "")) for _, r in countable]
    rule_entries: List[Tuple[str, Rule, List[str]]] = []
    for r in active_rules:
        rule_entries.append(("active", r, _tokenize(f"{r.id} {r.meta.get('hypothesis', '')} {r.body}")))
    for p in proposals:
        rule_entries.append(("proposal", p, _tokenize(f"{p.id} {p.meta.get('hypothesis', '')} {p.body}")))
    for a in archived_rules:
        rule_entries.append(("archived", a, _tokenize(f"{a.id} {a.meta.get('hypothesis', '')} {a.body}")))

    all_vecs = _tfidf_vectors(ins_tokens + [tokens for _, _, tokens in rule_entries])
    ins_vecs = all_vecs[: len(countable)]
    rule_vecs = all_vecs[len(countable) :]

    # Top-3 nearest neighbours for each countable insight
    neighbours: Dict[str, List[Dict[str, Any]]] = {}
    n_ins = len(countable)
    for i in range(n_ins):
        ins_id = str(countable[i][1].get("id") or f"row-{countable[i][0]}")
        scored = []
        for j in range(n_ins):
            if i == j:
                continue
            sim = _cosine(ins_vecs[i], ins_vecs[j])
            if sim > 0.0:
                scored.append((sim, str(countable[j][1].get("id") or f"row-{countable[j][0]}")))
        scored.sort(key=lambda item: (-item[0], item[1]))
        neighbours[ins_id] = [
            {"id": nid, "similarity": round(sim, 4)} for sim, nid in scored[:3]
        ]

    # Match each insight against active rules, proposals, and archived rules first
    ins_best_rule: List[Optional[Tuple[str, Rule, float]]] = []
    for i in range(n_ins):
        paths_i = set(countable[i][1].get("paths") or [])
        best_sim = 0.0
        best_match: Optional[Tuple[str, Rule, float]] = None
        for r_idx, (kind, rule_obj, _) in enumerate(rule_entries):
            sim = _cosine(ins_vecs[i], rule_vecs[r_idx])
            overlap = _paths_overlap_rule(paths_i, rule_obj)
            if (overlap and sim >= 0.15) or sim >= 0.30:
                if sim > best_sim:
                    best_sim = sim
                    best_match = (kind, rule_obj, sim)
        ins_best_rule.append(best_match)

    # Single-linkage clustering over countable insights (never merging insights that match different rules)
    parent = list(range(n_ins))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n_ins):
        paths_i = set(countable[i][1].get("paths") or [])
        match_i = ins_best_rule[i]
        rule_id_i = match_i[1].id if match_i is not None else None
        for j in range(i + 1, n_ins):
            match_j = ins_best_rule[j]
            rule_id_j = match_j[1].id if match_j is not None else None
            if rule_id_i != rule_id_j:
                continue
            sim = _cosine(ins_vecs[i], ins_vecs[j])
            paths_j = set(countable[j][1].get("paths") or [])
            path_overlap = bool(not paths_i or not paths_j or (paths_i & paths_j))
            if (rule_id_i is not None and rule_id_i == rule_id_j) or (path_overlap and sim >= 0.22) or sim >= 0.35:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[max(ri, rj)] = min(ri, rj)

    groups: Dict[int, List[int]] = {}
    for i in range(n_ins):
        groups.setdefault(find(i), []).append(i)

    clusters: List[Dict[str, Any]] = []
    suppressed: List[Dict[str, Any]] = []

    for member_indices in groups.values():
        member_rows = [countable[m][1] for m in member_indices]
        member_row_indices = [countable[m][0] for m in member_indices]
        member_ids = [str(r.get("id") or "") for r in member_rows]
        combined_tokens: List[str] = []
        combined_paths: Set[str] = set()
        for m in member_indices:
            combined_tokens.extend(ins_tokens[m])
            combined_paths.update(countable[m][1].get("paths") or [])

        # Determine matched rule from member matches or cluster centroid
        best_score = 0.0
        best_entry: Optional[Tuple[str, Rule]] = None
        for m in member_indices:
            m_match = ins_best_rule[m]
            if m_match is not None and m_match[2] > best_score:
                best_score = m_match[2]
                best_entry = (m_match[0], m_match[1])

        matched_rule_id: Optional[str] = None
        if best_entry is None:
            match_status = "no_rule"
        else:
            kind, rule_obj = best_entry
            matched_rule_id = rule_obj.id
            if kind == "active":
                if _rule_was_exposed(root, rule_obj, member_rows, home=home):
                    match_status = "exposed_and_ignored"
                else:
                    match_status = "not_exposed"
            elif kind == "proposal":
                match_status = "matches_proposal"
            else:
                match_status = "matches_archived"

        cid = _cluster_signature_id(combined_tokens, matched_rule_id)

        # Check rejection cooldown: suppressed until >= 2 new insights arrive after rejection
        latest_reject_idx: Optional[int] = None
        for dec_idx, dec_row in rejections:
            rej_ids = set(dec_row.get("insight_ids") or [])
            if dec_row.get("cluster_id") == cid or (rej_ids and rej_ids.intersection(member_ids)):
                if latest_reject_idx is None or dec_idx > latest_reject_idx:
                    latest_reject_idx = dec_idx

        is_suppressed = False
        if latest_reject_idx is not None:
            new_since_reject = sum(1 for r_idx in member_row_indices if r_idx > latest_reject_idx)
            if new_since_reject < REJECTION_RESURFACE_COUNT:
                is_suppressed = True

        cluster_info: Dict[str, Any] = {
            "cluster_id": cid,
            "insight_ids": member_ids,
            "count": len(member_ids),
            "paths": sorted(combined_paths),
            "excerpts": [str(r.get("text") or "") for r in member_rows],
            "levels": sorted({str(r.get("level") or "") for r in member_rows}),
            "match_status": match_status,
            "matched_rule": matched_rule_id,
            "similarity": round(best_score, 4),
            "neighbours": {mid: neighbours.get(mid, []) for mid in member_ids},
        }
        if is_suppressed:
            suppressed.append(cluster_info)
            if include_suppressed:
                clusters.append(cluster_info)
        else:
            clusters.append(cluster_info)

    return {
        "clusters": clusters,
        "suggestions": suggestions,
        "suppressed_clusters": suppressed,
        "neighbours": neighbours,
    }


# ── 8. Closed-template proposals (.aegis/proposals/<id>.md) ──────────────────

_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


def _contains_verbatim_hook_or_suggestion_text(
    candidate_texts: Iterable[str],
    rows: Sequence[Mapping[str, Any]],
) -> bool:
    protected_excerpts: List[str] = []
    for row in rows:
        if row.get("event") == "insight" and row.get("level") in ("W0", "W2", "hook", "suggestion"):
            txt = str(row.get("text") or "").strip()
            if txt:
                protected_excerpts.append(txt.lower())
    if not protected_excerpts:
        return False
    for candidate in candidate_texts:
        cand_low = candidate.strip().lower()
        if not cand_low:
            continue
        for excerpt in protected_excerpts:
            if excerpt in cand_low or (len(cand_low) >= 25 and cand_low in excerpt):
                return True
    return False


def write_proposal(
    workspace: Any,
    *,
    proposal_id: str,
    rule_type: str = "trap",
    target_paths: Sequence[str],
    category: str,
    summary_bullets: Sequence[str],
    insight_ids: Sequence[str] = (),
    enforcement: str = "advisory",
    home: Optional[Path] = None,
) -> Path:
    """Write a closed-template rule proposal to ``.aegis/proposals/<proposal_id>.md``.

    Proposals live outside ``.aegis/rules/`` (so ``load_rules`` never loads them) and
    refuse verbatim ``W0``/``W2``/``hook``/``suggestion`` prompt excerpts.
    """
    clean_id = proposal_id.strip()
    if not _SAFE_ID_RE.match(clean_id):
        raise ValueError(f"invalid proposal_id {proposal_id!r}")
    rows = read_insight_rows(workspace, home=home)
    if _contains_verbatim_hook_or_suggestion_text([category, *summary_bullets], rows):
        raise ValueError("proposal may not contain verbatim W0/W2/suggestion prompt text")

    norm_targets = [PurePath(str(p)).as_posix() for p in target_paths if str(p).strip()] or ["**"]
    clean_bullets = [redact_insight_text(str(b).strip(), max_len=200) for b in summary_bullets if str(b).strip()]
    if not clean_bullets:
        raise ValueError("summary_bullets must contain at least one non-empty item")

    targets_yaml = "\n".join(f"  - {json.dumps(p)}" for p in norm_targets)
    refs_yaml = "\n".join(f"  - {json.dumps(str(i).strip())}" for i in insight_ids if str(i).strip())
    bullets_md = "\n".join(f"- {b}" for b in clean_bullets)
    hypothesis = f"Prevent recurring {category.strip()} issues in {', '.join(norm_targets[:3])}."

    content = (
        f"---\n"
        f"id: {clean_id}\n"
        f"type: {rule_type.strip() or 'trap'}\n"
        f"status: proposal\n"
        f"enforcement: {enforcement.strip() or 'advisory'}\n"
        f"category: {json.dumps(category.strip())}\n"
        f"hypothesis: {json.dumps(hypothesis)}\n"
        f"target_paths:\n{targets_yaml}\n"
    )
    if refs_yaml:
        content += f"insight_ids:\n{refs_yaml}\n"
    content += (
        f"---\n"
        f"# Proposal: {clean_id}\n\n"
        f"## Guidance\n\n"
        f"{bullets_md}\n"
    )

    layout = WorkspaceLayout(Path(os.fspath(workspace)).resolve())
    prop_dir = layout.aegis_dir / "proposals"
    prop_dir.mkdir(parents=True, exist_ok=True)
    target = prop_dir / f"{clean_id}.md"
    atomic_write_text(target, content)
    return target


# ── 9. Post-activation recurrence measurement ────────────────────────────────

def _wilson_ucb95(k: int, n: int) -> float:
    """95% one-sided Wilson score upper confidence bound on binomial proportion k/n."""
    if n <= 0:
        return 1.0
    z = 1.6448536269514722
    phat = min(1.0, max(0.0, k / n))
    z2 = z * z
    denom = 1.0 + z2 / n
    center = phat + z2 / (2.0 * n)
    rad = z * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * n)) / n)
    return min(1.0, round((center + rad) / denom, 6))


def measure_recurrence(
    workspace: Any,
    rule_id: str,
    *,
    home: Optional[Path] = None,
    reset_on_rev_change: bool = True,
) -> Dict[str, Any]:
    """Measure post-activation recurrence for ``rule_id`` over heartbeat-alive sessions.

    - Counts only sessions and insights recorded while ``rule_id`` was active at its
      current ``rev`` (when ``reset_on_rev_change`` is True).
    - Collapses multiple insights in the same ``hs`` session or within
      ``BURST_WINDOW_SECONDS`` into a single recurrence episode.
    - Returns ``status='no_prompt_traffic'`` when 0 heartbeat-alive sessions exist,
      ``status='not_working'`` with ``alarm=True`` when ``>= 3`` recurrence episodes
      occur, and ``status='ok'`` otherwise.
    """
    root = Path(os.fspath(workspace)).resolve()
    ruleset = load_rules(root)
    rule = ruleset.get(rule_id)
    if rule is None:
        raise ValueError(f"unknown rule {rule_id!r}")

    current_rev = rule.digest[:16]
    rows = read_insight_rows(root, home=home)
    rule_tokens = _tokenize(f"{rule.id} {rule.meta.get('hypothesis', '')} {rule.body}")

    alive_sessions: Set[str] = set()
    matching_insights: List[Dict[str, Any]] = []

    for idx, row in enumerate(rows):
        row_revs = row.get("revs") if isinstance(row.get("revs"), Mapping) else {}
        if reset_on_rev_change:
            if row_revs.get(rule_id) != current_rev:
                continue
        ev = row.get("event")
        if ev == "heartbeat":
            hs_key = str(row.get("hs") or f"hb-{idx}")
            alive_sessions.add(hs_key)
        elif ev == "insight" and row.get("level") in COUNTABLE_LEVELS:
            paths = row.get("paths") or []
            if not _paths_overlap_rule(paths, rule):
                continue
            ins_toks = _tokenize(str(row.get("text") or ""))
            if not ins_toks or not rule_tokens:
                continue
            vecs = _tfidf_vectors([ins_toks, rule_tokens])
            sim = _cosine(vecs[0], vecs[1])
            if sim >= 0.12:
                matching_insights.append(row)

    n_sessions = len(alive_sessions)
    if n_sessions == 0:
        return {
            "rule": rule_id,
            "rev": current_rev,
            "sessions": 0,
            "recurrences": 0,
            "rate": 0.0,
            "rate_ucb95": 1.0,
            "alarm": False,
            "status": "no_prompt_traffic",
        }

    # Collapse bursts: at most 1 recurrence episode per hs session (or within BURST_WINDOW_SECONDS when hs is absent)
    episodes = 0
    seen_episode_hs: Set[str] = set()
    last_unkeyed_ts: Optional[datetime] = None

    for ins in matching_insights:
        hs_val = ins.get("hs")
        if isinstance(hs_val, str) and hs_val:
            if hs_val in seen_episode_hs:
                continue
            seen_episode_hs.add(hs_val)
            episodes += 1
        else:
            ts = _parse_ts(ins.get("ts"))
            if (
                ts is not None
                and last_unkeyed_ts is not None
                and abs((ts - last_unkeyed_ts).total_seconds()) <= BURST_WINDOW_SECONDS
            ):
                continue
            last_unkeyed_ts = ts
            episodes += 1

    alarm = episodes >= RECURRENCE_ALARM_COUNT
    rate = round(episodes / n_sessions, 6)
    ucb = _wilson_ucb95(episodes, n_sessions)
    return {
        "rule": rule_id,
        "rev": current_rev,
        "sessions": n_sessions,
        "recurrences": episodes,
        "rate": rate,
        "rate_ucb95": ucb,
        "alarm": alarm,
        "status": "not_working" if alarm else "ok",
    }


# ── 10. Per-host insight hook enablement & doctor status ─────────────────────

SUPPORTED_INSIGHT_HOSTS = ("claude-code", "codex-cli")


def _claude_settings_path(home: Path) -> Path:
    cfg_dir = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    base = Path(cfg_dir) if cfg_dir else (home / ".claude")
    return base / "settings.json"


def _codex_hooks_path(home: Path) -> Path:
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    base = Path(codex_home) if codex_home else (home / ".codex")
    return base / "hooks.json"


def _hook_command(host: str, excerpts: bool) -> str:
    flag = " --excerpts" if excerpts else " --no-excerpts"
    return f"python3 -I -m aegis_cli.hooks.insights --host {host}{flag}"


def enable_host_hook(
    host: str,
    *,
    excerpts: bool = False,
    home: Optional[Path] = None,
) -> Dict[str, Any]:
    """Opt-in installation of the ``UserPromptSubmit`` insight hook for ``claude-code`` or ``codex-cli``."""
    if host not in SUPPORTED_INSIGHT_HOSTS:
        raise ValueError(
            f"unsupported host {host!r} for insight hook; supported hosts: {list(SUPPORTED_INSIGHT_HOSTS)}"
        )
    layout = _user_layout(home)
    if layout is None:
        raise OSError("cannot resolve user home directory")
    create_link_key(layout.home)
    target = _claude_settings_path(layout.home) if host == "claude-code" else _codex_hooks_path(layout.home)
    data: Dict[str, Any] = {}
    if target.exists() and not target.is_symlink():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            data = {}

    cmd = _hook_command(host, excerpts)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        data["hooks"] = hooks
    ups = hooks.setdefault("UserPromptSubmit", [])
    if not isinstance(ups, list):
        ups = []
        hooks["UserPromptSubmit"] = ups

    # Remove any previous aegis_cli.hooks.insights entry before adding the updated one
    filtered = []
    for entry in ups:
        if isinstance(entry, dict):
            inner = entry.get("hooks")
            if isinstance(inner, list) and any(
                isinstance(h, dict) and "aegis_cli.hooks.insights" in str(h.get("command") or "")
                for h in inner
            ):
                continue
            if "aegis_cli.hooks.insights" in str(entry.get("command") or ""):
                continue
        filtered.append(entry)

    filtered.append({"matcher": "", "hooks": [{"type": "command", "command": cmd}]})
    hooks["UserPromptSubmit"] = filtered
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, json.dumps(data, indent=2) + "\n")
    return {
        "host": host,
        "status": "enabled_excerpts" if excerpts else "enabled_counters_only",
        "excerpts": bool(excerpts),
        "config_path": str(target),
        "command": cmd,
    }


def host_capture_status(host: str, home: Optional[Path] = None) -> Dict[str, Any]:
    """Read-only per-host insight capture state for ``aegis doctor``."""
    if host == "antigravity":
        return {
            "status": "explicit_only",
            "excerpts": False,
            "detail": "host provides no UserPromptSubmit prompt field; explicit capture only",
        }
    if host not in SUPPORTED_INSIGHT_HOSTS:
        return {
            "status": "unsupported",
            "excerpts": False,
            "detail": f"insight hook is not supported on {host}",
        }
    layout = _user_layout(home)
    if layout is None:
        return {"status": "disabled", "excerpts": False}
    target = _claude_settings_path(layout.home) if host == "claude-code" else _codex_hooks_path(layout.home)
    if not target.exists() or target.is_symlink():
        return {"status": "disabled", "excerpts": False}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "disabled", "excerpts": False}
    if not isinstance(data, Mapping):
        return {"status": "disabled", "excerpts": False}
    hooks = data.get("hooks")
    if not isinstance(hooks, Mapping):
        return {"status": "disabled", "excerpts": False}
    ups = hooks.get("UserPromptSubmit")
    if not isinstance(ups, list):
        return {"status": "disabled", "excerpts": False}

    for entry in ups:
        if not isinstance(entry, Mapping):
            continue
        candidates = [entry]
        inner = entry.get("hooks")
        if isinstance(inner, list):
            candidates.extend(h for h in inner if isinstance(h, Mapping))
        for item in candidates:
            cmd = str(item.get("command") or "")
            if "aegis_cli.hooks.insights" in cmd:
                excerpts = "--excerpts" in cmd and "--no-excerpts" not in cmd
                return {
                    "status": "enabled_excerpts" if excerpts else "enabled_counters_only",
                    "excerpts": excerpts,
                }
    return {"status": "disabled", "excerpts": False}
