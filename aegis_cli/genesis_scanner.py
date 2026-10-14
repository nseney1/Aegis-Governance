"""Language-agnostic codebase scanner for ``soma genesis``.

Detects architectural patterns (module boundaries, config stores,
shared state, API surfaces, data pipelines, state machines, test gaps)
and maps them to governance organelle candidates.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CellCandidate:
    """A detected governance organelle candidate."""

    name: str                       # e.g. "wall-core-isolation"
    proposed_type: str              # wall, membrane, vacuole, chloroplast, plasmodesmata
    hypothesis: str                 # what this cell guards
    prediction: str                 # observable failure if violated
    falsification: str              # when to prune
    target_paths: list[str]         # file globs
    confidence: float               # 0.0-1.0
    evidence: dict                  # detector-specific proof
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SKIP_DIRS = {
    "__pycache__", ".git", "node_modules", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "target", "dist", "build",
    ".soma", ".tox", ".venv", "venv",
}

# Common ALL_CAPS that are NOT project constants (Python builtins, test noise)
_CAPS_NOISE = {
    "TRUE", "FALSE", "NONE", "AND", "OR", "NOT", "IN", "IS",
    "UTF", "ASCII", "GET", "POST", "PUT", "DELETE", "HEAD", "PATCH",
    "OK", "API", "URL", "URI", "SQL", "HTML", "CSS", "JSON", "XML",
    "README", "TODO", "FIXME", "NOTE", "HACK", "XXX", "BUG",
    "MULTILINE", "IGNORECASE", "DOTALL", "VERBOSE",
    "LOCK_EX", "LOCK_UN", "LOCK_SH",
}

# Stdlib / builtin modules that are NOT shared project state
_STDLIB_MODULES = {
    "os", "sys", "re", "json", "yaml", "time", "datetime", "date",
    "pathlib", "subprocess", "shutil", "tempfile", "hashlib", "math",
    "typing", "collections", "functools", "itertools", "contextlib",
    "argparse", "logging", "unittest", "pytest", "dataclasses",
    "abc", "enum", "io", "copy", "textwrap", "string", "struct",
    "fcntl", "glob", "fnmatch", "socket", "http", "urllib",
    "__future__", "annotations", "from", "import", "this",
    "bar", "foo", "baz", "test", "tests", "tmp_path",
    "script", "user", "bypass", "cell", "classify",
    "multiply", "statements",
}

_SOURCE_EXTS: dict[str, set[str]] = {
    "rust": {".rs"},
    "python": {".py"},
    "javascript": {".js", ".ts", ".jsx", ".tsx"},
    "go": {".go"},
    "unknown": {".py", ".js", ".ts", ".rs", ".go", ".java", ".c", ".cpp"},
}


def _iter_source_files(
    root: Path, project_type: str, *, include_tests: bool = True,
) -> list[Path]:
    """Yield source files under *root*, skipping non-essential dirs."""
    exts = _SOURCE_EXTS.get(project_type, _SOURCE_EXTS["unknown"])
    results: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        dir_name = Path(dirpath).name.lower()
        if not include_tests and dir_name in ("tests", "test", "__tests__", "spec"):
            continue
        for fn in filenames:
            if not include_tests and fn.startswith("test_"):
                continue
            if any(fn.endswith(ext) for ext in exts):
                results.append(Path(dirpath) / fn)
    return results


def _read_text_safe(path: Path, limit: int = 256_000) -> str:
    """Read file text up to *limit* characters, returning '' on errors."""
    try:
        if not path.is_file():
            return ""
        with open(path, mode="r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except (OSError, PermissionError):
        return ""


def _get_source_files_with_content(
    root: Path,
    project_type: str,
    source_cache: list[tuple[Path, str]] | None = None,
) -> list[tuple[Path, str]]:
    """Return source files with their text content, reusing cache if provided."""
    if source_cache is not None:
        return source_cache
    return [
        (src, _read_text_safe(src))
        for src in _iter_source_files(root, project_type, include_tests=False)
    ]


# ---------------------------------------------------------------------------
# Project type detection
# ---------------------------------------------------------------------------

def detect_project_type(root: Path) -> str:
    """Detect the primary language of a project."""
    if (root / "Cargo.toml").exists():
        return "rust"
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        return "python"
    if (root / "package.json").exists():
        return "javascript"
    if (root / "go.mod").exists():
        return "go"
    return "unknown"


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

def detect_module_boundaries(root: Path, project_type: str) -> list[CellCandidate]:
    """Find directories with their own manifest files → wall candidates."""
    manifests = [
        "Cargo.toml", "package.json", "pyproject.toml",
        "go.mod", "pom.xml", "build.gradle",
    ]
    candidates: list[CellCandidate] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        p = Path(dirpath)
        if p == root:
            continue  # skip project root itself
        for mf in manifests:
            if mf in filenames:
                rel = p.relative_to(root)
                mod_name = str(rel).replace(os.sep, "-")
                src_count = sum(
                    1 for _ in _iter_source_files(p, project_type)
                )
                confidence = min(0.9, 0.5 + src_count * 0.05)
                candidates.append(CellCandidate(
                    name=f"wall-{mod_name}-isolation",
                    proposed_type="wall",
                    hypothesis=f"Module '{rel}' must maintain dependency isolation",
                    prediction=f"If '{rel}' imports disallowed deps, coupling increases",
                    falsification="Remove if module is merged or deleted",
                    target_paths=[f"{rel}/**"],
                    confidence=confidence,
                    evidence={"manifest": mf, "source_files": src_count},
                    tags=["boundary", "isolation"],
                ))
                break  # one manifest per directory
    return candidates


def detect_dependency_walls(root: Path, project_type: str) -> list[CellCandidate]:
    """Parse manifest deps to find isolation walls between modules."""
    candidates: list[CellCandidate] = []
    if project_type == "rust" and (root / "Cargo.toml").exists():
        # Look for workspace members with separate Cargo.toml
        for sub in root.iterdir():
            cargo = sub / "Cargo.toml"
            if sub.is_dir() and cargo.exists():
                text = _read_text_safe(cargo)
                dep_names = re.findall(r'^\s*(\w[\w-]*)\s*=', text, re.MULTILINE)
                if dep_names:
                    candidates.append(CellCandidate(
                        name=f"wall-{sub.name}-deps",
                        proposed_type="wall",
                        hypothesis=f"'{sub.name}' dependencies are intentionally constrained",
                        prediction="Adding undeclared deps breaks isolation",
                        falsification="Remove if dependency policy changes",
                        target_paths=[f"{sub.name}/Cargo.toml"],
                        confidence=0.7,
                        evidence={"declared_deps": dep_names[:20]},
                        tags=["dependency", "isolation"],
                    ))
    return candidates


def detect_config_stores(
    root: Path,
    project_type: str,
    source_cache: list[tuple[Path, str]] | None = None,
) -> list[CellCandidate]:
    """Find files with high density of ALL_CAPS identifiers → vacuole candidates."""
    candidates: list[CellCandidate] = []
    config_pattern = re.compile(r"^(config|constants|settings|defaults)", re.IGNORECASE)
    all_caps_pattern = re.compile(r"\b[A-Z][A-Z_]{2,}\b")

    sources = _get_source_files_with_content(root, project_type, source_cache)
    for src, content in sources:
        if not content:
            continue
        stem = src.stem.lower()

        raw_caps = all_caps_pattern.findall(content)
        # Filter noise: stdlib constants, HTTP methods, etc.
        caps = [c for c in raw_caps if c not in _CAPS_NOISE]
        is_config_name = bool(config_pattern.match(stem))

        # 20+ unique constants for any file, or config-named with 5+
        unique_caps = set(caps)
        if len(unique_caps) >= 20 or (is_config_name and len(unique_caps) >= 5):
            rel = src.relative_to(root)
            candidates.append(CellCandidate(
                name=f"vacuole-{src.stem}-config",
                proposed_type="vacuole",
                hypothesis=f"'{rel}' stores critical configuration constants ({len(unique_caps)} unique)",
                prediction="Unreviewed config changes cause runtime failures",
                falsification="Remove if file is deleted or constants are inlined",
                target_paths=[str(rel)],
                confidence=min(0.95, 0.6 + len(unique_caps) * 0.01),
                evidence={"unique_caps_count": len(unique_caps), "config_name": is_config_name},
                tags=["config", "constants"],
            ))
    return candidates


def detect_shared_state(
    root: Path,
    project_type: str,
    source_cache: list[tuple[Path, str]] | None = None,
) -> list[CellCandidate]:
    """Build simple import graph; project modules imported by 4+ others → vacuole candidates."""
    # Match 'from foo.bar import ...' or 'import foo.bar'
    from_pattern = re.compile(r"^\s*from\s+([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)\s+import", re.MULTILINE)
    import_pattern = re.compile(r"^\s*import\s+([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)", re.MULTILINE)
    import_count: dict[str, int] = {}
    sources = _get_source_files_with_content(root, project_type, source_cache)

    for src, content in sources:
        seen_in_file: set[str] = set()
        # 'from src.models import ...' → track 'src.models'
        for match in from_pattern.findall(content):
            mod = match.strip()
            if mod and mod not in seen_in_file:
                seen_in_file.add(mod)
                import_count[mod] = import_count.get(mod, 0) + 1
        # 'import os' → track 'os'
        for match in import_pattern.findall(content):
            mod = match.strip()
            if mod and mod not in seen_in_file:
                seen_in_file.add(mod)
                import_count[mod] = import_count.get(mod, 0) + 1

    candidates: list[CellCandidate] = []
    for mod, count in import_count.items():
        # Skip stdlib, builtins, and short names (likely noise)
        top_level = mod.split(".")[0]
        if mod.startswith(".") or top_level in _STDLIB_MODULES or len(top_level) <= 2:
            continue
        mod_parts = [p for p in mod.split(".") if p]
        mod_path = root.joinpath(*mod_parts)
        mod_file = root.joinpath(*mod_parts[:-1], f"{mod_parts[-1]}.py") if len(mod_parts) > 1 else root / f"{mod_parts[0]}.py"
        try:
            if not mod_path.resolve().is_relative_to(root.resolve()) and not mod_file.resolve().is_relative_to(root.resolve()):
                continue
        except (ValueError, RuntimeError):
            continue
        search_name = mod.split(".")[-1]
        if not mod_path.is_dir() and not mod_file.exists():
            # Search in already-loaded source files instead of expensive rglob
            has_match = any(
                s.name == f"{search_name}.py" or search_name in [p.name for p in s.relative_to(root).parents]
                for s, _ in sources  # sources is now list[tuple[Path, str]]
            )
            if not has_match:
                continue
        # 4+ importers indicates meaningful shared state
        if count >= 4:
            safe_name = mod.replace(".", "-")
            mod_as_path = os.sep.join(mod_parts)
            if mod_path.is_dir():
                target = f"{mod_as_path}/**"
            elif mod_file.exists():
                target = f"{mod_as_path}.py"
            else:
                target = f"**/{search_name}.py"
            candidates.append(CellCandidate(
                name=f"vacuole-{safe_name}-shared",
                proposed_type="vacuole",
                hypothesis=f"Module '{mod}' is shared state imported by {count} production files",
                prediction="Changes to shared module cause cascading failures",
                falsification="Remove if import count drops below 4",
                target_paths=[target],
                confidence=min(0.9, 0.5 + count * 0.04),
                evidence={"import_count": count},
                tags=["shared-state"],
            ))
    return candidates


def detect_api_surfaces(
    root: Path,
    project_type: str,
    source_cache: list[tuple[Path, str]] | None = None,
) -> list[CellCandidate]:
    """Find files with high export density → membrane candidates."""
    export_patterns = [
        re.compile(r"\bpub\s+fn\b"),
        re.compile(r"\bpub\s+struct\b"),
        re.compile(r"\bpub\s+enum\b"),
        re.compile(r"\bexport\s+(default|function|class|const|let)\b"),
        re.compile(r"\bmodule\.exports\b"),
        re.compile(r"^__all__\s*=", re.MULTILINE),
    ]
    candidates: list[CellCandidate] = []

    sources = _get_source_files_with_content(root, project_type, source_cache)
    for src, content in sources:
        if not content:
            continue

        export_count = sum(
            len(pat.findall(content)) for pat in export_patterns
        )
        if export_count >= 3:
            rel = src.relative_to(root)
            candidates.append(CellCandidate(
                name=f"membrane-{src.stem}-api",
                proposed_type="membrane",
                hypothesis=f"'{rel}' is a public API surface with {export_count} exports",
                prediction="Unreviewed API changes break downstream consumers",
                falsification="Remove if file becomes internal-only",
                target_paths=[str(rel)],
                confidence=min(0.9, 0.5 + export_count * 0.05),
                evidence={"export_count": export_count},
                tags=["api", "public-surface"],
            ))
    return candidates


def detect_data_pipelines(
    root: Path,
    project_type: str,
    source_cache: list[tuple[Path, str]] | None = None,
) -> list[CellCandidate]:
    """Find files with many typed functions → chloroplast candidates."""
    transform_patterns = [
        re.compile(r"fn\s+\w+\s*\([^)]*\)\s*->\s*\w+"),     # Rust
        re.compile(r"def\s+\w+\s*\([^)]*\)\s*->\s*\w+"),     # Python
        re.compile(r"func\s+\w+\s*\([^)]*\)\s+\w+"),         # Go
    ]
    candidates: list[CellCandidate] = []

    sources = _get_source_files_with_content(root, project_type, source_cache)
    for src, content in sources:
        if not content:
            continue

        transform_count = sum(
            len(pat.findall(content)) for pat in transform_patterns
        )
        # Higher threshold: 8+ typed functions indicates a real pipeline
        if transform_count >= 8:
            rel = src.relative_to(root)
            candidates.append(CellCandidate(
                name=f"chloroplast-{src.stem}-pipeline",
                proposed_type="chloroplast",
                hypothesis=f"'{rel}' contains {transform_count} data transformation functions",
                prediction="Pipeline changes without validation corrupt downstream data",
                falsification="Remove if transformations are refactored out",
                target_paths=[str(rel)],
                confidence=min(0.7, 0.5 + transform_count * 0.02),
                evidence={"transform_count": transform_count},
                tags=["pipeline", "transformation"],
            ))
    return candidates


def detect_state_machines(
    root: Path,
    project_type: str,
    source_cache: list[tuple[Path, str]] | None = None,
) -> list[CellCandidate]:
    """Find state machine patterns → plasmodesmata candidates."""
    state_type_pattern = re.compile(
        r"\b(?:enum|class|type)\s+(\w*(?:State|Status|Phase|Mode)\w*)",
    )
    candidates: list[CellCandidate] = []

    sources = _get_source_files_with_content(root, project_type, source_cache)
    for src, content in sources:
        if not content:
            continue

        matches = state_type_pattern.findall(content)
        if matches:
            rel = src.relative_to(root)
            candidates.append(CellCandidate(
                name=f"plasmodesmata-{src.stem}-state",
                proposed_type="plasmodesmata",
                hypothesis=f"'{rel}' defines state machine type(s): {', '.join(matches)}",
                prediction="Invalid state transitions cause undefined behaviour",
                falsification="Remove if state machine is deleted",
                target_paths=[str(rel)],
                confidence=min(0.8, 0.5 + len(matches) * 0.1),
                evidence={"state_types": matches},
                tags=["state-machine"],
            ))
    return candidates


def detect_test_boundaries(root: Path, project_type: str) -> list[CellCandidate]:
    """Find test directories; modules without tests get coverage-gap walls."""
    test_dirs = set()
    module_dirs = set()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        p = Path(dirpath)
        rel = p.relative_to(root)
        name = p.name.lower()

        if name in ("tests", "test", "__tests__", "spec"):
            test_dirs.add(str(rel))
        elif any(fn.endswith(ext) for fn in filenames
                 for ext in _SOURCE_EXTS.get(project_type, _SOURCE_EXTS["unknown"])):
            if str(rel) != ".":
                module_dirs.add(str(rel))

    candidates: list[CellCandidate] = []
    for mod in sorted(module_dirs):
        has_test = any(
            td.startswith(mod) or mod.split(os.sep)[0] in td
            for td in test_dirs
        )
        if not has_test and test_dirs:
            candidates.append(CellCandidate(
                name=f"wall-{mod.replace(os.sep, '-')}-test-coverage",
                proposed_type="wall",
                hypothesis=f"Module '{mod}' lacks dedicated test coverage",
                prediction="Untested code ships regressions undetected",
                falsification="Remove once test coverage is added",
                target_paths=[f"{mod}/**"],
                confidence=0.6,
                evidence={"module": mod, "test_dirs": sorted(test_dirs)},
                tags=["test-coverage", "gap"],
            ))
    return candidates


# ---------------------------------------------------------------------------
# Registry & main entry point
# ---------------------------------------------------------------------------

ALL_DETECTORS = [
    detect_module_boundaries,
    detect_dependency_walls,
    detect_config_stores,
    detect_shared_state,
    detect_api_surfaces,
    detect_data_pipelines,
    detect_state_machines,
    detect_test_boundaries,
]


def scan(root: Path, min_confidence: float = 0.5) -> list[CellCandidate]:
    """Run all detectors against the repository."""
    project_type = detect_project_type(root)
    source_cache = _get_source_files_with_content(root, project_type)
    candidates: list[CellCandidate] = []
    for detector in ALL_DETECTORS:
        try:
            candidates.extend(detector(root, project_type, source_cache=source_cache))
        except TypeError:
            # Detectors that don't accept source_cache (module_boundaries, dependency_walls, test_boundaries)
            candidates.extend(detector(root, project_type))
    # Deduplicate by name
    seen: set[str] = set()
    unique: list[CellCandidate] = []
    for c in candidates:
        if c.name not in seen and c.confidence >= min_confidence:
            seen.add(c.name)
            unique.append(c)
    return sorted(unique, key=lambda c: (-c.confidence, c.name))
