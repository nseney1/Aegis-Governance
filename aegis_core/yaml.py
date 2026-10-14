"""Zero-dependency AegisYAML parser, serializer, and polymorphic document model.

Provides high-speed, secure parsing of YAML subset and frontmatter markdown documents
with zero external dependencies (pure Python standard library).

Includes strict DoS protection:
- MAX_DOC_BYTES (512KB)
- MAX_SCALAR_CHARS (4096)
- MAX_LINES (5000)
- MAX_DEPTH (20)
- Anti-poisoning zero-width character stripping
- Strict duplicate key rejection
- Confined workspace path resolution
"""
from __future__ import annotations

import collections.abc
from datetime import date, datetime
import os
from pathlib import Path
import re
from typing import Any, Dict, Iterator, List, Mapping, Optional, Set, Tuple, Union

# ── Security & DoS Limits ───────────────────────────────────────────────────
MAX_DOC_BYTES: int = 512 * 1024  # 512 KB
MAX_SCALAR_CHARS: int = 4096     # 4 KB per scalar
MAX_LINES: int = 5000            # Max lines per document
MAX_DEPTH: int = 20              # Max nesting depth

ZERO_WIDTH_CHARS = ("\ufeff", "\u200b", "\u200c", "\u200d")


class AegisYAMLError(ValueError):
    """Base error raised when AegisYAML validation, parsing, or security limits fail."""


SomaYAMLError = AegisYAMLError
FrontmatterError = AegisYAMLError


_BOOL_TRUE = frozenset(("true", "yes", "on"))
_BOOL_FALSE = frozenset(("false", "no", "off"))
_NULL_VALUES = frozenset(("", "~", "null"))
_INT_RE = re.compile(r"^[-+]?[0-9]+$")
_FLOAT_RE = re.compile(
    r"^[-+]?(?:[0-9]+\.[0-9]*(?:[eE][-+][0-9]+)?|\.[0-9]+(?:[eE][-+][0-9]+)?)$"
)
_SEQ_MAPPING_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*:(?:\s|$)")
_UNSUPPORTED_PREFIXES = ("&", "*", "!", "%", "@", "`")
_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
    "/": "/",
    "'": "'",
    " ": " ",
}
_CLOSING_DELIM_RE = re.compile(r"(?m)^---[ \t]*\r?$")


# ── Unified Domain Model ─────────────────────────────────────────────────────

class AegisDocument(collections.abc.Mapping):
    """Unified polymorphic document model representing Rules or Skills.

    Implements collections.abc.Mapping for transparent dictionary drop-in compatibility.
    """

    def __init__(
        self,
        metadata: Dict[str, Any],
        body: str = "",
        kind: Optional[str] = None,
        source_path: Optional[str] = None,
    ) -> None:
        self._metadata: Dict[str, Any] = dict(metadata)
        self._body: str = body
        self._source_path: Optional[str] = source_path
        self._kind: str = self._resolve_kind(kind)
        self._apply_defaults()

    def _resolve_kind(self, explicit_kind: Optional[str]) -> str:
        if explicit_kind:
            return explicit_kind.strip().lower()
        if "kind" in self._metadata:
            return str(self._metadata["kind"]).strip().lower()

        # Auto-Inference for Active Cells, Rules, and Skills
        cell_types = {
            "wall", "membrane", "vacuole", "chloroplast", "plasmodesma", "plasmodesmata",
            "invariant", "boundary", "trap", "persona", "contract", "gate"
        }
        m_type = str(self._metadata.get("type", "")).lower()
        if m_type in cell_types:
            return "rule"

        if any(k in self._metadata for k in ("tier", "consumes", "produces", "handoff_targets")):
            return "skill"

        return "rule"

    def _apply_defaults(self) -> None:
        if self._kind == "rule":
            if "type" not in self._metadata:
                self._metadata["type"] = "advisory"
            if "target_paths" not in self._metadata:
                self._metadata["target_paths"] = []
            if "decay" not in self._metadata:
                self._metadata["decay"] = True
        elif self._kind == "skill":
            if "tier" not in self._metadata:
                self._metadata["tier"] = "method"
            if "consumes" not in self._metadata:
                self._metadata["consumes"] = []
            if "produces" not in self._metadata:
                self._metadata["produces"] = []
            if "handoff_targets" not in self._metadata:
                self._metadata["handoff_targets"] = []

    # ── Mapping Protocol Implementation ──────────────────────────────────────

    def __getitem__(self, key: str) -> Any:
        return self._metadata[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._metadata)

    def __len__(self) -> int:
        return len(self._metadata)

    def __contains__(self, key: object) -> bool:
        return key in self._metadata

    def get(self, key: str, default: Any = None) -> Any:
        return self._metadata.get(key, default)

    def keys(self):
        return self._metadata.keys()

    def values(self):
        return self._metadata.values()

    def items(self):
        return self._metadata.items()

    # ── Domain Accessors ─────────────────────────────────────────────────────

    @property
    def metadata(self) -> Dict[str, Any]:
        return self._metadata

    @property
    def body(self) -> str:
        return self._body

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def id(self) -> Optional[str]:
        val = self._metadata.get("id") or self._metadata.get("name")
        return str(val) if val is not None else None

    @property
    def name(self) -> Optional[str]:
        return self.id

    @property
    def type(self) -> Optional[str]:
        val = self._metadata.get("type")
        return str(val) if val is not None else None

    @property
    def enforcement(self) -> Optional[str]:
        val = self._metadata.get("enforcement")
        return str(val) if val is not None else None

    @property
    def target_paths(self) -> List[str]:
        paths = self._metadata.get("target_paths", [])
        return list(paths) if isinstance(paths, (list, tuple)) else []

    @property
    def tier(self) -> Optional[str]:
        val = self._metadata.get("tier")
        return str(val) if val is not None else None

    @property
    def consumes(self) -> List[str]:
        c = self._metadata.get("consumes", [])
        return list(c) if isinstance(c, (list, tuple)) else []

    @property
    def produces(self) -> List[str]:
        p = self._metadata.get("produces", [])
        return list(p) if isinstance(p, (list, tuple)) else []

    @property
    def handoff_targets(self) -> List[str]:
        h = self._metadata.get("handoff_targets", [])
        return list(h) if isinstance(h, (list, tuple)) else []

    @property
    def decay(self) -> bool:
        return bool(self._metadata.get("decay", False))

    @property
    def source_path(self) -> Optional[str]:
        return self._source_path

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._metadata)

    def __repr__(self) -> str:
        return f"AegisDocument(kind={self._kind!r}, id={self.id!r}, keys={list(self._metadata.keys())!r})"


# ── Parser Internals with DoS Protections ───────────────────────────────────

def _unescape_double(body: str) -> str:
    out: List[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt == "0":
                raise SomaYAMLError("Escape sequence \\0 is not permitted")
            if nxt == "\r" and i + 2 < len(body) and body[i + 2] == "\n":
                i += 3
                continue
            if nxt == "\n":
                i += 2
                continue
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
                i += 2
                continue
            if nxt == "u" and i + 5 < len(body):
                hex_part = body[i + 2 : i + 6]
                try:
                    out.append(chr(int(hex_part, 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            if nxt == "U" and i + 9 < len(body):
                hex_part = body[i + 2 : i + 10]
                try:
                    out.append(chr(int(hex_part, 16)))
                    i += 10
                    continue
                except ValueError:
                    pass
            out.append(nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t":
        i += 1
    return i


def _read_token(text: str, start: int, stops: str) -> Tuple[str, int]:
    i = start
    quote: Optional[str] = None
    while i < len(text):
        ch = text[i]
        if quote:
            if quote == '"' and ch == "\\" and i + 1 < len(text):
                i += 2
                continue
            if quote == "'" and ch == "'" and i + 1 < len(text) and text[i + 1] == "'":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'") and i == start:
            quote = ch
            i += 1
            continue
        if ch in stops:
            break
        i += 1
    if quote:
        raise FrontmatterError("unterminated quoted string")
    return text[start:i], i


def _strip_comment(line: str, quote: Optional[str] = None) -> str:
    """Drop a trailing ` #` comment that is not inside quotes."""
    if "#" not in line:
        return line
    out: List[str] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if quote == '"' and ch == "\\" and i + 1 < len(line):
                out.append(line[i : i + 2])
                i += 2
                continue
            if quote == "'" and ch == "'" and i + 1 < len(line) and line[i + 1] == "'":
                out.append(line[i : i + 2])
                i += 2
                continue
            if ch == quote:
                quote = None
            out.append(ch)
        elif ch in ('"', "'"):
            quote = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _find_unclosed_quote(line: str, initial_quote: Optional[str] = None) -> Optional[str]:
    quote = initial_quote
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if quote == '"' and ch == "\\" and i + 1 < len(line):
                i += 2
                continue
            if quote == "'" and ch == "'" and i + 1 < len(line) and line[i + 1] == "'":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
        i += 1
    return quote


def _is_quote_closed(text: str, quote_char: str) -> bool:
    if len(text) < 2:
        return False
    if quote_char == '"':
        if not text.endswith('"'):
            return False
        bs_count = 0
        k = len(text) - 2
        while k >= 0 and text[k] == "\\":
            bs_count += 1
            k -= 1
        return (bs_count % 2) == 0
    else:  # quote_char == "'"
        if not text.endswith("'"):
            return False
        q_count = 0
        k = len(text) - 1
        while k >= 0 and text[k] == "'":
            q_count += 1
            k -= 1
        if q_count == len(text):
            return q_count % 2 == 0
        return q_count % 2 == 1


def _parse_scalar(raw: str, lineno: int = 1) -> Any:
    """Convert a raw scalar token to a Python value with DoS scalar limits."""
    text = raw.strip()
    if "\\0" in raw:
        raise SomaYAMLError("Escape sequence \\0 is not permitted")
    if len(text) > MAX_SCALAR_CHARS:
        raise SomaYAMLError(
            f"Scalar length ({len(text)}) exceeds maximum limit ({MAX_SCALAR_CHARS}) at line {lineno}"
        )

    if text[:1] in ('"', "'"):
        if len(text) < 2 or text[-1] != text[0]:
            raise FrontmatterError(f"unterminated quoted scalar: {text[:24]!r}")
        body = text[1:-1]
        return _unescape_double(body) if text[0] == '"' else body.replace("''", "'")
    if text[:1] in ("[", "{"):
        value, idx = _parse_flow(text, 0, lineno=lineno)
        if text[idx:].strip():
            raise FrontmatterError(f"trailing content after flow collection: {text[idx:][:20]!r}")
        return value
    lowered = text.lower()
    if lowered in _NULL_VALUES:
        return None
    if lowered in _BOOL_TRUE:
        return True
    if lowered in _BOOL_FALSE:
        return False
    if _INT_RE.match(text):
        return int(text)
    if _FLOAT_RE.match(text):
        return float(text)
    if text[:1] in _UNSUPPORTED_PREFIXES:
        raise FrontmatterError(f"unsupported YAML construct: {text[:24]!r}")
    return text


def _parse_flow(text: str, i: int, lineno: int = 1, depth: int = 0) -> Tuple[Any, int]:
    if depth > MAX_DEPTH:
        raise SomaYAMLError("Maximum YAML nesting depth exceeded")
    i = _skip_ws(text, i)
    if i >= len(text):
        raise FrontmatterError("unexpected end of flow collection")
    if text[i] == "[":
        return _parse_flow_seq(text, i, lineno=lineno, depth=depth + 1)
    if text[i] == "{":
        return _parse_flow_map(text, i, lineno=lineno, depth=depth + 1)
    raw, i = _read_token(text, i, ",]}")
    if not raw.strip():
        raise FrontmatterError("empty entry in flow collection")
    return _parse_scalar(raw, lineno=lineno), i


def _parse_flow_seq(text: str, i: int, lineno: int = 1, depth: int = 0) -> Tuple[List[Any], int]:
    if depth > MAX_DEPTH:
        raise SomaYAMLError("Maximum YAML nesting depth exceeded")
    items = []
    i = _skip_ws(text, i + 1)
    if i < len(text) and text[i] == "]":
        return items, i + 1
    while True:
        value, i = _parse_flow(text, i, lineno=lineno, depth=depth)
        items.append(value)
        i = _skip_ws(text, i)
        if i >= len(text):
            raise FrontmatterError("unterminated flow sequence")
        if text[i] == "]":
            return items, i + 1
        if text[i] != ",":
            raise FrontmatterError(f"expected ',' in flow sequence, got {text[i]!r}")
        i = _skip_ws(text, i + 1)
        if i < len(text) and text[i] == "]":
            return items, i + 1


def _parse_flow_map(text: str, i: int, lineno: int = 1, depth: int = 0) -> Tuple[Dict[str, Any], int]:
    if depth > MAX_DEPTH:
        raise SomaYAMLError("Maximum YAML nesting depth exceeded")
    mapping: Dict[str, Any] = {}
    i = _skip_ws(text, i + 1)
    if i < len(text) and text[i] == "}":
        return mapping, i + 1
    while True:
        raw_key, i = _read_token(text, i, ":")
        if i >= len(text) or text[i] != ":":
            raise FrontmatterError("expected ':' in flow mapping")
        if not raw_key.strip():
            raise FrontmatterError("empty key in flow mapping")
        key = str(_parse_scalar(raw_key, lineno=lineno))
        if key in mapping:
            raise SomaYAMLError(f"Duplicate key '{key}' detected at line {lineno}")
        i = _skip_ws(text, i + 1)
        value, i = _parse_flow(text, i, lineno=lineno, depth=depth)
        mapping[key] = value
        i = _skip_ws(text, i)
        if i >= len(text):
            raise FrontmatterError("unterminated flow mapping")
        if text[i] == "}":
            return mapping, i + 1
        if text[i] != ",":
            raise FrontmatterError(f"expected ',' in flow mapping, got {text[i]!r}")
        i = _skip_ws(text, i + 1)
        if i < len(text) and text[i] == "}":
            return mapping, i + 1


def _prepare_lines(text: str) -> List[Tuple[int, str, int]]:
    """Tokenize YAML lines with indentation tracking and comment stripping."""
    raw_lines = text.splitlines()
    if len(raw_lines) > MAX_LINES:
        raise SomaYAMLError(f"Document line count ({len(raw_lines)}) exceeds maximum line limit ({MAX_LINES})")

    prepared: List[Tuple[int, str, int]] = []
    in_block_scalar = False
    scalar_indent = 0
    in_quote: Optional[str] = None

    for lineno, raw in enumerate(raw_lines, 1):
        for ch in raw:
            if ord(ch) < 32 and ch not in ("\t", "\n", "\r"):
                raise SomaYAMLError(f"Control character {ord(ch):#04x} is prohibited at line {lineno}")
        if raw.startswith("\t") or (len(raw) - len(raw.lstrip(" ")) > 0 and raw.lstrip(" ").startswith("\t")):
            raise FrontmatterError(f"line {lineno}: tab characters are not allowed for indentation in YAML")
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()

        # Block scalar mode: preserve all content verbatim including #
        if in_block_scalar:
            if not stripped:
                prepared.append((scalar_indent + 1, "", lineno))
                continue
            if indent > scalar_indent:
                prepared.append((indent, stripped, lineno))
                continue
            in_block_scalar = False

        # Multiline quoted scalar mode: preserve comments inside quotes
        if in_quote is not None:
            if not stripped:
                prepared.append((indent, "", lineno))
                continue
            line = _strip_comment(raw, quote=in_quote)
            in_quote = _find_unclosed_quote(line, initial_quote=in_quote)
            prepared.append((indent, line.strip(), lineno))
            continue

        # Normal line processing
        line = _strip_comment(raw)
        if not line.strip():
            continue
        line_indent = len(line) - len(line.lstrip(" "))
        line_content = line.strip()
        prepared.append((line_indent, line_content, lineno))

        # Check if line starts a block scalar or multiline quote
        idx = line_content.find(":")
        if idx != -1:
            rest = line_content[idx + 1 :].strip()
            if rest in ("|", "|-", "|+", ">", ">-", ">+"):
                in_block_scalar = True
                scalar_indent = line_indent
                continue
            if rest[:1] in ('"', "'"):
                quote_char = rest[0]
                if _find_unclosed_quote(rest) is not None:
                    in_quote = quote_char
        elif line_content.startswith("- "):
            rest = line_content[2:].strip()
            if rest[:1] in ('"', "'"):
                if _find_unclosed_quote(rest) is not None:
                    in_quote = rest[0]
    return prepared


def _parse_collection(lines: List[Tuple[int, str, int]], start: int, indent: int, depth: int = 0) -> Tuple[Any, int]:
    if depth > MAX_DEPTH:
        raise SomaYAMLError("Maximum YAML nesting depth exceeded")
    content = lines[start][1]
    if content == "-" or content.startswith("- "):
        return _parse_block_seq(lines, start, indent, depth=depth)
    return _parse_block_map(lines, start, indent, depth=depth)


def _parse_block_scalar(
    lines: List[Tuple[int, str, int]], start: int, parent_indent: int, style: str
) -> Tuple[str, int]:
    """Parse block scalar (| or >) lines with chomping indicators."""
    scalar_lines: List[str] = []
    base_indent = None
    i = start
    while i < len(lines):
        line_indent, content, lineno = lines[i]
        if line_indent <= parent_indent and content:
            break
        if base_indent is None and content:
            base_indent = line_indent
        if not content:
            scalar_lines.append("")
        else:
            rel = line_indent - (base_indent if base_indent is not None else line_indent)
            scalar_lines.append(" " * max(0, rel) + content)
        i += 1
    if style.startswith("|"):
        res = "\n".join(scalar_lines)
    else:
        res = " ".join(scalar_lines)
    if style.endswith("-"):
        res = res.rstrip("\n")
    elif style.endswith("+"):
        if not res.endswith("\n"):
            res = res + "\n"
    else:
        res = res.rstrip("\n") + "\n" if res.rstrip("\n") else ""
    return res, i


def _parse_block_map(
    lines: List[Tuple[int, str, int]], start: int, indent: int, depth: int = 0
) -> Tuple[Dict[str, Any], int]:
    if depth > MAX_DEPTH:
        raise SomaYAMLError("Maximum YAML nesting depth exceeded")
    mapping: Dict[str, Any] = {}
    i = start
    while i < len(lines):
        line_indent, content, lineno = lines[i]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise FrontmatterError(f"line {lineno}: unexpected indentation")
        if content == "-" or content.startswith("- "):
            raise FrontmatterError(f"line {lineno}: unexpected sequence item inside a mapping")
        raw_key, idx = _read_token(content, 0, ":")
        if idx >= len(content) or content[idx] != ":":
            raise FrontmatterError(f"line {lineno}: expected 'key: value'")
        if not raw_key.strip():
            raise FrontmatterError(f"line {lineno}: missing key")
        key = str(_parse_scalar(raw_key, lineno=lineno))
        if key in mapping:
            raise SomaYAMLError(f"Duplicate key '{key}' detected at line {lineno}")
        rest = content[idx + 1 :].strip()

        # Block scalar (| or >)
        if rest in ("|", "|-", "|+", ">", ">-", ">+"):
            mapping[key], i = _parse_block_scalar(lines, i + 1, indent, rest)
            continue

        if rest:
            # Quoted string that wraps across lines
            if rest[:1] in ('"', "'"):
                quote_char = rest[0]
                j = i
                accum = rest
                while not _is_quote_closed(accum, quote_char):
                    j += 1
                    if j >= len(lines):
                        raise FrontmatterError(f"line {lines[i][2]}: unterminated quoted string")
                    if lines[j][0] <= indent and lines[j][1]:
                        raise FrontmatterError(f"line {lines[j][2]}: unterminated quoted string before sibling key")
                    accum = accum + "\n" + lines[j][1]
                i = j + 1
                mapping[key] = _parse_scalar(accum, lineno=lineno)
                continue
            elif not rest[:1] in ("[", "{"):
                # Plain scalar: continuation lines indented > indent
                j = i + 1
                while j < len(lines):
                    next_indent, next_content, next_lineno = lines[j]
                    if next_indent <= indent:
                        break
                    if _SEQ_MAPPING_RE.match(next_content) or next_content.startswith("- ") or next_content == "-":
                        break
                    rest = rest + " " + next_content
                    j += 1
                i = j
                mapping[key] = _parse_scalar(rest, lineno=lineno)
                continue
            else:
                mapping[key] = _parse_scalar(rest, lineno=lineno)
                i += 1
                continue

        # Empty inline value:
        # Check if next line is sequence at same indent (e.g. target_paths:\n- item)
        if i + 1 < len(lines) and lines[i + 1][0] == indent and (lines[i + 1][1] == "-" or lines[i + 1][1].startswith("- ")):
            mapping[key], i = _parse_block_seq(lines, i + 1, indent, depth=depth + 1)
        elif i + 1 < len(lines) and lines[i + 1][0] > indent:
            mapping[key], i = _parse_collection(lines, i + 1, lines[i + 1][0], depth=depth + 1)
        else:
            mapping[key] = None
            i += 1
    return mapping, i


def _parse_block_seq(
    lines: List[Tuple[int, str, int]], start: int, indent: int, depth: int = 0
) -> Tuple[List[Any], int]:
    if depth > MAX_DEPTH:
        raise SomaYAMLError("Maximum YAML nesting depth exceeded")
    items: List[Any] = []
    i = start
    while i < len(lines):
        line_indent, content, lineno = lines[i]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise FrontmatterError(f"line {lineno}: unexpected indentation in sequence")
        if not (content == "-" or content.startswith("- ")):
            break
        body = content[1:].strip()
        if not body:
            if i + 1 < len(lines) and lines[i + 1][0] > indent:
                value, i = _parse_collection(lines, i + 1, lines[i + 1][0], depth=depth + 1)
                items.append(value)
            else:
                items.append(None)
                i += 1
            continue
        if _SEQ_MAPPING_RE.match(body):
            item_map: Dict[str, Any] = {}
            k, idx = _read_token(body, 0, ":")
            v = body[idx + 1 :].strip()
            key_name = str(_parse_scalar(k, lineno=lineno))
            item_map[key_name] = _parse_scalar(v, lineno=lineno) if v else None
            j = i + 1
            while j < len(lines):
                ni, nc, nl = lines[j]
                if ni <= indent or nc.startswith("- ") or nc == "-":
                    break
                if ":" in nc:
                    nk, nidx = _read_token(nc, 0, ":")
                    nv = nc[nidx + 1 :].strip()
                    nkey = str(_parse_scalar(nk, lineno=nl))
                    if nkey in item_map:
                        raise SomaYAMLError(f"Duplicate key '{nkey}' detected at line {nl}")
                    item_map[nkey] = _parse_scalar(nv, lineno=nl) if nv else None
                j += 1
            items.append(item_map)
            i = j
            continue
        if body[:1] in ('"', "'"):
            quote_char = body[0]
            j = i
            accum = body
            while not _is_quote_closed(accum, quote_char):
                j += 1
                if j >= len(lines):
                    raise FrontmatterError(f"line {lines[i][2]}: unterminated quoted string")
                if lines[j][0] <= indent and lines[j][1]:
                    raise FrontmatterError(f"line {lines[j][2]}: unterminated quoted string before sibling item")
                accum = accum + "\n" + lines[j][1]
            items.append(_parse_scalar(accum, lineno=lineno))
            i = j + 1
            continue
        items.append(_parse_scalar(body, lineno=lineno))
        i += 1
    return items, i


def parse_yaml_subset(text: str) -> Dict[str, Any]:
    """Parse YAML subset with DoS guards. Raises FrontmatterError/SomaYAMLError."""
    raw_bytes = text.encode("utf-8")
    if len(raw_bytes) > MAX_DOC_BYTES:
        raise SomaYAMLError(f"Document size ({len(raw_bytes)} bytes) exceeds maximum allowed size ({MAX_DOC_BYTES} bytes)")

    working_text = text
    for zw in ZERO_WIDTH_CHARS:
        working_text = working_text.replace(zw, "")

    lines = _prepare_lines(working_text)
    if not lines:
        return {}
    value, idx = _parse_collection(lines, 0, lines[0][0], depth=0)
    if idx != len(lines):
        raise FrontmatterError(f"line {lines[idx][2]}: unparsed content")
    if not isinstance(value, dict):
        raise FrontmatterError(f"Expected YAML mapping at document root, got {type(value).__name__}")
    return value


# ── Serializer API ───────────────────────────────────────────────────────────

def dump_frontmatter(data: Mapping[str, Any] | Dict[str, Any], body: Optional[str] = None) -> str:
    """Serialize metadata dictionary to YAML frontmatter string without requiring PyYAML."""
    def _format_scalar(val: object) -> str:
        if val is None:
            return "null"
        if isinstance(val, bool):
            return "true" if val else "false"
        if isinstance(val, (int, float)):
            return str(val)
        if isinstance(val, (datetime, date)):
            return val.isoformat()
        s = str(val)
        if (
            not s
            or any(c in s for c in ":#{}[]|>&*!%@`,\n\"'")
            or "---" in s
            or s.strip() != s
            or s.lower() in _BOOL_TRUE
            or s.lower() in _BOOL_FALSE
            or s.lower() in _NULL_VALUES
            or _INT_RE.match(s)
            or _FLOAT_RE.match(s)
        ):
            escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            return f'"{escaped}"'
        return s

    def _dump_lines(d: Mapping[str, Any], indent: int = 0) -> List[str]:
        lines: List[str] = []
        prefix = " " * indent
        for k, v in d.items():
            key_str = str(k)
            if isinstance(v, (dict, Mapping)):
                if not v:
                    lines.append(f"{prefix}{key_str}: {{}}")
                else:
                    lines.append(f"{prefix}{key_str}:")
                    lines.extend(_dump_lines(v, indent + 2))
            elif isinstance(v, (list, tuple, set)):
                if not v:
                    lines.append(f"{prefix}{key_str}: []")
                else:
                    lines.append(f"{prefix}{key_str}:")
                    for item in v:
                        if isinstance(item, (dict, Mapping)):
                            lines.append(f"{prefix}  -")
                            lines.extend(_dump_lines(item, indent + 4))
                        else:
                            lines.append(f"{prefix}  - {_format_scalar(item)}")
            else:
                lines.append(f"{prefix}{key_str}: {_format_scalar(v)}")
        return lines

    dict_data = dict(data)
    yaml_text = "\n".join(_dump_lines(dict_data)) + "\n"
    if body is not None:
        return f"---\n{yaml_text}---\n{body}"
    return yaml_text


# ── Frontmatter Helpers ───────────────────────────────────────────────────────

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


def parse_cell_frontmatter(content_or_path: str) -> Tuple[Dict[str, Any], str]:
    """Parse a cell file or markdown string into (frontmatter_dict, body)."""
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


def write_frontmatter(target_path: str | Path, metadata: Dict[str, Any], body: str) -> None:
    """Write metadata and markdown body to target_path with frontmatter delimiters."""
    content = dump_frontmatter(metadata, body=body)
    Path(target_path).write_text(content, encoding="utf-8")


# ── Primary AegisYAML Gateway Interface ───────────────────────────────────────

class AegisYAML:
    """Primary zero-dependency AegisYAML engine."""

    @staticmethod
    def parse_text(content: str) -> AegisDocument:
        """Parse pure in-memory markdown or yaml string into an AegisDocument. Never touches disk."""
        working_content = content
        for zw in ZERO_WIDTH_CHARS:
            working_content = working_content.replace(zw, "")

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


# Backward-compatibility aliases
SomaDocument = AegisDocument
SomaYAML = AegisYAML
parse_rule_frontmatter = parse_cell_frontmatter


__all__ = [
    "AegisDocument",
    "AegisYAML",
    "AegisYAMLError",
    "FrontmatterError",
    "MAX_DEPTH",
    "MAX_DOC_BYTES",
    "MAX_LINES",
    "MAX_SCALAR_CHARS",
    "SomaDocument",
    "SomaYAML",
    "SomaYAMLError",
    "ZERO_WIDTH_CHARS",
    "dump_frontmatter",
    "parse_cell_frontmatter",
    "parse_frontmatter",
    "parse_rule_frontmatter",
    "parse_yaml_subset",
    "write_frontmatter",
]
