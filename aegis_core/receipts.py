from __future__ import annotations

import secrets
import json
import os
import time
import threading
import hashlib
import hmac
from pathlib import Path
from typing import Dict, Any, Iterable, List, Optional

from aegis_core.rule_inventory import inventory_cells
from aegis_core.workspace import Workspace, confine_path


def _normalize_workspace_str(workspace: Any) -> str:
    """Canonicalize a workspace argument to an absolute string path."""
    if isinstance(workspace, Workspace):
        return str(workspace.root)
    if isinstance(workspace, (str, Path, os.PathLike)):
        return str(Path(os.fspath(workspace)).resolve())
    return str(workspace)

# Argument keys that name workspace files a tool will read or act on. A receipt
# binds the content of each of these, so editing a target between issuance and
# redemption makes the receipt stale.
TARGET_PATH_KEYS = ("file_path", "files", "context_files")

# Client-supplied keys the server owns. They are stripped before hashing and
# dispatch; "workspace" is re-injected from the operator-configured value.
SERVER_OWNED_KEYS = ("workspace", "receipt", "_sessionToken")

MAX_RECEIPTS = 1000
DEFAULT_TTL_SECONDS = 3600.0  # 1 hour


class ReceiptStore:
    """Thread-safe encapsulated storage for receipts with TTL and capacity pruning."""

    def __init__(
        self,
        max_receipts: int = MAX_RECEIPTS,
        default_ttl: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.max_receipts = max_receipts
        self.default_ttl = default_ttl
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

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
        cell_digest: str,
        ttl_seconds: Optional[float] = None,
    ) -> str:
        """Issue an opaque, stateful, session-bound receipt."""
        receipt_id = secrets.token_hex(32)
        now = time.time()
        canonical_workspace = _normalize_workspace_str(workspace)
        data = {
            "session_id": session_id,
            "workspace": canonical_workspace,
            "operation": operation,
            "args_hash": _hash_args(args),
            "file_digest": file_digest,
            "cell_digest": cell_digest,
            "created_at": now,
            "expires_at": (now + ttl_seconds) if ttl_seconds is not None else (now + self.default_ttl),
        }
        with self._lock:
            self.prune_expired(now)
            self._store[receipt_id] = data
        return receipt_id

    def verify(
        self,
        receipt_id: str,
        session_id: str,
        workspace: str | Path | os.PathLike[str] | Workspace,
        operation: str,
        args: Dict[str, Any],
        file_digest: str,
        cell_digest: str,
        consume: bool = True,
    ) -> bool:
        """Verify and optionally consume a receipt."""
        if not isinstance(receipt_id, str):
            return False

        with self._lock:
            self.prune_expired(time.time())
            stored = self._store.pop(receipt_id, None) if consume else self._store.get(receipt_id)
            if stored is None:
                return False

            if stored.get("expires_at") is not None and time.time() > stored["expires_at"]:
                return False

            if (
                not isinstance(session_id, str)
                or not isinstance(workspace, (str, Path, os.PathLike, Workspace))
                or not isinstance(operation, str)
                or not isinstance(file_digest, str)
                or not isinstance(cell_digest, str)
                or not isinstance(args, dict)
            ):
                return False

            canonical_workspace = _normalize_workspace_str(workspace)

            try:
                return (
                    _safe_compare(stored["session_id"], session_id) and
                    _safe_compare(stored["workspace"], canonical_workspace) and
                    _safe_compare(stored["operation"], operation) and
                    _safe_compare(stored["args_hash"], _hash_args(args)) and
                    _safe_compare(stored["file_digest"], file_digest) and
                    _safe_compare(stored["cell_digest"], cell_digest)
                )
            except Exception:
                return False

    def clear(self) -> None:
        """Clear all receipts (simulates process restart invalidation)."""
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


_default_store = ReceiptStore(max_receipts=MAX_RECEIPTS, default_ttl=DEFAULT_TTL_SECONDS)
_receipt_store: Dict[str, Dict[str, Any]] = _default_store._store
_receipt_lock = _default_store._lock


def _prune_expired_locked(now: float) -> None:
    _default_store.prune_expired(now)


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


def compute_cell_digest(workspace: str | Path | os.PathLike[str] | Workspace) -> str:
    """Return the canonical aggregate fingerprint of governance cell bytes."""
    ws_root = workspace.root if isinstance(workspace, Workspace) else Path(os.fspath(workspace)).resolve()
    return inventory_cells(str(ws_root)).fingerprint


def issue_receipt(
    session_id: str,
    workspace: str | Path | os.PathLike[str] | Workspace,
    operation: str,
    args: Dict[str, Any],
    file_digest: str,
    cell_digest: str,
    ttl_seconds: Optional[float] = None,
) -> str:
    """Issue an opaque, stateful, session-bound receipt."""
    return _default_store.issue(
        session_id=session_id,
        workspace=workspace,
        operation=operation,
        args=args,
        file_digest=file_digest,
        cell_digest=cell_digest,
        ttl_seconds=ttl_seconds,
    )


def verify_receipt(
    receipt_id: str,
    session_id: str,
    workspace: str | Path | os.PathLike[str] | Workspace,
    operation: str,
    args: Dict[str, Any],
    file_digest: str,
    cell_digest: str,
    consume: bool = True,
) -> bool:
    """Verify and optionally consume a receipt."""
    return _default_store.verify(
        receipt_id=receipt_id,
        session_id=session_id,
        workspace=workspace,
        operation=operation,
        args=args,
        file_digest=file_digest,
        cell_digest=cell_digest,
        consume=consume,
    )


def clear_receipts() -> None:
    """Clear all receipts (simulates process restart invalidation)."""
    _default_store.clear()


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "MAX_RECEIPTS",
    "SERVER_OWNED_KEYS",
    "TARGET_PATH_KEYS",
    "ReceiptStore",
    "clear_receipts",
    "compute_cell_digest",
    "compute_file_digest",
    "issue_receipt",
    "strip_server_owned",
    "target_paths",
    "verify_receipt",
]

