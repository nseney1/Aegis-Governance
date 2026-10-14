"""Cell creation and cross-project transfer."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Optional

from aegis_core.yaml import dump_frontmatter, parse_frontmatter
from aegis_core.workspace import Workspace, resolve_workspace
from .constants import (
    VALID_ENFORCEMENT,
    VALID_TYPES,
)
from .parsers import (
    generate_slug,
    validate_cell_id,
)

__all__ = [
    "create_cell",
    "create_cell_from_description",
    "cli_cell_create",
    "transfer_cell",
]


def create_cell(
    cell_type: str,
    hypothesis: str,
    prediction: str = "",
    falsification: str = "",
    weight: float = 1.0,
    tags: list[str] | None = None,
    expiry_sessions: int | None = 15,
    expiry_days: int | None = 60,
    minimum_mode: str = "",
    id_override: str | None = None,
    effector: bool = False,
    memory: bool = False,
    target_paths: list[str] | None = None,
    domain: str = "correctness",
    workspace: Workspace | Path | str | None = None,
    enforcement: str | None = None,
) -> Path:
    """Create a new Soma cell file with validated frontmatter and body."""
    validate_cell_id(id_override)

    type_lower = cell_type.lower()
    if type_lower not in VALID_TYPES:
        raise ValueError(
            f"Invalid type '{cell_type}'. Must be one of: vacuole, chloroplast, wall, membrane, plasmodesmata."
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

    response_type = ""
    activation = ""
    decay_to_yaml = ""

    if effector:
        expiry_sessions = 3
        weight = 3.0
        response_type = "effector"
        minimum_mode = "tempest"
        decay_to_yaml = (
            "decay_to:\n"
            "  type: membrane\n"
            "  impact_weight: 1.0\n"
            "  minimum_mode: trident\n"
            "  response_type: memory\n"
            "  activation: dormant\n"
        )

    if memory:
        expiry_sessions = None
        weight = 1.5
        response_type = "memory"
        minimum_mode = "maelstrom"
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
    target_dir.mkdir(parents=True, exist_ok=True)

    slug = generate_slug(hypothesis, id_override)
    file_path = target_dir / f"{slug}.md"

    if file_path.is_symlink():
        file_path.unlink()

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

    content = f"""---
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
## {type_title}: {truncated_hypo}

{hypothesis}

### Prediction
{prediction}

### Falsification Criteria
{falsification}
"""

    file_path.write_text(content, encoding="utf-8")

    if not file_path.is_file() or file_path.stat().st_size == 0:
        if file_path.exists():
            file_path.unlink()
        raise RuntimeError(f"Cell was not written correctly (empty file): {file_path}")

    read_back = file_path.read_text(encoding="utf-8")
    if read_back.count("---") < 2:
        raise ValueError(f"Cell frontmatter is malformed (missing closing '---'): {file_path}")

    return file_path


def create_cell_from_description(
    description: str,
    domain_hint: Optional[str] = None,
    cell_type: Optional[str] = None,
    provider_name: Optional[str] = None,
    workspace: Optional[Workspace | str | Path] = None,
) -> str:
    """Use AI inference provider to generate cell YAML from natural language."""
    from aegis_core.inference_provider import resolve_provider

    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    provider = resolve_provider(str(ws.root), provider_name)

    examples = []
    cells_dir = ws.rules_dir
    if cells_dir.is_dir():
        for cell_file in cells_dir.rglob("*.md"):
            if cell_file.name == "README.md":
                continue
            try:
                content = cell_file.read_text(encoding="utf-8")
                if content.startswith("---"):
                    examples.append(content[:500])
            except Exception:
                pass

    example_text = "\n---\n".join(examples[:3]) if examples else "No existing cells found."
    domain_context = f"\nDomain hint: {domain_hint}" if domain_hint else ""
    type_hint = f"\nPreferred cell type: {cell_type}" if cell_type else ""

    prompt = f"""You are a governance cell generator for Soma.

Given a natural language description of a concern, generate a governance cell in markdown with YAML frontmatter.

Cell types:
- wall: Non-negotiable invariant (hard safety gate). Use for things that must ALWAYS hold.
- vacuole: Learned anti-pattern trap. Use for known failure modes to watch for.
- membrane: Escalation gate. Use when sensitive areas need elevated review.
- chloroplast: Domain persona/accelerator. Use for idiomatic patterns to follow.
- plasmodesmata: Cross-service contract. Use for API/data shape agreements.

YAML fields required:
- id: (filename stem, e.g. 'trap-missing-tests' for trap-missing-tests.md)
- type: (one of above)
- domain: (one of: efficiency, correctness, security, style, governance)
- enforcement: (gate for walls, advisory for vacuoles)
- hypothesis: (clear, testable statement)
- prediction: (what will happen if the hypothesis is violated)
- falsification: (how to prove this cell is no longer needed)
- target_paths: (list of file glob patterns this cell monitors)
- minimum_mode: (breeze | gale | trident | maelstrom | tempest)
- tags: (list of relevant tags)

Existing cells in this project for reference:
{example_text}
{domain_context}{type_hint}

User description: "{description}"

Generate ONLY the complete markdown cell file content. Start with --- for the YAML frontmatter. After the closing ---, include a brief description paragraph explaining the cell's purpose. Do not include any other text."""

    return provider.generate(prompt).strip()


def cli_cell_create(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Programmatic Cell Creation for Soma", add_help=False)
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
    parser.add_argument("--from-description", dest="description", default="")
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

    if args.description:
        try:
            created = create_cell(
                cell_type=args.cell_type or "vacuole",
                hypothesis=args.description,
                id_override=args.cell_id or None,
                domain=args.domain,
                enforcement=args.enforcement,
            )
            print(f"Created: {created}")
            return 0
        except Exception as exc:
            print(f"Error generating cell from description: {exc}", file=sys.stderr)
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
    except ValueError as e:
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
    dest_path.write_text(new_content, encoding="utf-8")

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
