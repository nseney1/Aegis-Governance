"""Host hook payloads normalized to one shape (v4.1 spec §2 "Normalization").

``normalize(host, payload, environ)`` turns a PreToolUse stdin payload into a
:class:`HookCall`::

    {host, tool, kind: shell|edit|other, command, paths, workspace, workspace_source, call_id}

| Host | Shell tool -> command | Edit tools -> paths | call id |
|---|---|---|---|
| claude-code | Bash, PowerShell, Monitor -> tool_input.command | Write, Edit -> tool_input.file_path; NotebookEdit -> tool_input.notebook_path | tool_use_id |
| codex-cli | Bash -> tool_input.command | apply_patch -> the ``*** Add/Update/Delete File:`` and ``*** Move to:`` headers of tool_input.command; a Bash ``apply_patch`` heredoc likewise | tool_use_id |
| antigravity | run_command -> toolCall.args.CommandLine | write_to_file, replace_file_content, multi_replace_file_content -> toolCall.args.TargetFile | conversationId:stepIdx |

The workspace hint is where the host says the session runs: Claude ``CLAUDE_PROJECT_DIR``
(the hook's environment) then the payload ``cwd``; Codex ``cwd``; agy
``workspacePaths[0]`` (with the global agy hooks file the hook's own cwd is outside any
repository). Only an absolute hint counts. A relative edit path is joined to the hint
(or, for a Codex ``cd <dir> && apply_patch`` heredoc, to that directory) and is never
resolved here: the caller confines it under the governed root.

Normalization reads only the payload and the environment it is given, and never raises
for content: anything unusable becomes None (no payload), ``command=None`` or no paths.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any, List, Mapping, Optional, Tuple

__all__ = [
    "HOSTS",
    "HookCall",
    "KIND_EDIT",
    "KIND_OTHER",
    "KIND_SHELL",
    "apply_patch_paths",
    "normalize",
]

HOSTS = ("claude-code", "codex-cli", "antigravity")
KIND_SHELL, KIND_EDIT, KIND_OTHER = "shell", "edit", "other"

_CLAUDE_SHELL = frozenset({"Bash", "PowerShell", "Monitor"})
_CLAUDE_EDIT = {"Write": "file_path", "Edit": "file_path", "NotebookEdit": "notebook_path"}
_AGY_EDIT = frozenset({"write_to_file", "replace_file_content", "multi_replace_file_content"})

_PATCH_HEADER = re.compile(r"\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)")
# A shell command Codex runs as a patch: `apply_patch` (or `applypatch`) first, after an
# optional `cd <dir> &&`, with the patch in a heredoc or an argument.
_APPLY_PATCH_COMMAND = re.compile(
    r"\s*(?:cd[ \t]+(?P<dir>'[^'\n]*'|\"(?:[^\"\\`\n]|\\.)*\"|(?:[^\s;&|'\"`$()<>\n\\]|\\[^\n])+)[ \t]*&&[ \t]*)?(?:apply_patch|applypatch)(?=\s|$)"
)
_HEREDOC_HEADER = re.compile(
    r"[ \t]*<<(?P<dash>-?)[ \t]*(?:'(?P<sdelim>[A-Za-z0-9_]+)'|\"(?P<ddelim>[A-Za-z0-9_]+)\"|\\(?P<bdelim>[A-Za-z0-9_]+)|(?P<udelim>[A-Za-z0-9_]+))[ \t]*\r?\n"
)
_INLINE_HEREDOC = re.compile(
    r"<<(?P<dash>-?)[ \t]*(?:'(?P<sdelim>[A-Za-z0-9_]+)'|\"(?P<ddelim>[A-Za-z0-9_]+)\"|\\(?P<bdelim>[A-Za-z0-9_]+)|(?P<udelim>[A-Za-z0-9_]+))"
)
_SINGLE_QUOTED_ARG = re.compile(r"[ \t]*'(?P<body>[^']*)'\s*\Z", re.DOTALL)
_DOUBLE_QUOTED_ARG = re.compile(r'[ \t]*"(?P<body>(?:[^"\\]|\\.)*)"\s*\Z', re.DOTALL)


@dataclass(frozen=True)
class HookCall:
    """One tool call as every host's hook sees it.

    ``command`` is set only for a shell call with a non-empty command string; ``paths``
    for an edit call or a shell call that also applies a patch (absolute when the hint
    made them so, in payload order, without duplicates). ``workspace`` is the absolute
    workspace hint and ``workspace_source`` names it: "claude_project_dir", "cwd" or
    "workspace_paths".
    """

    host: str
    tool: str
    kind: str
    command: Optional[str]
    paths: Tuple[str, ...]
    workspace: Optional[str]
    workspace_source: Optional[str]
    call_id: Optional[str]


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value.strip() else None


def _absolute(value: Any) -> Optional[str]:
    text = _text(value)
    return text if text is not None and os.path.isabs(text) else None


def _joined(paths: List[str], base: Optional[str]) -> Tuple[str, ...]:
    out = [p if base is None or os.path.isabs(p) else os.path.join(base, p) for p in paths]
    return tuple(dict.fromkeys(out))


def apply_patch_paths(text: str) -> Tuple[str, ...]:
    """The file paths an apply_patch text names, in order, without duplicates: every
    ``*** Add File:``, ``*** Update File:``, ``*** Delete File:`` and ``*** Move to:``
    header (a hunk line starts with ``+``, ``-``, space or ``@`` and is never one)."""
    found: List[str] = []
    for line in text.splitlines():
        header = _PATCH_HEADER.fullmatch(line.strip())
        if header:
            path = header.group(1).strip()
            if path:
                found.append(path)
    return tuple(dict.fromkeys(found))


def _has_unescaped_cmd_subst(text: str) -> bool:
    """True when ``text`` contains an unescaped backtick or ``$(`` command substitution."""
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "`" or text.startswith("$(", i):
            return True
        i += 1
    return False


def _codex_patch_base(command: str, base: Optional[str]) -> Tuple[Optional[re.Match[str]], Optional[str]]:
    invocation = _APPLY_PATCH_COMMAND.match(command)
    if invocation is None:
        return None, base
    directory = invocation.group("dir")
    if directory:
        if directory.startswith('"') and _has_unescaped_cmd_subst(directory[1:-1]):
            return None, base
        directory = directory.strip("'\"")
        base = directory if os.path.isabs(directory) else (os.path.join(base, directory) if base else None)
    return invocation, base


def _pure_apply_patch_body(rest: str) -> Optional[str]:
    """The patch body of a pure single-command apply_patch tail (Form A/B/C), or None."""
    header = _HEREDOC_HEADER.match(rest)
    if header is not None:
        strip_tabs = header.group("dash") == "-"
        quoted = bool(header.group("sdelim") or header.group("ddelim") or header.group("bdelim"))
        delim = (
            header.group("sdelim")
            or header.group("ddelim")
            or header.group("bdelim")
            or header.group("udelim")
        )
        lines = rest[header.end() :].split("\n")
        close_idx = None
        for idx, line in enumerate(lines):
            raw = line.rstrip("\r")
            if (raw.lstrip("\t") if strip_tabs else raw) == delim:
                close_idx = idx
                break
        if close_idx is None or "\n".join(lines[close_idx + 1 :]).strip():
            return None
        body = "\n".join(lines[:close_idx])
        if not quoted and ("`" in body or "$(" in body):
            return None
        return body if "*** Begin Patch" in body else None
    sq = _SINGLE_QUOTED_ARG.match(rest)
    if sq is not None:
        body = sq.group("body")
        return body if "*** Begin Patch" in body else None
    dq = _DOUBLE_QUOTED_ARG.match(rest)
    if dq is not None:
        body = dq.group("body")
        if _has_unescaped_cmd_subst(body):
            return None
        return body if "*** Begin Patch" in body else None
    return None


def _sanitize_unquoted_heredoc_body(body: str) -> str:
    """Turn an unquoted heredoc body into safe ``: ...`` lines that preserve
    ``$(...)`` and backtick command substitutions for shell analysis."""
    out: List[str] = []
    i = 0
    n = len(body)
    paren_depth = 0
    in_backtick = False
    at_line_start = True
    while i < n:
        if at_line_start:
            out.append(": ")
            at_line_start = False
        c = body[i]
        if c == "\n" and paren_depth == 0 and not in_backtick:
            out.append("\n")
            at_line_start = True
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            if paren_depth > 0 or in_backtick:
                out.append(body[i : i + 2])
            i += 2
            continue
        if not in_backtick and body.startswith("$(", i):
            paren_depth += 1
            out.append("$(")
            i += 2
            continue
        if paren_depth > 0:
            if c == "(":
                paren_depth += 1
            elif c == ")":
                paren_depth -= 1
            out.append(c)
            i += 1
            continue
        if c == "`":
            in_backtick = not in_backtick
            out.append(c)
            i += 1
            continue
        if not in_backtick and c in "'\"();&|<>":
            out.append(" ")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _strip_quoted_patch_bodies(text: str) -> str:
    """Replace quoted patch bodies in ``text`` with harmless placeholders while keeping
    surrounding shell commands and unquoted heredoc command substitutions."""
    out: List[str] = []
    i = 0
    n = len(text)
    pending_heredocs: List[Tuple[int, bool, bool, str]] = []
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            out.append(text[i : i + 2])
            i += 2
            continue
        if c == "#" and (i == 0 or text[i - 1] in " \t;&|()\n\r"):
            nl = text.find("\n", i)
            i = n if nl == -1 else nl
            continue
        if c == "'":
            end = text.find("'", i + 1)
            if end != -1:
                inner = text[i + 1 : end]
                out.append("''" if "*** Begin Patch" in inner else text[i : end + 1])
                i = end + 1
                continue
        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            if j < n and text[j] == '"':
                inner = text[i + 1 : j]
                if "*** Begin Patch" in inner and not _has_unescaped_cmd_subst(inner):
                    out.append('""')
                else:
                    out.append(text[i : j + 1])
                i = j + 1
                continue
        if text.startswith("<<<", i):
            out.append("<<<")
            i += 3
            continue
        if text.startswith("<<", i):
            m = _INLINE_HEREDOC.match(text, i)
            if m is not None:
                strip_tabs = m.group("dash") == "-"
                quoted = bool(m.group("sdelim") or m.group("ddelim") or m.group("bdelim"))
                delim = (
                    m.group("sdelim")
                    or m.group("ddelim")
                    or m.group("bdelim")
                    or m.group("udelim")
                )
                out_idx = len(out)
                out.append(text[i : m.end()])
                pending_heredocs.append((out_idx, strip_tabs, quoted, delim))
                i = m.end()
                continue
        if c == "\n" and pending_heredocs:
            out.append("\n")
            i += 1
            for out_idx, strip_tabs, quoted, delim in pending_heredocs:
                body_lines: List[str] = []
                closing_line: Optional[str] = None
                while i < n:
                    nl = text.find("\n", i)
                    if nl == -1:
                        line = text[i:]
                        i = n
                    else:
                        line = text[i:nl]
                        i = nl + 1
                    raw = line.rstrip("\r")
                    if (raw.lstrip("\t") if strip_tabs else raw) == delim:
                        closing_line = line + ("\n" if nl != -1 else "")
                        break
                    body_lines.append(line + ("\n" if nl != -1 else ""))
                body_full = "".join(body_lines)
                if "*** Begin Patch" in body_full:
                    if not quoted and ("`" in body_full or "$(" in body_full):
                        out[out_idx] = "''"
                        out.append(_sanitize_unquoted_heredoc_body(body_full))
                    elif closing_line is not None:
                        out.append(closing_line)
                else:
                    out.append(body_full)
                    if closing_line is not None:
                        out.append(closing_line)
            pending_heredocs.clear()
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _codex_patch_command(command: str, base: Optional[str]) -> Optional[Tuple[str, ...]]:
    """The paths of a pure Bash command Codex runs as apply_patch, or None for any other command."""
    if "*** Begin Patch" not in command:
        return None
    invocation, resolved_base = _codex_patch_base(command, base)
    if invocation is None:
        return None
    body = _pure_apply_patch_body(command[invocation.end() :])
    if body is None:
        return None
    return _joined(list(apply_patch_paths(body)), resolved_base)


def _claude(payload: Mapping[str, Any], environ: Mapping[str, str]) -> HookCall:
    project = _absolute(environ.get("CLAUDE_PROJECT_DIR"))
    cwd = _absolute(payload.get("cwd"))
    workspace, source = (project, "claude_project_dir") if project else (cwd, "cwd" if cwd else None)
    tool = payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else ""
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    kind, command, paths = KIND_OTHER, None, ()
    if tool in _CLAUDE_SHELL:
        kind, command = KIND_SHELL, _text(tool_input.get("command"))
    elif tool in _CLAUDE_EDIT:
        path = _text(tool_input.get(_CLAUDE_EDIT[tool]))
        kind, paths = KIND_EDIT, _joined([path] if path else [], workspace)
    return HookCall("claude-code", tool, kind, command, paths, workspace, source, _text(payload.get("tool_use_id")))


def _codex(payload: Mapping[str, Any]) -> HookCall:
    cwd = _absolute(payload.get("cwd"))
    tool = payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else ""
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    text = _text(tool_input.get("command"))
    kind, command, paths = KIND_OTHER, None, ()
    if tool == "apply_patch":
        kind, paths = KIND_EDIT, _joined(list(apply_patch_paths(text)) if text else [], cwd)
    elif tool == "Bash":
        patched = _codex_patch_command(text, cwd) if text else None
        if patched is not None:
            kind, paths = KIND_EDIT, patched
        elif text and "*** Begin Patch" in text:
            _, resolved_base = _codex_patch_base(text, cwd)
            patched_paths = _joined(list(apply_patch_paths(text)), resolved_base)
            kind = KIND_SHELL
            command = _strip_quoted_patch_bodies(text)
            paths = patched_paths
        else:
            kind, command = KIND_SHELL, text
    return HookCall("codex-cli", tool, kind, command, paths, cwd, "cwd" if cwd else None, _text(payload.get("tool_use_id")))


def _agy(payload: Mapping[str, Any]) -> HookCall:
    spaces = payload.get("workspacePaths")
    first = _absolute(spaces[0]) if isinstance(spaces, list) and spaces else None
    call = payload.get("toolCall") if isinstance(payload.get("toolCall"), dict) else {}
    tool = call.get("name") if isinstance(call.get("name"), str) else ""
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    kind, command, paths = KIND_OTHER, None, ()
    if tool == "run_command":
        kind, command = KIND_SHELL, _text(args.get("CommandLine"))
    elif tool in _AGY_EDIT:
        target = _text(args.get("TargetFile"))
        kind, paths = KIND_EDIT, _joined([target] if target else [], first)
    conversation, step = _text(payload.get("conversationId")), payload.get("stepIdx")
    call_id = f"{conversation}:{step}" if conversation and type(step) is int else None
    return HookCall("antigravity", tool, kind, command, paths, first, "workspace_paths" if first else None, call_id)


def normalize(host: str, payload: Any, environ: Optional[Mapping[str, str]] = None) -> Optional[HookCall]:
    """The HookCall of one PreToolUse ``payload`` from ``host`` (one of HOSTS), or None
    when the host is unknown or the payload is not a JSON object. ``environ`` is the
    hook's environment (os.environ when None); only Claude's CLAUDE_PROJECT_DIR is read."""
    if host not in HOSTS or not isinstance(payload, dict):
        return None
    if host == "claude-code":
        return _claude(payload, os.environ if environ is None else environ)
    if host == "codex-cli":
        return _codex(payload)
    return _agy(payload)
