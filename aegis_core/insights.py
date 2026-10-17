"""Human insights closed loop (v4.3 spec §3.5 T8, v4.4 spec §3.4 & §12.2)."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
import hashlib, hmac, json, math, os, re, secrets, stat
from pathlib import Path, PurePath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from aegis_core import credit, gitsafe, human_gate
from aegis_core.errors import PathTraversalError
from aegis_core.match import first_match
from aegis_core.rules import Rule, load_rules
from aegis_core.scan_compliance import activity_path
from aegis_core.storage import append_jsonl, atomic_write_text, fsync_dir, read_jsonl, workspace_relative
from aegis_core.telemetry_engine import ledger
from aegis_core.workspace.layout import AEGIS_DIRNAME, UserLayout, WorkspaceLayout

__all__ = ["BURST_WINDOW_SECONDS", "DECISIONS", "INSIGHT_LEVELS", "INSIGHT_SCHEMA_VERSION", "KEY_SIZE", "MAX_EXCERPT_CHARS", "RECURRENCE_ALARM_COUNT", "REJECTION_RESURFACE_COUNT", "SUPPORTED_INSIGHT_HOSTS", "add_insight", "capture_suggestion", "create_link_key", "dirty_paths", "enable_host_hook", "has_correction_cue", "host_capture_status", "insight_workspace_id", "insights_path", "measure_recurrence", "read_insight_rows", "read_link_key", "record_decision", "record_hook_prompt", "redact_insight_text", "review_insights", "session_hs", "tfidf_cosine", "write_proposal"]
KEY_SIZE, INSIGHT_SCHEMA_VERSION, MAX_EXCERPT_CHARS = 32, 1, 300
REJECTION_RESURFACE_COUNT, RECURRENCE_ALARM_COUNT, BURST_WINDOW_SECONDS = 2, 3, 300
_HS_DOMAIN, _TS_FORMAT = b"aegis-hs/v1", "%Y-%m-%dT%H:%M:%SZ"
INSIGHT_LEVELS, COUNTABLE_LEVELS = ("H", "cli", "W2", "hook", "suggestion"), frozenset({"H", "cli", "W2", "hook"})
DECISIONS, SUPPORTED_INSIGHT_HOSTS = ("propose", "reject", "snooze", "merge-into-rule", "noise"), ("claude-code", "codex-cli")
_O_FLAGS = getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)

def _utc_now() -> str: return datetime.now(timezone.utc).strftime(_TS_FORMAT)
def _user_layout(home: Optional[Path] = None) -> Optional[UserLayout]: return UserLayout(Path(home)) if home is not None else UserLayout.current()
def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str): return None
    try: return datetime.strptime(value, _TS_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError: return None
def _lstat_or_none(path: Path) -> Optional[os.stat_result]:
    try: return os.lstat(path)
    except OSError: return None
def _chmod_quiet(path: Path, mode: int) -> None:
    if os.name == "posix":
        try: os.chmod(path, mode)
        except OSError: pass
def _ensure_private_dir(directory: Path) -> None:
    if (st := _lstat_or_none(directory)) is not None:
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise PathTraversalError(f"refusing to use {directory}: invalid directory", path=str(directory))
    else: directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    _chmod_quiet(directory, 0o700)

def create_link_key(home: Optional[Path] = None) -> Tuple[Path, bool]:
    if (layout := _user_layout(home)) is None: raise OSError("cannot resolve home directory for link.key")
    _ensure_private_dir(layout.aegis_dir)
    key_path = layout.aegis_dir / "link.key"
    if (st := _lstat_or_none(key_path)) is not None and stat.S_ISLNK(st.st_mode):
        raise PathTraversalError(f"refusing to use {key_path}: it is a symlink", path=str(key_path))
    try: fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_FLAGS, 0o600)
    except FileExistsError:
        st = os.lstat(key_path)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise PathTraversalError(f"refusing to use {key_path}: it is not a regular file", path=str(key_path))
        if st.st_size != KEY_SIZE: raise ValueError(f"corrupt {key_path}: expected {KEY_SIZE} bytes, found {st.st_size}")
        _chmod_quiet(key_path, 0o600)
        return key_path, False
    try:
        view = memoryview(secrets.token_bytes(KEY_SIZE))
        while view: view = view[os.write(fd, view) :]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        try: os.unlink(key_path)
        except OSError: pass
        raise
    os.close(fd)
    _chmod_quiet(key_path, 0o600)
    fsync_dir(layout.aegis_dir)
    return key_path, True

def read_link_key(home: Optional[Path] = None) -> Optional[bytes]:
    layout = _user_layout(home)
    st = _lstat_or_none(layout.aegis_dir / "link.key") if layout else None
    if not layout or not st or stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode): return None
    try:
        fd = os.open(str(layout.aegis_dir / "link.key"), os.O_RDONLY | _O_FLAGS)
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(KEY_SIZE + 1) if stat.S_ISREG(os.fstat(fd).st_mode) else b""
    except OSError: return None
    return data if len(data) == KEY_SIZE else None

def session_hs(host: str, value: str, link_key: Optional[bytes] = None, *, home: Optional[Path] = None) -> Optional[str]:
    if not isinstance(host, str) or not host.strip() or not isinstance(value, str): return None
    clean = value.strip()
    if not (1 <= len(clean) <= 128) or not all(0x20 <= ord(ch) <= 0x7E for ch in clean): return None
    key = link_key if link_key is not None else read_link_key(home)
    if key is None or len(key) != KEY_SIZE: return None
    return hmac.new(key, _HS_DOMAIN + b"\x00" + host.encode("utf-8") + b"\x00" + clean.encode("ascii"), hashlib.sha256).hexdigest()[:32]

def _ensure_hs(host: str, session: Optional[str], home: Optional[Path] = None) -> Optional[str]:
    if not isinstance(session, str) or not session.strip(): return None
    if (key := read_link_key(home)) is None:
        try:
            create_link_key(home)
            key = read_link_key(home)
        except (OSError, ValueError, PathTraversalError): return None
    return session_hs(host, session, key, home=home)

def _fast_git_common_and_top(root: Path) -> Optional[Tuple[Path, Path]]:
    cur = Path(os.path.realpath(root))
    for cand in (cur, *cur.parents):
        dot_git = cand / ".git"
        if not (st := _lstat_or_none(dot_git)): continue
        if stat.S_ISDIR(st.st_mode): return dot_git, cand
        if stat.S_ISREG(st.st_mode):
            try: raw = dot_git.read_text(encoding="utf-8", errors="replace").strip()
            except OSError: break
            if raw.startswith("gitdir:"):
                g_raw = raw[7:].strip()
                gitdir = (cand / g_raw).resolve() if not os.path.isabs(g_raw) else Path(g_raw).resolve()
                if (cfile := gitdir / "commondir").is_file():
                    try: return (gitdir / cfile.read_text(encoding="utf-8", errors="replace").strip()).resolve(), cand
                    except OSError: pass
                return gitdir, cand
    return None

def insight_workspace_id(workspace: Any) -> str:
    root = Path(os.fspath(workspace)).resolve()
    if (fast := _fast_git_common_and_top(root)) is not None:
        common, top = fast
        try: rel = os.path.relpath(os.path.normcase(os.path.realpath(root)), os.path.normcase(os.path.realpath(top))).replace(os.sep, "/")
        except ValueError: rel = "."
        canon = f"{Path(os.path.realpath(common)).as_posix()}\x00{rel}"
    else:
        c_fb = gitsafe.common_dir(root)
        r_fb = workspace_relative(root) if c_fb is not None else None
        canon = f"{Path(os.path.realpath(c_fb)).as_posix()}\x00{r_fb}" if (c_fb and r_fb) else Path(os.path.realpath(root)).as_posix()
    return hashlib.sha256(canon.encode("utf-8", "surrogatepass")).hexdigest()[:16]

def insights_path(workspace: Any, home: Optional[Path] = None) -> Path:
    if (layout := _user_layout(home)) is None: raise OSError("cannot resolve user home directory for insights storage")
    return layout.aegis_dir / "insights" / f"{insight_workspace_id(workspace)}.jsonl"
def _append_user_insights(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    if rows:
        _ensure_private_dir(path.parent.parent)
        _ensure_private_dir(path.parent)
        append_jsonl(path, rows)
        _chmod_quiet(path, 0o600)
def read_insight_rows(workspace: Any, home: Optional[Path] = None) -> List[Dict[str, Any]]:
    try: return list(read_jsonl(insights_path(workspace, home=home)).rows)
    except OSError: return []

_SENSITIVE_KEYS = r"(?:password|passwd|pwd|secret|token|api_?key|access_?key|private_?key|client_?secret|auth|credential|authorization)"
_REDACT_PATTERNS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL), "[REDACTED_PEM]"),
    (re.compile(r"\b([a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@/]+@"), r"\1[REDACTED]@"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b"), "[REDACTED_JWT]"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS]"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b|\bglpat-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_VCS_TOKEN]"),
    (re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}\b|\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}\b|\bnpm_[A-Za-z0-9]{20,}\b|\bAIza[A-Za-z0-9_-]{25,}\b|\bpypi-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"), "Bearer [REDACTED]"),
    (re.compile(rf"(?i)(\b[A-Za-z0-9_]*{_SENSITIVE_KEYS}[A-Za-z0-9_]*[\"']?\s*(?:=|:|\bis\b)\s*[\"']?)([^\s\"',;]{4,})"), r"\1[REDACTED]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"(?<=/home/)[^/\s]+|(?<=/Users/)[^/\s]+|(?<=C:\\Users\\)[^\\\s]+"), "~user"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[REDACTED_IP]"),
)
_HEX_UUID_RE = re.compile(r"^(?:[0-9a-fA-F]{7,64}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$")
_CANDIDATE_TOKEN_RE = re.compile(r"[A-Za-z0-9+_=-]{20,}")
def _is_high_entropy_secret(tok: str) -> bool:
    if "REDACTED" in tok or _HEX_UUID_RE.match(tok) or not any(c.isdigit() for c in tok): return False
    if int(any(c.islower() for c in tok)) + int(any(c.isupper() for c in tok)) + 1 < 2: return False
    n = len(tok)
    return -sum((c / n) * math.log2(c / n) for c in Counter(tok).values()) >= 3.8
def redact_insight_text(text: str, max_len: int = MAX_EXCERPT_CHARS) -> str:
    if not isinstance(text, str) or not text: return ""
    out = text
    for pat, repl in _REDACT_PATTERNS: out = pat.sub(repl, out)
    out = _CANDIDATE_TOKEN_RE.sub(lambda m: "[REDACTED_HIENT]" if _is_high_entropy_secret(m.group(0)) else m.group(0), out)
    out = " ".join(out.split())
    if max_len > 0 and len(out) > max_len:
        sliced = out[:max_len]
        last_open = sliced.rfind("[REDACTED")
        out = sliced[:last_open].rstrip() if (last_open != -1 and "]" not in sliced[last_open:]) else sliced
    return out

_CUE_RE = re.compile(r"\b(?:don'?t|do not|never|stop|no more|not acceptable|shouldn'?t|should not|must not|mustn'?t|again|already|i (?:said|told|asked|wanted)|last time|as i said|keep (?:doing|using|adding)|wrong|incorrect|broke|broken|breaks|mistake|not what i|instead|rather than|why (?:is|are|did|do) (?:there|you|this|we)|revert|undo)\b|^\s*(?:no|nope|nah)\b", re.I)
def has_correction_cue(text: str) -> bool: return bool(isinstance(text, str) and text.strip() and _CUE_RE.search(text))

def dirty_paths(workspace: Any) -> List[str]:
    root = Path(os.fspath(workspace)).resolve()
    if (top := gitsafe.toplevel(root)) is None: return []
    try: res = gitsafe.run(["status", "--porcelain", "-z", "-uall"], top, timeout=5.0)
    except gitsafe.GitError: return []
    if res.returncode != 0: return []
    found, entries, idx = set(), res.stdout.split(b"\0"), 0
    while idx < len(entries):
        entry, idx = entries[idx], idx + 1
        if len(entry) < 4: continue
        if entry[:1] in (b"R", b"C") and idx < len(entries): idx += 1
        try: rel = (top / entry[3:].decode("utf-8", "replace")).resolve().relative_to(root).as_posix()
        except ValueError: continue
        if not rel.startswith(f"{AEGIS_DIRNAME}/state/"): found.add(rel)
    return sorted(found)
def _served_rule_revs(workspace: Any) -> Dict[str, str]:
    root = Path(os.fspath(workspace)).resolve()
    if not (root / AEGIS_DIRNAME / "rules").is_dir(): return {}
    try: return {r.id: r.digest[:16] for r in load_rules(root).served}
    except Exception: return {}
def _has_human_approval(workspace: Any, commit: Optional[str], base_ref: Optional[str]) -> bool:
    root = Path(os.fspath(workspace)).resolve()
    if (top := gitsafe.toplevel(root)) is None: return False
    try:
        if not (base := base_ref or gitsafe.resolve_base_ref(top)): return False
        if commit: return human_gate.verify_approval(top, commit, human_gate.governance_tree_hash(top, commit), base).valid
        return bool((v := human_gate.find_approval(top, "HEAD", base)) and v.valid)
    except Exception: return False
def _resolve_paths(workspace: Any, paths: Optional[Sequence[str]]) -> Tuple[List[str], str]:
    if paths is not None and len(paths) > 0:
        return sorted({PurePath(str(p)).as_posix() for p in paths if str(p).strip()}), "explicit"
    return dirty_paths(workspace), "dirty"
def _matching_hook_insight(rows: Sequence[Mapping[str, Any]], hs: Optional[str], redacted_quote: str) -> Optional[str]:
    if not hs or not redacted_quote or len(redacted_quote.strip()) < 4: return None
    needle = redacted_quote.strip().lower()
    for r in rows:
        if r.get("event") == "insight" and r.get("level") in ("W2", "hook") and r.get("hs") == hs and isinstance(r.get("text"), str) and needle in r["text"].lower():
            return str(r.get("id") or "")
    return None
def _build_insight_row(workspace: Any, level: str, text: str, paths: List[str], psrc: str, host: str, hs: Optional[str], now: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {"v": INSIGHT_SCHEMA_VERSION, "ts": now or _utc_now(), "event": "insight", "id": f"ins-{secrets.token_hex(6)}", "level": level, "text": text, "paths": paths, "psrc": psrc, "host": host}
    if hs: row["hs"] = hs
    for k, v in extra.items():
        if v: row[k] = v
    if revs := _served_rule_revs(workspace): row["revs"] = revs
    return row
def add_insight(workspace: Any, text: str, *, paths: Optional[Sequence[str]] = None, kind: Optional[str] = None, host: str = "cli", session: Optional[str] = None, commit: Optional[str] = None, base_ref: Optional[str] = None, home: Optional[Path] = None) -> Dict[str, Any]:
    if not isinstance(text, str) or not text.strip(): raise ValueError("insight text must be a non-empty string")
    norm_paths, psrc = _resolve_paths(workspace, paths)
    row = _build_insight_row(workspace, "H" if _has_human_approval(workspace, commit, base_ref) else "cli", redact_insight_text(text), norm_paths, psrc, host or "cli", _ensure_hs(host, session, home), kind=str(kind) if kind else None)
    _append_user_insights(insights_path(workspace, home=home), [row])
    return row
def capture_suggestion(workspace: Any, quote: str, paths: Optional[Sequence[str]] = None, *, host: str = "mcp", session: Optional[str] = None, home: Optional[Path] = None) -> Dict[str, Any]:
    if not isinstance(quote, str) or not quote.strip(): raise ValueError("quote must be a non-empty string")
    redacted, (norm_paths, psrc), hs = redact_insight_text(quote), _resolve_paths(workspace, paths), _ensure_hs(host, session, home)
    m_hook = _matching_hook_insight(read_insight_rows(workspace, home=home), hs, redacted)
    row = _build_insight_row(workspace, "W2" if m_hook else "suggestion", redacted, norm_paths, psrc, host or "mcp", hs, confirmed_by=m_hook)
    _append_user_insights(insights_path(workspace, home=home), [row])
    return row
def _first_str(mapping: Mapping[str, Any], keys: Sequence[str], strip: bool = True) -> Optional[str]:
    for k in keys:
        if isinstance(v := mapping.get(k), str) and v.strip(): return v.strip() if strip else v
    return None
def _extract_hook_fields(payload: Any) -> Tuple[str, Optional[str], Optional[str]]:
    if isinstance(payload, str):
        s = payload.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                if isinstance(parsed := json.loads(s), Mapping): payload = parsed
            except ValueError: pass
    if isinstance(payload, str): return payload, None, None
    if not isinstance(payload, Mapping): return "", None, None
    return (_first_str(payload, ("prompt", "user_prompt", "text", "message", "input"), strip=False) or "", _first_str(payload, ("session_id", "sessionId", "conversation_id", "conversationId", "session")), _first_str(payload, ("cwd", "workspace", "working_directory", "project_dir")))
def record_hook_prompt(workspace_or_host: Any, host_or_payload: Any, payload: Any = None, *, workspace: Any = None, excerpts: bool = True, session: Optional[str] = None, home: Optional[Path] = None) -> Dict[str, Any]:
    host, actual_payload, actual_ws = (str(workspace_or_host), host_or_payload, workspace) if payload is None else (str(host_or_payload), payload, workspace_or_host)
    prompt_text, payload_session, payload_cwd = _extract_hook_fields(actual_payload)
    if actual_ws is None:
        from aegis_core.config import env_workspace
        actual_ws = payload_cwd or env_workspace() or os.getcwd()
    hs = _ensure_hs(host, session or payload_session, home=home)
    path, existing, revs, now = insights_path(actual_ws, home=home), read_insight_rows(actual_ws, home=home), _served_rule_revs(actual_ws), _utc_now()
    to_write: List[Dict[str, Any]] = []
    if not any(r.get("event") == "heartbeat" and r.get("host") == host and hs is not None and r.get("hs") == hs for r in existing):
        hb: Dict[str, Any] = {"v": INSIGHT_SCHEMA_VERSION, "ts": now, "event": "heartbeat", "host": host}
        if hs: hb["hs"] = hs
        if revs: hb["revs"] = revs
        to_write.append(hb)
    cue = has_correction_cue(prompt_text)
    insight_row: Optional[Dict[str, Any]] = None
    if cue and excerpts:
        insight_row = _build_insight_row(actual_ws, "W2", redact_insight_text(prompt_text), dirty_paths(actual_ws), "dirty", host, hs, now=now)
        to_write.append(insight_row)
    if to_write: _append_user_insights(path, to_write)
    return insight_row or {"v": INSIGHT_SCHEMA_VERSION, "ts": now, "event": "heartbeat", "host": host, "hs": hs, "cue": cue, "recorded": False}

_STOPWORDS = frozenset("a an the and or but if then else to of in on at for with by from up about into over after is are was were be been being have has had do does did don t not no never stop don't shouldn't mustn't should must can could would will just please you your i me my we our it its this that these those there here what which who why how when where again already said told asked wanted last time as keep doing using adding wrong incorrect broke broken breaks mistake instead rather than nope nah revert undo use always avoid make sure only any all every some rule trap prevent recurring defect modules module file files".split())
_TOKEN_RE = re.compile(r"[a-z0-9_]+")
def _stem(word: str) -> str:
    for suf in ("ing", "ed", "es", "s", "ly"):
        if word.endswith(suf) and len(word) > len(suf) + 2: return word[: -len(suf)]
    return word
def _tokenize(text: str) -> List[str]:
    if not isinstance(text, str): return []
    return [st for raw in _TOKEN_RE.findall(text.lower()) for part in raw.split("_") if len(part) > 1 and part not in _STOPWORDS and len(st := _stem(part)) > 1 and st not in _STOPWORDS]
def _tfidf_vectors(docs: Sequence[Sequence[str]]) -> List[Dict[str, float]]:
    if not (n := len(docs)): return []
    df: Counter[str] = Counter(t for doc in docs for t in set(doc))
    vecs: List[Dict[str, float]] = []
    for doc in docs:
        vec = {t: (1.0 + math.log(c)) * (math.log((n + 1.0) / (df[t] + 1.0)) + 1.0) for t, c in Counter(doc).items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vecs.append({k: v / norm for k, v in vec.items()})
    return vecs
def _cosine(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    if not a or not b: return 0.0
    if len(a) > len(b): a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())
def tfidf_cosine(text_a: str, text_b: str) -> float:
    ta, tb = _tokenize(text_a), _tokenize(text_b)
    return _cosine(*_tfidf_vectors([ta, tb])) if (ta and tb) else 0.0
def _load_md_rules(workspace: Any, folder: Path, *, recursive: bool = False) -> List[Rule]:
    if not folder.is_dir(): return []
    from aegis_core.yaml_engine.frontmatter import split_frontmatter
    from aegis_core.yaml_engine.parser import AegisYAMLError, parse_yaml_subset
    root_path, items = Path(os.fspath(workspace)).resolve(), []
    for md in sorted(folder.rglob("*.md") if recursive else folder.glob("*.md")):
        if not md.is_file() or md.is_symlink(): continue
        try:
            raw = md.read_bytes()
            _, fm, body = split_frontmatter(raw.decode("utf-8"))
            meta = parse_yaml_subset(fm) if fm else {}
            if not isinstance(meta, dict): meta = {}
        except (OSError, UnicodeDecodeError, AegisYAMLError): continue
        items.append(Rule(id=str(meta.get("id") or md.stem), path=md.relative_to(root_path).as_posix(), type=str(meta.get("type") or "trap"), meta=meta, body=body, digest=hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()))
    return items
def _rule_was_exposed(workspace: Any, rule: Rule, cluster_rows: Sequence[Mapping[str, Any]], home: Optional[Path] = None) -> bool:
    root, link_key = Path(os.fspath(workspace)).resolve(), read_link_key(home)
    scan_hs = {(str(a.get("host") or ""), hs) for a in read_jsonl(activity_path(root)).rows if a.get("event") == "scan" and a.get("session") and (hs := session_hs(str(a.get("host") or ""), str(a.get("session") or ""), link_key, home=home))}
    exposed_hs: Set[Tuple[str, str]] = set()
    for lrow in ledger.read(root).rows:
        if lrow.get("rule") != rule.id: continue
        rev = (lrow.get("meta") if isinstance(lrow.get("meta"), Mapping) else {}).get("rev")
        if isinstance(rev, str) and rev and not rule.digest.startswith(rev): continue
        lh, ls = str(lrow.get("host") or ""), str(lrow.get("session") or "")
        if (lhs := session_hs(lh, ls, link_key, home=home) if ls else None) and (rule.id in credit.exposed_rules(root, lh, ls) or (lh, lhs) in scan_hs or lrow.get("outcome") in ("trigger", "tp", "fp")):
            exposed_hs.add((lh, lhs))
    return any((str(ins.get("host") or ""), str(ins.get("hs") or "")) in exposed_hs for ins in cluster_rows)
def _paths_overlap_rule(paths: Iterable[str], rule: Rule) -> bool:
    plist = [p for p in paths if p]
    return not plist or not rule.target_paths or any(rule.applies_to(p) or first_match(rule.target_paths, p) is not None for p in plist)
def _cluster_signature_id(tokens: Sequence[str], matched_id: Optional[str]) -> str:
    if matched_id: return f"cluster-{matched_id}"
    top = [t for t, _ in Counter(tokens).most_common(4)]
    return f"cluster-{hashlib.sha256(('-'.join(sorted(top)) if top else 'misc').encode('utf-8')).hexdigest()[:8]}"
def record_decision(workspace: Any, *, cluster_id: str, decision: str, insight_ids: Sequence[str], reason: Optional[str] = None, rule_id: Optional[str] = None, home: Optional[Path] = None) -> Dict[str, Any]:
    if decision not in DECISIONS: raise ValueError(f"decision must be one of {list(DECISIONS)}, got {decision!r}")
    if not isinstance(cluster_id, str) or not cluster_id.strip(): raise ValueError("cluster_id must be a non-empty string")
    row: Dict[str, Any] = {"v": INSIGHT_SCHEMA_VERSION, "ts": _utc_now(), "event": "decision", "cluster_id": cluster_id.strip(), "decision": decision, "insight_ids": [str(i) for i in insight_ids if str(i).strip()]}
    if reason: row["reason"] = redact_insight_text(str(reason))
    if rule_id: row["rule_id"] = str(rule_id)
    _append_user_insights(insights_path(workspace, home=home), [row])
    return row

def review_insights(workspace: Any, *, home: Optional[Path] = None, include_suppressed: bool = False) -> Dict[str, Any]:
    all_rows = read_insight_rows(workspace, home=home)
    noise_ids = {str(x) for r in all_rows if r.get("event") == "decision" and r.get("decision") == "noise" for x in (r.get("insight_ids") or []) if x}
    rejections = [(idx, r) for idx, r in enumerate(all_rows) if r.get("event") == "decision" and r.get("decision") == "reject"]
    hook_rows = [r for r in all_rows if r.get("event") == "insight" and r.get("level") in ("W2", "hook")]
    suggestions, countable, seen_hook_ids = [], [], set()
    for idx, row in enumerate(all_rows):
        if row.get("event") != "insight" or (ins_id := str(row.get("id") or f"row-{idx}")) in noise_ids: continue
        level = row.get("level")
        if level == "suggestion":
            if not (m_hook := _matching_hook_insight(hook_rows, row.get("hs"), str(row.get("text") or ""))):
                suggestions.append(row)
                continue
            if m_hook in seen_hook_ids: continue
        if level in COUNTABLE_LEVELS or level == "suggestion":
            if level in ("W2", "hook") and ins_id: seen_hook_ids.add(ins_id)
            countable.append((idx, row))
    if not countable: return {"clusters": [], "suggestions": suggestions, "suppressed_clusters": [], "neighbours": {}}
    root = Path(os.fspath(workspace)).resolve()
    layout = WorkspaceLayout(root)
    active = list(load_rules(root).served) if layout.rules_dir.is_dir() else []
    proposals, archived = _load_md_rules(root, layout.aegis_dir / "proposals"), _load_md_rules(root, layout.rules_dir / ".archive", recursive=True)
    ins_tokens = [_tokenize(str(r.get("text") or "")) for _, r in countable]
    rule_entries = [(k, r, _tokenize(f"{r.id} {r.meta.get('hypothesis', '')} {r.body}")) for k, rl in (("active", active), ("proposal", proposals), ("archived", archived)) for r in rl]
    all_vecs = _tfidf_vectors(ins_tokens + [toks for _, _, toks in rule_entries])
    n_ins = len(countable)
    ins_vecs, rule_vecs = all_vecs[:n_ins], all_vecs[n_ins:]
    neighbours = {str(countable[i][1].get("id") or f"row-{countable[i][0]}"): [{"id": nid, "similarity": round(sim, 4)} for sim, nid in sorted(((_cosine(ins_vecs[i], ins_vecs[j]), str(countable[j][1].get("id") or f"row-{countable[j][0]}")) for j in range(n_ins) if i != j), key=lambda x: (-x[0], x[1]))[:3] if sim > 0.0] for i in range(n_ins)}
    ins_best_rule: List[Optional[Tuple[str, Rule, float]]] = []
    for i in range(n_ins):
        paths_i, best = set(countable[i][1].get("paths") or []), None
        for r_idx, (kind, robj, _) in enumerate(rule_entries):
            sim = _cosine(ins_vecs[i], rule_vecs[r_idx])
            if ((_paths_overlap_rule(paths_i, robj) and sim >= 0.15) or sim >= 0.30) and (best is None or sim > best[2]):
                best = (kind, robj, sim)
        ins_best_rule.append(best)
    parent = list(range(n_ins))
    def find(x: int) -> int:
        while parent[x] != x: parent[x] = x = parent[parent[x]]
        return x
    for i in range(n_ins):
        paths_i, rid_i = set(countable[i][1].get("paths") or []), (ins_best_rule[i][1].id if ins_best_rule[i] else None)
        for j in range(i + 1, n_ins):
            if rid_i != (ins_best_rule[j][1].id if ins_best_rule[j] else None): continue
            sim, paths_j = _cosine(ins_vecs[i], ins_vecs[j]), set(countable[j][1].get("paths") or [])
            if rid_i is not None or (bool(not paths_i or not paths_j or (paths_i & paths_j)) and sim >= 0.22) or sim >= 0.35:
                ri, rj = find(i), find(j)
                if ri != rj: parent[max(ri, rj)] = min(ri, rj)
    groups: Dict[int, List[int]] = {}
    for i in range(n_ins): groups.setdefault(find(i), []).append(i)
    clusters, suppressed = [], []
    for members in groups.values():
        m_rows, m_row_idxs = [countable[m][1] for m in members], [countable[m][0] for m in members]
        m_ids, c_tokens = [str(r.get("id") or "") for r in m_rows], [t for m in members for t in ins_tokens[m]]
        c_paths = {p for m in members for p in (countable[m][1].get("paths") or [])}
        best_m = max((ins_best_rule[m] for m in members if ins_best_rule[m] is not None), key=lambda x: x[2], default=None)
        if best_m is None: matched_id, status, best_score = None, "no_rule", 0.0
        else:
            kind, robj, best_score = best_m
            matched_id = robj.id
            status = ("exposed_and_ignored" if _rule_was_exposed(root, robj, m_rows, home=home) else "not_exposed") if kind == "active" else ("matches_proposal" if kind == "proposal" else "matches_archived")
        cid = _cluster_signature_id(c_tokens, matched_id)
        latest_rej = max((d_idx for d_idx, d_row in rejections if d_row.get("cluster_id") == cid or set(d_row.get("insight_ids") or []).intersection(m_ids)), default=None)
        is_sup = latest_rej is not None and sum(1 for r_idx in m_row_idxs if r_idx > latest_rej) < REJECTION_RESURFACE_COUNT
        info = {"cluster_id": cid, "insight_ids": m_ids, "count": len(m_ids), "paths": sorted(c_paths), "excerpts": [str(r.get("text") or "") for r in m_rows], "levels": sorted({str(r.get("level") or "") for r in m_rows}), "match_status": status, "matched_rule": matched_id, "similarity": round(best_score, 4), "neighbours": {mid: neighbours.get(mid, []) for mid in m_ids}}
        if is_sup:
            suppressed.append(info)
            if include_suppressed: clusters.append(info)
        else: clusters.append(info)
    return {"clusters": clusters, "suggestions": suggestions, "suppressed_clusters": suppressed, "neighbours": neighbours}

_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
def write_proposal(workspace: Any, *, proposal_id: str, rule_type: str = "trap", target_paths: Sequence[str], category: str, summary_bullets: Sequence[str], insight_ids: Sequence[str] = (), enforcement: str = "advisory", home: Optional[Path] = None) -> Path:
    if not _SAFE_ID_RE.match(clean_id := proposal_id.strip()): raise ValueError(f"invalid proposal_id {proposal_id!r}")
    protected = [str(r.get("text") or "").strip().lower() for r in read_insight_rows(workspace, home=home) if r.get("event") == "insight" and r.get("level") in ("W0", "W2", "hook", "suggestion") and str(r.get("text") or "").strip()]
    for cand in (category, *summary_bullets):
        if (clow := str(cand).strip().lower()) and any(ex in clow or (len(clow) >= 25 and clow in ex) for ex in protected):
            raise ValueError("proposal may not contain verbatim W0/W2/suggestion prompt text")
    norm_targets = [PurePath(str(p)).as_posix() for p in target_paths if str(p).strip()] or ["**"]
    if not (clean_bullets := [redact_insight_text(str(b).strip(), max_len=200) for b in summary_bullets if str(b).strip()]):
        raise ValueError("summary_bullets must contain at least one non-empty item")
    targets_yaml = "\n".join(f"  - {json.dumps(p)}" for p in norm_targets)
    refs_yaml = "\n".join(f"  - {json.dumps(str(i).strip())}" for i in insight_ids if str(i).strip())
    hyp = f"Prevent recurring {category.strip()} issues in {', '.join(norm_targets[:3])}."
    lines = ["---", f"id: {clean_id}", f"type: {rule_type.strip() or 'trap'}", "status: proposal", f"enforcement: {enforcement.strip() or 'advisory'}", f"category: {json.dumps(category.strip())}", f"hypothesis: {json.dumps(hyp)}", f"target_paths:\n{targets_yaml}"]
    if refs_yaml: lines.append(f"insight_ids:\n{refs_yaml}")
    lines.extend(["---", f"# Proposal: {clean_id}\n", "## Guidance\n", "\n".join(f"- {b}" for b in clean_bullets) + "\n"])
    prop_dir = WorkspaceLayout(Path(os.fspath(workspace)).resolve()).aegis_dir / "proposals"
    prop_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target := prop_dir / f"{clean_id}.md", "\n".join(lines))
    return target

def _wilson_ucb95(k: int, n: int) -> float:
    if n <= 0: return 1.0
    z, phat, z2 = 1.6448536269514722, min(1.0, max(0.0, k / n)), 2.705543454095404
    return min(1.0, round(((phat + z2 / (2.0 * n)) + z * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * n)) / n)) / (1.0 + z2 / n), 6))
def measure_recurrence(workspace: Any, rule_id: str, *, home: Optional[Path] = None, reset_on_rev_change: bool = True) -> Dict[str, Any]:
    root = Path(os.fspath(workspace)).resolve()
    if (rule := load_rules(root).get(rule_id)) is None: raise ValueError(f"unknown rule {rule_id!r}")
    cur_rev, rule_tokens = rule.digest[:16], _tokenize(f"{rule.id} {rule.meta.get('hypothesis', '')} {rule.body}")
    alive, matching = set(), []
    for idx, row in enumerate(read_insight_rows(root, home=home)):
        revs = row.get("revs") if isinstance(row.get("revs"), Mapping) else {}
        if reset_on_rev_change and revs.get(rule_id) != cur_rev: continue
        if (ev := row.get("event")) == "heartbeat": alive.add(str(row.get("hs") or f"hb-{idx}"))
        elif ev == "insight" and row.get("level") in COUNTABLE_LEVELS and _paths_overlap_rule(row.get("paths") or [], rule):
            if (itoks := _tokenize(str(row.get("text") or ""))) and rule_tokens and _cosine(*_tfidf_vectors([itoks, rule_tokens])) >= 0.12:
                matching.append(row)
    if not (n_sess := len(alive)):
        return {"rule": rule_id, "rev": cur_rev, "sessions": 0, "recurrences": 0, "rate": 0.0, "rate_ucb95": 1.0, "alarm": False, "status": "no_prompt_traffic"}
    episodes, seen_hs, last_ts = 0, set(), None
    for ins in matching:
        if isinstance(hs_val := ins.get("hs"), str) and hs_val:
            if hs_val not in seen_hs:
                seen_hs.add(hs_val)
                episodes += 1
        else:
            ts = _parse_ts(ins.get("ts"))
            if ts is not None and last_ts is not None and abs((ts - last_ts).total_seconds()) <= BURST_WINDOW_SECONDS: continue
            last_ts, episodes = ts, episodes + 1
    alarm = episodes >= RECURRENCE_ALARM_COUNT
    return {"rule": rule_id, "rev": cur_rev, "sessions": n_sess, "recurrences": episodes, "rate": round(episodes / n_sess, 6), "rate_ucb95": _wilson_ucb95(episodes, n_sess), "alarm": alarm, "status": "not_working" if alarm else "ok"}

def _host_config_path(host: str, home: Path) -> Path:
    env_var, default_dir, fname = ("CLAUDE_CONFIG_DIR", ".claude", "settings.json") if host == "claude-code" else ("CODEX_HOME", ".codex", "hooks.json")
    cfg = os.environ.get(env_var, "").strip()
    return (Path(cfg) if cfg else (home / default_dir)) / fname
def _entry_cmds(entry: Any) -> List[str]:
    if not isinstance(entry, Mapping): return []
    hooks = entry.get("hooks") if isinstance(entry.get("hooks"), list) else []
    return [str(x.get("command") or "") for x in (entry, *hooks) if isinstance(x, Mapping)]
def enable_host_hook(host: str, *, excerpts: bool = False, home: Optional[Path] = None) -> Dict[str, Any]:
    if host not in SUPPORTED_INSIGHT_HOSTS:
        raise ValueError(f"unsupported host {host!r} for insight hook; supported hosts: {list(SUPPORTED_INSIGHT_HOSTS)}")
    if (layout := _user_layout(home)) is None: raise OSError("cannot resolve user home directory")
    create_link_key(layout.home)
    target, data = _host_config_path(host, layout.home), {}
    if target.exists() and not target.is_symlink():
        try:
            if isinstance(loaded := json.loads(target.read_text(encoding="utf-8")), dict): data = loaded
        except (OSError, ValueError): pass
    cmd = f"python3 -I -m aegis_cli.hooks.insights --host {host}{' --excerpts' if excerpts else ' --no-excerpts'}"
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    data["hooks"] = hooks
    ups = hooks.get("UserPromptSubmit") if isinstance(hooks.get("UserPromptSubmit"), list) else []
    hooks["UserPromptSubmit"] = [e for e in ups if not any("aegis_cli.hooks.insights" in c for c in _entry_cmds(e))] + [{"matcher": "", "hooks": [{"type": "command", "command": cmd}]}]
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, json.dumps(data, indent=2) + "\n")
    return {"host": host, "status": "enabled_excerpts" if excerpts else "enabled_counters_only", "excerpts": bool(excerpts), "config_path": str(target), "command": cmd}
def host_capture_status(host: str, home: Optional[Path] = None) -> Dict[str, Any]:
    if host == "antigravity":
        return {"status": "explicit_only", "excerpts": False, "detail": "host provides no UserPromptSubmit prompt field; explicit capture only"}
    if host not in SUPPORTED_INSIGHT_HOSTS:
        return {"status": "unsupported", "excerpts": False, "detail": f"insight hook is not supported on {host}"}
    if (layout := _user_layout(home)) is None or not (target := _host_config_path(host, layout.home)).exists() or target.is_symlink():
        return {"status": "disabled", "excerpts": False}
    try: data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {"status": "disabled", "excerpts": False}
    ups = data.get("hooks", {}).get("UserPromptSubmit") if isinstance(data, Mapping) and isinstance(data.get("hooks"), Mapping) else None
    if not isinstance(ups, list): return {"status": "disabled", "excerpts": False}
    for cmd in (c for e in ups for c in _entry_cmds(e)):
        if "aegis_cli.hooks.insights" in cmd:
            ex = "--excerpts" in cmd and "--no-excerpts" not in cmd
            return {"status": "enabled_excerpts" if ex else "enabled_counters_only", "excerpts": ex}
    return {"status": "disabled", "excerpts": False}
