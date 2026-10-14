"""SomaTestHarness: Zero-dependency sandboxed test harness for Soma Governance."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping

from aegis_core.yaml import dump_frontmatter, parse_cell_frontmatter


CELL_TYPE_DIRS = {
    "wall": "walls",
    "membrane": "membranes",
    "vacuole": "vacuoles",
    "chloroplast": "chloroplasts",
    "mitochondria": "mitochondria",
    "nucleus": "nucleus",
    "ribosome": "ribosomes",
}


class AegisTestHarness:
    """Isolated sandbox fixture for testing Aegis Governance lifecycle, telemetry, and CLI."""

    def __init__(self, workspace: Path, use_aegis: bool = True) -> None:
        self.workspace = Path(workspace).resolve()
        self.use_aegis = use_aegis
        if use_aegis or (self.workspace / ".aegis").is_dir():
            self.soma_dir = self.workspace / ".aegis"
            self.cells_dir = self.soma_dir / "rules"
            self.locks_dir = self.soma_dir / "locks"
        else:
            self.soma_dir = self.workspace / ".soma"
            self.cells_dir = self.soma_dir / "cells"
            self.locks_dir = self.soma_dir / "locks"
        self.aegis_dir = self.soma_dir
        self.rules_dir = self.cells_dir
        self._init_workspace()

    def _init_workspace(self) -> None:
        """Initialize standard Aegis directory layout inside the isolated workspace."""
        for subdir in CELL_TYPE_DIRS.values():
            (self.cells_dir / subdir).mkdir(parents=True, exist_ok=True)
        self.locks_dir.mkdir(parents=True, exist_ok=True)

    def create_cell(
        self,
        cell_id: str,
        cell_type: str = "wall",
        domain: str = "correctness",
        hypothesis: str = "Standard test hypothesis",
        prediction: str = "Standard test prediction",
        falsification: str = "Standard test falsification",
        tags: list[str] | tuple[str, ...] | None = None,
        body: str = "# Rule content\n\nRule details.",
        extra_fm: Mapping[str, Any] | None = None,
    ) -> Path:
        """Create a governance cell markdown file with valid frontmatter."""
        type_dir = CELL_TYPE_DIRS.get(cell_type, f"{cell_type}s")
        target_dir = self.cells_dir / type_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{cell_id}.md" if not cell_id.endswith(".md") else cell_id
        target_file = target_dir / filename

        fm_data: dict[str, Any] = {
            "id": cell_id if not cell_id.endswith(".md") else cell_id[:-3],
            "type": cell_type,
            "domain": domain,
            "enforcement": "advisory",
            "hypothesis": hypothesis,
            "prediction": prediction,
            "falsification": falsification,
            "tags": list(tags) if tags else ["test"],
        }
        if extra_fm:
            fm_data.update(extra_fm)

        content = dump_frontmatter(fm_data, body)
        target_file.write_text(content, encoding="utf-8")
        return target_file

    create_rule = create_cell

    def record_signal(
        self,
        cell_id: str,
        signal_type: str = "test_pass",
        score: float = 1.0,
        session_id: str = "test-session",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Append an event line to .aegis/signals.jsonl."""
        signals_file = self.soma_dir / "signals.jsonl"
        payload = {
            "event_id": str(uuid.uuid4()),
            "cell_id": cell_id,
            "signal_type": signal_type,
            "score": score,
            "session_id": session_id,
            "details": dict(details) if details else {},
        }
        with signals_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")

    def run_cli(
        self,
        args: list[str],
        env: Mapping[str, str] | None = None,
        check: bool = True,
        timeout: float = 30.0,
    ) -> subprocess.CompletedProcess[str]:
        """Execute an aegis CLI command out-of-process via subprocess."""
        merged_env = dict(os.environ)
        merged_env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
        merged_env["AEGIS_WORKSPACE"] = str(self.workspace)
        if env:
            merged_env.update(env)

        cmd = [sys.executable, "-m", "aegis_cli.cli", *args]
        return subprocess.run(
            cmd,
            cwd=str(self.workspace),
            capture_output=True,
            text=True,
            env=merged_env,
            timeout=timeout,
            check=check,
        )


__all__ = [
    "AegisTestHarness",
    "CELL_TYPE_DIRS",
]

