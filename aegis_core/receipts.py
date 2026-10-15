from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Set

from aegis_core.errors import ReceiptExpiredError
from aegis_core.locking import workspace_lock
from aegis_core.rule_inventory import inventory_rules
from aegis_core.storage import Storage
from aegis_core.taxonomy import DEFAULT_RECEIPT_TTL_SECONDS
from aegis_core.workspace import Workspace, confine_path
from aegis_core.workspace.layout import LockResource, WorkspaceLayout


class ReceiptVerificationError(ValueError):
    """Raised when a receipt fails verification, HMAC validation, or is already consumed."""


def _normalize_workspace_str(workspace: Any) -> str:
    """Canonicalize a workspace argument to an absolute string path."""
    if isinstance(workspace, Workspace):
        return str(workspace.root)
    if isinstance(workspace, (str, Path, os.PathLike)):
        return str(Path(os.fspath(workspace)).resolve())
    return str(workspace)


def _resolve_workspace_dir(workspace: Any) -> Optional[Path]:
    """Return the resolved Path if workspace refers to an existing governed (.aegis) directory on disk."""
    try:
        if isinstance(workspace, Workspace):
            p = workspace.root
        elif isinstance(workspace, (str, Path, os.PathLike)):
            raw = str(os.fspath(workspace)).strip()
            if not raw or raw == "/":
                return None
            p = Path(raw)
            if not p.exists():
                return None
            p = p.resolve()
        else:
            return None
        if p == Path("/") or not p.is_dir():
            return None
        return p if (p / ".aegis").is_dir() else None
    except OSError:
        return None


# Argument keys that name workspace files a tool will read or act on. A receipt
# binds the content of each of these, so editing a target between issuance and
# redemption makes the receipt stale.
TARGET_PATH_KEYS = ("file_path", "files", "context_files")

# Client-supplied keys the server owns. They are stripped before hashing and
# dispatch; "workspace" is re-injected from the operator-configured value.
SERVER_OWNED_KEYS = ("workspace", "receipt", "_sessionToken")

MAX_RECEIPTS = 1000
DEFAULT_TTL_SECONDS = float(DEFAULT_RECEIPT_TTL_SECONDS)


class ReceiptManager:
    """Thread- and process-safe manager for burn-first single-use HMAC receipts."""

    def __init__(
        self,
        workspace: str | Path | os.PathLike[str] | Workspace | None = None,
        max_receipts: int = MAX_RECEIPTS,
        default_ttl: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.max_receipts = max_receipts
        self.default_ttl = default_ttl
        self._workspace = workspace
        ws_dir = _resolve_workspace_dir(workspace) if workspace is not None else None
        self._storage: Optional[Storage] = Storage(ws_dir) if ws_dir is not None else None
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._ephemeral_key: bytes = secrets.token_bytes(32)
        self._known_ledgers: Set[Path] = set()

    @property
    def _key(self) -> bytes:
        return self._get_hmac_key(self._storage)

    def _get_storage_for(self, workspace: Any) -> Optional[Storage]:
        if self._storage is not None:
            return self._storage
        ws_dir = _resolve_workspace_dir(workspace)
        if ws_dir is not None:
            return Storage(ws_dir)
        return None

    def _get_hmac_key(self, storage: Optional[Storage]) -> bytes:
        if storage is None:
            return self._ephemeral_key
        legacy_key_file = storage.layout.aegis_dir / "receipt_key"
        key_file = storage.layout.keys_dir / "receipt.key"
        try:
            if legacy_key_file.is_file():
                raw = legacy_key_file.read_bytes().strip()
                if raw:
                    return raw
            if key_file.is_file():
                raw = key_file.read_bytes().strip()
                if len(raw) >= 32:
                    return raw
            key_file.parent.mkdir(parents=True, exist_ok=True)
            new_key = secrets.token_hex(32).encode("ascii")
            storage.write_atomic(key_file, new_key.decode("ascii"))
            return new_key
        except OSError:
            return self._ephemeral_key

    @staticmethod
    def _compute_hmac(key: bytes, payload: Dict[str, Any]) -> str:
        canonical = "|".join(
            str(payload.get(k, ""))
            for k in (
                "nonce",
                "session_id",
                "workspace",
                "operation",
                "args_hash",
                "file_digest",
                "rule_digest",
                "created_at",
                "expires_at",
            )
        )
        return hmac.new(
            key,
            canonical.encode("utf-8", errors="surrogatepass"),
            hashlib.sha256,
        ).hexdigest()

    def _compact_ledger_locked(self, storage: Storage, now: float) -> Dict[str, Dict[str, Any]]:
        """Compact expired records from .aegis/receipts.jsonl while retaining unexpired consumed nonces."""
        ledger_path = storage.layout.receipts_file
        self._known_ledgers.add(ledger_path)
        records = storage.read_jsonl(ledger_path)
        if not records:
            return {}

        effective_max = min(self.max_receipts, MAX_RECEIPTS)
        by_id: Dict[str, Dict[str, Any]] = {}
        consumed_ids: Dict[str, Dict[str, Any]] = {}

        for rec in records:
            rid = rec.get("receipt_id") or rec.get("nonce")
            if not isinstance(rid, str):
                continue
            exp = rec.get("expires_at")
            if exp is not None and now > float(exp):
                by_id.pop(rid, None)
                consumed_ids.pop(rid, None)
                continue
            if rec.get("status") == "consumed":
                consumed_ids[rid] = rec
                by_id.pop(rid, None)
            elif rid not in consumed_ids:
                by_id[rid] = rec

        if len(by_id) > effective_max:
            sorted_issued = sorted(
                by_id.items(),
                key=lambda item: float(item[1].get("created_at", 0.0)),
            )
            for rid, _ in sorted_issued[: len(by_id) - effective_max]:
                by_id.pop(rid, None)

        kept_lines = [
            json.dumps(rec, sort_keys=True)
            for rec in list(by_id.values()) + list(consumed_ids.values())
        ]
        try:
            content = ("\n".join(kept_lines) + "\n") if kept_lines else ""
            storage.write_atomic(ledger_path, content)
        except OSError:
            pass

        merged: Dict[str, Dict[str, Any]] = {}
        merged.update(by_id)
        merged.update(consumed_ids)
        return merged

    def prune_expired(self, now: Optional[float] = None) -> None:
        """Evict expired receipts and enforce max_receipts cap."""
        current_time = time.time() if now is None else now
        effective_max = min(self.max_receipts, MAX_RECEIPTS)
        with self._lock:
            expired = [
                rid for rid, data in self._store.items()
                if data.get("expires_at") is not None and current_time > data["expires_at"]
            ]
            for rid in expired:
                self._store.pop(rid, None)

            if len(self._store) >= effective_max:
                sorted_by_age = sorted(
                    self._store.items(),
                    key=lambda item: item[1].get("created_at", 0)
                )
                to_evict = len(self._store) - effective_max + 1
                for rid, _ in sorted_by_age[:to_evict]:
                    self._store.pop(rid, None)

    def issue(
        self,
        session_id: str,
        workspace: str | Path | os.PathLike[str] | Workspace,
        operation: str,
        args: Dict[str, Any],
        file_digest: str,
        rule_digest: str = "",
        ttl_seconds: Optional[float] = None,
        *,
        cell_digest: Optional[str] = None,
    ) -> str:
        """Issue an opaque, stateful, session-bound HMAC receipt."""
        effective_rule_digest = cell_digest if cell_digest is not None else rule_digest
        receipt_id = secrets.token_hex(32)
        now = time.time()
        canonical_workspace = _normalize_workspace_str(workspace)
        expires_at = (now + ttl_seconds) if ttl_seconds is not None else (now + self.default_ttl)
        args_hash = _hash_args(args)

        storage = self._get_storage_for(workspace)
        key = self._get_hmac_key(storage)

        data: Dict[str, Any] = {
            "receipt_id": receipt_id,
            "nonce": receipt_id,
            "status": "issued",
            "session_id": session_id,
            "workspace": canonical_workspace,
            "operation": operation,
            "args_hash": args_hash,
            "file_digest": file_digest,
            "rule_digest": effective_rule_digest,
            "cell_digest": effective_rule_digest,
            "created_at": now,
            "expires_at": expires_at,
        }
        data["hmac"] = self._compute_hmac(key, data)

        with self._lock:
            self.prune_expired(now)
            self._store[receipt_id] = data
            if storage is not None:
                with workspace_lock(storage.layout.root, LockResource.RECEIPTS):
                    self._compact_ledger_locked(storage, now)
                    storage.append_jsonl(storage.layout.receipts_file, data)
                    self._known_ledgers.add(storage.layout.receipts_file)
        return receipt_id

    def verify(
        self,
        receipt_id: str,
        session_id: str,
        workspace: str | Path | os.PathLike[str] | Workspace,
        operation: str,
        args: Dict[str, Any],
        file_digest: str,
        rule_digest: str = "",
        consume: bool = True,
        *,
        cell_digest: Optional[str] = None,
    ) -> bool:
        """Verify and optionally consume a receipt using Burn-First Single-Use semantics."""
        if not isinstance(receipt_id, str) or not receipt_id:
            return False

        effective_rule_digest = cell_digest if cell_digest is not None else rule_digest
        now = time.time()
        storage = self._get_storage_for(workspace)

        with self._lock:
            self.prune_expired(now)
            stored = self._store.get(receipt_id)

            if storage is not None:
                with workspace_lock(storage.layout.root, LockResource.RECEIPTS):
                    ledger_state = self._compact_ledger_locked(storage, now)
                    ledger_rec = ledger_state.get(receipt_id)
                    if ledger_rec is not None:
                        if ledger_rec.get("status") == "consumed":
                            return False
                        if stored is None:
                            stored = ledger_rec
                    if stored is None:
                        return False

                    # Step 1: Verify timestamp expiry and HMAC before burning or comparing
                    if stored.get("expires_at") is not None and now > float(stored["expires_at"]):
                        return False

                    key = self._get_hmac_key(storage)
                    expected_hmac = self._compute_hmac(key, stored)
                    if not _safe_compare(stored.get("hmac", ""), expected_hmac):
                        return False

                    # Step 2: BURN BEFORE COMPARE — persist consumed nonce immediately
                    if consume:
                        self._store.pop(receipt_id, None)
                        burn_record = {
                            "receipt_id": receipt_id,
                            "nonce": receipt_id,
                            "status": "consumed",
                            "consumed_at": now,
                            "expires_at": stored.get("expires_at"),
                        }
                        storage.append_jsonl(storage.layout.receipts_file, burn_record)
                        self._known_ledgers.add(storage.layout.receipts_file)
            else:
                if stored is None:
                    return False
                if stored.get("expires_at") is not None and now > float(stored["expires_at"]):
                    return False
                key = self._get_hmac_key(None)
                expected_hmac = self._compute_hmac(key, stored)
                if not _safe_compare(stored.get("hmac", ""), expected_hmac):
                    return False
                if consume:
                    self._store.pop(receipt_id, None)

            # Step 3: Compare bound parameters only AFTER the receipt has been burned
            if (
                not isinstance(session_id, str)
                or not isinstance(workspace, (str, Path, os.PathLike, Workspace))
                or not isinstance(operation, str)
                or not isinstance(file_digest, str)
                or not isinstance(effective_rule_digest, str)
                or not isinstance(args, dict)
            ):
                return False

            canonical_workspace = _normalize_workspace_str(workspace)
            stored_rule_digest = stored.get("rule_digest", stored.get("cell_digest", ""))

            try:
                return (
                    _safe_compare(stored["session_id"], session_id)
                    and _safe_compare(stored["workspace"], canonical_workspace)
                    and _safe_compare(stored["operation"], operation)
                    and _safe_compare(stored["args_hash"], _hash_args(args))
                    and _safe_compare(stored["file_digest"], file_digest)
                    and _safe_compare(stored_rule_digest, effective_rule_digest)
                )
            except Exception:
                return False

    def clear(self) -> None:
        """Clear all receipts (simulates process restart invalidation)."""
        with self._lock:
            self._store.clear()
            for ledger_path in list(self._known_ledgers):
                try:
                    if ledger_path.is_file():
                        ledger_path.unlink()
                except OSError:
                    pass
            self._known_ledgers.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


ReceiptStore = ReceiptManager

_default_store = ReceiptManager(max_receipts=MAX_RECEIPTS, default_ttl=DEFAULT_TTL_SECONDS)
_receipt_store: Dict[str, Dict[str, Any]] = _default_store._store
_receipt_lock = _default_store._lock


def _hash_args(args: Dict[str, Any]) -> str:
    """Consistently hash a dictionary of arguments."""
    try:
        serialized = json.dumps(args, sort_keys=True, default=str)
    except Exception:
        try:
            serialized = str(sorted(args.items(), key=lambda x: str(x[0])))
        except Exception:
            serialized = str(args)
    return hashlib.sha256(serialized.encode("utf-8", errors="surrogatepass")).hexdigest()


def strip_server_owned(args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a copy of client arguments without server-owned keys."""
    if not isinstance(args, dict):
        return {}
    return {k: v for k, v in args.items() if k not in SERVER_OWNED_KEYS}


def target_paths(args: Dict[str, Any]) -> List[str]:
    """Collect the workspace file paths named by a tool's arguments."""
    found = []
    for key in TARGET_PATH_KEYS:
        value = args.get(key)
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, (list, tuple)):
            found.extend(v for v in value if isinstance(v, str))
    return sorted(set(p for p in found if p))


def _safe_compare(a: Any, b: Any) -> bool:
    """Safely compare two strings or byte sequences in constant time without non-ASCII crash."""
    if not isinstance(a, (str, bytes)) or not isinstance(b, (str, bytes)):
        return False
    try:
        a_bytes = a.encode("utf-8", errors="surrogatepass") if isinstance(a, str) else a
        b_bytes = b.encode("utf-8", errors="surrogatepass") if isinstance(b, str) else b
        return hmac.compare_digest(a_bytes, b_bytes)
    except Exception:
        return False


def _confined(workspace: str | Path | os.PathLike[str] | Workspace, rel_or_abs: str) -> str:
    """Resolve a path and require it to stay inside the workspace using single-authority confinement."""
    if isinstance(workspace, Workspace):
        resolved, _ = workspace.confine_path(rel_or_abs)
        return resolved
    resolved, _ = confine_path(rel_or_abs, workspace)
    return resolved


def compute_file_digest(
    workspace: str | Path | os.PathLike[str] | Workspace,
    paths: Iterable[str],
) -> str:
    """sha256 over (path, content) for every target path.

    Missing files are bound as missing, so creating one later also makes the
    receipt stale. Raises ValueError for paths outside the workspace.
    """
    ws_root = workspace.root if isinstance(workspace, Workspace) else Path(os.fspath(workspace)).resolve()
    seen = set()
    canonical_items = []
    for p in paths:
        resolved = _confined(workspace, p)
        canonical_rel = Path(resolved).resolve().relative_to(ws_root).as_posix()
        if canonical_rel not in seen:
            seen.add(canonical_rel)
            canonical_items.append((canonical_rel, resolved))
    canonical_items.sort(key=lambda x: x[0])

    h = hashlib.sha256(b"soma-file-digest-v1\0")
    if not canonical_items:
        if ws_root.is_dir() and (ws_root / ".git").exists():
            try:
                head_res = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(ws_root),
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                status_res = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=str(ws_root),
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if status_res.returncode == 0:
                    head_str = head_res.stdout.strip() if head_res.returncode == 0 else "NO_HEAD"
                    git_state = f"{head_str}\n{status_res.stdout}"
                    h.update(b"git-working-tree\0" + git_state.encode("utf-8") + b"\0")
            except Exception:
                pass
        return h.hexdigest()

    for rel_posix, resolved in canonical_items:
        h.update(rel_posix.encode("utf-8") + b"\0")
        if os.path.isfile(resolved):
            try:
                with open(resolved, "rb") as f:
                    fh = hashlib.sha256()
                    while chunk := f.read(65536):
                        fh.update(chunk)
                    h.update(fh.digest())
            except OSError:
                h.update(b"<missing>")
        else:
            h.update(b"<missing>")
        h.update(b"\0")
    return h.hexdigest()


def compute_rule_digest(workspace: str | Path | os.PathLike[str] | Workspace) -> str:
    """Return the canonical aggregate fingerprint of governance rule bytes."""
    ws_root = workspace.root if isinstance(workspace, Workspace) else Path(os.fspath(workspace)).resolve()
    return inventory_rules(str(ws_root)).fingerprint


compute_cell_digest = compute_rule_digest


def issue_receipt(
    session_id: str,
    workspace: str | Path | os.PathLike[str] | Workspace,
    operation: str,
    args: Dict[str, Any],
    file_digest: str,
    rule_digest: str = "",
    ttl_seconds: Optional[float] = None,
    *,
    cell_digest: Optional[str] = None,
) -> str:
    """Issue an opaque, stateful, session-bound receipt."""
    return _default_store.issue(
        session_id=session_id,
        workspace=workspace,
        operation=operation,
        args=args,
        file_digest=file_digest,
        rule_digest=cell_digest if cell_digest is not None else rule_digest,
        ttl_seconds=ttl_seconds,
    )


def verify_receipt(
    receipt_id: str,
    session_id: str,
    workspace: str | Path | os.PathLike[str] | Workspace,
    operation: str,
    args: Dict[str, Any],
    file_digest: str,
    rule_digest: str = "",
    consume: bool = True,
    *,
    cell_digest: Optional[str] = None,
) -> bool:
    """Verify and optionally consume a receipt."""
    return _default_store.verify(
        receipt_id=receipt_id,
        session_id=session_id,
        workspace=workspace,
        operation=operation,
        args=args,
        file_digest=file_digest,
        rule_digest=cell_digest if cell_digest is not None else rule_digest,
        consume=consume,
    )


def clear_receipts() -> None:
    """Clear all receipts (simulates process restart invalidation)."""
    _default_store.clear()


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "MAX_RECEIPTS",
    "ReceiptExpiredError",
    "ReceiptManager",
    "ReceiptStore",
    "ReceiptVerificationError",
    "SERVER_OWNED_KEYS",
    "TARGET_PATH_KEYS",
    "clear_receipts",
    "compute_cell_digest",
    "compute_file_digest",
    "compute_rule_digest",
    "issue_receipt",
    "strip_server_owned",
    "target_paths",
    "verify_receipt",
]

