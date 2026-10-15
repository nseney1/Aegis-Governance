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

from aegis_core.errors import AegisError, AegisValidationError
from aegis_core.schemas.artifacts import ArtifactEnvelope, ArtifactRegistry
from aegis_core.skills.graph import SkillGraph, SkillNode
from aegis_core.workspace import Workspace, as_workspace

__all__ = [
    "HandoffTicket",
    "HandoffRouter",
    "soma_handoff",
    "aegis_handoff",
    "consume_handoff",
]


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
    payload: Optional[Dict[str, Any]] = None
    status: str = "pending"

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
            f"<!-- AEGIS_HANDOFF_TICKET -->\n"
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


def _resolve_session_secret(root: Path, session_secret: Optional[str] = None) -> str:
    """Resolve the HMAC signing secret from explicit arg, env, or workspace receipt key."""
    if session_secret is not None:
        return session_secret.decode("utf-8", errors="replace") if isinstance(session_secret, bytes) else str(session_secret)
    env_secret = os.environ.get("AEGIS_SESSION_SECRET")
    if env_secret:
        return env_secret
    legacy_key_file = root / ".aegis" / "receipt_key"
    if legacy_key_file.is_file():
        try:
            raw = legacy_key_file.read_text(encoding="utf-8").strip()
            if raw:
                return raw
        except OSError:
            pass
    if (root / ".aegis").is_dir():
        try:
            from aegis_core.receipts import ReceiptManager

            key_bytes = ReceiptManager(root)._key
            if key_bytes:
                return key_bytes.decode("utf-8", errors="replace")
        except Exception:
            pass
    return "aegis_default_session_secret"


class _ConsumeHandoffDescriptor:
    """Allows HandoffRouter.consume_handoff to be called on an instance or class."""

    def __get__(self, instance: Optional[HandoffRouter], owner: type[HandoffRouter]):
        if instance is not None:
            def _bound(
                ticket_id: str,
                verify_tree: bool = True,
                session_secret: Optional[str] = None,
            ) -> HandoffTicket:
                if instance.workspace is None:
                    raise ValueError("HandoffRouter instance has no workspace configured")
                return owner._consume_handoff_impl(
                    workspace=instance.workspace,
                    ticket_id=ticket_id,
                    verify_tree=verify_tree,
                    session_secret=session_secret,
                )
            return _bound

        def _unbound(
            workspace_or_self: Union[HandoffRouter, Workspace, Path, str],
            ticket_id: str,
            verify_tree: bool = True,
            session_secret: Optional[str] = None,
        ) -> HandoffTicket:
            if isinstance(workspace_or_self, owner):
                if workspace_or_self.workspace is None:
                    raise ValueError("HandoffRouter instance has no workspace configured")
                ws_target: Union[Workspace, Path, str] = workspace_or_self.workspace
            else:
                ws_target = workspace_or_self
            return owner._consume_handoff_impl(
                workspace=ws_target,
                ticket_id=ticket_id,
                verify_tree=verify_tree,
                session_secret=session_secret,
            )

        return _unbound


class HandoffRouter:
    """Manages file-buffered swarm handoffs between skills."""

    def __init__(self, workspace: Optional[Union[Workspace, Path, str]] = None) -> None:
        self.workspace: Optional[Workspace] = as_workspace(workspace) if workspace is not None else None

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
        gov_dir = root / ".aegis"
        gov_dir.mkdir(parents=True, exist_ok=True)
        graph = SkillGraph.discover(SkillGraph.default_search_paths(root))

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
        secret = _resolve_session_secret(root, session_secret)

        # 5. Create signed ArtifactEnvelope
        envelope = ArtifactEnvelope.create(
            artifact_type=artifact_type,
            producer_skill=from_skill,
            producer_tier=tier,
            tree_hash=tree_hash,
            session_secret=secret,
            payload=payload_dict,
        )

        # 6. Produce ultra-compact summary (<150 tokens)
        summary = (
            payload_dict.get("summary")
            or payload_dict.get("risk")
            or f"{artifact_type} from {from_skill}"
        )
        if len(summary) > 160:
            summary = summary[:157] + "..."

        # 7. File buffer: write to .aegis/swarm/handoffs/ and .aegis/handoffs/
        cid = cycle_id or str(uuid.uuid4())[:8]
        ticket_id = f"{cid}_{artifact_type.lower()}"

        envelope_data = envelope.to_dict()
        envelope_data["ticket_id"] = ticket_id
        envelope_data["target_skill"] = to_skill
        envelope_data["summary"] = summary
        envelope_data["status"] = "pending"
        serialized_envelope = json.dumps(envelope_data, indent=2)

        swarm_handoffs_dir = gov_dir / "swarm" / "handoffs"
        swarm_handoffs_dir.mkdir(parents=True, exist_ok=True)
        swarm_file = swarm_handoffs_dir / f"{ticket_id}.json"
        resolved_swarm, _ = ws.confine_path(str(swarm_file.relative_to(root)))
        Path(resolved_swarm).write_text(serialized_envelope, encoding="utf-8")

        direct_handoffs_dir = gov_dir / "handoffs"
        direct_handoffs_dir.mkdir(parents=True, exist_ok=True)
        direct_file = direct_handoffs_dir / f"{ticket_id}.json"
        resolved_direct, _ = ws.confine_path(str(direct_file.relative_to(root)))
        Path(resolved_direct).write_text(serialized_envelope, encoding="utf-8")

        # 8. Append disk telemetry
        telemetry_dir = gov_dir / "telemetry"
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

        return HandoffTicket(
            ticket_id=ticket_id,
            artifact_type=artifact_type,
            producer_skill=from_skill,
            target_skill=to_skill,
            file_path=str(resolved_swarm),
            tree_hash=tree_hash,
            session_hmac=envelope.session_hmac,
            summary=summary,
            created_at=envelope.timestamp,
            payload=envelope.payload,
            status="pending",
        )

    @classmethod
    def _consume_handoff_impl(
        cls,
        workspace: Union[Workspace, Path, str],
        ticket_id: str,
        verify_tree: bool = True,
        session_secret: Optional[str] = None,
    ) -> HandoffTicket:
        """Load, cryptographically verify, and mark a handoff ticket as consumed."""
        ws = as_workspace(workspace)
        root = Path(ws.root)
        gov_dir = root / ".aegis"

        clean_id = ticket_id[:-5] if ticket_id.endswith(".json") else ticket_id
        candidate_rels = [
            Path(".aegis") / "handoffs" / f"{clean_id}.json",
            Path(".aegis") / "swarm" / "handoffs" / f"{clean_id}.json",
        ]
        existing_paths: list[Path] = []
        for rel in candidate_rels:
            resolved_str, _ = ws.confine_path(str(rel))
            p = Path(resolved_str)
            if p.is_file():
                existing_paths.append(p)

        if not existing_paths:
            raise FileNotFoundError(
                f"Handoff ticket '{ticket_id}' not found in {gov_dir / 'handoffs'}"
            )

        primary_file = existing_paths[0]
        try:
            data = json.loads(primary_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"Handoff ticket verification failed: malformed JSON ({exc})") from exc

        if not isinstance(data, dict):
            raise ValueError("Handoff ticket verification failed: ticket content must be a JSON object")

        if data.get("status") == "consumed":
            raise ValueError(f"Handoff ticket verification failed: ticket '{clean_id}' already consumed")

        try:
            envelope = ArtifactEnvelope.from_dict(data)
        except Exception as exc:
            raise ValueError(f"Handoff ticket verification failed: invalid envelope ({exc})") from exc

        secret = _resolve_session_secret(root, session_secret)
        if not envelope.verify_integrity(secret, expected_tree_hash=None):
            raise ValueError("Handoff ticket verification failed: HMAC signature mismatch")

        if verify_tree and envelope.tree_hash:
            current_tree = _get_tree_hash(root)
            if current_tree != envelope.tree_hash:
                raise ValueError(
                    f"Handoff ticket verification failed: git tree_hash drift "
                    f"(expected {envelope.tree_hash}, got {current_tree})"
                )

        data["status"] = "consumed"
        data["consumed_at"] = datetime.now(timezone.utc).isoformat()
        updated_json = json.dumps(data, indent=2)
        for p in existing_paths:
            p.write_text(updated_json, encoding="utf-8")

        summary = (
            data.get("summary")
            or envelope.payload.get("summary")
            or envelope.payload.get("risk")
            or f"{envelope.artifact_type} from {envelope.producer_skill}"
        )
        if len(summary) > 160:
            summary = summary[:157] + "..."

        return HandoffTicket(
            ticket_id=str(data.get("ticket_id", clean_id)),
            artifact_type=envelope.artifact_type,
            producer_skill=envelope.producer_skill,
            target_skill=str(data.get("target_skill", "")),
            file_path=str(primary_file),
            tree_hash=envelope.tree_hash,
            session_hmac=envelope.session_hmac,
            summary=summary,
            created_at=envelope.timestamp,
            payload=envelope.payload,
            status="consumed",
        )

    consume_handoff = _ConsumeHandoffDescriptor()


def consume_handoff(
    workspace: Union[Workspace, Path, str],
    ticket_id: str,
    verify_tree: bool = True,
    session_secret: Optional[str] = None,
) -> HandoffTicket:
    """Functional helper to verify and consume an inbound handoff ticket."""
    return HandoffRouter._consume_handoff_impl(
        workspace=workspace,
        ticket_id=ticket_id,
        verify_tree=verify_tree,
        session_secret=session_secret,
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


aegis_handoff = soma_handoff
