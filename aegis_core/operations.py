"""Workspace file, JSONL, and atomic I/O primitives composed by Storage."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from aegis_core.taxonomy import STORAGE_INITIAL_DELAY_SECONDS, STORAGE_MAX_RETRIES
from aegis_core.workspace.base import Workspace
from aegis_core.workspace.layout import WorkspaceLayout


class Operations:
    """Encapsulates workspace file, JSONL, and atomic I/O primitives using WorkspaceLayout."""

    def __init__(self, workspace: str | Path | os.PathLike[str] | Workspace) -> None:
        if isinstance(workspace, Workspace):
            root = workspace.root
        else:
            root = Path(os.fspath(workspace)).resolve()
        self.layout = WorkspaceLayout(root=root)

    @property
    def root(self) -> Path:
        return self.layout.root

    def resolve_path(self, path: str | Path) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return (self.layout.root / p).resolve()

    def read_text(self, path: str | Path, default: str = "") -> str:
        from aegis_core.storage import read_text_utf8

        p = self.resolve_path(path)
        if not p.is_file():
            return default
        return read_text_utf8(p)

    def write_text(
        self,
        path: str | Path,
        content: str,
        max_retries: int = STORAGE_MAX_RETRIES,
        initial_delay: float = STORAGE_INITIAL_DELAY_SECONDS,
    ) -> None:
        from aegis_core.storage import atomic_write_text

        p = self.resolve_path(path)
        atomic_write_text(
            p,
            content,
            max_retries=max_retries,
            initial_delay=initial_delay,
        )

    def write_bytes(
        self,
        path: str | Path,
        data: bytes,
        max_retries: int = STORAGE_MAX_RETRIES,
        initial_delay: float = STORAGE_INITIAL_DELAY_SECONDS,
    ) -> None:
        from aegis_core.storage import atomic_write_bytes

        p = self.resolve_path(path)
        atomic_write_bytes(
            p,
            data,
            max_retries=max_retries,
            initial_delay=initial_delay,
        )

    def read_jsonl(self, path: str | Path) -> list[dict[str, Any]]:
        p = self.resolve_path(path)
        if not p.is_file():
            return []
        records: list[dict[str, Any]] = []
        try:
            with p.open("r", encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        parsed = json.loads(stripped)
                        if isinstance(parsed, dict):
                            records.append(parsed)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []
        return records

    def append_jsonl(self, path: str | Path, record: dict[str, Any]) -> None:
        from aegis_core.storage import fsync_dir

        p = self.resolve_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(record, sort_keys=True) + "\n"
        with p.open("a", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        fsync_dir(p.parent)

    def write_jsonl(self, path: str | Path, records: list[dict[str, Any]]) -> None:
        lines = [json.dumps(r, sort_keys=True) for r in records]
        content = ("\n".join(lines) + "\n") if lines else ""
        self.write_text(path, content)


__all__ = ["Operations"]
