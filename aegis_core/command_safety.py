"""aegis_core.command_safety — Structured AST/token command safety analyzer.

Replaces monolithic regular expressions with lexical tokenization, wrapper unwrapping,
pipeline sequence analysis, and domain-specific command evaluators.
Zero external dependencies (pure stdlib). Target latency < 0.05ms.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import os
import re
import shlex
from typing import Sequence

# ── Canonical Reason Strings (1:1 Parity with aegis_cli/hooks.py) ─────────────

REASON_GIT_BRANCH = "Destructive branch operation (git branch -d/-D/-M/-f/--delete/--force)"
REASON_GIT_CONFIG = "git configuration override / exec-path injection (-c/--exec-path/--config-env)"
REASON_GIT_DIFF = "git diff write/execute flag detected"
REASON_RM_RF = "Recursive delete targeting home/root directory or wildcard/current directory"
REASON_RMTREE = "Recursive directory deletion (rmtree) detected"
REASON_RMDIR_BYPASS = "rmdir with --ignore-fail-on-non-empty — bypasses safety check"
REASON_MKFS = "Filesystem format (mkfs) detected — destructive operation"
REASON_DD = "Raw disk write (dd) detected — destructive operation"
REASON_CHMOD_777 = "chmod 777 — overly permissive, potential security risk"
REASON_KILL_ALL = "kill -9 -1 — would kill all user processes"
REASON_SUDO = "sudo detected — elevated privileges require confirmation"
REASON_PIPE_TO_SHELL = "Piping remote content to shell — potential code execution risk"
REASON_GIT_PUSH_FORCE = "Force push detected — destructive-ops mandate requires confirmation"
REASON_GIT_PUSH_REFSPEC = "Force push via +refspec detected — destructive-ops mandate requires confirmation"
REASON_GIT_RESET_HARD = "Hard reset — will discard uncommitted changes"
REASON_GIT_CHECKOUT_FORCE = "Force checkout — will discard uncommitted changes"
REASON_GIT_CLEAN_FORCE = "git clean -f — will permanently remove untracked files"
REASON_GIT_ADD_BULK = "Bulk staging (git add -A/./*/--all) — run git status first to verify file count"
REASON_DB_DESTRUCTIVE = "Destructive database operation without WHERE clause"
REASON_WINDOWS_FORMAT = "Disk partition format detected — destructive operation"
REASON_POWERSHELL_DELETE = "PowerShell recursive force delete detected"
REASON_CMD_DELETE = "Windows command-line recursive delete (/s /q) detected"
REASON_HUMAN_REVIEW_GATE = "Human Review Gate: Agents are strictly prohibited from merging pull requests (gh pr merge). Merging requires human authority."
REASON_PROTECTED_BRANCH = "Protected branch operation: Direct push to main is strictly prohibited for agents."
REASON_GIT_MERGE = "Git branch merge detected — merging branches requires human confirmation"
REASON_UNABLE_TO_PARSE = "Unable to parse command — requesting confirmation"

MAX_DEPTH = 5

# ── Classification Sets ───────────────────────────────────────────────────────

REMOTE_FETCHERS = frozenset({
    "curl", "wget", "iwr", "irm", "invoke-webrequest", "invoke-restmethod"
})

SHELL_INTERPRETERS = frozenset({
    "sh", "bash", "zsh", "dash", "ksh", "fish",
    "powershell", "pwsh", "iex", "invoke-expression"
})

SHELL_PREFIX_KEYWORDS = frozenset({
    "{", "}", "then", "do", "elif", "else", "if", "while", "until", "fi", "done", "esac"
})

SUDO_FLAGS_WITH_ARG = frozenset({
    "-u", "-g", "-p", "-C", "-D", "-R", "-T", "-U", "-h", "-c", "-a",
    "--user", "--group", "--prompt", "--close-from", "--chdir", "--chroot",
    "--command-timeout", "--other-user", "--host"
})

ENV_FLAGS_WITH_ARG = frozenset({
    "-u", "--unset", "-C", "--chdir", "-S", "--split-string"
})

TIME_FLAGS_WITH_ARG = frozenset({
    "-o", "--output", "-f", "--format"
})

EXEC_FLAGS_WITH_ARG = frozenset({
    "-a"
})

GIT_GLOBAL_FLAGS_WITH_ARG = frozenset({
    "-C", "-c", "--exec-path", "--config-env", "--work-tree", "--namespace", "--git-dir"
})

GH_GLOBAL_FLAGS_WITH_ARG = frozenset({
    "-R", "--repo"
})

ENV_VAR_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*=")
WIN_DRIVE_RE = re.compile(r'([a-zA-Z]:)\\([\s*?$"]|$)')
RM_DANGEROUS_TARGETS = frozenset({"/", "~", "/home", "$home", "/root", "$root", ".", "..", "*"})
GLOB_CHARS = frozenset({"*", "?", "[", "]"})


@dataclass(frozen=True)
class SafetyEvaluation:
    is_destructive: bool
    reason: str = ""


@dataclass
class CommandStage:
    raw_tokens: list[str]


@dataclass
class Pipeline:
    stages: list[CommandStage]


@dataclass
class UnwrappedCommand:
    binary: str
    subcommand: str | None
    flags: list[str]
    positional_args: list[str]
    has_sudo: bool = False
    env_vars: dict[str, str] = field(default_factory=dict)


# ── String Pre-processing & Subshell Scanner ──────────────────────────────────

def decode_ansi_c_quotes(cmd: str) -> str:
    """Expand Bash ANSI-C quoting ($'...') into decoded strings."""
    if "$'" not in cmd:
        return cmd

    def _repl(match: re.Match[str]) -> str:
        content = match.group(1)
        try:
            decoded = content.encode("utf-8").decode("unicode_escape")
        except Exception:
            decoded = content
        return shlex.quote(decoded)

    return re.sub(r"\$'([^'\\]*(?:\\.[^'\\]*)*)'", _repl, cmd)


def extract_subshell_commands(cmd: str) -> list[str]:
    """Extract nested subshells strictly respecting shell quoting context.
    
    Guarantees:
    - Never extracts parentheses inside single quotes ('...').
    - Only extracts $(...) and `...` inside double quotes or unquoted.
    - Extracts bare (...) if unquoted AND at a command boundary, OR if
      containing destructive PowerShell/CMD operations.
    - Only extracts <(...) or >(...) if unquoted.
    """
    if not any(c in cmd for c in ("$", "`", "(", "<", ">")):
        return []

    extracted: list[str] = []
    n = len(cmd)
    i = 0
    in_single_quote = False
    in_double_quote = False

    while i < n:
        c = cmd[i]

        # Handle backslash escapes
        if c == "\\":
            if not in_single_quote:
                i += 2
                continue
            else:
                i += 1
                continue

        # Single quote toggle (inhibits all expansions inside)
        if c == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            i += 1
            continue

        # Double quote toggle
        if c == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            i += 1
            continue

        if in_single_quote:
            i += 1
            continue

        # Backticks (valid unquoted or inside double quotes)
        if c == "`":
            j = i + 1
            while j < n and cmd[j] != "`":
                if cmd[j] == "\\" and j + 1 < n:
                    j += 2
                else:
                    j += 1
            if j < n and cmd[j] == "`":
                extracted.append(cmd[i + 1 : j])
                i = j + 1
                continue

        # $(...) command substitution (valid unquoted or inside double quotes)
        if c == "$" and i + 1 < n and cmd[i + 1] == "(":
            start = i + 2
            depth = 1
            j = start
            inner_sq = False
            inner_dq = False
            while j < n and depth > 0:
                cj = cmd[j]
                if cj == "\\" and not inner_sq:
                    j += 2
                    continue
                if cj == "'" and not inner_dq:
                    inner_sq = not inner_sq
                elif cj == '"' and not inner_sq:
                    inner_dq = not inner_dq
                elif not inner_sq and not inner_dq:
                    if cj == "(":
                        depth += 1
                    elif cj == ")":
                        depth -= 1
                j += 1
            if depth == 0:
                extracted.append(cmd[start : j - 1])
                i = j
                continue

        # Process substitution <(...) or >(...) (unquoted only)
        if not in_double_quote and c in ("<", ">") and i + 1 < n and cmd[i + 1] == "(":
            start = i + 2
            depth = 1
            j = start
            inner_sq = False
            inner_dq = False
            while j < n and depth > 0:
                cj = cmd[j]
                if cj == "\\" and not inner_sq:
                    j += 2
                    continue
                if cj == "'" and not inner_dq:
                    inner_sq = not inner_sq
                elif cj == '"' and not inner_sq:
                    inner_dq = not inner_dq
                elif not inner_sq and not inner_dq:
                    if cj == "(":
                        depth += 1
                    elif cj == ")":
                        depth -= 1
                j += 1
            if depth == 0:
                extracted.append(cmd[start : j - 1])
                i = j
                continue

        # Bare (...) subshell (unquoted AND [command boundary OR PowerShell expression])
        if not in_double_quote and c == "(":
            k = i - 1
            while k >= 0 and cmd[k] in " \t":
                k -= 1
            is_cmd_boundary = (k < 0) or (cmd[k] in ";|&\n\r({")
            is_ps_expr = bool(re.match(r'\(\s*(?:remove-item|rm|del|erase|rd|ri|format-volume)\b', cmd[i:], re.IGNORECASE))
            if is_cmd_boundary or is_ps_expr:
                start = i + 1
                depth = 1
                j = start
                inner_sq = False
                inner_dq = False
                while j < n and depth > 0:
                    cj = cmd[j]
                    if cj == "\\" and not inner_sq:
                        j += 2
                        continue
                    if cj == "'" and not inner_dq:
                        inner_sq = not inner_sq
                    elif cj == '"' and not inner_sq:
                        inner_dq = not inner_dq
                    elif not inner_sq and not inner_dq:
                        if cj == "(":
                            depth += 1
                        elif cj == ")":
                            depth -= 1
                    j += 1
                if depth == 0:
                    extracted.append(cmd[start : j - 1])
                    i = j
                    continue

        i += 1

    return extracted


# ── Lexing & Hierarchy Decomposition ─────────────────────────────────────────

def tokenize_command(cmd: str) -> list[str]:
    """Tokenize command handling multiline, punctuation delimiters and escapes."""
    normalized = decode_ansi_c_quotes(cmd)
    # Pre-normalize Windows drive backslashes so posix lexer does not treat C:\ as escape
    if ":\\" in normalized:
        normalized = WIN_DRIVE_RE.sub(r'\1/\2', normalized)
    lex = shlex.shlex(normalized, posix=True, punctuation_chars="|;&\n\r")
    lex.whitespace_split = True
    lex.commenters = ""
    lex.whitespace = " \t"
    return list(lex)


def decompose_command(tokens: list[str]) -> list[Pipeline]:
    """Split token stream into Pipelines by sequence delimiters (; , &&, ||, &, newline)."""
    seq_delims = {";", "&&", "||", "&", "\n", "\r", "\r\n"}
    pipelines: list[Pipeline] = []
    curr_pipeline_stages: list[CommandStage] = []
    curr_stage_tokens: list[str] = []

    def flush_stage():
        nonlocal curr_stage_tokens
        if curr_stage_tokens:
            curr_pipeline_stages.append(CommandStage(raw_tokens=list(curr_stage_tokens)))
            curr_stage_tokens = []

    def flush_pipeline():
        nonlocal curr_pipeline_stages
        flush_stage()
        if curr_pipeline_stages:
            pipelines.append(Pipeline(stages=list(curr_pipeline_stages)))
            curr_pipeline_stages = []

    for tok in tokens:
        if tok in seq_delims:
            flush_pipeline()
        elif tok in ("|", "|&"):
            flush_stage()
        else:
            curr_stage_tokens.append(tok)

    flush_pipeline()
    return pipelines


# ── Wrapper & Keyword Unwrapping Automaton ────────────────────────────────────

def unwrap_command_stage(tokens: list[str]) -> tuple[UnwrappedCommand | None, str | None]:
    """Peel keywords, wrappers (with full option consumption), env vars, and expansions.
    
    Returns (UnwrappedCommand, inner_command_to_recurse).
    """
    if not tokens:
        return None, None

    # Expansion Guard 1: Brace expansion on command position (e.g. {rm,-rf,/})
    if tokens and tokens[0].startswith("{") and tokens[0].endswith("}") and "," in tokens[0]:
        inner = tokens[0][1:-1]
        tokens = inner.split(",") + tokens[1:]

    idx = 0
    has_sudo = False
    env_vars: dict[str, str] = {}

    while idx < len(tokens):
        tok = tokens[idx]

        # 1. Shell compound / control flow keywords
        if tok in SHELL_PREFIX_KEYWORDS:
            idx += 1
            continue

        # 2. Leading environment variables (e.g. FOO=bar cmd)
        if "=" in tok and ENV_VAR_RE.match(tok):
            k, _, v = tok.partition("=")
            env_vars[k] = v
            idx += 1
            continue

        clean_tok = tok.lstrip("\\")
        base = os.path.basename(clean_tok).lower()
        if base.endswith(".exe"):
            base = base[:-4]

        # 3. sudo / doas wrapper (with full option & argument consumption)
        if base in ("sudo", "doas"):
            has_sudo = True
            idx += 1
            while idx < len(tokens):
                stok = tokens[idx]
                if stok == "--":
                    idx += 1
                    break
                if stok.startswith("-"):
                    idx += 1
                    if "=" not in stok and stok in SUDO_FLAGS_WITH_ARG:
                        if idx < len(tokens):
                            idx += 1
                else:
                    break
            continue

        # 4. env wrapper (with option and variable consumption)
        if base == "env":
            idx += 1
            while idx < len(tokens):
                etok = tokens[idx]
                if etok == "--":
                    idx += 1
                    break
                if etok.startswith("-"):
                    idx += 1
                    if "=" not in etok and etok in ENV_FLAGS_WITH_ARG:
                        if idx < len(tokens):
                            idx += 1
                elif ENV_VAR_RE.match(etok):
                    k, _, v = etok.partition("=")
                    env_vars[k] = v
                    idx += 1
                else:
                    break
            continue

        # 5. time wrapper (with option consumption)
        if base == "time":
            idx += 1
            while idx < len(tokens):
                ttok = tokens[idx]
                if ttok == "--":
                    idx += 1
                    break
                if ttok.startswith("-"):
                    idx += 1
                    if "=" not in ttok and ttok in TIME_FLAGS_WITH_ARG:
                        if idx < len(tokens):
                            idx += 1
                else:
                    break
            continue

        # 6. command & builtin wrappers
        if base in ("command", "builtin"):
            idx += 1
            while idx < len(tokens) and tokens[idx].startswith("-"):
                if tokens[idx] == "--":
                    idx += 1
                    break
                idx += 1
            continue

        # 7. exec wrapper
        if base == "exec":
            idx += 1
            while idx < len(tokens):
                xtok = tokens[idx]
                if xtok == "--":
                    idx += 1
                    break
                if xtok.startswith("-"):
                    idx += 1
                    if "=" not in xtok and xtok in EXEC_FLAGS_WITH_ARG:
                        if idx < len(tokens):
                            idx += 1
                else:
                    break
            continue

        # 7a. nohup wrapper
        if base == "nohup":
            idx += 1
            while idx < len(tokens) and tokens[idx] == "--":
                idx += 1
            continue

        # 7b. nice wrapper
        if base == "nice":
            idx += 1
            while idx < len(tokens):
                ntok = tokens[idx]
                if ntok == "--":
                    idx += 1
                    break
                if ntok.startswith("-"):
                    idx += 1
                    if ntok == "-n" and idx < len(tokens):
                        idx += 1
                else:
                    break
            continue

        # 7c. timeout wrapper
        if base == "timeout":
            idx += 1
            has_duration = False
            while idx < len(tokens):
                ttok = tokens[idx]
                if ttok == "--":
                    idx += 1
                    continue
                if ttok.startswith("-"):
                    idx += 1
                    if ttok in ("-s", "--signal", "-k", "--kill-after") and idx < len(tokens):
                        idx += 1
                elif not has_duration:
                    has_duration = True
                    idx += 1
                else:
                    break
            continue

        # 7d. xargs wrapper
        if base == "xargs":
            idx += 1
            while idx < len(tokens):
                xtok = tokens[idx]
                if xtok == "--":
                    idx += 1
                    break
                if xtok.startswith("-"):
                    idx += 1
                    if xtok in ("-n", "-L", "-I", "-s", "-d", "-E", "-P") and idx < len(tokens):
                        idx += 1
                else:
                    break
            continue

        # 8. eval builtin (evaluates remaining tokens as inner command)
        if base == "eval":
            if idx + 1 < len(tokens):
                inner_eval_cmd = " ".join(tokens[idx + 1 :])
                return None, inner_eval_cmd
            return None, None

        # 9. Shell interpreter with script (-c / /c / -Command / bundled flags like -lc, -ec, -xc)
        if base in SHELL_INTERPRETERS:
            c_idx = -1
            for j in range(idx + 1, len(tokens)):
                tok = tokens[j]
                if tok in ("-c", "/c", "-Command", "-command"):
                    c_idx = j
                    break
                # POSIX short-flag bundling (e.g. bash -lc, sh -ec, zsh -xic)
                if (
                    base in ("bash", "sh", "zsh", "dash")
                    and tok.startswith("-")
                    and not tok.startswith("--")
                    and "c" in tok[1:]
                ):
                    c_idx = j
                    break
            if c_idx != -1 and c_idx + 1 < len(tokens):
                inner_cmd = tokens[c_idx + 1]
                # Positional argument decoupling defense:
                extra_args = tokens[c_idx + 3 :] if len(tokens) > c_idx + 3 else []
                if extra_args:
                    inner_cmd = inner_cmd + " " + " ".join(extra_args)
                return None, inner_cmd

        # Expansion Guard 2: Path globbing on command binary word
        if any(g in base for g in GLOB_CHARS):
            matched_bin = None
            for candidate in ("rm", "git", "dd", "mkfs", "chmod", "kill", "rmdir"):
                if fnmatch.fnmatch(candidate, base):
                    matched_bin = candidate
                    break
            base = matched_bin if matched_bin else "__unresolved_glob__"

        binary = base
        idx += 1
        subcommand: str | None = None
        flags: list[str] = []
        pos_args: list[str] = []

        while idx < len(tokens):
            arg = tokens[idx]
            if arg.startswith("-") or (binary in ("del", "rmdir") and arg.startswith("/")):
                flags.append(arg)
                # Global Git options with arguments (-C <dir>, --work-tree <dir>)
                if binary == "git" and "=" not in arg and arg in GIT_GLOBAL_FLAGS_WITH_ARG:
                    idx += 1
                    if idx < len(tokens):
                        flags.append(tokens[idx])
                # Global GitHub CLI options with arguments (-R <repo>, --repo <repo>)
                elif binary == "gh" and "=" not in arg and arg in GH_GLOBAL_FLAGS_WITH_ARG:
                    idx += 1
                    if idx < len(tokens):
                        flags.append(tokens[idx])
            else:
                if subcommand is None and binary in ("git", "gh"):
                    subcommand = arg.lower()
                else:
                    pos_args.append(arg)
            idx += 1

        return UnwrappedCommand(
            binary=binary,
            subcommand=subcommand,
            flags=flags,
            positional_args=pos_args,
            has_sudo=has_sudo,
            env_vars=env_vars,
        ), None

    return None, None


# ── Domain-Specific Command Evaluators ────────────────────────────────────────

def evaluate_git(cmd: UnwrappedCommand) -> SafetyEvaluation:
    flags = [f.lstrip("\\") for f in cmd.flags]

    # git config override / exec-path injection
    for f in flags:
        if f in ("-c", "--exec-path", "--config-env") or f.startswith(("--exec-path=", "--config-env=")):
            return SafetyEvaluation(True, REASON_GIT_CONFIG)

    sub = cmd.subcommand
    if not sub:
        return SafetyEvaluation(False)

    if sub == "branch":
        for f in flags:
            if f in ("--delete", "--force"):
                return SafetyEvaluation(True, REASON_GIT_BRANCH)
            if f.startswith("-") and not f.startswith("--"):
                letters = f[1:]
                if any(c in letters for c in "dDMf"):
                    return SafetyEvaluation(True, REASON_GIT_BRANCH)

    elif sub == "push":
        if any(f in ("-f", "--force", "--force-with-lease") for f in flags):
            return SafetyEvaluation(True, REASON_GIT_PUSH_FORCE)
        for arg in cmd.positional_args:
            if arg.startswith("+"):
                return SafetyEvaluation(True, REASON_GIT_PUSH_REFSPEC)
            if arg == "main" or arg.endswith(":main") or arg.endswith("/main"):
                return SafetyEvaluation(True, REASON_PROTECTED_BRANCH)

    elif sub == "reset":
        if any(f == "--hard" for f in flags):
            return SafetyEvaluation(True, REASON_GIT_RESET_HARD)

    elif sub == "checkout":
        if any(f in ("-f", "--force") for f in flags):
            return SafetyEvaluation(True, REASON_GIT_CHECKOUT_FORCE)

    elif sub == "clean":
        for f in flags:
            if f == "--force" or (f.startswith("-") and not f.startswith("--") and "f" in f[1:]):
                return SafetyEvaluation(True, REASON_GIT_CLEAN_FORCE)

    elif sub == "add":
        for f in flags:
            if f in ("-A", "--all"):
                return SafetyEvaluation(True, REASON_GIT_ADD_BULK)
        for arg in cmd.positional_args:
            if arg in (".", "./", "*"):
                return SafetyEvaluation(True, REASON_GIT_ADD_BULK)

    elif sub == "diff":
        for f in flags:
            if f.startswith(("--output", "--ext-cmd")):
                return SafetyEvaluation(True, REASON_GIT_DIFF)

    elif sub == "merge":
        if any(f in ("--abort", "--quit", "--continue") for f in flags):
            return SafetyEvaluation(False)
        return SafetyEvaluation(True, REASON_GIT_MERGE)

    return SafetyEvaluation(False)


def evaluate_gh(cmd: UnwrappedCommand) -> SafetyEvaluation:
    sub = cmd.subcommand
    if not sub:
        return SafetyEvaluation(False)

    if sub == "pr":
        if any(arg == "merge" for arg in cmd.positional_args):
            return SafetyEvaluation(True, REASON_HUMAN_REVIEW_GATE)

    return SafetyEvaluation(False)


def evaluate_rm(cmd: UnwrappedCommand) -> SafetyEvaluation:
    flags = [f.lstrip("\\") for f in cmd.flags]
    has_r = False

    for f in flags:
        if f == "--recursive":
            has_r = True
        elif f.startswith("-") and not f.startswith("--"):
            body = f[1:]
            if any(c in body for c in "rR"):
                has_r = True

    if has_r:
        for arg in cmd.positional_args:
            target = arg.strip("'\"").lower()
            # Path normalization (BUG-075): strip trailing slashes, e.g. ./, ../, ~/, /home
            norm_target = target.rstrip("/\\")
            if not norm_target and target.startswith(("/", "\\")):
                norm_target = "/"
            if (
                target in RM_DANGEROUS_TARGETS
                or norm_target in RM_DANGEROUS_TARGETS
                or any(norm_target.endswith("/" + t) for t in RM_DANGEROUS_TARGETS if t != "/")
            ):
                return SafetyEvaluation(True, REASON_RM_RF)

    return SafetyEvaluation(False)


def evaluate_powershell(cmd: UnwrappedCommand) -> SafetyEvaluation:
    flags_lower = [f.lower() for f in cmd.flags]
    has_recurse = any(f in ("-recurse", "-r") for f in flags_lower)
    has_force = any(f in ("-force", "-fo") for f in flags_lower)
    if has_recurse and has_force:
        return SafetyEvaluation(True, REASON_POWERSHELL_DELETE)
    return SafetyEvaluation(False)


def evaluate_cmd_del(cmd: UnwrappedCommand) -> SafetyEvaluation:
    flags_lower = [f.lower() for f in cmd.flags]
    has_s = any(f in ("/s", "-s") for f in flags_lower)
    has_q = any(f in ("/q", "-q") for f in flags_lower)
    if has_s and has_q:
        return SafetyEvaluation(True, REASON_CMD_DELETE)
    return SafetyEvaluation(False)


def evaluate_system_binary(cmd: UnwrappedCommand) -> SafetyEvaluation:
    b = cmd.binary
    if b == "__unresolved_glob__":
        return SafetyEvaluation(True, REASON_UNABLE_TO_PARSE)

    if b.startswith("mkfs"):
        return SafetyEvaluation(True, REASON_MKFS)

    if b == "dd":
        all_items = cmd.positional_args + cmd.flags
        if any(item.startswith("if=") for item in all_items):
            return SafetyEvaluation(True, REASON_DD)

    if b == "chmod":
        for item in cmd.flags + cmd.positional_args:
            if re.search(r"0?777", item):
                return SafetyEvaluation(True, REASON_CHMOD_777)

    if b == "kill":
        combined = set(cmd.flags + cmd.positional_args)
        if "-9" in combined and "-1" in combined:
            return SafetyEvaluation(True, REASON_KILL_ALL)

    if b == "rmdir":
        if any(f == "--ignore-fail-on-non-empty" for f in cmd.flags):
            return SafetyEvaluation(True, REASON_RMDIR_BYPASS)

    if b in ("format-volume", "initialize-disk", "clear-disk"):
        return SafetyEvaluation(True, REASON_WINDOWS_FORMAT)

    if cmd.has_sudo:
        return SafetyEvaluation(True, REASON_SUDO)

    return SafetyEvaluation(False)


# ── Pipeline & Top-Level Analyzer ─────────────────────────────────────────────

class CommandAnalyzer:
    """Evaluates raw command strings for destructive operations."""

    @classmethod
    def evaluate(cls, cmd: str, depth: int = 0) -> SafetyEvaluation:
        # Recursion Limit Clamp (Defense against DoS)
        if depth >= MAX_DEPTH:
            return SafetyEvaluation(True, REASON_UNABLE_TO_PARSE)

        if not cmd or not isinstance(cmd, str) or not cmd.strip():
            return SafetyEvaluation(True, REASON_UNABLE_TO_PARSE)

        # 1. Non-shell string checks (Python rmtree, SQL keywords)
        if "rmtree(" in cmd:
            return SafetyEvaluation(True, REASON_RMTREE)

        if any(k in cmd for k in ("DROP", "drop", "DELETE", "delete", "TRUNCATE", "truncate")):
            sql_patterns = ("DROP TABLE", "DROP DATABASE", "DELETE FROM", "TRUNCATE TABLE")
            cmd_upper = cmd.upper()
            if any(p in cmd_upper for p in sql_patterns):
                return SafetyEvaluation(True, REASON_DB_DESTRUCTIVE)

        # 2. Hardened Subshell & Process Substitution Extraction
        if any(c in cmd for c in ("$", "`", "(", "<", ">")):
            subshells = extract_subshell_commands(cmd)
            for sub in subshells:
                sub_res = cls.evaluate(sub, depth=depth + 1)
                if sub_res.is_destructive:
                    return sub_res

        # 3. Lexical Tokenization with fail-closed error handling
        try:
            tokens = tokenize_command(cmd)
        except ValueError:
            return SafetyEvaluation(True, REASON_UNABLE_TO_PARSE)

        if not tokens:
            return SafetyEvaluation(False)

        # 4. Pipeline Decomposition
        pipelines = decompose_command(tokens)

        for pipeline in pipelines:
            # Check 4A: Pipe-to-Shell cross-stage pattern
            stage_unwrapped = []
            for stage in pipeline.stages:
                unwrapped, inner = unwrap_command_stage(stage.raw_tokens)
                if inner:
                    inner_res = cls.evaluate(inner, depth=depth + 1)
                    if inner_res.is_destructive:
                        return inner_res
                stage_unwrapped.append(unwrapped)

            for i, st in enumerate(stage_unwrapped):
                if st and st.binary in REMOTE_FETCHERS:
                    for downstream in stage_unwrapped[i + 1 :]:
                        if downstream and downstream.binary in SHELL_INTERPRETERS:
                            return SafetyEvaluation(True, REASON_PIPE_TO_SHELL)

            # Check 4B: Individual Stage Evaluation
            for st in stage_unwrapped:
                if not st:
                    continue
                if st.binary == "git":
                    res = evaluate_git(st)
                    if res.is_destructive:
                        return res
                elif st.binary == "gh":
                    res = evaluate_gh(st)
                    if res.is_destructive:
                        return res
                elif st.binary == "rm":
                    ps_res = evaluate_powershell(st)
                    if ps_res.is_destructive:
                        return ps_res
                    res = evaluate_rm(st)
                    if res.is_destructive:
                        return res
                elif st.binary in ("remove-item", "erase", "rd", "ri"):
                    res = evaluate_powershell(st)
                    if res.is_destructive:
                        return res
                elif st.binary == "del":
                    ps_res = evaluate_powershell(st)
                    if ps_res.is_destructive:
                        return ps_res
                    res = evaluate_cmd_del(st)
                    if res.is_destructive:
                        return res
                elif st.binary == "rmdir":
                    cmd_res = evaluate_cmd_del(st)
                    if cmd_res.is_destructive:
                        return cmd_res
                    sys_res = evaluate_system_binary(st)
                    if sys_res.is_destructive:
                        return sys_res

                sys_res = evaluate_system_binary(st)
                if sys_res.is_destructive:
                    return sys_res

        return SafetyEvaluation(False)


__all__ = [
    "CommandAnalyzer",
    "SafetyEvaluation",
    "REASON_CHMOD_777",
    "REASON_CMD_DELETE",
    "REASON_DB_DESTRUCTIVE",
    "REASON_DD",
    "REASON_GIT_ADD_BULK",
    "REASON_GIT_BRANCH",
    "REASON_GIT_CHECKOUT_FORCE",
    "REASON_GIT_CLEAN_FORCE",
    "REASON_GIT_CONFIG",
    "REASON_GIT_DIFF",
    "REASON_GIT_MERGE",
    "REASON_GIT_PUSH_FORCE",
    "REASON_GIT_PUSH_REFSPEC",
    "REASON_GIT_RESET_HARD",
    "REASON_KILL_ALL",
    "REASON_MKFS",
    "REASON_PIPE_TO_SHELL",
    "REASON_POWERSHELL_DELETE",
    "REASON_PROTECTED_BRANCH",
    "REASON_HUMAN_REVIEW_GATE",
    "REASON_RMDIR_BYPASS",
    "REASON_RM_RF",
    "REASON_RMTREE",
    "REASON_SUDO",
    "REASON_UNABLE_TO_PARSE",
    "REASON_WINDOWS_FORMAT",
]
