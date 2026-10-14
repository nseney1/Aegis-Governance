"""File-buffered Swarm Handoff router with compact ticket references (< 150 tokens)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Dict, Mapping, Optional, Union
import uuid

from aegis_core.errors import SomaError, SomaValidationError
from aegis_core.schemas.artifacts import ArtifactEnvelope, ArtifactRegistry
from aegis_core.skills.graph import SkillGraph, SkillNode
from aegis_core.workspace import Workspace, as_workspace

__all__ = ["HandoffTicket", "HandoffRouter", "soma_handoff"]


@dataclass(frozen=True)
class HandoffTicket:
    """Ultra-compact ticket delivered to recipient agent (< 150 tokens)."""

    ticket_id: str
    artifact_type: str
    producer_skill: str
    target_skill: str
    file_path: str
    tree_hash: str
    session_hmac: str
    summary: str
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "artifact_type": self.artifact_type,
            "producer_skill": self.producer_skill,
            "target_skill": self.target_skill,
            "file_path": self.file_path,
            "tree_hash": self.tree_hash,
            "session_hmac": self.session_hmac,
            "summary": self.summary,
            "created_at": self.created_at,
        }

    def format_prompt_block(self) -> str:
        """Format minimal token reference block for recipient subagent."""
        return (
            f"<!-- SOMA_HANDOFF_TICKET -->\n"
            f"[TICKET]: {self.ticket_id} | [TYPE]: {self.artifact_type}\n"
            f"[FROM]: {self.producer_skill} -> [TO]: {self.target_skill}\n"
            f"[PAYLOAD]: file://{self.file_path}\n"
            f"[TREE]: {self.tree_hash} | [HMAC]: {self.session_hmac[:12]}...\n"
            f"[SUMMARY]: {self.summary}\n"
            f"<!-- END_HANDOFF_TICKET -->"
        )


def _get_tree_hash(ws_root: Path) -> str:
    """Get current HEAD tree hash."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=str(ws_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return "0000000000000000000000000000000000000000"


class HandoffRouter:
    """Manages file-buffered swarm handoffs between skills."""

    @classmethod
    def execute_handoff(
        cls,
        workspace: Union[Workspace, Path, str],
        from_skill: str,
        to_skill: str,
        artifact_type: str,
        payload: Union[Mapping[str, Any], str],
        producer_tier: Optional[str] = None,
        session_secret: Optional[str] = None,
        cycle_id: Optional[str] = None,
    ) -> HandoffTicket:
        """Execute typed handoff, write envelope to disk, and return compact ticket."""
        ws = as_workspace(workspace)
        root = Path(ws.root)

        # 1. Discover SkillGraph
        project_skills = root / ".soma" / "skills"
        global_skills = Path.home() / ".soma" / "skills"
        graph = SkillGraph.discover([project_skills, global_skills])

        from_node = graph.get(from_skill)
        tier = producer_tier or (from_node.tier if from_node else "method")

        # 2. Validate routing path
        graph.validate_handoff_path(from_skill, to_skill, artifact_type)

        # 3. Parse and validate payload
        if isinstance(payload, str):
            try:
                payload_dict = json.loads(payload)
            except Exception:
                payload_dict = {"summary": payload}
        else:
            payload_dict = dict(payload)

        # 4. Resolve tree hash and secret
        tree_hash = _get_tree_hash(root)
        secret = session_secret or os.environ.get("SOMA_SESSION_SECRET", "soma_default_session_secret")

        # 5. Create signed ArtifactEnvelope
        envelope = ArtifactEnvelope.create(
            artifact_type=artifact_type,
            producer_skill=from_skill,
            producer_tier=tier,
            tree_hash=tree_hash,
            session_secret=secret,
            payload=payload_dict,
        )

        # 6. File buffer: write to .soma/swarm/handoffs/
        handoffs_dir = root / ".soma" / "swarm" / "handoffs"
        handoffs_dir.mkdir(parents=True, exist_ok=True)

        cid = cycle_id or str(uuid.uuid4())[:8]
        ticket_id = f"{cid}_{artifact_type.lower()}"
        target_file = handoffs_dir / f"{ticket_id}.json"

        # Confinement check
        resolved_file, _ = ws.confine_path(str(target_file.relative_to(root)))
        Path(resolved_file).write_text(json.dumps(envelope.to_dict(), indent=2), encoding="utf-8")

        # 7. Append disk telemetry
        telemetry_dir = root / ".soma" / "telemetry"
        telemetry_dir.mkdir(parents=True, exist_ok=True)
        telemetry_file = telemetry_dir / "skills.jsonl"
        telemetry_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "handoff",
            "from_skill": from_skill,
            "to_skill": to_skill,
            "artifact_type": artifact_type,
            "tree_hash": tree_hash,
            "ticket_id": ticket_id,
        }
        with open(telemetry_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(telemetry_entry) + "\n")

        # 8. Produce ultra-compact summary (<150 tokens)
        summary = (
            payload_dict.get("summary")
            or payload_dict.get("risk")
            or f"{artifact_type} from {from_skill}"
        )
        if len(summary) > 160:
            summary = summary[:157] + "..."

        return HandoffTicket(
            ticket_id=ticket_id,
            artifact_type=artifact_type,
            producer_skill=from_skill,
            target_skill=to_skill,
            file_path=str(resolved_file),
            tree_hash=tree_hash,
            session_hmac=envelope.session_hmac,
            summary=summary,
            created_at=envelope.timestamp,
        )


def soma_handoff(
    workspace: Union[Workspace, Path, str],
    from_skill: str,
    to_skill: str,
    artifact_type: str,
    payload: Union[Mapping[str, Any], str],
    producer_tier: Optional[str] = None,
    session_secret: Optional[str] = None,
    cycle_id: Optional[str] = None,
) -> HandoffTicket:
    """High-level functional interface for executing swarm skill handoffs."""
    return HandoffRouter.execute_handoff(
        workspace=workspace,
        from_skill=from_skill,
        to_skill=to_skill,
        artifact_type=artifact_type,
        payload=payload,
        producer_tier=producer_tier,
        session_secret=session_secret,
        cycle_id=cycle_id,
    )
