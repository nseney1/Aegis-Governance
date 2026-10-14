"""Selection pressure, cell crossover, and hypothesis merging."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Optional

from aegis_core.somayaml import dump_frontmatter
from aegis_core.workspace import Workspace, resolve_workspace
from .constants import (
    EXTINCTION_THRESHOLD,
)
from .parsers import (
    find_cell,
    get_type_plural,
    parse_cell,
)

__all__ = [
    "run_cell_selection",
    "select_cell",
    "cli_cell_crossover",
    "crossover_cells",
    "tournament_select",
]


def run_cell_selection(workspace: Workspace | Path | str | None = None, execute: bool = False) -> int:
    """Selection pressure engine for Soma immune cells."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells_dir = ws.cells_dir
    archive_dir = cells_dir / ".archive"
    evidence_dir = ws.evidence_dir
    evidence_dir.mkdir(parents=True, exist_ok=True)
    fitness_log = evidence_dir / "lifecycle.jsonl"

    if not cells_dir.exists():
        print("No cells directory found.")
        return 0

    print(f"Running cell selection (execute={execute})...")
    if execute:
        archive_dir.mkdir(parents=True, exist_ok=True)

    for root_str, _dirs, files in os.walk(cells_dir):
        if ".archive" in root_str:
            continue
        for f in files:
            if not f.endswith(".md") or f == "README.md":
                continue
            fpath = Path(root_str) / f
            try:
                content = fpath.read_text(encoding="utf-8")
            except Exception:
                continue

            fm_match = re.search(r"^---\n(.*?)\n---", content, re.DOTALL)
            if not fm_match:
                continue
            fm = fm_match.group(1)

            def get_val(key: str, default: float = 0.0) -> float:
                m = re.search(rf"{key}:\s*(\S+)", fm)
                if m and m.group(1) != "null":
                    try:
                        return float(m.group(1))
                    except ValueError:
                        return default
                return default

            triggers = get_val("triggers", 0.0)
            tp = get_val("true_positives", 0.0)
            fp = get_val("false_positives", 0.0)
            type_match = re.search(r"type:\s*([^\s\n]+)", fm)
            cell_type = type_match.group(1) if type_match else ""
            dormant = "dormant_since" in fm

            if triggers == 0:
                category = "DORMANT"
                score = 0.0
            else:
                score = tp / triggers
                if fp > 0 and tp > 0 and fp > 2 * tp:
                    category = "APOPTOSIS_WARNING" if cell_type == "wall" else "APOPTOSIS"
                elif score > 0.7:
                    category = "SURVIVE"
                elif score >= EXTINCTION_THRESHOLD:
                    category = "ADAPT"
                else:
                    category = "EXTINCT"

            print(f"[{category}] {f} (Score: {score:.2f})")

            if execute:
                action = None
                if category in ("EXTINCT", "APOPTOSIS"):
                    if category == "APOPTOSIS":
                        last_gasp_dir = cells_dir / ".last_gasp_queue"
                        last_gasp_dir.mkdir(parents=True, exist_ok=True)
                        dest = last_gasp_dir / f
                        shutil.move(str(fpath), str(dest))
                        action = "last_gasp_requested"
                    else:
                        dest = archive_dir / f
                        shutil.move(str(fpath), str(dest))
                        action = "moved_to_archive"
                elif category == "DORMANT" and not dormant:
                    timestamp = datetime.now(timezone.utc).isoformat() + "Z"
                    new_content = content.replace("fitness:", f"dormant_since: {timestamp}\nfitness:")
                    fpath.write_text(new_content, encoding="utf-8")
                    action = "marked_dormant"

                if action:
                    with open(fitness_log, "a", encoding="utf-8") as log:
                        log.write(json.dumps({
                            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                            "cell": f,
                            "action": action,
                        }) + "\n")
    return 0


def prune_cells(workspace: Workspace | Path | str | None = None, execute: bool = False) -> int:
    """Evaluate and prune extinct or apoptotic rules."""
    return run_cell_selection(workspace=workspace, execute=execute)


def crossover_cells(workspace: Workspace | Path | str, cell_a_id: str, cell_b_id: str) -> tuple[str, str, str]:
    """Merge complementary hypotheses from two high-fitness cells."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cell_a_path = find_cell(ws, cell_a_id)
    cell_b_path = find_cell(ws, cell_b_id)

    if not cell_a_path or not cell_b_path:
        raise ValueError(f"Could not locate one or both parent cells: {cell_a_id}, {cell_b_id}")

    meta_a, body_a = parse_cell(cell_a_path)
    meta_b, body_b = parse_cell(cell_b_path)

    if not meta_a or not meta_b:
        raise ValueError("One or both parent cells lack valid YAML frontmatter.")

    hyp_a = meta_a.get("hypothesis", "").strip()
    hyp_b = meta_b.get("hypothesis", "").strip()
    merged_hypothesis = f"{hyp_a}, prioritizing {hyp_b}"

    pred_a = meta_a.get("prediction", "").strip()
    pred_b = meta_b.get("prediction", "").strip()
    merged_prediction = f"{pred_a}\n\n{pred_b}".strip()

    weight_a = meta_a.get("impact_weight", 1.0)
    weight_b = meta_b.get("impact_weight", 1.0)
    merged_weight = max(weight_a, weight_b)

    type_a = meta_a.get("type", "vacuole")
    type_b = meta_b.get("type", "vacuole")
    merged_type = type_a if type_a == type_b else "vacuole"

    slug = re.sub(r"[^a-z0-9 ]", "", merged_hypothesis.lower())
    slug = re.sub(r"\s+", "-", slug)[:50].strip("-")

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    type_plural = get_type_plural(merged_type)
    out_dir = ws.cells_dir / type_plural
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}.md"

    tp_a = meta_a.get("target_paths", []) or []
    tp_b = meta_b.get("target_paths", []) or []
    if isinstance(tp_a, str):
        tp_a = [tp_a]
    if isinstance(tp_b, str):
        tp_b = [tp_b]
    merged_target_paths = sorted(set(tp_a + tp_b))

    tags_a = meta_a.get("tags", []) or []
    tags_b = meta_b.get("tags", []) or []
    if isinstance(tags_a, str):
        tags_a = [tags_a]
    if isinstance(tags_b, str):
        tags_b = [tags_b]
    merged_tags = sorted(set(tags_a + tags_b))

    gen_a = meta_a.get("lineage", {}).get("generation", 0) if isinstance(meta_a.get("lineage"), dict) else 0
    gen_b = meta_b.get("lineage", {}).get("generation", 0) if isinstance(meta_b.get("lineage"), dict) else 0
    merged_generation = max(gen_a, gen_b) + 1

    new_meta = {
        "type": merged_type,
        "hypothesis": merged_hypothesis,
        "prediction": merged_prediction,
        "falsification": "Falsification criteria combined or needs review.",
        "target_paths": merged_target_paths,
        "expiry_sessions": 15,
        "expiry_days": 60,
        "created": date_str,
        "impact_weight": merged_weight,
        "tags": merged_tags,
        "lineage": {
            "parent_id": f"{cell_a_id} × {cell_b_id}",
            "created_by": "crossover",
            "generation": merged_generation,
            "siblings": [],
        },
        "fitness": {
            "triggers": 0,
            "true_positives": 0,
            "false_positives": 0,
            "score": None,
        }
    }

    nfm = dump_frontmatter(new_meta)

    content = f"---\n{nfm.strip()}\n---\n\n## {merged_type.capitalize()}: {merged_hypothesis[:60]}\n\n{merged_hypothesis}\n\n### Prediction\n{merged_prediction}\n"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    parent_a_name = os.path.basename(cell_a_path)
    parent_b_name = os.path.basename(cell_b_path)
    new_cell_name = os.path.basename(out_path)

    metrics_dir = ws.metrics_dir
    metrics_dir.mkdir(parents=True, exist_ok=True)
    metrics_file = metrics_dir / "crossovers.jsonl"
    log_entry = {
        "timestamp": date_str,
        "parent_a": parent_a_name,
        "parent_b": parent_b_name,
        "new_cell": new_cell_name,
        "merged_type": merged_type,
    }
    with open(metrics_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

    return parent_a_name, parent_b_name, new_cell_name


def cli_cell_crossover(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge complementary hypotheses from two high-fitness cells")
    parser.add_argument("cell_a_id", help="ID of the first parent cell")
    parser.add_argument("cell_b_id", help="ID of the second parent cell")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    workspace = resolve_workspace()
    try:
        pa, pb, out = crossover_cells(workspace, args.cell_a_id, args.cell_b_id)
        try:
            print(f"Crossover: {pa} × {pb} → {out}")
        except (UnicodeEncodeError, UnicodeError):
            print(f"Crossover: {pa} x {pb} -> {out}")
        return 0
    except Exception as exc:
        print(f"Crossover failed: {exc}", file=sys.stderr)
        return 1
