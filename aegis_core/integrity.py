"""Rule integrity verification and HMAC-SHA256 signing.

Provides hash-based integrity checking for governance rules. A manifest file
(``.aegis/rules/manifest.json``) stores SHA-256 hashes of all known rules.
During rule loading, hashes are verified to detect tampering or unauthorized
additions.

Key management uses HMAC-SHA256 with a locally stored secret key
(``.aegis/keys/manifest.key``). The key is generated once and used to sign
manifests, providing tamper-evident verification without external dependencies.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from aegis_core.workspace.layout import WorkspaceLayout


_MANIFEST_FILENAME = "manifest.json"


def _hash_file(filepath: str) -> str:
    """Return the SHA-256 hex digest of a file's contents."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def generate_manifest(rules_dir: str | Path) -> dict:
    """Generate a SHA-256 manifest of all rules under ``rules_dir``.

    Returns::

        {
            "cells": {"relative/path.md": "sha256:abc123...", ...},
            "rules": {"relative/path.md": "sha256:abc123...", ...},
            "generated_at": "2026-10-01T19:00:00Z",
            "cell_count": 42,
            "rule_count": 42,
        }
    """
    rules_dir_str = str(rules_dir)
    cells = {}
    if not os.path.isdir(rules_dir_str):
        return {
            "cells": cells,
            "rules": dict(cells),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cell_count": 0,
            "rule_count": 0,
        }

    for dirpath, _dirnames, filenames in os.walk(rules_dir_str):
        for fn in filenames:
            if not fn.endswith(".md") or fn == "README.md":
                continue
            if fn == _MANIFEST_FILENAME:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, rules_dir_str).replace("\\", "/")
            cells[rel] = _hash_file(full)

    return {
        "cells": cells,
        "rules": dict(cells),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cell_count": len(cells),
        "rule_count": len(cells),
    }


def _hash_file_lf_normalized(filepath: str) -> str:
    """Return the SHA-256 hex digest of a file with CRLF normalized to LF."""
    with open(filepath, "rb") as f:
        data = f.read().replace(b"\r\n", b"\n")
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def verify_manifest(rules_dir: str | Path, manifest: dict) -> list:
    """Verify rules against a manifest.

    Returns a list of issue dicts, each with keys:
    - ``type``: one of ``"added"``, ``"modified"``, ``"removed"``
    - ``path``: the relative rule path
    - ``detail``: human-readable description

    An empty list means all rules match the manifest.
    """
    if not isinstance(manifest, dict):
        raise ValueError(f"Manifest must be a JSON object, got {type(manifest).__name__}")
    issues = []
    raw_known = manifest.get("cells") if "cells" in manifest else manifest.get("rules", {})
    if not isinstance(raw_known, dict):
        raw_known = {}
    known_cells = {str(k).replace("\\", "/"): v for k, v in raw_known.items()}
    rules_dir_str = str(rules_dir)

    # Discover current rules on disk
    current_cells = {}
    current_files = {}
    if os.path.isdir(rules_dir_str):
        for dirpath, _dirnames, filenames in os.walk(rules_dir_str):
            for fn in filenames:
                if not fn.endswith(".md") or fn == "README.md":
                    continue
                if fn == _MANIFEST_FILENAME:
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, rules_dir_str).replace("\\", "/")
                current_cells[rel] = _hash_file(full)
                current_files[rel] = full

    # Check for added rules (on disk but not in manifest)
    for rel in sorted(current_cells):
        if rel not in known_cells:
            issues.append({
                "type": "added",
                "path": rel,
                "detail": f"rule not in manifest (unknown origin): {rel}",
            })

    # Check for modified rules (hash mismatch)
    for rel in sorted(current_cells):
        if rel in known_cells and current_cells[rel] != known_cells[rel]:
            if _hash_file_lf_normalized(current_files[rel]) == known_cells[rel]:
                continue
            issues.append({
                "type": "modified",
                "path": rel,
                "detail": f"rule hash mismatch (content changed): {rel}",
            })

    # Check for removed rules (in manifest but not on disk)
    for rel in sorted(known_cells):
        if rel not in current_cells:
            issues.append({
                "type": "removed",
                "path": rel,
                "detail": f"rule in manifest but missing from disk: {rel}",
            })

    return issues


# ── Key Management ────────────────────────────────────────────────────

_KEY_DIR = "keys"
_KEY_FILENAME = "manifest.key"


def _key_path(workspace: str | Path) -> str:
    """Return the path to .aegis/keys/manifest.key."""
    return str(WorkspaceLayout(Path(workspace)).manifest_key_file)


def generate_key(workspace: str | Path) -> str:
    """Generate a 256-bit HMAC key and store it in .aegis/keys/manifest.key.

    Returns the key file path. Raises FileExistsError if a key already exists
    (prevents accidental key rotation — use ``rotate_key`` instead).
    """
    path = _key_path(workspace)
    if os.path.isfile(path):
        raise FileExistsError(f"HMAC key already exists: {path}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    key_hex = secrets.token_hex(32)  # 256-bit key
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    with open(fd, "w", encoding="utf-8") as f:
        f.write(key_hex + "\n")
    return path


def load_key(workspace: str | Path) -> bytes | None:
    """Load the HMAC key from .aegis/keys/manifest.key.

    Returns the key as bytes, or None if no key file exists
    (graceful degradation for unsigned workflows).
    """
    path = _key_path(workspace)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            key_hex = f.read().strip()
        return bytes.fromhex(key_hex)
    except (OSError, ValueError) as exc:
        _warn(f"failed to load HMAC key: {exc}")
        return None


def rotate_key(workspace: str | Path) -> str:
    """Force-rotate the HMAC key. Backs up the old key as manifest.key.bak.

    Returns the new key file path. After rotation, existing manifests
    will fail signature verification until re-signed.
    """
    path = _key_path(workspace)
    if os.path.isfile(path):
        bak = path + ".bak"
        os.replace(path, bak)
    return generate_key(workspace)


# ── Manifest Signing ─────────────────────────────────────────────────


def _canonical_cells_json(manifest: dict) -> bytes:
    """Produce a deterministic JSON encoding of the cells dict for signing."""
    mapping = manifest.get("cells") if "cells" in manifest else manifest.get("rules", {})
    return json.dumps(mapping if isinstance(mapping, dict) else {}, sort_keys=True).encode("utf-8")


def sign_manifest(manifest: dict, key: bytes) -> str:
    """Compute HMAC-SHA256 of the canonical manifest cells JSON.

    Only the ``cells`` dict is signed (not metadata like ``generated_at``).
    Returns the hex digest string.
    """
    return hmac.new(key, _canonical_cells_json(manifest), hashlib.sha256).hexdigest()


def verify_signature(manifest: dict, key: bytes) -> bool:
    """Verify the manifest signature against the stored HMAC.

    Returns True if the signature matches, False if mismatch or missing.
    Uses ``hmac.compare_digest`` on UTF-8 bytes for constant-time comparison.
    """
    stored_sig = manifest.get("signature")
    if not stored_sig or not isinstance(stored_sig, str):
        return False
    expected = sign_manifest(manifest, key)
    return hmac.compare_digest(stored_sig.encode("utf-8"), expected.encode("utf-8"))


# ── Manifest I/O ─────────────────────────────────────────────────────


def _manifest_path(workspace: str | Path) -> str:
    """Return the path to .aegis/rules/manifest.json."""
    return str(WorkspaceLayout(Path(workspace)).manifest_file)


def load_manifest(workspace: str | Path) -> dict | None:
    """Load the rule manifest from ``.aegis/rules/manifest.json``.

    Returns None if the manifest file does not exist.
    """
    manifest_path = _manifest_path(workspace)
    if not os.path.isfile(manifest_path):
        return None
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        _warn(f"failed to load manifest: {exc}")
        return None


def save_manifest(workspace: str | Path, manifest: dict) -> None:
    """Save a manifest to ``.aegis/rules/manifest.json``.

    If an HMAC key exists, the manifest is automatically signed before saving.
    """
    key = load_key(workspace)
    if key is not None:
        manifest["signature"] = sign_manifest(manifest, key)
    manifest_path = _manifest_path(workspace)
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    from aegis_core.storage import atomic_write_bytes
    atomic_write_bytes(manifest_path, manifest_bytes)


def sync_manifest_if_present(workspace: str | Path) -> dict | None:
    """Regenerate and save .aegis/rules/manifest.json if it exists and has no HMAC key mismatch."""
    manifest_path = _manifest_path(workspace)
    if not os.path.isfile(manifest_path):
        return None
    existing = load_manifest(workspace)
    key = load_key(workspace)
    if key is not None and existing is not None:
        if "signature" not in existing or not verify_signature(existing, key):
            return None
    rules_dir = os.path.dirname(manifest_path)
    manifest = generate_manifest(rules_dir)
    save_manifest(workspace, manifest)
    return manifest


def _warn(message: str) -> None:
    """Emit a diagnostic on stderr (stdout is the JSON-RPC transport)."""
    try:
        print(f"[aegis-integrity] {message}", file=sys.stderr, flush=True)
    except Exception:
        pass


__all__ = [
    "generate_manifest",
    "verify_manifest",
    "generate_key",
    "load_key",
    "rotate_key",
    "sign_manifest",
    "verify_signature",
    "load_manifest",
    "save_manifest",
    "sync_manifest_if_present",
]

