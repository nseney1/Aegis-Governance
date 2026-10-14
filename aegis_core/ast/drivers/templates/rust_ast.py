#!/usr/bin/env python3
"""Rust Normalized AST Driver for Soma.

Emits JSON conforming to Soma's NormalizedAST schema (v1.0).
Zero third-party dependencies: uses standard library Python.
Extracts definitions, call sites, use statements (imports), and mutation points.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple


def _strip_comments_and_strings(source: str) -> Tuple[str, List[Tuple[int, int, str]]]:
    """Mask comment and string bodies with spaces to preserve line/column offsets.

    Returns:
        (masked_source, list_of_literals) where literals are (start, end, content).
    """
    chars = list(source)
    n = len(chars)
    i = 0
    in_line_comment = False
    in_block_comment = False
    in_string = False
    in_char = False
    string_start = 0

    while i < n:
        c = chars[i]
        next_c = chars[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if c == "\n":
                in_line_comment = False
            else:
                chars[i] = " "
        elif in_block_comment:
            if c == "*" and next_c == "/":
                chars[i] = " "
                chars[i + 1] = " "
                i += 1
                in_block_comment = False
            elif c != "\n":
                chars[i] = " "
        elif in_string:
            if c == "\\" and i + 1 < n:
                chars[i] = " "
                chars[i + 1] = " "
                i += 1
            elif c == '"':
                chars[i] = " "
                in_string = False
            elif c != "\n":
                chars[i] = " "
        elif in_char:
            if c == "\\" and i + 1 < n:
                chars[i] = " "
                chars[i + 1] = " "
                i += 1
            elif c == "'":
                chars[i] = " "
                in_char = False
            elif c != "\n":
                chars[i] = " "
        else:
            if c == "/" and next_c == "/":
                chars[i] = " "
                chars[i + 1] = " "
                i += 1
                in_line_comment = True
            elif c == "/" and next_c == "*":
                chars[i] = " "
                chars[i + 1] = " "
                i += 1
                in_block_comment = True
            elif c == '"':
                chars[i] = " "
                in_string = True
            elif c == "'":
                # Guard against Rust lifetime annotations like `'a`
                if i + 2 < n and chars[i + 2] == "'":
                    chars[i] = " "
                    chars[i + 1] = " "
                    chars[i + 2] = " "
                    i += 2
                elif i + 3 < n and chars[i + 1] == "\\" and chars[i + 3] == "'":
                    chars[i] = " "
                    chars[i + 1] = " "
                    chars[i + 2] = " "
                    chars[i + 3] = " "
                    i += 3
        i += 1

    return "".join(chars), []


def _compute_line_col(source: str, offset: int) -> Tuple[int, int]:
    """Compute 1-indexed line and 0-indexed column from byte offset."""
    prefix = source[:offset]
    line = prefix.count("\n") + 1
    last_newline = prefix.rfind("\n")
    col = offset if last_newline == -1 else offset - (last_newline + 1)
    return line, col


def parse_rust_source(source: str, file_path: str) -> Dict[str, Any]:
    """Extract NormalizedAST from Rust source code."""
    masked, _ = _strip_comments_and_strings(source)

    definitions: List[Dict[str, Any]] = []
    call_sites: List[Dict[str, Any]] = []
    imports: List[Dict[str, Any]] = []
    mutations: List[Dict[str, Any]] = []

    # 1. Imports (use statements)
    use_pattern = re.compile(r"\buse\s+([^;]+);", re.MULTILINE)
    for m in use_pattern.finditer(masked):
        use_expr = m.group(1).strip()
        line, _ = _compute_line_col(source, m.start())
        alias = None
        if " as " in use_expr:
            parts = use_expr.split(" as ")
            use_expr = parts[0].strip()
            alias = parts[1].strip()

        is_wildcard = use_expr.endswith("::*")
        module_name = use_expr
        imported_names = []

        if "::{" in use_expr and use_expr.endswith("}"):
            base_mod, symbols = use_expr.split("::{", 1)
            symbols = symbols.rstrip("}")
            module_name = base_mod.strip()
            imported_names = [s.strip() for s in symbols.split(",") if s.strip()]
        else:
            last_part = use_expr.split("::")[-1].strip()
            imported_names = [last_part] if not is_wildcard else []

        imports.append({
            "module": module_name,
            "imported_names": imported_names,
            "alias": alias,
            "is_wildcard": is_wildcard,
            "line": line,
        })

    # 2. Impl blocks tracking for methods
    impl_blocks: List[Tuple[int, int, str]] = []  # (start, end, type_name)
    impl_pattern = re.compile(r"\bimpl(?:<[^>]+>)?(?:\s+([A-Za-z0-9_]+)\s+for)?\s+([A-Za-z0-9_]+)", re.MULTILINE)
    for m in impl_pattern.finditer(masked):
        type_name = m.group(2)
        # Find matching brace
        brace_start = masked.find("{", m.end())
        if brace_start != -1:
            depth = 1
            curr = brace_start + 1
            while curr < len(masked) and depth > 0:
                if masked[curr] == "{":
                    depth += 1
                elif masked[curr] == "}":
                    depth -= 1
                curr += 1
            impl_blocks.append((brace_start, curr, type_name))

    # 3. Definitions: functions, structs, traits, enums
    fn_pattern = re.compile(
        r"(?:(pub(?:\([^)]+\))?)\s+)?(?:(async|const|unsafe|extern(?:\s+\"[^\"]+\")?)\s+)*fn\s+([A-Za-z0-9_]+)\s*(?:<[^>]+>)?\s*\(",
        re.MULTILINE,
    )
    for m in fn_pattern.finditer(masked):
        is_exported = bool(m.group(1))
        fn_name = m.group(3)
        offset = m.start()
        line, col = _compute_line_col(source, offset)

        class_name = None
        is_method = False
        for start, end, t_name in impl_blocks:
            if start <= offset <= end:
                is_method = True
                class_name = t_name
                break

        # Estimate end line by finding matching brace
        end_line = None
        brace_start = masked.find("{", m.end())
        if brace_start != -1 and brace_start - m.end() < 500:
            depth = 1
            curr = brace_start + 1
            while curr < len(masked) and depth > 0:
                if masked[curr] == "{":
                    depth += 1
                elif masked[curr] == "}":
                    depth -= 1
                curr += 1
            end_line, _ = _compute_line_col(source, curr)

        definitions.append({
            "name": fn_name,
            "kind": "method" if is_method else "function",
            "line": line,
            "column": col,
            "end_line": end_line,
            "is_exported": is_exported,
            "is_method": is_method,
            "class_name": class_name,
            "docstring": None,
        })

    # Structs & Enums
    type_pattern = re.compile(
        r"(?:(pub(?:\([^)]+\))?)\s+)?(struct|enum|trait|type)\s+([A-Za-z0-9_]+)",
        re.MULTILINE,
    )
    for m in type_pattern.finditer(masked):
        is_exported = bool(m.group(1))
        kind = m.group(2)
        name = m.group(3)
        line, col = _compute_line_col(source, m.start())
        definitions.append({
            "name": name,
            "kind": kind if kind != "type" else "type_alias",
            "line": line,
            "column": col,
            "end_line": None,
            "is_exported": is_exported,
            "is_method": False,
            "class_name": None,
            "docstring": None,
        })

    # 4. Call Sites
    call_pattern = re.compile(
        r"(?:([A-Za-z0-9_]+(?:::[A-Za-z0-9_]+)*)\s*\.|([A-Za-z0-9_]+(?:::[A-Za-z0-9_]+)*)::)?([A-Za-z0-9_]+)\s*\(",
        re.MULTILINE,
    )
    keywords = {"fn", "if", "while", "for", "match", "let", "return", "impl", "struct", "enum", "type", "use", "mod"}
    for m in call_pattern.finditer(masked):
        callee = m.group(3)
        prefix = masked[:m.start()].rstrip()
        if prefix.endswith("fn"):
            continue
        # Also ensure this is not the definition of a function itself
        if any(d["name"] == callee and d["line"] == line for d in definitions):
            continue
        line, col = _compute_line_col(source, m.start())

        caller_scope = None
        for d in definitions:
            if d.get("end_line") and d["line"] <= line <= d["end_line"]:
                caller_scope = d["name"]
                break

        full_target = callee
        if m.group(2):
            full_target = f"{m.group(2)}::{callee}"
        elif m.group(1):
            full_target = f"{m.group(1)}.{callee}"

        call_sites.append({
            "target": full_target,
            "line": line,
            "column": col,
            "caller_scope": caller_scope,
        })

    # 5. Mutations
    mutation_ops = [
        ("==", "!=", "comparison"),
        ("!=", "==", "comparison"),
        ("<=", ">", "comparison"),
        (">=", "<", "comparison"),
        ("<", ">=", "comparison"),
        (">", "<=", "comparison"),
        ("&&", "||", "logical"),
        ("||", "&&", "logical"),
        ("+", "-", "binop"),
        ("-", "+", "binop"),
        ("*", "/", "binop"),
        ("/", "*", "binop"),
    ]
    # Sort multi-char first
    for orig, rep, kind in mutation_ops:
        idx = 0
        while True:
            pos = masked.find(orig, idx)
            if pos == -1:
                break
            # Guard against comment tokens or arrow / ref tokens
            valid = True
            if orig == "/" and (pos + 1 < len(masked) and masked[pos + 1] in ("/", "*")):
                valid = False
            elif orig == "-" and (pos + 1 < len(masked) and masked[pos + 1] == ">"):
                valid = False
            elif orig == "*" and (pos > 0 and masked[pos - 1] in ("/", "*")):
                valid = False
            elif len(orig) == 1 and pos + 1 < len(masked) and masked[pos + 1] == "=":
                valid = False
            elif orig == "<" and (pos > 0 and masked[pos - 1] == "<"):
                valid = False
            elif orig == ">" and ((pos > 0 and masked[pos - 1] in ("-", "=")) or (pos > 0 and masked[pos - 1] == ">")):
                valid = False

            if valid:
                line, col = _compute_line_col(source, pos)
                fn_scope = None
                for d in definitions:
                    if d.get("end_line") and d["line"] <= line <= d["end_line"]:
                        fn_scope = d["name"]
                        break

                mutations.append({
                    "line": line,
                    "column": col,
                    "original": orig,
                    "mutated": rep,
                    "kind": kind,
                    "function_scope": fn_scope,
                    "byte_offset": pos,
                })
            idx = pos + len(orig)

    return {
        "version": "1.0",
        "file_path": file_path,
        "language": "rust",
        "definitions": definitions,
        "call_sites": call_sites,
        "imports": imports,
        "mutations": mutations,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: rust_ast.py <file.rs> | -", file=sys.stderr)
        return 1

    arg = sys.argv[1]
    if arg == "-":
        source = sys.stdin.read()
        file_path = "<stdin>"
    else:
        file_path = os.path.abspath(arg)
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except OSError as e:
            print(f"Error reading {file_path}: {e}", file=sys.stderr)
            return 1

    ast_data = parse_rust_source(source, file_path)
    sys.stdout.write(json.dumps(ast_data, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
