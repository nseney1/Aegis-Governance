"""Fail-closed slot resolution binding abstract skill parameters to host and user values.

Trust model (H5, D10): the repo's .aegis/config.json is untrusted input. It can only
opt in to the AST drivers that ship inside aegis (``ast.packaged_drivers``); it
cannot name a command or set a slot, and such keys are reported in ``warnings``.
Driver commands and slot overrides (TOOL_*/MODEL_* included) come only from code or
the user-scope ~/.aegis/config.json outside the workspace (aegis_core.config).
"""
from __future__ import annotations

from pathlib import Path
import re
import unicodedata
from typing import Any, Dict, List, Mapping, Optional, Sequence

from aegis_core.errors import AegisValidationError

__all__ = [
    "SlotResolutionError",
    "SlotRegistry",
    "SLOT_REF_PATTERN",
    "PLATFORM_SLOT_PROFILES",
    "DEFAULT_SLOTS",
    "sanitize_slot_value",
    "MAX_SLOT_VALUE_LEN",
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


MAX_SLOT_VALUE_LEN = 80
_CAPABILITY_PREFIXES = ("TOOL_", "MODEL_")
_CAPABILITY_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@+\-]*")
_KNOWN_CAPABILITY_KEYS = frozenset(_GENERIC_PROFILE)
_MAX_LISTED_KEYS = 5
# Cc: C0/C1 controls incl. newlines; Cf: bidi overrides, zero-width chars; Zl/Zp: U+2028/U+2029.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})


def sanitize_slot_value(key: str, value: str) -> Optional[str]:
    """Return ``value`` made safe to inline into agent-facing text, or None to leave it unresolved.

    Control and format characters become spaces, whitespace collapses to one line and
    the result is capped at MAX_SLOT_VALUE_LEN. TOOL_*/MODEL_* values must be a plain
    tool or model name, otherwise None.
    """
    text = "".join(" " if unicodedata.category(ch) in _UNSAFE_CATEGORIES else ch for ch in str(value))
    text = " ".join(text.split())
    if str(key).startswith(_CAPABILITY_PREFIXES):
        if len(text) <= MAX_SLOT_VALUE_LEN and _CAPABILITY_VALUE.fullmatch(text):
            return text
        return None
    return text[:MAX_SLOT_VALUE_LEN] or None


def _keys_summary(keys: Sequence[str]) -> str:
    """'N slot(s) (names)' for a warning; only slot names aegis defines are listed."""
    listed = [k for k in keys if k in _KNOWN_CAPABILITY_KEYS][:_MAX_LISTED_KEYS]
    names = ", ".join(repr(k) for k in listed)
    rest = len(keys) - len(listed)
    if rest:
        names = f"{names} and {rest} more" if names else "names not shown"
    return f"{len(keys)} {'slot' if len(keys) == 1 else 'slots'} ({names})"


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
    """Slot bindings: host profile, ~/.aegis/config.json (user) and .aegis/config.json opt-ins (repo)."""

    def __init__(
        self,
        slots: Optional[Mapping[str, Any]] = None,
        warnings: Optional[Sequence[str]] = None,
    ) -> None:
        self._slots: Dict[str, str] = {str(k): str(v) for k, v in (slots or {}).items() if v is not None}
        self._warnings: List[str] = list(warnings or [])

    @property
    def warnings(self) -> List[str]:
        """Why slot keys were ignored, for callers to surface (doctor, scan)."""
        return list(self._warnings)

    @classmethod
    def load(cls, workspace_root: Path | str) -> SlotRegistry:
        """The repo's packaged-driver opt-ins (``ast_driver_<ext>`` slots) from .aegis/config.json.

        The slot value names the packaged driver and is never run (aegis_core.ast.runner).
        Ignored config keys go to ``warnings``. Raises SlotResolutionError if the file
        exists but cannot be read or parsed.
        """
        from aegis_core.ast.detect import packaged_driver_for_extension
        from aegis_core.config import ConfigError, RepoConfig

        try:
            repo = RepoConfig.load(workspace_root)
        except ConfigError as exc:
            raise SlotResolutionError(str(exc)) from exc
        slots = {}
        warnings = list(repo.warnings)
        unknown = 0
        for ext in repo.packaged_drivers:
            config = packaged_driver_for_extension(ext)
            if config is not None:
                slots[f"ast_driver_{ext}"] = config["default_command"]
            else:
                unknown += 1
        if unknown:
            warnings.append(
                f"ignored {unknown} 'ast.packaged_drivers' entr{'y' if unknown == 1 else 'ies'} in "
                ".aegis/config.json: only extensions with a driver that ships inside aegis can be enabled"
            )
        return cls(slots, warnings=warnings)

    @classmethod
    def load_user(cls, workspace_root: Path | str | None = None) -> SlotRegistry:
        """The trusted user-scope ~/.aegis/config.json: driver commands and slot overrides.

        A user file inside the workspace is ignored with a warning. Raises
        SlotResolutionError if the file exists but cannot be read or parsed.
        """
        from aegis_core.config import ConfigError, UserConfig

        try:
            user = UserConfig.load(workspace_root)
        except ConfigError as exc:
            raise SlotResolutionError(str(exc)) from exc
        slots = dict(user.slots)
        slots.update({f"ast_driver_{ext}": command for ext, command in user.drivers.items()})
        return cls(slots, warnings=user.warnings)

    @classmethod
    def for_platform(cls, platform: str, workspace: str | Path | None = None) -> SlotRegistry:
        """Platform capability slots, then user-scope overrides, then the repo's driver opt-ins."""
        merged: Dict[str, str] = dict(DEFAULT_SLOTS)
        raw_norm = (platform or "gemini").strip().lower()
        profile = PLATFORM_SLOT_PROFILES.get(raw_norm) or PLATFORM_SLOT_PROFILES.get(_normalize_platform_name(raw_norm), _GENERIC_PROFILE)
        merged.update(profile)
        user_reg = cls.load_user(workspace)
        warnings = user_reg.warnings
        invalid: List[str] = []
        for key, value in user_reg.to_dict().items():
            if key.startswith(_CAPABILITY_PREFIXES):
                clean = sanitize_slot_value(key, value)
                if clean is None:
                    invalid.append(key)
                    continue
                value = clean
            merged[key] = value
        if invalid:
            warnings.append(
                f"ignored {_keys_summary(invalid)} in ~/.aegis/config.json: tool/model names "
                f"may use only letters, digits and _.:/@+- (max {MAX_SLOT_VALUE_LEN})"
            )
        if workspace is not None:
            ws_reg = cls.load(workspace)
            warnings.extend(ws_reg.warnings)
            merged.update(ws_reg.to_dict())
        return cls(merged, warnings=warnings)

    def sanitized(self) -> SlotRegistry:
        """Copy whose values are safe to inline into agent-facing text (see sanitize_slot_value)."""
        safe = {}
        for key, value in self._slots.items():
            clean = sanitize_slot_value(key, value)
            if clean is not None:
                safe[key] = clean
        return SlotRegistry(safe, warnings=self._warnings)

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


