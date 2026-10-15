"""Fail-closed slot resolution binding abstract skill parameters to repo commands."""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, Dict, Mapping, Optional

from aegis_core.errors import AegisValidationError
from aegis_core.yaml import AegisYAML

__all__ = [
    "SlotResolutionError",
    "SlotRegistry",
    "SLOT_REF_PATTERN",
    "PLATFORM_SLOT_PROFILES",
    "DEFAULT_SLOTS",
    "resolve_text_for_platform",
]

SLOT_REF_PATTERN = re.compile(r"\$\{(?:SLOT|RULE)\.([A-Za-z0-9_\-]+)\}|\$\{([A-Za-z0-9_\-]+)\}")

_GEMINI_PROFILE: dict[str, str] = {
    "TOOL_READ": "view_file",
    "TOOL_EDIT": "replace_file_content",
    "TOOL_WRITE": "write_to_file",
    "TOOL_SEARCH": "grep_search",
    "TOOL_RUN": "run_command",
    "TOOL_SUBAGENT": "invoke_subagent",
    "MODEL_FAST": "flash",
    "MODEL_STANDARD": "inherit",
    "MODEL_HEAVY": "pro",
}

_CLAUDE_PROFILE: dict[str, str] = {
    "TOOL_READ": "Read",
    "TOOL_EDIT": "Edit",
    "TOOL_WRITE": "Write",
    "TOOL_SEARCH": "Grep",
    "TOOL_RUN": "Bash",
    "TOOL_SUBAGENT": "Task",
    "MODEL_FAST": "haiku",
    "MODEL_STANDARD": "sonnet",
    "MODEL_HEAVY": "opus",
}

_GENERIC_PROFILE: dict[str, str] = {
    "TOOL_READ": "read_file",
    "TOOL_EDIT": "edit_file",
    "TOOL_WRITE": "write_file",
    "TOOL_SEARCH": "grep",
    "TOOL_RUN": "run_terminal_cmd",
    "TOOL_SUBAGENT": "subagent",
    "MODEL_FAST": "fast-tier",
    "MODEL_STANDARD": "standard-tier",
    "MODEL_HEAVY": "heavy-tier",
}

PLATFORM_SLOT_PROFILES: dict[str, dict[str, str]] = {
    "gemini": dict(_GEMINI_PROFILE),
    "antigravity": dict(_GEMINI_PROFILE),
    "claude": dict(_CLAUDE_PROFILE),
    "claude-code": dict(_CLAUDE_PROFILE),
    "claude-ai": dict(_CLAUDE_PROFILE),
    "claude-desktop": dict(_CLAUDE_PROFILE),
    "cursor": dict(_GENERIC_PROFILE),
    "copilot": dict(_GENERIC_PROFILE),
    "kiro": dict(_GENERIC_PROFILE),
    "generic": dict(_GENERIC_PROFILE),
}

DEFAULT_SLOTS: dict[str, str] = {
    "TEST_RUNNER": "python3 -m pytest -q",
    "LINTER": "ruff check",
    "FORMATTER": "ruff format",
    "TYPE_CHECKER": "mypy",
    "BUILD_TOOL": "python3 -m build",
    **_GEMINI_PROFILE,
}


def _normalize_platform_name(platform: str) -> str:
    norm = (platform or "gemini").strip().lower()
    if norm in ("antigravity", "gemini"):
        return "gemini"
    if norm.startswith("claude"):
        return "claude"
    if norm in PLATFORM_SLOT_PROFILES:
        return norm
    return "generic"


class SlotResolutionError(AegisValidationError):
    """Raised when a required skill slot cannot be resolved fail-closed."""


class SlotRegistry:
    """Manages repository slot bindings from .aegis/slots.yaml."""

    def __init__(self, slots: Optional[Mapping[str, Any]] = None) -> None:
        self._slots: Dict[str, str] = {str(k): str(v) for k, v in (slots or {}).items() if v is not None}

    @classmethod
    def load(cls, workspace_root: Path | str) -> SlotRegistry:
        """Load slot definitions from .aegis/slots.yaml or return empty registry."""
        root = Path(workspace_root)
        slots_file = root / ".aegis" / "slots.yaml"
        if not slots_file.exists():
            return cls({})

        try:
            content = slots_file.read_text(encoding="utf-8")
            doc = AegisYAML.parse_text(content)
            raw_slots = doc.get("slots", {})
            if isinstance(raw_slots, Mapping):
                return cls(raw_slots)
            return cls({})
        except Exception as exc:
            raise SlotResolutionError(f"Failed to parse .aegis/slots.yaml: {exc}") from exc

    @classmethod
    def for_platform(cls, platform: str, workspace: str | Path | None = None) -> SlotRegistry:
        """Create a SlotRegistry pre-populated with platform capability slots and workspace overrides."""
        merged: Dict[str, str] = dict(DEFAULT_SLOTS)
        raw_norm = (platform or "gemini").strip().lower()
        profile = PLATFORM_SLOT_PROFILES.get(raw_norm) or PLATFORM_SLOT_PROFILES.get(_normalize_platform_name(raw_norm), _GENERIC_PROFILE)
        merged.update(profile)
        if workspace is not None:
            ws_reg = cls.load(workspace)
            merged.update(ws_reg.to_dict())
        return cls(merged)

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


def resolve_text_for_platform(
    text: str,
    platform: str,
    workspace: str | Path | None = None,
) -> str:
    """Resolve ${SLOT.*} placeholders for a target platform without raising on unknown slots."""
    registry = SlotRegistry.for_platform(platform, workspace=workspace)
    return registry.resolve(text, strict=False)

