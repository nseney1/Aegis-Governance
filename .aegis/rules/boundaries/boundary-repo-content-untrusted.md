---
id: boundary-repo-content-untrusted
domain: security
type: boundary
enforcement: advisory
hypothesis: "When repository files choose what the verifier executes or interpolates (commands, slots, scripts, interpreters, test files), a hostile clone runs its own code with the governance tool's trust"
prediction: "Each subprocess sink takes its executable from packaged templates or user-scope config only, and ships with a hostile-clone marker-file test"
falsification: "0 findings in 15 sessions: prune"
expiry_sessions: 15
expiry_days: 60
created: "2026-10-15T16:11:59Z"
impact_weight: 1.0
tags: ["debrief", "citadel", "subprocess", "trust"]
target_paths: ["aegis_core/ast/runner.py", "aegis_core/skills/slots.py", "aegis_core/outcomes/engine.py", "aegis_core/outcomes/telemetry.py", "aegis_core/verification/test_runner.py", "aegis_core/verification/mutation_tester.py", "aegis_mcp/server.py", "aegis_cli/hooks/management.py", "aegis_cli/hooks/runtime.py"]
lineage:
  parent_id: null
  created_by: "manual"
  generation: 0
  siblings: []
---
# Boundary: the governed repository is untrusted input

**Rule**: Treat the repository under governance as untrusted input. Never
subprocess a command, interpreter, script or test file whose selection comes
from repository files; resolve executables only from packaged templates or
user-scope config (D10). Never put the cwd on `sys.path` for hooks. Run every
child with a scrubbed environment and a process-group kill. Every new
subprocess sink needs a hostile-clone marker-file test.

## Incident (v4 Citadel review)

- `.aegis/slots.yaml` `ast_driver` commands were run by `aegis check`, the
  pre-commit hook and MCP verify. Session close ran the repository's own test
  and build commands, and Layer 1 mutation and coverage ran pytest from it.
- The pre-commit hook exec'd `$PWD/.venv/bin/python`, imported `aegis_cli` from
  the cwd and failed open. The enforcement generator interpolated rule `type`
  unescaped, and pre-commit ran `check-*` scripts from the repository.
- Scan-time slot interpolation injected unsigned `slots.yaml` values into
  HMAC-signed rule text, and tier promotion trusted repo-set fitness frontmatter.
- It was missed because the BUG-073 guard covered only API keys and URLs, so
  nobody inventoried the subprocess sinks; existing tests pinned the unsafe
  behavior, and no test ran a marker-file probe from a hostile clone.

## Check

1. List every `subprocess`, `os.exec*` and `os.system` call in `aegis_*` with the
   source of its argv. Any argv element read from a repository file fails.
2. Hook runners never insert the cwd or a repository path on `sys.path`, and
   fail closed when the installed aegis is missing.
3. Hostile-clone test: a temp repository whose config, slots, scripts and test
   files would create a marker file if executed; run the command and assert the
   marker does not exist.
