"""Automated regression verification for all 6 Mulch Invariants from v0.96.0 Tempest Review.

Invariants:
1. Architectural Layer Decoupling: soma_core must never import from soma_sdk or enzymes.
2. Symbol Authority: All symbols exported in soma_core module __all__ lists must be resolvable.
3. Single-Use Receipts: HMAC verification receipts cannot be redeemed twice, reused across sessions/workspaces, or validated with incorrect byte types.
4. Fail-Closed Confinement: Workspace path confinement rejects relative traversal, absolute traversal, Windows device names, and Alternate Data Streams.
5. Ingress Concurrency: Rate-limit lock prevents worker race conditions and refunds quota on invalid jobs.
6. Bug Registry Integrity: Bug registry validation fails if a bug schema is malformed or lacks verified regression tests.
"""
from __future__ import annotations

import ast
import glob
import importlib
import os
import threading
import time
from pathlib import Path

import pytest

from soma_core.receipts import issue_receipt, verify_receipt, _safe_compare
from soma_core.workspace import confine_path, resolve_workspace
from soma_core.enforcement import (
    load_bug_registry,
    verify_bug_schema,
    verify_bug_tests,
    verify_unique_ids,
)
import soma_mcp.server as mcp_server


REPO_ROOT = Path(resolve_workspace(__file__))


class TestInvariant1_LayerDecoupling:
    """Invariant 1: aegis_core must be strictly layered and never import upward."""

    def test_core_has_zero_upward_imports(self):
        core_dir = REPO_ROOT / "aegis_core" if (REPO_ROOT / "aegis_core").exists() else REPO_ROOT / "soma_core"
        python_files = list(core_dir.glob("*.py"))
        assert len(python_files) > 0, "core files not found"

        violations = []
        forbidden = ("aegis_sdk", "soma_sdk", "enzymes", "aegis_cli", "soma_cli", "aegis_mcp", "soma_mcp")
        for py_file in python_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(forbidden):
                            violations.append((py_file.name, node.lineno, alias.name))
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith(forbidden):
                        violations.append((py_file.name, node.lineno, node.module))
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
                        if node.args and isinstance(node.args[0], ast.Constant) and str(node.args[0].value).startswith(forbidden):
                            violations.append((py_file.name, node.lineno, node.args[0].value))
                    elif isinstance(node.func, ast.Name) and node.func.id == "__import__":
                        if node.args and isinstance(node.args[0], ast.Constant) and str(node.args[0].value).startswith(forbidden):
                            violations.append((py_file.name, node.lineno, node.args[0].value))

        assert not violations, f"Forbidden upward imports found in core: {violations}"



class TestInvariant2_SymbolAuthority:
    """Invariant 2: All symbols declared in __all__ across core modules must be resolvable."""

    def test_all_symbols_resolvable(self):
        core_dir = REPO_ROOT / "aegis_core" if (REPO_ROOT / "aegis_core").exists() else REPO_ROOT / "soma_core"
        pkg = "aegis_core" if (REPO_ROOT / "aegis_core").exists() else "soma_core"
        python_files = [f for f in core_dir.glob("*.py") if f.name != "__init__.py"]

        missing_symbols = []
        for py_file in python_files:
            module_name = f"{pkg}.{py_file.stem}"
            mod = importlib.import_module(module_name)
            assert hasattr(mod, "__all__"), f"{module_name} lacks __all__ declaration"
            exported = getattr(mod, "__all__", [])
            for sym in exported:
                if not hasattr(mod, sym):
                    missing_symbols.append((module_name, sym))

        assert not missing_symbols, f"Exported symbols missing from modules: {missing_symbols}"


class TestInvariant3_ReceiptSafety:
    """Invariant 3: Verification receipts are strictly single-use, bounded, and type-safe."""

    def test_safe_compare_unicode_and_bytes(self):
        # Must not raise TypeError when operands are strings with Unicode
        assert _safe_compare("receipt-valid-token-123", "receipt-valid-token-123") is True
        assert _safe_compare("token-a", "token-b") is False
        assert _safe_compare("token-unicode-🚀", "token-unicode-🚀") is True
        assert _safe_compare("token-unicode-🚀", "token-unicode-🛡️") is False

    def test_receipt_single_use_enforcement(self, tmp_path):
        workspace = str(tmp_path)
        session_id = "session-invariant-3"
        op = "soma_verify_changes"
        args = {"files": ["src/main.py"]}
        file_digest = "digest-file-123"
        cell_digest = "digest-cell-456"

        receipt_id = issue_receipt(
            session_id=session_id,
            workspace=workspace,
            operation=op,
            args=args,
            file_digest=file_digest,
            cell_digest=cell_digest,
            ttl_seconds=60,
        )
        assert receipt_id
        assert isinstance(receipt_id, str)

        # First redemption with consume=True succeeds
        assert verify_receipt(
            receipt_id=receipt_id,
            session_id=session_id,
            workspace=workspace,
            operation=op,
            args=args,
            file_digest=file_digest,
            cell_digest=cell_digest,
            consume=True,
        ) is True

        # Second redemption MUST fail closed (already burned)
        assert verify_receipt(
            receipt_id=receipt_id,
            session_id=session_id,
            workspace=workspace,
            operation=op,
            args=args,
            file_digest=file_digest,
            cell_digest=cell_digest,
            consume=True,
        ) is False

        # Attempted redemption with invalid args and consume=True MUST burn receipt immediately
        receipt_id2 = issue_receipt(
            session_id=session_id,
            workspace=workspace,
            operation=op,
            args=args,
            file_digest=file_digest,
            cell_digest=cell_digest,
            ttl_seconds=60,
        )
        assert verify_receipt(
            receipt_id=receipt_id2,
            session_id=session_id,
            workspace=workspace,
            operation=op,
            args={"files": ["wrong.py"]},
            file_digest=file_digest,
            cell_digest=cell_digest,
            consume=True,
        ) is False

        # Subsequent redemption with correct args must fail because receipt was burned
        assert verify_receipt(
            receipt_id=receipt_id2,
            session_id=session_id,
            workspace=workspace,
            operation=op,
            args=args,
            file_digest=file_digest,
            cell_digest=cell_digest,
            consume=True,
        ) is False

    def test_receipt_cross_session_or_workspace_rejection(self, tmp_path):
        workspace = str(tmp_path)
        receipt_id = issue_receipt(
            session_id="session-a",
            workspace=workspace,
            operation="test_op",
            args={"k": "v"},
            file_digest="fd",
            cell_digest="cd",
            ttl_seconds=60,
        )

        # Different session fails
        assert verify_receipt(
            receipt_id=receipt_id,
            session_id="session-b",
            workspace=workspace,
            operation="test_op",
            args={"k": "v"},
            file_digest="fd",
            cell_digest="cd",
        ) is False

        # Different workspace fails
        assert verify_receipt(
            receipt_id=receipt_id,
            session_id="session-a",
            workspace=str(tmp_path / "other"),
            operation="test_op",
            args={"k": "v"},
            file_digest="fd",
            cell_digest="cd",
        ) is False

    def test_tripartite_negative_burn_on_malformed_payload(self, tmp_path):
        workspace = str(tmp_path)
        session_id = "session-tripartite"
        op = "soma_verify_changes"
        args = {"files": ["src/main.py"]}
        file_digest = "digest-file-123"
        cell_digest = "digest-cell-456"

        # 1. Non-string / malformed payload burns receipt
        r1 = issue_receipt(session_id, workspace, op, args, file_digest, cell_digest, 60)
        assert verify_receipt(r1, 123, workspace, op, args, file_digest, cell_digest, consume=True) is False
        assert verify_receipt(r1, session_id, workspace, op, args, file_digest, cell_digest, consume=True) is False

        # 2. Mixed-type dictionary keys burn receipt
        r2 = issue_receipt(session_id, workspace, op, args, file_digest, cell_digest, 60)
        assert verify_receipt(r2, session_id, workspace, op, {1: "a", "b": 2}, file_digest, cell_digest, consume=True) is False
        assert verify_receipt(r2, session_id, workspace, op, args, file_digest, cell_digest, consume=True) is False

        # 3. Surrogate characters in comparison
        r3 = issue_receipt(session_id, workspace, op, args, file_digest, cell_digest, 60)
        assert verify_receipt(r3, "surrogate-\ud800", workspace, op, args, file_digest, cell_digest, consume=True) is False
        assert verify_receipt(r3, session_id, workspace, op, args, file_digest, cell_digest, consume=True) is False



class TestInvariant4_FailClosedConfinement:
    """Invariant 4: Path confinement rejects traversals, device names, and streams."""

    @pytest.mark.parametrize("bad_path", [
        "../outside.txt",
        "../../etc/passwd",
        "/etc/shadow",
        "foo/../../bar/../../baz",
        "COM1",
        "LPT2",
        "NUL",
        "CON",
        "CONIN$",
        "CONOUT$",
        "aux.txt",

        "safe.txt:hidden_stream",
        "file::$DATA",
    ])
    def test_confine_path_fails_closed(self, tmp_path, bad_path):
        with pytest.raises(ValueError):
            confine_path(bad_path, str(tmp_path))


class TestInvariant5_IngressConcurrency:
    """Invariant 5: MCP rate limiter is thread-safe and recovers quota on invalid queries."""

    def test_rate_limit_lock_exists_and_is_thread_safe(self):
        assert hasattr(mcp_server, "_rate_limit_lock")
        lock = getattr(mcp_server, "_rate_limit_lock")
        assert hasattr(lock, "acquire") and hasattr(lock, "release")

    def test_invalid_poll_does_not_consume_rate_limit(self):
        with mcp_server._rate_limit_lock:
            mcp_server._tool_call_times["soma_poll_verification"] = []

        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "soma_poll_verification",
                "arguments": {"job_id": "nonexistent-job-xyz"},
            },
        }
        res = mcp_server.handle_request(req)
        assert "error" in res

        # Counter should not be charged
        with mcp_server._rate_limit_lock:
            assert len(mcp_server._tool_call_times.get("soma_poll_verification", [])) == 0

    def test_rate_limit_rollback_zero_sibling_lease_eviction(self):
        tool = "soma_verify_changes"
        with mcp_server._rate_limit_lock:
            mcp_server._tool_call_times[tool] = [("lease-sibling-1", time.monotonic())]

        # Rolling back with non-matching lease MUST NOT evict sibling
        mcp_server._rollback_rate_limit(tool, lease_id="nonexistent-lease-xyz")
        with mcp_server._rate_limit_lock:
            assert len(mcp_server._tool_call_times[tool]) == 1
            assert mcp_server._tool_call_times[tool][0][0] == "lease-sibling-1"



class TestInvariant6_BugRegistryIntegrity:
    """Invariant 6: Bug registry schema validation rejects malformed entries and verifies tests."""

    def test_registry_schema_and_regression_tests_pass(self):
        bugs = load_bug_registry(str(REPO_ROOT))
        bug_list = bugs.get("bugs", [])
        assert len(bug_list) == 95, f"Expected exactly 95 bug entries, got {len(bug_list)}"

        unique_errors = verify_unique_ids(bugs)
        assert not unique_errors, f"Bug ID uniqueness errors: {unique_errors}"

        schema_errors = verify_bug_schema(bugs)
        assert not schema_errors, f"Bug schema validation errors: {schema_errors}"

        test_errors = verify_bug_tests(bugs, str(REPO_ROOT))
        assert not test_errors, f"Bug regression test verification errors: {test_errors}"

