"""Content-fingerprinted in-memory rule cache for the MCP hot path."""
from __future__ import annotations

import os
import threading
from typing import Any, Iterable, Optional

from aegis_core import rule_inventory
from aegis_core.rule_inventory import RuleInventoryEntry, RuleInventoryError


class RuleCacheError(RuntimeError):
    """Rule loading failed; cached or partial results were not returned."""

    def __init__(
        self,
        operation: str,
        path: str = "",
        message: str = "",
        cause: Optional[BaseException] = None,
    ) -> None:
        self.operation = operation
        self.path = path
        self.message = message or operation
        self.cause = cause
        if path or message:
            super().__init__(f"cell cache {operation} failed for {path}: {message}")
        else:
            super().__init__(operation)


CellCacheError = RuleCacheError


class RuleCache:
    """Thread-safe parsed-rule cache keyed by canonical content fingerprint."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cells = []  # type: list[dict[str, Any]]
        self._fingerprint = None  # type: Optional[str]
        self._workspace = None  # type: Optional[str]

    @staticmethod
    def _compute_manifest_state_digest(workspace: str) -> str:
        """Compute SHA-256 of manifest.json and manifest.key if they exist."""
        import hashlib
        from aegis_core.integrity import _manifest_path, _key_path
        h = hashlib.sha256()
        manifest_path = _manifest_path(workspace)
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "rb") as f:
                    h.update(f.read())
            except OSError:
                pass
        else:
            h.update(b"no-manifest")

        key_path = _key_path(workspace)
        if os.path.isfile(key_path):
            try:
                with open(key_path, "rb") as f:
                    h.update(f.read())
            except OSError:
                pass
        else:
            h.update(b"no-key")

        return h.hexdigest()

    def get_cells(self, workspace: str) -> list[dict[str, Any]]:
        """Return rules, reparsing only when canonical inventory bytes change."""
        workspace_key = os.path.abspath(os.fspath(workspace))
        with self._lock:
            try:
                inventory = rule_inventory.inventory_rules(workspace_key)
            except RuleInventoryError as exc:
                raise RuleCacheError(
                    exc.operation, exc.path, str(exc), exc
                ) from exc

            manifest_digest = self._compute_manifest_state_digest(workspace_key)
            composite_fingerprint = f"{inventory.fingerprint}:{manifest_digest}"

            if (
                self._workspace == workspace_key
                and self._fingerprint == composite_fingerprint
            ):
                return self._cells

            cells = self._load(workspace_key, inventory.entries)
            self._cells = cells
            self._fingerprint = composite_fingerprint
            self._workspace = workspace_key
            return self._cells

    get_rules = get_cells

    def invalidate(self) -> None:
        """Force parsing on the next successful inventory."""
        with self._lock:
            self._fingerprint = None
            self._workspace = None

    @staticmethod
    def _load(
        workspace: str,
        entries: Iterable[RuleInventoryEntry],
    ) -> list[dict[str, Any]]:
        """Parse the exact bytes already captured by canonical inventory."""
        from aegis_mcp.jit_engine import parse_frontmatter, _get_body, warn

        cells = []
        for entry in entries:
            if os.path.basename(entry.relative_path) == "README.md":
                continue
            try:
                content = entry.content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CellCacheError(
                    "decode", entry.absolute_path, str(exc), exc
                ) from exc
            try:
                fm = parse_frontmatter(content)
            except Exception as exc:
                raise CellCacheError(
                    "parse", entry.absolute_path, str(exc), exc
                ) from exc
            if fm is None:
                warn(
                    f"skipped cell {entry.relative_path}: "
                    "malformed YAML frontmatter"
                )
                continue
            if not fm:
                warn(f"skipped cell {entry.relative_path}: no frontmatter metadata")
                continue
            if fm.get("expired_at"):
                continue
            fm["_name"] = os.path.splitext(os.path.basename(entry.absolute_path))[0]
            fm["_path"] = entry.relative_path
            fm["_body"] = _get_body(content)
            fm["_full"] = content
            cells.append(fm)

        CellCache._verify_integrity(workspace)
        return cells

    @staticmethod
    def _verify_integrity(workspace: str) -> None:
        """Preserve optional manifest diagnostics without affecting cell bytes."""
        from aegis_mcp.jit_engine import warn

        try:
            from aegis_core.integrity import (
                _manifest_path,
                load_manifest,
                verify_manifest,
                load_key,
                verify_signature,
            )
            manifest_path = _manifest_path(workspace)
            cells_dir = os.path.dirname(manifest_path)
            key = load_key(workspace)
            manifest = load_manifest(workspace)
            if key is None and manifest is None:
                return
            if key is not None and manifest is None:
                raise CellCacheError(
                    "integrity",
                    manifest_path,
                    "missing manifest.json while HMAC key is configured",
                )
            if manifest is not None:
                issues = list(verify_manifest(cells_dir, manifest))
                for issue in issues:
                    warn(f"integrity: {issue['type']} — {issue['detail']}")
                if key is not None:
                    if issues:
                        raise CellCacheError(
                            "integrity",
                            cells_dir,
                            f"cell file integrity verification failed: {issues[0]['detail']}",
                        )
                    if "signature" not in manifest:
                        raise CellCacheError(
                            "integrity",
                            manifest_path,
                            "missing HMAC signature while HMAC key is configured",
                        )
                    if verify_signature(manifest, key):
                        warn("integrity: HMAC signature verified ✓")
                    else:
                        raise CellCacheError(
                            "integrity",
                            manifest_path,
                            "HMAC signature verification FAILED — manifest may be tampered",
                        )
        except RuleCacheError:
            raise
        except Exception as exc:
            if key is not None:
                raise RuleCacheError(
                    "integrity",
                    manifest_path,
                    f"HMAC integrity verification failed unexpectedly: {exc}",
                ) from exc
            warn(f"integrity check failed (non-fatal): {exc}")


CellCache = RuleCache

__all__ = [
    "RuleCache",
    "RuleCacheError",
    "CellCache",
    "CellCacheError",
]

