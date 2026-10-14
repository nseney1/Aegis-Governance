"""Credit assignment, fitness signals calculation, frontmatter updates, and platform transcript parsing."""
from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
from fractions import Fraction
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any, Optional

from aegis_core.cell_inventory import find_matching_cells
from aegis_core.yaml import _get_body, dump_frontmatter, parse_frontmatter, parse_rule_frontmatter

INSIGHT_PRINCIPAL = "outcome_engine"
INSIGHT_SCOPE = "human_insight"


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_fraction(credit: Any) -> str:
    """Convert credit float to a string Fraction (e.g., '1/3') for deterministic storage."""
    if isinstance(credit, str) and "/" in credit:
        return credit
    try:
        val = max(0.0, min(1.0, float(credit)))
    except (ValueError, TypeError):
        val = 0.0
    f = Fraction(val).limit_denominator(1000)
    return f"{f.numerator}/{f.denominator}"


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


def compute_fitness_signals(triggered_cells: list[dict], outcomes: dict, changed_files: Optional[list[str]] = None) -> list[dict]:
    """ACE-aligned reflector: score cells based on VERIFIABLE outcomes."""
    credit_weights = compute_credit_weights(triggered_cells, changed_files or [])
    results = []
    test_outcome = outcomes.get("tests", {})
    build_outcome = outcomes.get("build", {})
    git = outcomes.get("git", {})
    mcp = outcomes.get("mcp", [])

    for cell in triggered_cells:
        signal = 0.0
        reasons = []

        # 1. Test exit code — GROUND TRUTH
        if test_outcome.get("verified") and test_outcome.get("passed") is not None:
            if test_outcome["passed"]:
                signal += 1.0
                reasons.append(f"tests passed ({test_outcome.get('framework', '?')})")
            else:
                signal -= 1.0
                reasons.append(f"tests FAILED ({test_outcome.get('framework', '?')})")

        # 2. Build exit code — STRONG SIGNAL
        elif build_outcome.get("verified") and build_outcome.get("passed") is not None:
            if build_outcome["passed"]:
                signal += 0.7
                reasons.append("build passed")
            else:
                signal -= 0.7
                reasons.append("build FAILED")

        # 3. Git reverts — VERIFIABLE FAILURE
        if git.get("reverts", 0) > 0:
            signal -= 1.0
            reasons.append(f"{git['reverts']} revert(s) detected")

        # 4. Rework on cell's target files — WEAK BUT VERIFIABLE
        rework_files = git.get("rework_files", [])
        cell_targets = cell.get("target_paths", [])
        if isinstance(cell_targets, str):
            cell_targets = [cell_targets]

        rework_hit = False
        for rf in rework_files:
            for tp in cell_targets:
                if fnmatch.fnmatch(rf, tp):
                    rework_hit = True
                    break
            if rework_hit:
                break
        if rework_hit:
            signal -= 0.3
            reasons.append("rework detected on target files")

        # 5. MCP self-report — WEAKEST
        cell_name = cell.get("_name", cell.get("id", ""))
        for mcp_entry in mcp:
            cells_used = list(mcp_entry.get("cells_used", []))
            cell_id = mcp_entry.get("cell_id") or mcp_entry.get("cell_name") or mcp_entry.get("cell")
            if cell_id and cell_id not in cells_used:
                cells_used.append(cell_id)

            if cell_name in cells_used:
                outcome = mcp_entry.get("outcome", "")
                if outcome in ("success", "tp"):
                    if test_outcome.get("verified") and test_outcome.get("passed") is False:
                        signal -= 2.0
                        reasons.append("agent claimed success but tests FAILED (overconfidence penalty)")
                    elif not test_outcome.get("verified") and not build_outcome.get("verified") and git.get("reverts", 0) == 0:
                        signal -= 1.0
                        reasons.append("agent claimed success with zero verifiable evidence (overconfidence penalty)")
                    else:
                        signal += 0.2
                        reasons.append("agent reported success")
                elif outcome in ("failure", "fp"):
                    signal -= 0.2
                    reasons.append("agent reported failure")

        signal = max(-2.0, min(2.0, signal))

        results.append({
            "cell": cell_name,
            "_path": cell.get("_path"),
            "signal": round(signal, 2),
            "reasons": reasons,
            "verified": bool(test_outcome.get("verified", False) or build_outcome.get("verified", False)),
            "credit_weight": credit_weights.get(cell_name, 1.0),
            "signal_method": "credit_weighted",
        })

    return results


def update_cell_fitness(workspace: str, fitness_signals: list[dict]) -> None:
    """Update cell frontmatter with fitness signals using YAML / dump_frontmatter."""
    for sig in fitness_signals:
        fpath = sig.get("_path")
        if not fpath or not os.path.isfile(fpath):
            continue
        signal = sig.get("signal", 0.0)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            try:
                fm, raw_body = parse_rule_frontmatter(content)
            except Exception:
                continue
            body = raw_body.strip()

            fitness = fm.get("fitness")
            if fitness is None or isinstance(fitness, bool):
                fitness = {"score": None, "impact_weight": 1.0}
            elif isinstance(fitness, (int, float)):
                fitness = {"score": float(fitness), "impact_weight": 1.0}
            elif isinstance(fitness, str):
                try:
                    fitness = {"score": float(fitness), "impact_weight": 1.0}
                except ValueError:
                    fitness = {"score": None, "impact_weight": 1.0}
            elif not isinstance(fitness, dict):
                fitness = {"score": None, "impact_weight": 1.0}

            fitness["triggers"] = _as_int(fitness.get("triggers", 0)) + 1
            fitness.setdefault("true_positives", 0)
            fitness.setdefault("false_positives", 0)

            credit_weight = sig.get("credit_weight", 1.0)
            frac_str = to_fraction(credit_weight)

            if signal > 0:
                raw_tp = str(fitness["true_positives"]).strip()
                try:
                    current = Fraction(raw_tp)
                except Exception:
                    current = Fraction(0)
                new_val = current + Fraction(frac_str)
                r = round(float(new_val), 4)
                fitness["true_positives"] = int(r) if r.is_integer() else r
            elif signal < 0:
                raw_fp = str(fitness["false_positives"]).strip()
                try:
                    current = Fraction(raw_fp)
                except Exception:
                    current = Fraction(0)
                new_val = current + Fraction(frac_str)
                r = round(float(new_val), 4)
                fitness["false_positives"] = int(r) if r.is_integer() else r

            fitness["last_trigger_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            fm["fitness"] = fitness

            new_fm = dump_frontmatter(fm)
            new_content = f"---\n{new_fm.strip()}\n---\n\n{body}\n" if body else f"---\n{new_fm.strip()}\n---\n"

            tmp_fpath = f"{fpath}.tmp.{os.getpid()}"
            with open(tmp_fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_fpath, fpath)
        except Exception as e:
            print(f"    ! failed to update fitness for {fpath}: {e}", file=sys.stderr)


def append_fitness_log(
    workspace: str,
    fitness_signals: list[dict],
    outcomes: dict,
    expected_generation: Optional[int] = None,
    idempotency_prefix: Optional[str] = None,
) -> bool:
    """Atomically append one outcome-engine batch to canonical evidence."""
    if not fitness_signals:
        return True

    from aegis_core.telemetry import append_signals

    if idempotency_prefix is None:
        idempotency_prefix = secrets.token_hex(16)

    events = []
    for sig in fitness_signals:
        signal_val = sig.get("signal", 0)
        if signal_val > 0:
            signal_type = "tp"
        elif signal_val < 0:
            signal_type = "fp"
        else:
            signal_type = "trigger"

        metadata = {
            "raw_signal": sig.get("signal"),
            "verified": sig.get("verified", False),
            "credit_weight": sig.get("credit_weight", 1.0),
            "signal_method": sig.get("signal_method", "legacy"),
            "reasons": sig.get("reasons", []),
            "outcomes": {
                "tests": {
                    "verified": outcomes.get("tests", {}).get("verified", False),
                    "passed": outcomes.get("tests", {}).get("passed"),
                    "framework": outcomes.get("tests", {}).get("framework"),
                },
                "build": {
                    "verified": outcomes.get("build", {}).get("verified", False),
                    "passed": outcomes.get("build", {}).get("passed"),
                },
                "git": {
                    "reverts": outcomes.get("git", {}).get("reverts", 0),
                    "rework_count": len(outcomes.get("git", {}).get("rework_files", [])),
                },
            },
        }

        insight_id = sig.get("insight_id")
        if insight_id:
            metadata["insight_id"] = insight_id
            principal = INSIGHT_PRINCIPAL
            scope = INSIGHT_SCOPE
            key = insight_id
        else:
            principal = "outcome_engine"
            scope = "run"
            key = idempotency_prefix

        events.append({
            "cell_name": sig["cell"],
            "signal_type": signal_type,
            "source": "session",
            "metadata": metadata,
            "principal": principal,
            "idempotency_scope": scope,
            "idempotency_key": key,
        })

    try:
        append_signals(workspace, events, expected_generation=expected_generation)
    except Exception as exc:
        print(f"    ! failed to log fitness signal batch: {exc}", file=sys.stderr)
        return False
    return True


PLATFORMS = {
    "antigravity": {
        "write_tools": {"write_to_file", "replace_file_content", "multi_replace_file_content"},
        "target_file_keys": ["TargetFile"],
        "args_keys": ["arguments", "args"],
        "id_skip_dirs": {"logs", ".system_generated"},
    },
    "claude": {
        "write_tools": {"write_to_file", "edit_file", "create_file"},
        "target_file_keys": ["path", "file_path", "TargetFile"],
        "args_keys": ["arguments", "args", "input"],
        "id_skip_dirs": {"logs"},
    },
}

PLATFORMS["generic"] = {
    "write_tools": PLATFORMS["antigravity"]["write_tools"] | PLATFORMS["claude"]["write_tools"],
    "target_file_keys": list(set(PLATFORMS["antigravity"]["target_file_keys"] + PLATFORMS["claude"]["target_file_keys"])),
    "args_keys": list(set(PLATFORMS["antigravity"]["args_keys"] + PLATFORMS["claude"]["args_keys"])),
    "id_skip_dirs": PLATFORMS["antigravity"]["id_skip_dirs"] | PLATFORMS["claude"]["id_skip_dirs"],
}

DEFAULT_PLATFORM = "antigravity"


def _get_platform_config(platform: Optional[str] = None) -> dict:
    name = platform or DEFAULT_PLATFORM
    if name not in PLATFORMS:
        print(f"Warning: unknown platform '{name}', using generic config", file=sys.stderr)
        return PLATFORMS["generic"]
    return PLATFORMS[name]


def detect_platform(transcript_path: Path | str) -> str:
    transcript_path = Path(transcript_path)
    if not transcript_path.exists():
        return DEFAULT_PLATFORM

    tool_to_platform = {}
    for name, config in PLATFORMS.items():
        if name == "generic":
            continue
        for tool in config["write_tools"]:
            if tool not in tool_to_platform:
                tool_to_platform[tool] = name

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    step = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                for tc in step.get("tool_calls", []):
                    tool_name = tc.get("name", "")
                    if tool_name in tool_to_platform:
                        return tool_to_platform[tool_name]
    except Exception:
        pass

    return DEFAULT_PLATFORM


def resolve_transcript_id(transcript_path: Path | str, platform: Optional[str] = None) -> str:
    config = _get_platform_config(platform)
    candidate = Path(transcript_path).resolve().parent
    while candidate.name in config["id_skip_dirs"]:
        candidate = candidate.parent
    return candidate.name


def extract_modified_files(transcript_path: Path | str, platform: Optional[str] = None) -> set[str]:
    transcript_path = Path(transcript_path)
    if not transcript_path.exists():
        return set()

    config = _get_platform_config(platform)
    write_tools = config["write_tools"]
    args_keys = config["args_keys"]
    target_file_keys = config["target_file_keys"]

    modified = set()
    try:
        text = transcript_path.read_text(encoding="utf-8")
    except Exception:
        return set()

    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            step = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        for tc in step.get("tool_calls", []):
            tool_name = tc.get("name", "")
            if tool_name not in write_tools:
                continue
            args = {}
            for key in args_keys:
                args = tc.get(key) or args
                if args:
                    break
            if not isinstance(args, dict):
                continue
            for tf_key in target_file_keys:
                target = args.get(tf_key, "")
                if isinstance(target, str):
                    target = target.strip('"').strip("'")
                if target:
                    modified.add(target)

    return modified


def match_cells(modified_files: set[str], cells_dir: Path | str, repo_root: str = "") -> list[dict]:
    cells_path = Path(cells_dir)
    matches = find_matching_cells(cells_path, modified_files, repo_root=repo_root, allow_basename_match=False)
    results = []
    for m in matches:
        try:
            rel_cell = str(Path(m.cell_path).relative_to(cells_path.resolve())).replace("\\", "/")
        except ValueError:
            rel_cell = Path(m.cell_path).name
        results.append({
            "cell_id": m.cell_id,
            "cell_path": rel_cell,
            "matched_files": sorted(list(m.matched_files)),
        })
    return results


def update_fitness(triggered_cells: list[dict], transcript_id: str, evidence_dir: Path | str) -> list[dict]:
    """Atomically record every cell triggered by one transcript."""
    if not triggered_cells:
        return []

    from aegis_core.telemetry import append_signals, read_generation

    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    workspace = str(evidence_dir.parent.parent)

    generation = read_generation(workspace)
    events = [
        {
            "cell_name": cell["cell_id"],
            "signal_type": "trigger",
            "source": "session",
            "metadata": {
                "transcript_id": transcript_id,
                "matched_files": cell.get("matched_files", []),
            },
            "principal": "fitness_updater",
            "idempotency_scope": "transcript",
            "idempotency_key": f"{transcript_id}:{cell['cell_id']}",
        }
        for cell in triggered_cells
    ]
    return append_signals(workspace, events, expected_generation=generation)
