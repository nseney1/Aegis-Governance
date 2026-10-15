"""Frontmatter extraction helpers and primary AegisYAML gateway interface."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from aegis_core.yaml_engine.document import AegisDocument
from aegis_core.yaml_engine.parser import (
    AegisYAMLError,
    ZERO_WIDTH_CHARS,
    _CLOSING_DELIM_RE,
    parse_yaml_subset,
)
from aegis_core.yaml_engine.serializer import dump_frontmatter


def _get_body(content: str) -> str:
    """Extract body text after YAML frontmatter delimiters."""
    for zw in ZERO_WIDTH_CHARS:
        if content.startswith(zw):
            content = content[len(zw):]
    if not content.startswith("---"):
        return content
    nl = content.find("\n")
    if nl == -1:
        return content
    m = _CLOSING_DELIM_RE.search(content, nl + 1)
    if not m:
        return content
    return content[m.end():].strip()


def parse_frontmatter(content: str) -> Optional[Dict[str, Any]]:
    """Legacy helper: parse frontmatter mapping or return None/empty dict."""
    if not isinstance(content, str):
        return None

    for zw in ZERO_WIDTH_CHARS:
        if content.startswith(zw):
            content = content[len(zw):]

    if not content.startswith("---"):
        return {}

    nl = content.find("\n")
    if nl == -1:
        return None

    rest = content[nl + 1 :]
    m = _CLOSING_DELIM_RE.search(rest)
    if not m:
        return None

    fm_text = rest[: m.start()].strip()
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

    for zw in ZERO_WIDTH_CHARS:
        if content.startswith(zw):
            content = content[len(zw):]

    if not content.startswith("---"):
        raise ValueError("No frontmatter delimiter")

    nl = content.find("\n")
    if nl == -1:
        raise ValueError("Unclosed frontmatter")
    m = _CLOSING_DELIM_RE.search(content, nl + 1)
    if not m:
        raise ValueError("Unclosed frontmatter")

    fm_text = content[nl + 1 : m.start()].strip()
    data = {} if not fm_text else parse_yaml_subset(fm_text)

    body = content[m.end():].lstrip("\r\n")
    return data, body


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
        working_content = content
        for zw in ZERO_WIDTH_CHARS:
            if working_content.startswith(zw):
                working_content = working_content[len(zw):]

        if working_content.startswith("---"):
            nl = working_content.find("\n")
            if nl != -1:
                m = _CLOSING_DELIM_RE.search(working_content, nl + 1)
                if m:
                    fm_text = working_content[nl + 1 : m.start()].strip()
                    body = working_content[m.end():].strip()
                    metadata = parse_yaml_subset(fm_text) if fm_text else {}
                    return AegisDocument(metadata=metadata, body=body)

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

    @staticmethod
    def dump(doc: Union[AegisDocument, Dict[str, Any]], body: Optional[str] = None) -> str:
        """Serialize document to YAML frontmatter string."""
        if isinstance(doc, AegisDocument):
            target_body = body if body is not None else doc.body
            return dump_frontmatter(doc.metadata, body=target_body if target_body else None)
        return dump_frontmatter(doc, body=body)


__all__ = [
    "AegisYAML",
    "_get_body",
    "parse_frontmatter",
    "parse_rule_file",
    "parse_rule_frontmatter",
]
