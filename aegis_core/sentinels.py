"""aegis_core.sentinels — Subagent liveness, deadlock detection, protocol escalation, and last-gasp sentinels.

Consolidates:
- Subagent liveness & deadlock sentinel (formerly enzymes/liveness_sentinel.py)
- Protocol escalation recommender & last-gasp sentinel (formerly enzymes/escalation_sentinel.py)
"""
from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import glob
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from aegis_core.somayaml import parse_frontmatter, _get_body, dump_frontmatter


# ── Liveness Sentinel ──────────────────────────────────────────────────────

def check_liveness(payload_str: str) -> int:
    """Detect stalled or deadlocked subagents that fail to report back."""
    try:
        data = json.loads(payload_str)
        now = datetime.now(timezone.utc)
        for agent in data.get("agents", []):
            name = agent.get("name", "Unknown")
            dispatch_str = agent.get("dispatched", "")
            timeout = agent.get("timeout_seconds", 0)

            try:
                if dispatch_str.endswith("Z"):
                    dispatch_str = dispatch_str[:-1] + "+00:00"
                dispatch_time = datetime.fromisoformat(dispatch_str)
                if dispatch_time.tzinfo is None:
                    dispatch_time = dispatch_time.replace(tzinfo=timezone.utc)
            except ValueError:
                print(f"[{name}] INVALID_DATE: {dispatch_str}")
                continue

            elapsed = (now - dispatch_time).total_seconds()

            if elapsed > timeout:
                print(
                    f"[{name}] STALLED (Elapsed: {elapsed:.1f}s, Timeout: {timeout}s) - Action suggested: kill or escalate"
                )
            elif elapsed > timeout * 0.8:
                print(
                    f"[{name}] WARNING (Elapsed: {elapsed:.1f}s, Timeout: {timeout}s) - Action suggested: nudge"
                )
            else:
                print(f"[{name}] HEALTHY (Elapsed: {elapsed:.1f}s, Timeout: {timeout}s)")
        return 0
    except json.JSONDecodeError:
        print("Error: Invalid JSON provided.", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


# ── Escalation Sentinel ────────────────────────────────────────────────────

HIGH_PATTERNS = [
    r"enzymes/.*\.sh$",
    r"install\.sh$",
    r"install\.ps1$",
    r"Makefile$",
    r"hooks\.json",
    r"\.github/workflows/",
    r"auth|credential|secret|token|password",
    r"docker|Dockerfile",
    r"requirements\.txt$|package\.json$|go\.mod$",
]

MEDIUM_PATTERNS = [
    r"genome/.*\.md$",
    r"rules/.*\.md$",
    r"organs/.*/SKILL\.md$",
    r"skills/.*/SKILL\.md$",
    r"steering\.conf",
    r"\.py$|\.js$|\.ts$|\.go$",
]

LOW_PATTERNS = [
    r"(?:^|/)docs/",
    r"README\.md$",
    r"LICENSE$",
    r"CHANGELOG|EVOLUTION|METRICS|EXPERIMENTS",
    r"\.txt$|\.csv$|\.json$",
]

TEST_PATTERNS = [
    r"\.test\.",
    r"_test\.",
    r"^tests/",
]

PROTOCOL_RANKS = {
    "breeze": 1,
    "gale": 2,
    "trident": 3,
    "maelstrom": 4,
    "tempest": 5,
}


def classify_file(filepath: str) -> str:
    norm = filepath.replace("\\", "/")
    if norm.startswith("./"):
        norm = norm[2:]
    for pat in HIGH_PATTERNS:
        if re.search(pat, norm, re.IGNORECASE):
            return "HIGH"
    for pat in MEDIUM_PATTERNS:
        if re.search(pat, norm, re.IGNORECASE):
            return "MEDIUM"
    for pat in LOW_PATTERNS:
        if re.search(pat, norm, re.IGNORECASE):
            return "LOW"
    return "MEDIUM"


def is_test_file(filepath: str) -> bool:
    norm = filepath.replace("\\", "/")
    if norm.startswith("./"):
        norm = norm[2:]
    for pat in TEST_PATTERNS:
        if re.search(pat, norm, re.IGNORECASE):
            return True
    return False


def gather_files(mode: str, file_args: list[str], workspace: Path) -> list[str]:
    if file_args:
        return [f.strip() for f in file_args if f.strip()]

    files: set[str] = set()
    try:
        if mode == "--staged":
            out = subprocess.check_output(
                ["git", "diff", "--cached", "--name-only"],
                cwd=workspace,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            files.update(line.strip() for line in out.splitlines() if line.strip())
        else:
            out1 = subprocess.check_output(
                ["git", "diff", "--name-only"],
                cwd=workspace,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            out2 = subprocess.check_output(
                ["git", "diff", "--cached", "--name-only"],
                cwd=workspace,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            files.update(line.strip() for line in out1.splitlines() if line.strip())
            files.update(line.strip() for line in out2.splitlines() if line.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pass

    return sorted(files)


def get_diff_size(mode: str, file_args: list[str], workspace: Path) -> int:
    total_lines = 0
    try:
        commands: list[list[str]] = []
        if file_args:
            commands.append(["git", "diff", "--numstat", "--"] + file_args)
            commands.append(["git", "diff", "--cached", "--numstat", "--"] + file_args)
        elif mode == "--staged":
            commands.append(["git", "diff", "--cached", "--numstat"])
        else:
            commands.append(["git", "diff", "--numstat"])
            commands.append(["git", "diff", "--cached", "--numstat"])

        for cmd in commands:
            out = subprocess.check_output(
                cmd,
                cwd=workspace,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        ins = int(parts[0]) if parts[0] != "-" else 0
                        dele = int(parts[1]) if parts[1] != "-" else 0
                        total_lines += ins + dele
                    except ValueError:
                        pass
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pass

    return total_lines


def detect_branch_ops(workspace: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "reflog", "--format=%gs", "-5"],
            cwd=workspace,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        if re.search(r"branch -[mMdD]|push.*force|rebase|reset.*hard", out, re.IGNORECASE):
            return "CRITICAL"
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pass
    return "NONE"


def check_membrane_overrides(workspace: Path, files: list[str], current_protocol: str) -> tuple[str, str]:
    best_protocol = current_protocol
    best_rank = PROTOCOL_RANKS.get(current_protocol, 1)
    override_reason = ""

    cells_dir = workspace / ".soma" / "cells"
    for cell_subdir in ["membranes", "walls"]:
        target_dir = cells_dir / cell_subdir
        if not target_dir.is_dir():
            continue
        for cell_path in target_dir.glob("*.md"):
            if not cell_path.is_file():
                continue
            try:
                with open(cell_path, "r", encoding="utf-8-sig") as cf:
                    metadata = parse_frontmatter(cf.read())
                if not metadata:
                    continue
                min_mode = str(metadata.get("minimum_mode", "")).strip().lower()
                target_paths = metadata.get("target_paths", [])
                if isinstance(target_paths, str):
                    target_paths = [target_paths]

                if min_mode in PROTOCOL_RANKS and target_paths:
                    mem_rank = PROTOCOL_RANKS[min_mode]
                    path_matched = False
                    matched_target = ""
                    for tp in target_paths:
                        for f in files:
                            if f == tp or fnmatch.fnmatch(f, tp) or fnmatch.fnmatch(f, f"*{tp}*"):
                                path_matched = True
                                matched_target = tp
                                break
                        if path_matched:
                            break

                    if path_matched and mem_rank > best_rank:
                        best_rank = mem_rank
                        best_protocol = min_mode
                        override_reason = f"Membrane escalation for {matched_target} ({min_mode})"
            except Exception:
                continue

    return best_protocol, override_reason


def recommend_protocol(mode: str, file_args: list[str], workspace: Path | None = None) -> int:
    root = workspace or Path.cwd()
    files = gather_files(mode, file_args, root)

    if not files:
        print("PROTOCOL=none")
        print("REASON=No changes detected")
        return 1

    total_files = len(files)
    high_count = 0
    medium_count = 0
    low_count = 0
    test_count = 0
    high_files_list: list[str] = []

    for f in files:
        level = classify_file(f)
        if level == "HIGH":
            high_count += 1
            high_files_list.append(f)
        elif level == "MEDIUM":
            medium_count += 1
        elif level == "LOW":
            low_count += 1

        if is_test_file(f):
            test_count += 1

    high_files = ", ".join(high_files_list)
    branch_ops = detect_branch_ops(root)
    diff_lines = get_diff_size(mode, file_args, root)

    protocol = "breeze"
    reasons_list: list[str] = []

    if branch_ops == "CRITICAL":
        protocol = "maelstrom"
        reasons_list.append("Branch operation detected (rename/force-push/rebase)")

    if high_count >= 3:
        protocol = "maelstrom"
        reasons_list.append(f"{high_count} high-sensitivity files: {high_files}")
    elif high_count >= 1:
        if protocol not in ("maelstrom", "tempest"):
            protocol = "trident"
            reasons_list.append(f"High-sensitivity file(s): {high_files}")

    if re.search(r"auth|credential|secret|token|password", high_files, re.IGNORECASE):
        protocol = "maelstrom"
        reasons_list.append("Security-sensitive path detected")

    if diff_lines > 200:
        if protocol == "breeze":
            protocol = "gale"
            reasons_list.append(f"Large diff ({diff_lines} lines)")
        elif protocol == "gale":
            protocol = "trident"
            reasons_list.append(f"Large diff ({diff_lines} lines)")
        elif protocol == "trident":
            protocol = "maelstrom"
            reasons_list.append(f"Large diff ({diff_lines} lines)")

    if high_count == 0 and medium_count == 0 and low_count > 0:
        protocol = "breeze"
        reasons_list = ["All changes are low-sensitivity (docs/README)"]

    if high_count == 0 and test_count > 0 and (test_count + low_count) == total_files:
        protocol = "gale"
        reasons_list = [f"Test-only changes ({test_count} test file(s); test changes do not need Trident)"]

    if protocol == "breeze" and total_files == 1 and high_count == 0 and test_count == 0:
        reasons_list = ["Single file, non-infrastructure change"]

    protocol, mem_override = check_membrane_overrides(root, files, protocol)
    if mem_override:
        reasons_list.append(mem_override)

    reasons = "; ".join(reasons_list) if reasons_list else "Default classification"

    print(f"PROTOCOL={protocol}")
    print(f"REASON={reasons}")
    print(f"FILES_TOTAL={total_files}")
    print(f"FILES_HIGH={high_count}")
    print(f"FILES_MEDIUM={medium_count}")
    print(f"FILES_LOW={low_count}")
    print(f"FILES_TEST={test_count}")
    print(f"DIFF_LINES={diff_lines}")
    print(f"BRANCH_OPS={branch_ops}")

    print(f"⚡ Escalation Sentinel: {protocol.upper()} recommended", file=sys.stderr)
    print(f"   {reasons}", file=sys.stderr)
    print(
        f"   Files: {total_files} ({high_count} high, {medium_count} medium, {low_count} low, {test_count} test)",
        file=sys.stderr,
    )
    return 0


def set_review_mode(workspace: str, mode: str) -> None:
    conf_path = os.path.join(workspace, "steering.conf")
    if not os.path.exists(conf_path):
        return

    with open(conf_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    with open(conf_path, "w", encoding="utf-8") as f:
        for line in lines:
            if line.startswith("REVIEW_MODE="):
                f.write(f"REVIEW_MODE={mode}\n")
            else:
                f.write(line)
    print(f"[Sentinel] Escalated REVIEW_MODE to {mode}")


def write_frontmatter(filepath: str, metadata: dict[str, Any], body: str) -> None:
    dumped = dump_frontmatter(metadata)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"---\n{dumped}---\n")
        if body.startswith("\n"):
            f.write(body[1:])
        else:
            f.write(body)


def run_last_gasp(workspace: Path | None = None) -> int:
    ws = str(workspace or Path.cwd())
    cells_dir = os.path.join(ws, ".soma", "cells")
    if not os.path.exists(cells_dir):
        return 0

    last_gasp_dir = os.path.join(cells_dir, ".last_gasp_queue")
    archive_dir = os.path.join(cells_dir, ".archive")

    if not os.path.exists(last_gasp_dir):
        return 0

    queued_files = glob.glob(os.path.join(last_gasp_dir, "*.md"))
    if not queued_files:
        return 0

    for fpath in queued_files:
        filename = os.path.basename(fpath)
        try:
            with open(fpath, "r", encoding="utf-8-sig") as cf:
                content = cf.read()
            metadata = parse_frontmatter(content)
            body = _get_body(content)
        except Exception:
            continue
        if not metadata:
            continue

        organ = metadata.get("organ", "governance-auditor")
        print(f"[Sentinel] Cell {filename} faces APOPTOSIS. Invoking Last Gasp Organ: {organ}...")

        result_file = os.path.join(last_gasp_dir, filename.replace(".md", ".result"))
        organ_validates_cell = os.path.exists(result_file)

        if organ_validates_cell:
            print(f"[Sentinel] Organ '{organ}' VALIDATED the cell! Saving from Apoptosis.")
            conf_path = os.path.join(ws, "steering.conf")
            if os.path.exists(conf_path):
                with open(conf_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                with open(conf_path, "w", encoding="utf-8") as f:
                    for line in lines:
                        if line.startswith("REVIEW_MODE="):
                            f.write("REVIEW_MODE=TEMPEST\n")
                        else:
                            f.write(line)

            if "fitness" not in metadata:
                metadata["fitness"] = {}
            metadata["fitness"]["score"] = 0.75
            metadata["fitness"]["stress_survived"] = metadata["fitness"].get("stress_survived", 0) + 1

            raw_type = str(metadata.get("type", "wall")).rstrip("s")
            allowed_types = {"wall", "membrane", "vacuole", "chloroplast", "ribosome", "nucleus"}
            cell_type = raw_type if raw_type in allowed_types else "wall"
            parent_type = cell_type + "s"
            target_dir = os.path.abspath(os.path.join(cells_dir, parent_type))
            abs_cells_dir = os.path.abspath(cells_dir)
            if not target_dir.startswith(abs_cells_dir) or os.path.commonpath([abs_cells_dir, target_dir]) != abs_cells_dir:
                target_dir = os.path.join(abs_cells_dir, "walls")
            os.makedirs(target_dir, exist_ok=True)
            new_path = os.path.join(target_dir, filename)

            new_content = "---\n" + dump_frontmatter(metadata) + "---\n" + body
            with open(new_path, "w", encoding="utf-8") as outf:
                outf.write(new_content)
            os.remove(fpath)
        else:
            print(f"[Sentinel] Organ '{organ}' REFUTED the cell! Brutally punishing and archiving.")
            if "fitness" not in metadata:
                metadata["fitness"] = {}
            metadata["fitness"]["score"] = 0.0
            metadata["fitness"]["false_positives"] = metadata["fitness"].get("false_positives", 0) + 10

            os.makedirs(archive_dir, exist_ok=True)
            new_path = os.path.join(archive_dir, filename)

            new_content = "---\n" + dump_frontmatter(metadata) + "---\n" + body
            with open(new_path, "w", encoding="utf-8") as outf:
                outf.write(new_content)
            os.remove(fpath)

    return 0


__all__ = [
    "HIGH_PATTERNS",
    "MEDIUM_PATTERNS",
    "LOW_PATTERNS",
    "TEST_PATTERNS",
    "PROTOCOL_RANKS",
    "check_liveness",
    "classify_file",
    "is_test_file",
    "gather_files",
    "get_diff_size",
    "detect_branch_ops",
    "check_membrane_overrides",
    "recommend_protocol",
    "set_review_mode",
    "write_frontmatter",
    "run_last_gasp",
]
