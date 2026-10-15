---
id: trap-optional-import-guard
domain: correctness
type: trap
enforcement: advisory
hypothesis: "An unguarded import of a package that is neither standard library nor a declared dependency crashes every importing module, and the whole test suite, wherever the package is absent"
prediction: "Fires when a change adds a third-party or platform-only import to aegis_cli, aegis_core, aegis_mcp or aegis_sdk without a try/except ImportError guard"
falsification: "0 findings in 15 sessions: prune"
expiry_sessions: 15
expiry_days: 60
created: "2026-10-15T16:18:02Z"
impact_weight: 1.0
tags: ["dogfood", "imports", "portability"]
target_paths: ["aegis_cli/**/*.py", "aegis_core/**/*.py", "aegis_mcp/**/*.py", "aegis_sdk/**/*.py"]
lineage:
  parent_id: null
  created_by: "manual"
  generation: 0
  siblings: []
---
# Optional Import Guard

**Role**: Prevents bare imports of optional packages that crash the module when the dependency isn't installed.

## Rule

Any `import` of a package not in the Python standard library and not listed as a **required** dependency in `pyproject.toml` or `requirements.txt` MUST be wrapped in a `try/except ImportError` guard:

```python
try:
    import toml
except ImportError:
    toml = None
```

## Scope

This applies to ALL files in `aegis_cli/`, `aegis_core/`, `aegis_mcp/` and `aegis_sdk/`.

## Required Dependencies (bare import OK)

*(None — Aegis has zero runtime dependencies. All runtime code uses the Python standard library only.)*

## Known Optional Dependencies

*(None. v4.0 cut the vendor SDK providers and `keyring`: Layer 2 runs any model
through `--llm-cmd` / `AEGIS_LLM_CMD`, so no third-party package is imported.)*

Platform-only standard-library modules follow the same guard: `fcntl` and
`msvcrt` are each imported inside `try/except ImportError` in
`aegis_core/locking.py`, so the module loads on every OS.

## Why This Matters

Unguarded imports of truly optional packages crash the entire test suite when
the dependency isn't installed. The blast radius is recursive: `test_foo.py`
imports `module_a.py` which imports `module_b.py` which has `import optional_lib`
→ ALL tests touching `module_a` fail with `ModuleNotFoundError`.

> **Historical note:** PyYAML was previously a required runtime dependency
> for YAML frontmatter parsing. `aegis_core.yaml` is now a
> pure standard library frontmatter engine, eliminating PyYAML completely from runtime
> dependencies (`dependencies = []`).

## Enforcement

When reviewing or writing code that adds an `import` statement:

1. Check if the package is in the standard library → if yes, bare import is fine
2. Check if it's a required dependency in `pyproject.toml` → if yes, bare import is fine
3. Otherwise → MUST use `try/except ImportError` guard

## Violation Detection

The naive `grep '^import toml$'` misses compound imports (`import os, toml`)
and indented imports inside functions. Use AST-based detection:

```bash
# AST-based scan for unguarded optional imports
# NOTE: Aegis has zero runtime dependencies.
# This script checks for truly optional packages only.
python3 -c "
import ast, glob, os, sys
from aegis_core.verification.import_guard import _get_stdlib_modules
STDLIB = set(_get_stdlib_modules()) | set(sys.builtin_module_names)
INTERNAL = {'aegis_cli', 'aegis_core', 'aegis_mcp', 'aegis_sdk', 'install', 'rules', 'skills'} | {os.path.splitext(os.path.basename(p))[0] for p in glob.glob('aegis_core/*.py')}
for f in glob.glob('aegis_cli/**/*.py', recursive=True) + \
         glob.glob('aegis_core/**/*.py', recursive=True) + \
         glob.glob('aegis_mcp/**/*.py', recursive=True) + \
         glob.glob('aegis_sdk/**/*.py', recursive=True):
    if '__pycache__' in f: continue
    tree = ast.parse(open(f, encoding='utf-8').read())
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules = [a.name.split('.')[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules = [node.module.split('.')[0]]
        for mod in modules:
            if mod in STDLIB or mod in INTERNAL or mod.startswith('aegis_'):
                continue
            in_try = any(
                isinstance(p, ast.Try) and any(any(c is node for c in ast.walk(item)) for item in p.body)
                for p in ast.walk(tree)
            )
            if not in_try:
                print(f'{f}:{node.lineno}: unguarded import {mod}')
"
```

Any match is a violation.
