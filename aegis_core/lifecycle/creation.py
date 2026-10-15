"""Cell creation and cross-project transfer."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from aegis_core.yaml import dump_frontmatter, parse_frontmatter
from aegis_core.locking import workspace_lock
from aegis_core.storage import atomic_write_text
from aegis_core.taxonomy import ReviewMode, normalize_review_mode
from aegis_core.workspace import Workspace
from aegis_core.workspace.layout import LockResource
from .constants import (
    VALID_ENFORCEMENT,
    VALID_TYPES,
)
from .parsers import (
    generate_slug,
    validate_cell_id,
)
# Rules parked by selection are no longer active, so their ids are free.
from .selection import PARKED_RULE_DIRS

__all__ = [
    "MAX_RULE_BODY_BYTES",
    "create_cell",
    "cli_cell_create",
    "transfer_cell",
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
    effector: bool = False,
    memory: bool = False,
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
    if type_lower not in VALID_TYPES:
        raise ValueError(
            f"Invalid type '{cell_type}'. Must be one of: trap, persona, invariant, boundary, contract."
        )

    if enforcement is None:
        enforcement = "gate" if type_lower in ("wall", "invariant") else "advisory"
    else:
        enforcement_lower = enforcement.lower()
        if enforcement_lower not in VALID_ENFORCEMENT:
            raise ValueError(
                f"Invalid enforcement '{enforcement}'. Must be one of: {', '.join(VALID_ENFORCEMENT)}."
            )
        if type_lower in ("wall", "invariant") and enforcement_lower != "gate":
            raise ValueError(
                f"Wall cells must use 'gate' enforcement, got '{enforcement}'."
            )
        enforcement = enforcement_lower

    if effector and memory:
        raise ValueError("--effector and --memory are mutually exclusive.")

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

    response_type = ""
    activation = ""
    decay_to_yaml = ""

    if effector:
        expiry_sessions = 3
        weight = 3.0
        response_type = "effector"
        minimum_mode = str(ReviewMode.FORTRESS)
        decay_to_yaml = (
            "decay_to:\n"
            "  type: boundary\n"
            "  impact_weight: 1.0\n"
            f"  minimum_mode: {ReviewMode.VANGUARD}\n"
            "  response_type: memory\n"
            "  activation: dormant\n"
        )

    if memory:
        expiry_sessions = None
        weight = 1.5
        response_type = "memory"
        minimum_mode = str(ReviewMode.BULWARK)
        activation = "dormant"

    if not prediction:
        prediction = f"Behavior conforms to hypothesis: {hypothesis}"
    if not falsification:
        falsification = f"Behavior violates hypothesis: {hypothesis}"

    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    type_plural = VALID_TYPES[type_lower]
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

    optional_lines = []
    if response_type:
        optional_lines.append(f"response_type: {response_type}")
    if minimum_mode:
        optional_lines.append(f"minimum_mode: {minimum_mode}")
    if activation:
        optional_lines.append(f"activation: {activation}")
    if decay_to_yaml:
        optional_lines.append(decay_to_yaml.rstrip())

    optional_block = ("\n" + "\n".join(optional_lines)) if optional_lines else ""

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
    from aegis_core.yaml import AegisYAML

    AegisYAML.parse_text(content)

    with workspace_lock(ws.root, LockResource.RULES):
        # Checked under the lock that promote/demote hold: replacing a rule
        # would discard its fitness and lineage, and the same id in a second
        # tier would make two active rules answer to one id. A symlink at the
        # target counts as existing, so the writer never follows it out.
        existing = file_path if os.path.lexists(file_path) else _active_rule_path(ws.rules_dir, slug)
        if existing is not None:
            raise FileExistsError(f"rule '{slug}' already exists: {existing}")
        target_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(file_path, content)

    return file_path


def _active_rule_path(rules_dir: Path, slug: str) -> Path | None:
    name = f"{slug}.md"
    for dirpath, dirnames, filenames in os.walk(rules_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in PARKED_RULE_DIRS)
        if name in filenames:
            return Path(dirpath) / name
    return None


def _as_number(label: str, value: object, cast: type) -> float | int:
    try:
        return cast(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {label} {value!r}: must be a number.") from None


def cli_cell_create(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Programmatic Cell Creation for Aegis", add_help=False)
    parser.add_argument("--help", action="store_true", default=False)
    parser.add_argument("-t", "--type", dest="cell_type", default="")
    parser.add_argument("-h", "--hypothesis", dest="hypothesis", default="")
    parser.add_argument("-p", "--prediction", dest="prediction", default="")
    parser.add_argument("-f", "--falsification", dest="falsification", default="")
    parser.add_argument("-w", "--weight", dest="weight", type=float, default=1.0)
    parser.add_argument("--tags", dest="tags", default="")
    parser.add_argument("--expiry-sessions", dest="expiry_sessions", type=int, default=15)
    parser.add_argument("--expiry-days", dest="expiry_days", type=int, default=60)
    parser.add_argument("--minimum-mode", dest="minimum_mode", default="")
    parser.add_argument("-n", "--name", "--id", dest="cell_id", default="")
    parser.add_argument("--effector", action="store_true", default=False)
    parser.add_argument("--memory", action="store_true", default=False)
    parser.add_argument("--target-paths", dest="target_paths", default="")
    parser.add_argument("-d", "--domain", dest="domain", default="correctness")
    parser.add_argument("-e", "--enforcement", dest="enforcement", default=None)

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.help:
        print("Usage: cell_create.py --type <type> --hypothesis <hypo> [options]")
        return 0

    if args.cell_id:
        try:
            validate_cell_id(args.cell_id)
        except ValueError:
            print("Error: Invalid ID_OVERRIDE contains path traversal characters.", file=sys.stderr)
            return 1

    if not args.cell_type or not args.hypothesis:
        print("Error: Missing required arguments --type and --hypothesis", file=sys.stderr)
        return 1

    hypo = args.hypothesis
    tag_list = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
    paths = [p.strip() for p in args.target_paths.split(",") if p.strip()] if args.target_paths else None

    try:
        created = create_cell(
            cell_type=args.cell_type,
            hypothesis=hypo,
            prediction=args.prediction,
            falsification=args.falsification,
            weight=args.weight,
            tags=tag_list,
            expiry_sessions=args.expiry_sessions,
            expiry_days=args.expiry_days,
            minimum_mode=args.minimum_mode,
            id_override=args.cell_id or None,
            effector=args.effector,
            memory=args.memory,
            target_paths=paths,
            domain=args.domain,
            enforcement=args.enforcement,
        )
        print(f"Created cell: {created}")
        return 0
    except (ValueError, FileExistsError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Execution failed: {e}", file=sys.stderr)
        return 1


def transfer_cell(
    cell_id: str,
    target_dir_str: str,
    source_workspace: Workspace | Path | str | None = None,
) -> int:
    """Transfer a cell from source workspace to target directory with fitness reset."""
    src_ws = source_workspace if isinstance(source_workspace, Workspace) else (
        Workspace(root=Path(source_workspace).resolve()) if source_workspace else Workspace.resolve()
    )
    if not src_ws.rules_dir.is_dir():
        print(f"Error: No Aegis project found: no .aegis/rules/ in {src_ws.root or os.getcwd()} or any parent directory.", file=sys.stderr)
        print("Run from inside the source project, or set AEGIS_WORKSPACE to its root.", file=sys.stderr)
        return 1

    target_dir = Path(target_dir_str).resolve()
    if not (target_dir / ".aegis").is_dir():
        print(f"Error: Target directory does not have a .aegis/ directory: {target_dir}", file=sys.stderr)
        return 1

    source_path = None
    cells_dir = src_ws.rules_dir
    for cand in cells_dir.rglob("*.md"):
        if cand.name == "README.md":
            continue
        if cand.stem == cell_id or cell_id in cand.name:
            source_path = cand
            break

    if not source_path:
        print(f"Error: Could not find cell '{cell_id}' in {cells_dir}", file=sys.stderr)
        return 1

    try:
        content = source_path.read_text(encoding="utf-8")
        meta = parse_frontmatter(content) or {}
    except Exception as exc:
        print(f"Error reading cell {source_path}: {exc}", file=sys.stderr)
        return 1

    meta["fitness"] = {
        "triggers": 0,
        "true_positives": 0,
        "false_positives": 0,
        "score": None,
    }
    lineage = meta.get("lineage") or {}
    if isinstance(lineage, dict):
        lineage["parent_id"] = source_path.stem
        lineage["generation"] = int(lineage.get("generation", 0)) + 1
        lineage["created_by"] = "transfer"
        meta["lineage"] = lineage

    target_sub = source_path.parent.name
    dest_dir = target_dir / ".aegis" / "rules" / target_sub
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / source_path.name
    from aegis_core.yaml import _get_body
    new_fm = dump_frontmatter(meta)
    body = _get_body(content).lstrip()
    new_content = f"---\n{new_fm.strip()}\n---\n\n{body}\n" if body else f"---\n{new_fm.strip()}\n---\n"
    with workspace_lock(target_dir, LockResource.RULES):
        atomic_write_text(dest_path, new_content)

    metrics_dir = src_ws.metrics_dir
    metrics_dir.mkdir(parents=True, exist_ok=True)
    log_file = metrics_dir / "transfers.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cell": source_path.name,
            "target": str(target_dir),
        }) + "\n")

    print(f"Transferred: {source_path.name} -> {dest_path}")
    return 0
