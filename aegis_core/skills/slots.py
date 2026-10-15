"""Fail-closed slot resolution binding abstract skill parameters to repo commands.

Trust model (H5): the repo's .aegis/slots.yaml is untrusted input. It may bind repo
slots such as TEST_RUNNER, but it cannot name AST driver commands or override the
host's TOOL_*/MODEL_* slots; such keys are dropped and reported in ``warnings``.
Commands and tool/model overrides come only from code or the user-scope
~/.aegis/slots.yaml outside the workspace.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import unicodedata
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from aegis_core.errors import AegisValidationError
from aegis_core.yaml_engine.frontmatter import AegisYAML

__all__ = [
    "SlotResolutionError",
    "SlotRegistry",
    "SLOT_REF_PATTERN",
    "PLATFORM_SLOT_PROFILES",
    "DEFAULT_SLOTS",
    "sanitize_slot_value",
    "user_slots_path",
    "MAX_SLOT_VALUE_LEN",
    "MAX_SLOTS_FILE_BYTES",
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
MAX_SLOTS_FILE_BYTES = 64 * 1024
_CAPABILITY_PREFIXES = ("TOOL_", "MODEL_")
_CAPABILITY_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@+\-]*")
_KNOWN_CAPABILITY_KEYS = frozenset(_GENERIC_PROFILE)
_LISTABLE_DRIVER_KEY = re.compile(r"ast_driver(?:_[a-z0-9]{1,8})?")
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


def user_slots_path() -> Optional[Path]:
    """Path of the user-scope slot file (~/.aegis/slots.yaml), or None if no home directory resolves."""
    try:
        return Path.home() / ".aegis" / "slots.yaml"
    except (RuntimeError, KeyError, OSError):  # 3.10+: RuntimeError; 3.9: KeyError from pwd
        return None


def _keys_summary(keys: Sequence[str]) -> str:
    """'N slot(s) (names)' for a warning.

    Keys are repo-chosen and warnings reach the agent, so only key names aegis itself
    defines are listed, at most _MAX_LISTED_KEYS of them; the rest are only counted.
    """
    listed = [k for k in keys if k in _KNOWN_CAPABILITY_KEYS or _LISTABLE_DRIVER_KEY.fullmatch(k)]
    listed = listed[:_MAX_LISTED_KEYS]
    names = ", ".join(repr(k) for k in listed)
    rest = len(keys) - len(listed)
    if rest:
        names = f"{names} and {rest} more" if names else "names not shown"
    return f"{len(keys)} {'slot' if len(keys) == 1 else 'slots'} ({names})"


def _is_within(path: Path, root: Path) -> bool:
    # realpath, not Path.resolve(): it never raises (3.9 resolve raises RuntimeError on loops).
    try:
        Path(os.path.realpath(path)).relative_to(os.path.realpath(root))
        return True
    except ValueError:
        return False


def _read_capped(fd: int, limit: int) -> bytes:
    data = b""
    while len(data) <= limit:
        chunk = os.read(fd, limit + 1 - len(data))
        if not chunk:
            break
        data += chunk
    return data


def _read_slots_file(path: Path, label: str) -> Dict[str, str]:
    """Return the ``slots`` mapping of a slot file, or {} if there is none.

    Raises SlotResolutionError when the file cannot be read, is not a regular file
    (a FIFO blocks, /dev/zero never ends), exceeds MAX_SLOTS_FILE_BYTES or does not
    parse. Read errors name only ``label``, never the path the file resolves to.
    """
    # O_NONBLOCK: opening a FIFO for reading would otherwise wait for a writer. The type
    # check runs on the opened descriptor, so a swap after the check cannot bypass it.
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except (FileNotFoundError, NotADirectoryError):
        return {}
    except OSError as exc:
        raise SlotResolutionError(f"Cannot read {label}") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise SlotResolutionError(f"{label} is not a regular file")
        data = _read_capped(fd, MAX_SLOTS_FILE_BYTES)
    except OSError as exc:
        raise SlotResolutionError(f"Cannot read {label}") from exc
    finally:
        os.close(fd)
    if len(data) > MAX_SLOTS_FILE_BYTES:
        raise SlotResolutionError(f"{label} is larger than {MAX_SLOTS_FILE_BYTES // 1024} KiB")
    try:
        text = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        doc = AegisYAML.parse_text(text)
        raw = doc.get("slots", {})
    except Exception as exc:
        raise SlotResolutionError(f"Failed to parse {label}: {exc}") from exc
    if not isinstance(raw, Mapping):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v is not None}


def _filter_workspace_slots(raw: Mapping[str, str]) -> Tuple[Dict[str, str], List[str]]:
    """Drop keys a repo file may not set; keep ast_driver_<ext> only as a packaged-driver opt-in.

    Returns at most one warning per reason, however many keys the file holds.
    """
    from aegis_core.ast.detect import names_packaged_driver, packaged_driver_for_extension

    kept: Dict[str, str] = {}
    capability: List[str] = []
    no_driver: List[str] = []
    custom: List[str] = []
    for key, value in raw.items():
        if key.startswith(_CAPABILITY_PREFIXES):
            capability.append(key)
            continue
        if not key.strip().lower().startswith("ast_driver"):
            kept[key] = value
            continue
        ext = key[len("ast_driver_"):] if key.startswith("ast_driver_") else ""
        config = packaged_driver_for_extension(ext) if ext else None
        if config is None:
            no_driver.append(key)
            continue
        if not names_packaged_driver(value, config):
            custom.append(key)
            value = config["default_command"]
        kept[key] = value

    warnings: List[str] = []
    if capability:
        warnings.append(
            f"ignored {_keys_summary(capability)} in .aegis/slots.yaml: TOOL_*/MODEL_* slots "
            "come only from the host profile or ~/.aegis/slots.yaml"
        )
    if no_driver:
        warnings.append(
            f"ignored {_keys_summary(no_driver)} in .aegis/slots.yaml: repository files cannot "
            "define AST driver commands; set them in ~/.aegis/slots.yaml"
        )
    if custom:
        warnings.append(
            f"{_keys_summary(custom)} in .aegis/slots.yaml name a custom AST driver command, "
            "which is not executed; the packaged driver is used instead"
        )
    return kept, warnings


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
    """Manages slot bindings from .aegis/slots.yaml (untrusted) and ~/.aegis/slots.yaml (user)."""

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
        """Load the repo's .aegis/slots.yaml as untrusted input; disallowed keys go to ``warnings``.

        Raises SlotResolutionError if the file cannot be read or parsed (see _read_slots_file).
        """
        root = Path(workspace_root)
        path = root / ".aegis" / "slots.yaml"
        if os.path.lexists(path) and not _is_within(path, root):
            # A committed symlink could point the read at any file the user can open.
            return cls({}, warnings=[
                "ignored .aegis/slots.yaml: it resolves to a path outside the workspace"
            ])
        raw = _read_slots_file(path, ".aegis/slots.yaml")
        kept, warnings = _filter_workspace_slots(raw)
        return cls(kept, warnings=warnings)

    @classmethod
    def load_user(cls, workspace_root: Path | str | None = None) -> SlotRegistry:
        """Load the trusted user-scope ~/.aegis/slots.yaml, unless it lies inside the workspace.

        Raises SlotResolutionError if the file exists but cannot be read or parsed.
        """
        path = user_slots_path()
        if path is None:
            return cls({})
        if workspace_root is not None and os.path.lexists(path) and _is_within(path, Path(workspace_root)):
            return cls({}, warnings=[
                "ignored ~/.aegis/slots.yaml as user scope: it lies inside the workspace, "
                "so it is treated as repository content"
            ])
        return cls(_read_slots_file(path, "~/.aegis/slots.yaml"))

    @classmethod
    def for_platform(cls, platform: str, workspace: str | Path | None = None) -> SlotRegistry:
        """Platform capability slots, then user-scope overrides, then the repo's own slots."""
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
                f"ignored {_keys_summary(invalid)} in ~/.aegis/slots.yaml: tool/model names "
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


