"""Zero-dependency YAML frontmatter serializer.

Contract: ``parse_yaml_subset(dump_frontmatter(d))`` returns ``d`` for str keys and str / int /
finite float / bool / None / list / dict values (tuples and sets come back as lists, dates as ISO
strings, other keys as their str()). Characters the parser would reject or alter are escaped. Input
the parser refuses in every spelling (U+0000), keys that collide once converted with str(), and
input over the parser's DoS caps raise AegisYAMLError here, so a file that cannot be read back is
never written.
"""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional

from aegis_core.yaml_engine.parser import (
    MAX_DEPTH,
    MAX_DOC_BYTES,
    MAX_LINES,
    MAX_SCALAR_CHARS,
    AegisYAMLError,
    _BOOL_FALSE,
    _BOOL_TRUE,
    _FLOAT_RE,
    _INT_RE,
    _NULL_VALUES,
)

_SEQUENCE_TYPES = (list, tuple, set)
_RESERVED_WORDS = _BOOL_TRUE | _BOOL_FALSE | _NULL_VALUES
# Plain keys are limited to identifier-like text so that nothing in a key can be read as YAML
# syntax (':' or '#'), a typed scalar (numbers, booleans, null) or a sequence item.
_PLAIN_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]*")
_PLAIN_UNSAFE_CHARS = frozenset(":#{}[]|>&*!%@`,\"'")
# Control (C0/C1/DEL), format (zero-width, BOM, bidi), surrogate and line/paragraph separator
# characters are rejected by the parser, split lines, or are invisible to a reviewer: always escape.
_ESCAPED_CATEGORIES = frozenset(("Cc", "Cf", "Cs", "Zl", "Zp"))
_NAMED_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r"}


def _needs_escape(ch: str) -> bool:
    return unicodedata.category(ch) in _ESCAPED_CATEGORIES


def _quote(s: str) -> str:
    if "\x00" in s:
        raise AegisYAMLError(f"Cannot serialize {s[:40]!r}: U+0000 (NUL) is not permitted; the parser rejects it raw and escaped")
    out = []
    for ch in s:
        if ch in _NAMED_ESCAPES:
            out.append(_NAMED_ESCAPES[ch])
        elif _needs_escape(ch):
            cp = ord(ch)
            out.append(f"\\u{cp:04X}" if cp <= 0xFFFF else f"\\U{cp:08X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _format_str(s: str) -> str:
    if (
        not s
        or s.strip() != s
        or "---" in s
        or s == "-"
        or s.startswith("- ")  # a sequence item "- - x" is a nested sequence, not the text "- x"
        or any(c in _PLAIN_UNSAFE_CHARS or _needs_escape(c) for c in s)
        or s.lower() in _RESERVED_WORDS
        or _INT_RE.match(s)
        or _FLOAT_RE.match(s)
    ):
        return _quote(s)
    return s


def _format_float(val: float) -> str:
    if not math.isfinite(val):
        raise AegisYAMLError(f"Cannot serialize non-finite float {val!r}: the parser has no representation for it")
    text = repr(val)
    if not _FLOAT_RE.match(text):  # '1e-05' / '1e+20' lack the '.' the parser requires and would read back as str
        mantissa, _, exponent = text.partition("e")
        text = f"{mantissa}.0e{exponent}"
    return text


def _format_scalar(val: object) -> str:
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int):
        try:
            return str(int(val))
        except ValueError:  # CPython's int->str digit limit; far beyond what the parser accepts anyway
            raise AegisYAMLError(
                f"Cannot serialize int: it has more digits than the parser limit MAX_SCALAR_CHARS={MAX_SCALAR_CHARS}"
            ) from None
    if isinstance(val, float):
        return _format_float(val)
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return _format_str(str(val))


def _format_key(key: object) -> str:
    s = str(key)
    if _PLAIN_KEY_RE.fullmatch(s) and s.lower() not in _RESERVED_WORDS:
        return s
    return _quote(s)


def _checked(token: str, what: str) -> str:
    if len(token) > MAX_SCALAR_CHARS:
        raise AegisYAMLError(
            f"Cannot serialize {what}: encoded scalar is {len(token)} characters, over the parser limit "
            f"MAX_SCALAR_CHARS={MAX_SCALAR_CHARS}"
        )
    return token


def _child_depth(depth: int) -> int:
    if depth + 1 > MAX_DEPTH:
        raise AegisYAMLError(f"Cannot serialize: nesting is deeper than the parser limit MAX_DEPTH={MAX_DEPTH}")
    return depth + 1


def _format_leaf(val: object, what: str) -> str:
    if isinstance(val, Mapping):
        return "{}"
    if isinstance(val, _SEQUENCE_TYPES):
        return "[]"
    return _checked(_format_scalar(val), what)


def _dump_lines(d: Mapping[str, Any], indent: int = 0, depth: int = 0) -> List[str]:
    lines: List[str] = []
    prefix = " " * indent
    seen: Dict[str, object] = {}
    for k, v in d.items():
        name = str(k)
        if name in seen:  # e.g. {1: .., "1": ..}: the parser would reject the second as a duplicate key
            raise AegisYAMLError(f"Cannot serialize: keys {seen[name]!r:.60} and {k!r:.60} both serialize as {name[:40]!r}")
        seen[name] = k
        key = _checked(_format_key(k), f"key {name[:40]!r}")
        if isinstance(v, Mapping) and v:
            lines.append(f"{prefix}{key}:")
            lines.extend(_dump_lines(v, indent + 2, _child_depth(depth)))
        elif isinstance(v, _SEQUENCE_TYPES) and v:
            lines.append(f"{prefix}{key}:")
            lines.extend(_dump_seq(v, indent + 2, _child_depth(depth)))
        else:
            lines.append(f"{prefix}{key}: {_format_leaf(v, f'value of key {str(k)[:40]!r}')}")
    return lines


def _dump_seq(items: Iterable[Any], indent: int, depth: int) -> List[str]:
    # Non-empty nested containers go on their own lines under a bare "-" (the parser's block form);
    # writing them inline would turn them into the str() of the Python object.
    lines: List[str] = []
    prefix = " " * indent
    for item in items:
        if isinstance(item, Mapping) and item:
            lines.append(f"{prefix}-")
            lines.extend(_dump_lines(item, indent + 2, _child_depth(depth)))
        elif isinstance(item, _SEQUENCE_TYPES) and item:
            lines.append(f"{prefix}-")
            lines.extend(_dump_seq(item, indent + 2, _child_depth(depth)))
        else:
            lines.append(f"{prefix}- {_format_leaf(item, 'sequence item')}")
    return lines


def dump_frontmatter(data: Mapping[str, Any] | Dict[str, Any], body: Optional[str] = None) -> str:
    """Serialize metadata dictionary to YAML frontmatter string without requiring PyYAML."""
    lines = _dump_lines(dict(data))
    if len(lines) > MAX_LINES:
        raise AegisYAMLError(f"Cannot serialize: {len(lines)} lines is over the parser limit MAX_LINES={MAX_LINES}")
    yaml_text = "\n".join(lines) + "\n"
    size = len(yaml_text.encode("utf-8"))
    if size > MAX_DOC_BYTES:
        raise AegisYAMLError(f"Cannot serialize: {size} bytes is over the parser limit MAX_DOC_BYTES={MAX_DOC_BYTES}")
    if body is not None:
        return f"---\n{yaml_text}---\n{body}"
    return yaml_text


__all__ = [
    "_dump_lines",
    "_format_scalar",
    "dump_frontmatter",
]
