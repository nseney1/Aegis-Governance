import pytest
from aegis_core.receipts import issue_receipt, verify_receipt, clear_receipts

def test_issue_and_verify_receipt():
    # Failing test to drive receipt implementation
    args = {"test": "data"}
    receipt_id = issue_receipt("session_1", "workspace_1", "op_1", args, "file_digest", "cell_digest")
    assert receipt_id is not None
    assert type(receipt_id) == str
    
    # Verify should succeed with identical parameters
    assert verify_receipt(receipt_id, "session_1", "workspace_1", "op_1", args, "file_digest", "cell_digest") == True
    
    # Verify should fail with wrong session
    assert verify_receipt(receipt_id, "session_2", "workspace_1", "op_1", args, "file_digest", "cell_digest") == False

def test_receipt_invalidation():
    # This should fail if state is not kept
    receipt_id = issue_receipt("s1", "w1", "o1", {}, "fd", "cd")
    clear_receipts()
    assert verify_receipt(receipt_id, "s1", "w1", "o1", {}, "fd", "cd") == False

def test_receipt_ttl_expiration():
    import time
    receipt_id = issue_receipt("s1", "w1", "o1", {}, "fd", "cd", ttl_seconds=0.01)
    time.sleep(0.02)
    assert verify_receipt(receipt_id, "s1", "w1", "o1", {}, "fd", "cd") == False

def test_receipt_capacity_cap(monkeypatch):
    import aegis_core.receipts as r_mod
    clear_receipts()
    monkeypatch.setattr(r_mod, "MAX_RECEIPTS", 5)

    rids = []
    for i in range(10):
        rid = issue_receipt(f"s{i}", "w", "op", {}, "fd", "cd")
        rids.append(rid)

    # Store size must not exceed MAX_RECEIPTS
    assert len(r_mod._receipt_store) <= 5
    # The oldest receipts should have been evicted
    assert verify_receipt(rids[0], "s0", "w", "op", {}, "fd", "cd") == False
    # The newest receipt should still be valid
    assert verify_receipt(rids[-1], "s9", "w", "op", {}, "fd", "cd") == True
    clear_receipts()


def test_verify_receipt_with_invalid_types():
    assert verify_receipt(None, "s1", "w1", "o1", {}, "fd", "cd") is False
    assert verify_receipt(12345, "s1", "w1", "o1", {}, "fd", "cd") is False
    rid = issue_receipt("s1", "w1", "o1", {}, "fd", "cd")
    try:
        assert verify_receipt(rid, None, "w1", "o1", {}, "fd", "cd") is False
        assert verify_receipt(rid, 123, "w1", "o1", {}, "fd", "cd") is False
        assert verify_receipt(rid, "s1", None, "o1", {}, "fd", "cd") is False
        assert verify_receipt(rid, "s1", "w1", None, {}, "fd", "cd") is False
        assert verify_receipt(rid, "s1", "w1", "o1", None, "fd", "cd") is False
        assert verify_receipt(rid, "s1", "w1", "o1", {}, None, "cd") is False
        assert verify_receipt(rid, "s1", "w1", "o1", {}, "fd", None) is False
    finally:
        clear_receipts()


def test_verify_receipt_unconditional_burn_on_consume():
    """C-03: Verify that consume=True burns receipt even if verification fails, preventing replay/probing."""
    clear_receipts()
    try:
        rid = issue_receipt("sess_auth", "ws_1", "write_op", {"file": "a.txt"}, "fd_1", "cd_1")

        # Invalid call with consume=True: wrong session -> returns False AND burns receipt
        assert verify_receipt(rid, "wrong_sess", "ws_1", "write_op", {"file": "a.txt"}, "fd_1", "cd_1", consume=True) is False

        # Subsequent redemption attempt (even with valid credentials) must fail because receipt was burned
        assert verify_receipt(rid, "sess_auth", "ws_1", "write_op", {"file": "a.txt"}, "fd_1", "cd_1", consume=True) is False
    finally:
        clear_receipts()


def test_compute_file_digest_path_normalization(tmp_path):
    from aegis_core.receipts import compute_file_digest

    sub = tmp_path / "sub"
    sub.mkdir()
    target = sub / "file.txt"
    target.write_text("content", encoding="utf-8")

    digest_clean = compute_file_digest(str(tmp_path), ["sub/file.txt"])
    digest_dot = compute_file_digest(str(tmp_path), ["sub/./file.txt"])
    digest_dups = compute_file_digest(str(tmp_path), ["sub/file.txt", "sub/./file.txt"])
    digest_abs = compute_file_digest(str(tmp_path), [str(target)])

    assert digest_clean == digest_dot
    assert digest_clean == digest_dups
    assert digest_clean == digest_abs


def test_verify_receipt_unicode_workspace_and_args():
    """C-02: verify_receipt must handle non-ASCII / Unicode paths without TypeError."""
    clear_receipts()
    try:
        ws_unicode = "/tmp/söma_test_日本語_workspace"
        args = {"target": "ファイル.txt", "notes": "René Descartes"}
        rid = issue_receipt("sess_123", ws_unicode, "op_write", args, "fd_unicode", "cd_unicode")

        # Must verify cleanly without throwing TypeError from hmac.compare_digest
        assert verify_receipt(rid, "sess_123", ws_unicode, "op_write", args, "fd_unicode", "cd_unicode") is True
        # Mismatch check must also not raise
        assert verify_receipt(rid, "sess_123", "/tmp/other_unicode_ путь", "op_write", args, "fd_unicode", "cd_unicode") is False
    finally:
        clear_receipts()


def test_confined_path_rejects_devices_and_streams(tmp_path):
    """C-04: _confined must delegate to confine_path and reject Windows devices and ADS."""
    from aegis_core.receipts import _confined

    ws = str(tmp_path)
    (tmp_path / "valid.txt").write_text("hello", encoding="utf-8")

    # Valid file resolves
    resolved = _confined(ws, "valid.txt")
    assert resolved == str(tmp_path / "valid.txt")

    # Windows device name rejected
    with pytest.raises(ValueError, match="reserved Windows device name"):
        _confined(ws, "CON")

    with pytest.raises(ValueError, match="reserved Windows device name"):
        _confined(ws, "nul.txt")

    # Alternate data stream rejected
    with pytest.raises(ValueError, match="alternate data stream"):
        _confined(ws, "valid.txt:stream")

    # Path traversal rejected
    with pytest.raises(ValueError, match="path traversal blocked"):
        _confined(ws, "../../etc/passwd")


def test_receipt_store_class_isolation():
    """Verify ReceiptStore provides encapsulated state isolation, capacity eviction, and thread safety."""
    import concurrent.futures
    from aegis_core.receipts import ReceiptStore

    store = ReceiptStore(max_receipts=10, default_ttl=60.0)
    assert len(store) == 0

    # Thread-safe concurrent issuance
    def _issue_worker(i):
        return store.issue(
            session_id=f"sess_{i}",
            workspace="/tmp/ws",
            operation="test_op",
            args={"i": i},
            file_digest="fd",
            cell_digest="cd",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        receipt_ids = list(executor.map(_issue_worker, range(20)))

    assert len(receipt_ids) == 20
    # Capacity pruning must enforce max_receipts=10
    assert len(store) <= 10

    # Verification of remaining receipts succeeds
    last_rid = receipt_ids[-1]
    assert store.verify(last_rid, "sess_19", "/tmp/ws", "test_op", {"i": 19}, "fd", "cd") is True

    # Consumed receipt cannot be verified again
    assert store.verify(last_rid, "sess_19", "/tmp/ws", "test_op", {"i": 19}, "fd", "cd") is False

    # Store clear empties all receipts
    store.clear()
    assert len(store) == 0


def test_receipt_dataclass_model():
    """Verify Receipt frozen dataclass model contract."""
    from dataclasses import FrozenInstanceError
    from aegis_core.schemas import Receipt

    r = Receipt(
        receipt_id="r-123",
        session_id="sess-abc",
        workspace="/tmp/ws",
        operation="run_tool",
        args_hash="hash123",
        file_digest="fd123",
        cell_digest="cd123",
        created_at=1000.0,
        expires_at=2000.0,
    )
    assert r.receipt_id == "r-123"
    assert r.expires_at == 2000.0

    with pytest.raises(FrozenInstanceError):
        r.receipt_id = "r-456"  # type: ignore[misc]


def test_receipt_manager_burns_nonce_to_ledger_before_digest_comparison(tmp_path):
    """S3: ReceiptManager.verify(..., consume=True) burns nonce to .aegis/receipts.jsonl before digest comparison."""
    import json
    from aegis_core.receipts import ReceiptManager

    (tmp_path / ".aegis").mkdir()
    mgr = ReceiptManager(workspace=tmp_path)
    rid = mgr.issue(
        session_id="sess_s3",
        workspace=tmp_path,
        operation="aegis_propose_change",
        args={"file_path": "target.py"},
        file_digest="orig_file_digest",
        rule_digest="orig_rule_digest",
    )

    # Attempt redemption with a stale file_digest -> returns False AND burns nonce to .aegis/receipts.jsonl
    assert mgr.verify(
        rid,
        "sess_s3",
        tmp_path,
        "aegis_propose_change",
        {"file_path": "target.py"},
        "stale_file_digest",
        "orig_rule_digest",
        consume=True,
    ) is False

    ledger_file = tmp_path / ".aegis" / "receipts.jsonl"
    assert ledger_file.is_file()
    records = [json.loads(line) for line in ledger_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(r.get("nonce") == rid and r.get("status") == "consumed" for r in records)

    # Even if the file is reverted back to orig_file_digest (or verified via a fresh ReceiptManager process), replay fails
    mgr_restarted = ReceiptManager(workspace=tmp_path)
    assert mgr_restarted.verify(
        rid,
        "sess_s3",
        tmp_path,
        "aegis_propose_change",
        {"file_path": "target.py"},
        "orig_file_digest",
        "orig_rule_digest",
        consume=True,
    ) is False

