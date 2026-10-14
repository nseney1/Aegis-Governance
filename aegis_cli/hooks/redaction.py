"""Secret redaction utilities for command logging."""
from __future__ import annotations

import re

SECRET_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"""
            AKIA[0-9A-Z]{16}  # AWS standard access key
            """,
            re.VERBOSE,
        ),
        "AKIA_REDACTED",
    ),
    (
        re.compile(
            r"""
            ASIA[0-9A-Z]{16}  # AWS temporary/session access key
            """,
            re.VERBOSE,
        ),
        "ASIA_REDACTED",
    ),
    (
        re.compile(
            r"""
            ghp_[a-zA-Z0-9]{36}  # GitHub Personal Access Token (classic)
            """,
            re.VERBOSE,
        ),
        "ghp_REDACTED",
    ),
    (
        re.compile(
            r"""
            gh[ousr]_[a-zA-Z0-9]{36}  # GitHub OAuth/user/server/refresh tokens
            """,
            re.VERBOSE,
        ),
        "gh_token_REDACTED",
    ),
    (
        re.compile(
            r"""
            github_pat_[a-zA-Z0-9_]{20,}  # GitHub Fine-grained PAT
            """,
            re.VERBOSE,
        ),
        "github_pat_REDACTED",
    ),
    (
        re.compile(
            r"""
            sk-(?:proj-|ant-)?[a-zA-Z0-9_-]{20,}  # OpenAI / Anthropic API keys
            """,
            re.VERBOSE,
        ),
        "sk-REDACTED",
    ),
    (
        re.compile(
            r"""
            AIzaSy[a-zA-Z0-9_-]{33}  # Google API key
            """,
            re.VERBOSE,
        ),
        "AIzaSy_REDACTED",
    ),
    (
        re.compile(
            r"""
            Bearer\s+[a-zA-Z0-9._-]{20,}  # HTTP Bearer authentication token
            """,
            re.VERBOSE,
        ),
        "Bearer REDACTED",
    ),
    (
        re.compile(
            r"""
            GEMINI_API_KEY=[^\s]*  # Gemini API Key assignment
            """,
            re.VERBOSE,
        ),
        "GEMINI_API_KEY=REDACTED",
    ),
]


def redact_secrets(cmd: str) -> str:
    """Mask known secret patterns before logging."""
    for pattern, replacement in SECRET_REPLACEMENTS:
        cmd = pattern.sub(replacement, cmd)
    return cmd
