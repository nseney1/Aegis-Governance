"""Fail-closed slot resolution binding abstract skill parameters to repo commands."""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, Dict, Mapping, Optional

from aegis_core.errors import SomaValidationError
from aegis_core.yaml import SomaYAML

__all__ = ["SlotResolutionError", "SlotRegistry", "SLOT_REF_PATTERN"]

SLOT_REF_PATTERN = re.compile(r"\$\{(?:SLOT|RULE)\.([A-Za-z0-9_\-]+)\}|\$\{([A-Za-z0-9_\-]+)\}")


class SlotResolutionError(SomaValidationError):
    """Raised when a required skill slot cannot be resolved fail-closed."""


class SlotRegistry:
    """Manages repository slot bindings from .soma/slots.yaml."""

    def __init__(self, slots: Optional[Mapping[str, Any]] = None) -> None:
        self._slots: Dict[str, str] = {str(k): str(v) for k, v in (slots or {}).items() if v is not None}

    @classmethod
    def load(cls, workspace_root: Path | str) -> SlotRegistry:
        """Load slot definitions from .soma/slots.yaml or return empty registry."""
        root = Path(workspace_root)
        slots_file = root / ".aegis" / "slots.yaml"
        if not slots_file.exists():
            slots_file = root / ".soma" / "slots.yaml"
        if not slots_file.exists():
            return cls({})

        try:
            content = slots_file.read_text(encoding="utf-8")
            doc = SomaYAML.parse_text(content)
            raw_slots = doc.get("slots", {})
            if isinstance(raw_slots, Mapping):
                return cls(raw_slots)
            return cls({})
        except Exception as exc:
            raise SlotResolutionError(f"Failed to parse .soma/slots.yaml: {exc}") from exc

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self._slots.get(key, default)

    def resolve(self, template: str, strict: bool = True) -> str:
        """Interpolate ${SLOT.key} or ${key} references.

        If strict=True and a slot is missing, raises SlotResolutionError (fail-closed).
        """
        def _replacer(m: re.Match) -> str:
            key = m.group(1) or m.group(2)
            if key in self._slots:
                return self._slots[key]
            if strict:
                raise SlotResolutionError(f"Unresolved required slot: '{key}'")
            return m.group(0)

        return SLOT_REF_PATTERN.sub(_replacer, template)

    def to_dict(self) -> Dict[str, str]:
        return dict(self._slots)

    def get_ast_driver(self, extension: str) -> Optional[str]:
        """Resolve configured AST driver command for a given file extension."""
        clean_ext = extension.lstrip(".").lower()
        if clean_ext == "py":
            return None
        return self.get(f"ast_driver_{clean_ext}") or self.get("ast_driver")

    def get_configured_extensions(self) -> set[str]:
        """Return the set of source extensions configured with an AST driver, plus '.py'."""
        exts = {".py"}
        for key in self._slots:
            if key.startswith("ast_driver_"):
                ext = key[len("ast_driver_"):].strip().lower()
                if ext:
                    exts.add(f".{ext}" if not ext.startswith(".") else ext)
        return exts
