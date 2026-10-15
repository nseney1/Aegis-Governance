"""Frontmatter extraction helpers and primary AegisYAML gateway interface."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from aegis_core.yaml_engine.document import AegisDocument
from aegis_core.yaml_engine.parser import (
    AegisYAMLError,
    ZERO_WIDTH_CHARS,
    _CLOSING_DELIM_RE,
    parse_yaml_subset,
)


def split_frontmatter(content: str) -> Tuple[str, Optional[str], str]:
    """The one frontmatter delimiter scanner: ``(status, frontmatter text, body)``.

    ``status`` is ``"ok"``, ``"none"`` (the text does not start with ``---``; the body is
    the whole text) or ``"unterminated"`` (no closing ``---`` line). Leading zero-width
    characters (a BOM) are not part of the text. The façades below keep their own
    failure contracts on top of it (defense #30).
    """
    for zw in ZERO_WIDTH_CHARS:
        if content.startswith(zw):
            content = content[len(zw):]
    if not content.startswith("---"):
        return "none", None, content
    nl = content.find("\n")
    if nl == -1:
        return "unterminated", None, content
    m = _CLOSING_DELIM_RE.search(content, nl + 1)
    if not m:
        return "unterminated", None, content
    return "ok", content[nl + 1 : m.start()], content[m.end():]


def _get_body(content: str) -> str:
    """Extract body text after YAML frontmatter delimiters."""
    status, _fm, body = split_frontmatter(content)
    return body.strip() if status == "ok" else body


def parse_frontmatter(content: str) -> Optional[Dict[str, Any]]:
    """Legacy helper: parse frontmatter mapping or return None/empty dict."""
    if not isinstance(content, str):
        return None
    status, fm_text, _body = split_frontmatter(content)
    if status == "none":
        return {}
    if status == "unterminated" or fm_text is None:
        return None
    fm_text = fm_text.strip()
    if not fm_text:
        return {}
    try:
        return parse_yaml_subset(fm_text)
    except Exception:
        return None


def parse_rule_frontmatter(content_or_path: str) -> Tuple[Dict[str, Any], str]:
    """Parse a rule file or markdown string into (frontmatter_dict, body)."""
    if os.path.exists(content_or_path) and os.path.isfile(content_or_path):
        with open(content_or_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
    else:
        content = content_or_path

    status, fm_text, body = split_frontmatter(content)
    if status == "none":
        raise ValueError("No frontmatter delimiter")
    if status == "unterminated" or fm_text is None:
        raise ValueError("Unclosed frontmatter")
    fm_text = fm_text.strip()
    data = {} if not fm_text else parse_yaml_subset(fm_text)
    return data, body.lstrip("\r\n")


def parse_rule_file(filepath: str) -> Tuple[Dict[str, Any], str]:
    """Parse the rule file at ``filepath`` into (frontmatter_dict, body).

    Raises RuleNotFoundError if it is not a file and RuleParseError if its
    frontmatter is missing or malformed. Public through ``aegis_sdk``.
    """
    from aegis_core.errors import RuleNotFoundError, RuleParseError

    if not os.path.isfile(filepath):
        raise RuleNotFoundError(f"Rule file not found: {filepath}")
    try:
        return parse_rule_frontmatter(filepath)
    except ValueError as exc:
        raise RuleParseError(f"Error parsing rule {filepath}: {exc}") from exc


class AegisYAML:
    """Primary zero-dependency AegisYAML engine."""

    @staticmethod
    def parse_text(content: str) -> AegisDocument:
        """Parse pure in-memory markdown or yaml string into an AegisDocument. Never touches disk."""
        # Same leading-only strip as the other entry points: removing these characters anywhere in the
        # document silently altered metadata values and the body (review M5).
        status, fm_text, body = split_frontmatter(content)
        if status == "ok" and fm_text is not None:
            fm_text = fm_text.strip()
            metadata = parse_yaml_subset(fm_text) if fm_text else {}
            return AegisDocument(metadata=metadata, body=body.strip())
        working_content = body

        data = parse_yaml_subset(working_content)
        return AegisDocument(metadata=data, body="")

    @staticmethod
    def parse_file(rel_path: str | Path, workspace: Any) -> AegisDocument:
        """Parse file strictly confined within workspace boundaries, rejecting symlinks."""
        if not hasattr(workspace, "confine_path"):
            raise AegisYAMLError("Workspace with confine_path() required to parse file")

        ws_root = getattr(workspace, "root", None)
        if ws_root:
            raw_target = Path(ws_root) / rel_path
            if raw_target.is_symlink():
                raise AegisYAMLError(f"Symlink parsing prohibited for security: {raw_target}")

        resolved = workspace.confine_path(rel_path)
        if isinstance(resolved, tuple):
            resolved_abs = resolved[0]
        else:
            resolved_abs = resolved

        path_obj = Path(resolved_abs)
        if not path_obj.exists():
            raise FileNotFoundError(f"File does not exist: {resolved_abs}")
        if path_obj.is_symlink():
            raise AegisYAMLError(f"Symlink parsing prohibited for security: {resolved_abs}")

        content = path_obj.read_text(encoding="utf-8")
        doc = AegisYAML.parse_text(content)
        doc._source_path = str(resolved_abs)
        return doc

__all__ = [
    "AegisYAML",
    "_get_body",
    "parse_frontmatter",
    "parse_rule_file",
    "parse_rule_frontmatter",
    "split_frontmatter",
]
