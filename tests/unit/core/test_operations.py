"""Unit tests for aegis_core.operations (Operations and Storage composition)."""
from __future__ import annotations

from pathlib import Path

from aegis_core.operations import Operations
from aegis_core.storage import Storage
from aegis_core.workspace.base import Workspace


def test_operations_text_and_bytes_io(tmp_path: Path):
    ops = Operations(tmp_path)
    assert ops.root == tmp_path.resolve()
    assert ops.read_text("missing.txt", default="fallback") == "fallback"

    ops.write_text("sub/hello.txt", "hello aegis\n")
    assert ops.read_text("sub/hello.txt") == "hello aegis\n"

    ops.write_bytes("sub/raw.bin", b"\x01\x02\x03")
    assert (tmp_path / "sub" / "raw.bin").read_bytes() == b"\x01\x02\x03"


def test_operations_jsonl_roundtrip_and_malformed_lines(tmp_path: Path):
    ops = Operations(Workspace(root=tmp_path))
    assert ops.read_jsonl("events.jsonl") == []

    ops.append_jsonl("events.jsonl", {"id": 1, "event": "alpha"})
    ops.append_jsonl("events.jsonl", {"id": 2, "event": "beta"})
    records = ops.read_jsonl("events.jsonl")
    assert records == [{"event": "alpha", "id": 1}, {"event": "beta", "id": 2}]

    # Inject a blank line and malformed JSON line; read_jsonl must skip them gracefully
    raw_file = tmp_path / "events.jsonl"
    raw_file.write_text(
        raw_file.read_text(encoding="utf-8") + "\nnot-valid-json\n[1, 2, 3]\n",
        encoding="utf-8",
    )
    assert ops.read_jsonl("events.jsonl") == [{"event": "alpha", "id": 1}, {"event": "beta", "id": 2}]

    ops.write_jsonl("events.jsonl", [{"id": 3, "event": "gamma"}])
    assert ops.read_jsonl("events.jsonl") == [{"event": "gamma", "id": 3}]


def test_storage_composes_operations_and_layout(tmp_path: Path):
    storage = Storage(tmp_path)
    assert isinstance(storage.ops, Operations)
    assert storage.layout == storage.ops.layout

    storage.write_atomic("notes.txt", "atomic text")
    assert storage.read_text("notes.txt") == "atomic text"

    storage.append_jsonl(storage.layout.receipts_file, {"nonce": "n1", "status": "issued"})
    assert storage.read_jsonl(storage.layout.receipts_file) == [{"nonce": "n1", "status": "issued"}]
