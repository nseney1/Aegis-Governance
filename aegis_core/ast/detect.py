"""Language detection and zero-touch AST driver provisioning for polyglot codebases."""
from __future__ import annotations

import importlib.resources
import os
from pathlib import Path
import shutil
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from aegis_core.errors import PathTraversalError
from aegis_core.yaml import AegisYAML, dump_frontmatter

__all__ = [
    "detect_project_languages",
    "resolve_recommended_drivers",
    "provision_ast_driver_slots",
    "packaged_driver_for_extension",
    "names_packaged_driver",
    "LANGUAGE_DEFINITIONS",
]

_SKIP_DIRS = {
    "__pycache__", ".git", "node_modules", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "target", "dist", "build",
    ".aegis", ".soma", ".tox", ".venv", "venv",
}

LANGUAGE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "rust": {
        "manifests": ["Cargo.toml", "Cargo.lock"],
        "extensions": [".rs"],
        "toolchains": ["cargo", "rustc"],
        "driver_slot": "ast_driver_rs",
        "default_command": "{python} .aegis/drivers/rust_ast.py",
        "driver_filename": "rust_ast.py",
    },
    "typescript": {
        "manifests": ["tsconfig.json"],
        "extensions": [".ts", ".tsx"],
        "toolchains": ["node"],
        "driver_slot": "ast_driver_ts",
        "default_command": "node .aegis/drivers/ts_ast.js",
        "driver_filename": "ts_ast.js",
    },
    "javascript": {
        "manifests": ["package.json"],
        "extensions": [".js", ".jsx", ".mjs", ".cjs"],
        "toolchains": ["node"],
        "driver_slot": "ast_driver_js",
        "default_command": "node .aegis/drivers/ts_ast.js",
        "driver_filename": "ts_ast.js",
    },
    "go": {
        "manifests": ["go.mod", "go.sum"],
        "extensions": [".go"],
        "toolchains": ["go"],
        "driver_slot": "ast_driver_go",
        "default_command": "go run .aegis/drivers/go_ast.go",
        "driver_filename": "go_ast.go",
    },
    "python": {
        "manifests": ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile", "poetry.lock"],
        "extensions": [".py"],
        "toolchains": ["python3", "python"],
        "driver_slot": None,  # Handled in-process
        "default_command": None,
        "driver_filename": None,
    },
}


def packaged_driver_for_extension(extension: str) -> Optional[Dict[str, Any]]:
    """Return the language definition whose packaged AST driver handles ``extension``, or None.

    Its ``default_command`` is the repo slot value that opts in to that driver; the
    command itself is never executed (see ``aegis_core.ast.runner``).
    """
    ext = "." + extension.strip().lower().lstrip(".")
    for config in LANGUAGE_DEFINITIONS.values():
        if ext in config["extensions"] and config.get("driver_filename") and config.get("default_command"):
            return config
    return None


def names_packaged_driver(value: str, config: Mapping[str, Any]) -> bool:
    """True for a selector `aegis init` provisioned, including legacy forms like 'python3 .soma/drivers/rust_ast.py'."""
    parts = value.split()
    canonical = str(config["default_command"]).split()
    if len(parts) != len(canonical):
        return False
    if parts[-1] not in (f".aegis/drivers/{config['driver_filename']}", f".soma/drivers/{config['driver_filename']}"):
        return False
    if canonical[0] == "{python}" and parts[0] in ("python3", "python"):
        return True
    return parts[:-1] == canonical[:-1]


def _refuse_symlinks(root: Path, targets: Iterable[Path]) -> None:
    """Raise if any path component between ``root`` and a target is a symlink.

    The repo is untrusted: a committed .aegis/slots.yaml -> ~/.aegis/slots.yaml would let
    provisioning plant a trusted user-scope driver, and a driver copy linked to ~/.zshrc
    would be overwritten.
    """
    for target in targets:
        current = root
        for part in target.relative_to(root).parts:
            current = current / part
            if current.is_symlink():
                raise PathTraversalError(
                    f"Refusing to provision AST drivers: {current} is a symlink; "
                    "aegis writes .aegis/ only as regular files inside the workspace"
                )


def _write_no_follow(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path``, failing instead of following a symlink planted after the check."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o644)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def _find_driver_template(filename: str) -> Optional[Path]:
    """Locate a driver recipe shipped in the aegis_core.ast.drivers.templates package.

    Only packaged templates are used: a recipe never comes from the repository
    being governed (H5).
    """
    try:
        path = Path(str(importlib.resources.files("aegis_core.ast.drivers.templates") / filename))
    except (ModuleNotFoundError, TypeError):
        return None
    return path if path.is_file() else None


def detect_project_languages(project_root: Path | str) -> Dict[str, Dict[str, Any]]:
    """Detect all active programming languages in a project using manifests and source scan."""
    root = Path(project_root).resolve()
    detected: Dict[str, Dict[str, Any]] = {}

    # Quick manifest check
    manifest_found: Set[str] = set()
    for lang, config in LANGUAGE_DEFINITIONS.items():
        found_manifests = [m for m in config["manifests"] if (root / m).is_file()]
        if found_manifests:
            detected[lang] = {
                "manifests": found_manifests,
                "extensions": set(),
                "file_count": 0,
                "toolchains": [t for t in config["toolchains"] if shutil.which(t)],
            }
            manifest_found.add(lang)

    # Scan extensions under root (skipping build/vendor dirs)
    ext_to_lang: Dict[str, str] = {}
    for lang, config in LANGUAGE_DEFINITIONS.items():
        for ext in config["extensions"]:
            ext_to_lang[ext] = lang

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            ext = Path(fn).suffix.lower()
            if ext in ext_to_lang:
                lang = ext_to_lang[ext]
                if lang not in detected:
                    detected[lang] = {
                        "manifests": [],
                        "extensions": set(),
                        "file_count": 0,
                        "toolchains": [t for t in LANGUAGE_DEFINITIONS[lang]["toolchains"] if shutil.which(t)],
                    }
                detected[lang]["extensions"].add(ext)
                detected[lang]["file_count"] += 1

    # Normalize sets to sorted lists for JSON serialization
    for lang_data in detected.values():
        lang_data["extensions"] = sorted(lang_data["extensions"])

    return detected


def resolve_recommended_drivers(languages: Dict[str, Any]) -> Dict[str, str]:
    """Map detected languages to recommended slot bindings for .aegis/slots.yaml."""
    recommended: Dict[str, str] = {}
    for lang, data in languages.items():
        config = LANGUAGE_DEFINITIONS.get(lang)
        if not config or not config.get("driver_slot") or not config.get("default_command"):
            continue
        slot_key = config["driver_slot"]
        recommended[slot_key] = config["default_command"]

    return recommended


def provision_ast_driver_slots(
    workspace_root: Path | str,
    languages: Optional[Dict[str, Any]] = None,
    copy_drivers: bool = True,
    dry_run: bool = False,
) -> Tuple[Dict[str, str], List[str]]:
    """Automatically scaffold .aegis/slots.yaml and stage required driver recipes.

    The ``ast_driver_<ext>`` values written here only opt the repo in to the packaged
    driver for that extension; the staged copies under .aegis/drivers/ are never run.

    Raises:
        PathTraversalError: .aegis, .aegis/drivers, a driver copy or slots.yaml is a
            symlink. Nothing is written in that case.

    Returns:
        (slots_dict, list_of_created_files)
    """
    root = Path(workspace_root).resolve()
    gov_dir = root / ".aegis"
    drivers_dir = gov_dir / "drivers"
    slots_path = gov_dir / "slots.yaml"

    if languages is None:
        languages = detect_project_languages(root)

    recommended_slots = resolve_recommended_drivers(languages)
    created_files: List[str] = []

    driver_files: List[str] = []
    if copy_drivers and recommended_slots:
        for config in LANGUAGE_DEFINITIONS.values():
            filename = config.get("driver_filename")
            if config.get("driver_slot") in recommended_slots and filename and filename not in driver_files:
                driver_files.append(filename)
    _refuse_symlinks(root, [slots_path, *(drivers_dir / f for f in driver_files)])

    # 1. Copy required driver scripts if requested (reference copies: nothing executes them)
    for filename in driver_files:
        src_path = _find_driver_template(filename)
        target_path = drivers_dir / filename
        if not dry_run:
            drivers_dir.mkdir(parents=True, exist_ok=True)
            if src_path and src_path.is_file():
                _write_no_follow(target_path, src_path.read_bytes())
        created_files.append(str(target_path))

    # 2. Read or create slots.yaml
    current_slots: Dict[str, str] = {}
    if slots_path.is_file():
        try:
            doc = AegisYAML.parse_text(slots_path.read_text(encoding="utf-8"))
        except Exception:
            # Never replace a file we cannot read back: that would drop the user's slots.
            return dict(recommended_slots), created_files
        raw = doc.get("slots") if isinstance(doc, Mapping) else None
        if isinstance(raw, Mapping):
            current_slots = {str(k): str(v) for k, v in raw.items() if v is not None}

    # Merge newly recommended slots without overwriting custom user overrides
    merged_slots = dict(current_slots)
    for k, v in recommended_slots.items():
        if k not in merged_slots:
            merged_slots[k] = v

    # Write back slots.yaml
    if not dry_run and (merged_slots != current_slots or not slots_path.is_file()):
        gov_dir.mkdir(parents=True, exist_ok=True)
        header = (
            "# .aegis/slots.yaml — Repository skill & driver slot bindings\n"
            "# Auto-generated by Aegis Init\n\n"
        )
        body = dump_frontmatter({"slots": dict(sorted(merged_slots.items()))})
        _write_no_follow(slots_path, (header + body).encode("utf-8"))
        created_files.append(str(slots_path))

    return merged_slots, created_files
