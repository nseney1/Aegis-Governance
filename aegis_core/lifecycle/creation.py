"""Rule creation: one new rule file in its type directory, under the workspace lock."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from aegis_core.rules import VALID_ENFORCEMENT, load_rules
from aegis_core.storage import atomic_write_text, locked
from aegis_core.taxonomy import CANONICAL_RULE_TYPES, RULE_TYPE_DIRS, RULE_TYPES, normalize_review_mode
from aegis_core.workspace import literal_workspace
from aegis_core.workspace.base import Workspace
from .parsers import (
    generate_slug,
    validate_cell_id,
)

__all__ = [
    "MAX_RULE_BODY_BYTES",
    "create_cell",
    "validate_rule_body",
]

MAX_RULE_BODY_BYTES = 64 * 1024


def validate_rule_body(body: str) -> str:
    """Return ``body`` if it is a usable rule body, else raise ValueError."""
    if not body.strip():
        raise ValueError("rule body is empty")
    if len(body.encode("utf-8")) > MAX_RULE_BODY_BYTES:
        raise ValueError(f"rule body exceeds 64 KiB ({MAX_RULE_BODY_BYTES} bytes)")
    return body


def create_cell(
    cell_type: str,
    hypothesis: str,
    prediction: str = "",
    falsification: str = "",
    weight: float = 1.0,
    tags: list[str] | None = None,
    expiry_sessions: int | None = 15,
    expiry_days: int | None = 60,
    minimum_mode: str | None = "",
    id_override: str | None = None,
    target_paths: list[str] | None = None,
    domain: str | None = "correctness",
    workspace: Workspace | Path | str | None = None,
    enforcement: str | None = None,
    body: str | None = None,
) -> Path:
    """Create a new Aegis rule file with validated frontmatter and body.

    ``body`` replaces the generated markdown body (everything after the
    frontmatter); the hypothesis still populates the frontmatter.
    """
    validate_cell_id(id_override)
    if body is not None:
        validate_rule_body(body)

    type_lower = cell_type.lower()
    if type_lower not in RULE_TYPES:
        raise ValueError(
            f"Invalid type '{cell_type}'. Must be one of: {', '.join(CANONICAL_RULE_TYPES)}."
        )
    mandatory = RULE_TYPES[type_lower].mandatory

    if enforcement is None:
        enforcement = "gate" if mandatory else "advisory"
    else:
        enforcement_lower = enforcement.lower()
        if enforcement_lower not in VALID_ENFORCEMENT:
            raise ValueError(
                f"Invalid enforcement '{enforcement}'. Must be one of: {', '.join(VALID_ENFORCEMENT)}."
            )
        if mandatory and enforcement_lower != "gate":
            raise ValueError(
                f"{type_lower.capitalize()} rules must use 'gate' enforcement, got '{enforcement}'."
            )
        enforcement = enforcement_lower

    # Programmatic callers pass None for "not given".
    domain = "correctness" if domain is None else domain
    minimum_mode = minimum_mode or ""
    if minimum_mode:
        minimum_mode = normalize_review_mode(minimum_mode, default=minimum_mode.strip().lower())

    # These values are interpolated into the frontmatter unquoted; a line
    # break would let the caller inject arbitrary keys (e.g. `activation`).
    # The frontmatter parser breaks lines wherever str.splitlines() does
    # (\v, \f, \x1c-\x1e, \x85, \u2028, \u2029 as well as \n and \r).
    for label, value in (("domain", domain), ("minimum_mode", minimum_mode)):
        if value != "".join(value.splitlines()):
            raise ValueError(f"Invalid {label} {value!r}: must be a single line.")
    weight = _as_number("weight", weight, float)
    expiry_sessions = None if expiry_sessions is None else _as_number("expiry_sessions", expiry_sessions, int)
    expiry_days = None if expiry_days is None else _as_number("expiry_days", expiry_days, int)

    if not prediction:
        prediction = f"Behavior conforms to hypothesis: {hypothesis}"
    if not falsification:
        falsification = f"Behavior violates hypothesis: {hypothesis}"

    ws = literal_workspace(workspace)
    type_plural = RULE_TYPE_DIRS[type_lower]
    target_dir = ws.rules_dir / type_plural

    slug = generate_slug(hypothesis, id_override)
    file_path = target_dir / f"{slug}.md"

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    type_title = type_lower.capitalize()
    truncated_hypo = hypothesis[:60] + ("..." if len(hypothesis) > 60 else "")

    def escape_yaml_string(val: str) -> str:
        s = val.replace("\\", "\\\\").replace('"', '\\"')
        return " ".join(s.splitlines())

    tags_list = tags or []
    paths_list = target_paths or []

    optional_block = f"\nminimum_mode: {minimum_mode}" if minimum_mode else ""

    expiry_sess_str = "null" if expiry_sessions is None else str(expiry_sessions)
    expiry_days_str = "null" if expiry_days is None else str(expiry_days)

    frontmatter = f"""---
id: {slug}
domain: {domain}
type: {type_lower}
enforcement: {enforcement}
hypothesis: "{escape_yaml_string(hypothesis)}"
prediction: "{escape_yaml_string(prediction)}"
falsification: "{escape_yaml_string(falsification)}"
expiry_sessions: {expiry_sess_str}
expiry_days: {expiry_days_str}
created: "{date_str}"
impact_weight: {weight}
tags: {json.dumps(tags_list)}
target_paths: {json.dumps(paths_list)}
lineage:
  parent_id: null
  created_by: "manual"
  generation: 0
  siblings: []{optional_block}
---
"""
    if body is None:
        body = f"""## {type_title}: {truncated_hypo}

{hypothesis}

### Prediction
{prediction}

### Falsification Criteria
{falsification}
"""
    elif not body.endswith("\n"):
        body += "\n"
    content = frontmatter + body

    # Validate in memory so a malformed rule never reaches disk.
    from aegis_core.yaml_engine.frontmatter import AegisYAML

    AegisYAML.parse_text(content)

    with locked(ws.root):
        # Checked under the lock that promote/demote hold: replacing a rule
        # would discard its fitness and lineage, and the same id in a second
        # tier would make two active rules answer to one id. A symlink at the
        # target counts as existing, so the writer never follows it out.
        existing = file_path if os.path.lexists(file_path) else _existing_rule_path(ws, slug)
        if existing is not None:
            raise FileExistsError(f"rule '{slug}' already exists: {existing}")
        target_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(file_path, content)

    return file_path


def _existing_rule_path(ws: Workspace, slug: str) -> Path | None:
    """A rule record already using ``slug`` (broken or not; archived rules free their id)."""
    for rule in load_rules(ws).rules:
        if rule.id == slug:
            return ws.root / rule.path
    return None


def _as_number(label: str, value: object, cast: type) -> float | int:
    try:
        return cast(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {label} {value!r}: must be a number.") from None


