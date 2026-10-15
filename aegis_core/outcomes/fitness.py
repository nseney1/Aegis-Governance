"""Credit assignment: split one outcome across the rules that matched the changed files."""
from __future__ import annotations

import fnmatch
import os


def compute_credit_weights(triggered_cells: list[dict], changed_files: list[str]) -> dict[str, float]:
    """Compute per-cell credit weights using per-file scope narrowing."""
    if not changed_files or not triggered_cells:
        return {c.get("_name", c.get("id", "")): 1.0 for c in triggered_cells}

    file_to_cells: dict[str, list[str]] = {}
    for fpath in changed_files:
        matching = []
        for cell in triggered_cells:
            cell_name = cell.get("_name", cell.get("id", ""))
            target_paths = cell.get("target_paths", [])
            if isinstance(target_paths, str):
                target_paths = [target_paths]
            for tp in target_paths:
                if fnmatch.fnmatch(fpath, tp) or fnmatch.fnmatch(os.path.basename(fpath), tp):
                    matching.append(cell_name)
                    break
        if matching:
            file_to_cells[fpath] = matching

    credit = {c.get("_name", c.get("id", "")): 0.0 for c in triggered_cells}
    for fpath, cell_names in file_to_cells.items():
        per_cell = 1.0 / len(cell_names)
        for cn in cell_names:
            credit[cn] += per_cell

    return credit
