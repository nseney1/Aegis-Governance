"""Horizontal Skill Graph with scale-to-zero memory footprint and string edge IDs."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Set, Tuple

from aegis_core.errors import SomaValidationError
from aegis_core.somayaml import SomaDocument, SomaYAML

__all__ = ["SkillNode", "SkillGraph"]


@dataclass(frozen=True)
class SkillNode:
    """Immutable skill graph node representing a deterministic agent organ/capability."""

    id: str
    tier: str = "method"
    consumes: Tuple[str, ...] = ()
    produces: Tuple[str, ...] = ()
    handoff_targets: Tuple[str, ...] = ()
    instructions_file: Optional[str] = None
    decay: bool = False
    description: str = ""
    slot_constraints: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_doc(cls, doc: SomaDocument, file_path: Optional[str | Path] = None) -> SkillNode:
        return cls(
            id=str(doc.id or (Path(file_path).stem if file_path else "unknown")),
            tier=str(doc.tier or "method"),
            consumes=tuple(str(c) for c in doc.consumes),
            produces=tuple(str(p) for p in doc.produces),
            handoff_targets=tuple(str(h) for h in doc.handoff_targets),
            instructions_file=str(file_path) if file_path else doc.source_path,
            decay=False,  # Skills represent deterministic capabilities and do not decay
            description=str(doc.get("description", "")),
            slot_constraints={str(k): str(v) for k, v in doc.get("slot_constraints", {}).items()}
            if isinstance(doc.get("slot_constraints"), Mapping)
            else {},
        )

    def load_instructions(self) -> str:
        """Lazily load markdown body instructions from disk."""
        if not self.instructions_file:
            return ""
        p = Path(self.instructions_file)
        if not p.exists():
            return ""
        doc = SomaYAML.parse_text(p.read_text(encoding="utf-8"))
        return doc.body

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tier": self.tier,
            "consumes": list(self.consumes),
            "produces": list(self.produces),
            "handoff_targets": list(self.handoff_targets),
            "instructions_file": self.instructions_file,
            "decay": self.decay,
            "description": self.description,
            "slot_constraints": self.slot_constraints,
        }


class SkillGraph:
    """Lightweight directed graph of skills with scale-to-zero memory."""

    def __init__(self, nodes: Optional[Mapping[str, SkillNode]] = None) -> None:
        self._nodes: Dict[str, SkillNode] = dict(nodes or {})

    def __len__(self) -> int:
        return len(self._nodes)

    def __iter__(self) -> Iterator[str]:
        return iter(self._nodes)

    def __getitem__(self, skill_id: str) -> SkillNode:
        return self._nodes[skill_id]

    def get(self, skill_id: str, default: Optional[SkillNode] = None) -> Optional[SkillNode]:
        return self._nodes.get(skill_id, default)

    @classmethod
    def discover(cls, search_paths: Sequence[Path | str]) -> SkillGraph:
        """Discover skills across project and global paths without keeping bodies in RAM."""
        nodes: Dict[str, SkillNode] = {}
        for sp in search_paths:
            base = Path(sp)
            if not base.exists():
                continue

            # Check individual skill markdown files or directories with SKILL.md
            candidates: List[Path] = []
            if base.is_file() and base.suffix == ".md":
                candidates.append(base)
            elif base.is_dir():
                for p in base.rglob("*.md"):
                    if p.name == "README.md":
                        continue
                    candidates.append(p)

            for cand in candidates:
                try:
                    text = cand.read_text(encoding="utf-8")
                    doc = SomaYAML.parse_text(text)
                    if doc.kind == "skill" or any(k in doc for k in ("tier", "consumes", "produces", "handoff_targets")):
                        node = SkillNode.from_doc(doc, file_path=str(cand.resolve()))
                        if node.id not in nodes:
                            nodes[node.id] = node
                except Exception:
                    # Non-fatal error on malformed candidate
                    continue

        return cls(nodes)

    def get_downstream(self, skill_id: str) -> List[SkillNode]:
        """Return list of downstream target skills."""
        node = self.get(skill_id)
        if not node:
            return []
        downstream: List[SkillNode] = []
        for target_id in node.handoff_targets:
            target = self.get(target_id)
            if target:
                downstream.append(target)
        return downstream

    def validate_handoff_path(self, from_skill: str, to_skill: str, artifact_type: str) -> None:
        """Validate edge exists and matches consumes/produces type contracts."""
        from_node = self.get(from_skill)
        to_node = self.get(to_skill)

        if from_node and from_node.produces and artifact_type not in from_node.produces:
            raise SomaValidationError(
                f"Skill '{from_skill}' does not produce artifact type '{artifact_type}'. "
                f"Declared produces: {from_node.produces}"
            )

        if from_node and from_node.handoff_targets and to_skill not in from_node.handoff_targets:
            raise SomaValidationError(
                f"Skill '{from_skill}' cannot handoff to '{to_skill}'. "
                f"Allowed targets: {from_node.handoff_targets}"
            )

        if to_node and to_node.consumes and artifact_type not in to_node.consumes:
            raise SomaValidationError(
                f"Skill '{to_skill}' does not consume artifact type '{artifact_type}'. "
                f"Declared consumes: {to_node.consumes}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {k: v.to_dict() for k, v in self._nodes.items()}
