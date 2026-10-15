# ADR-014: Structured Lexical Command Tokenization Over Regex Builder DSL

## Status
**Accepted** (v0.97.1 — 2026-10-06; updated for Aegis Guardrails v3.2.0)

## Context
In `aegis_cli/hooks/runtime.py` (`aegis_cli/hooks/`), the pre-execution safety gate (`run_safety_gate()`) enforces protection against destructive commands (e.g. `rm -rf`, raw database drops, non-fast-forward git operations, and secret exposures). Historically, this gate relied on monolithic regular expression chains (`_GIT_CMD_PREFIX`, `_GIT_GLOBAL_OPTS`, `_GIT_CMD`, and a 22-entry `DESTRUCTIVE_PATTERNS` table).

As part of codebase de-bloating analysis, a proposal was evaluated:
- **Proposal**: Build a generic internal fluent `RegexBuilder` class to construct composable regex patterns across CLI commands and hooks.

### Adversarial Evaluation of RegexBuilder
An adversarial architectural audit revealed two fatal flaws with the `RegexBuilder` approach:
1. **Maintenance & Cognitive Bloat**: An internal fluent DSL for regular expressions requires ~800 lines of complex metaprogramming, combinatorial state testing, and custom type definitions without reducing the underlying complexity of the compiled regexes.
2. **Grammar Mismatch & Security Vulnerability**: POSIX and Bash shell grammars are non-regular languages context-free or context-sensitive in structure. Regular expressions inherently fail to handle:
   - Nested command substitution: `$(cmd)`, `` `cmd` ``, and arbitrary nesting depths.
   - ANSI-C quoting: `$'foo\x20bar'`.
   - Dynamic wrapper chains: `sudo env nice -n 10 time sh -c "..."`.
   - Variable whitespace, quote interleaving (`r"m" -rf /`), and chained pipeline/subshell delimiters (`;`, `&&`, `||`, `|`).

Relying on regular expressions to inspect shell command safety leads to either catastrophic evasion vectors or severe false positives on benign agent commands.

## Decision
1. **Formal Rejection of `RegexBuilder` DSL**:
   - The proposed `RegexBuilder` class is rejected. No regex DSL will be introduced into the repository.
2. **Adoption of Pure-Stdlib Lexical Tokenizer & Automaton**:
   - Introduce `CommandAnalyzer` in `aegis_core/command_safety.py`.
   - Use standard library `shlex.shlex` in POSIX mode as the core lexical tokenizer, avoiding third-party grammar parsers (`bashlex`, `tree-sitter`) in adherence to Aegis Guardrails' zero-dependency runtime invariant (`dependencies = []`).
   - Implement iterative/bounded recursive unwrapping of shell compound delimiters (`;`, `&&`, `||`, `|`, `&`).
   - Extract and recursively evaluate nested command substitutions (`$(...)` and `` `...` ``) with a hard recursion depth clamp (default depth: 8) to eliminate algorithmic DoS / stack overflow vectors.
   - Implement an unrolling state automaton for transparent command wrappers (`sudo`, `doas`, `env`, `nice`, `nohup`, `time`, `command`, `builtin`, `exec`, `xargs`, and shell executors `sh`, `bash`, `zsh`, `dash`).
3. **Dual-Path Safety Gate Execution**:
   - `aegis_cli/hooks/runtime.py` runs a sub-millisecond fast-path check: simple, safe, non-destructive commands (e.g., standard `git status`, `git diff` without dangerous flags) bypass full analysis.
   - Non-fast-path commands are evaluated via `CommandAnalyzer.evaluate(cmd)`, yielding structured `SafetyEvaluation(allowed, reason, confidence)`.
   - Redundant shell command regex patterns are removed (reducing 123 LOC).
4. **Scope-Constrained `re.VERBOSE` for Unstructured Data**:
   - Regular expressions are strictly reserved for flat pattern matching on unstructured text (such as API keys and credential redaction in `SECRET_REPLACEMENTS` and `aegis_mcp/projection.py`).
   - All remaining regexes use `re.VERBOSE` with inline comments documenting matching groups and token semantics.

## Consequences

### Positive
- **Immunity to Shell Evasion**: Lexical analysis correctly handles arbitrary whitespace, quote stripping, ANSI-C escapes, and wrapped subshells.
- **Sub-Millisecond Performance**: In-process stdlib tokenization executes in under 0.05ms per command evaluation, preserving instantaneous safety gate throughput.
- **Codebase De-bloating**: Net deletion of 123 lines of brittle regular expressions from `aegis_cli/hooks/` with zero introduced external dependencies.
- **Maintainability & Testability**: Canonical unit test suite in `tests/unit/core/test_command_safety.py` provides isolated, deterministic unit tests for malicious evasion patterns.

### Negative / Trade-offs
- **Shell Grammar Limitations**: `CommandAnalyzer` does not implement full Bash AST parsing (by deliberate design to avoid C dependencies). Complex control flow constructs (such as `case`, `while`, or function definitions) default to conservative blocking if ambiguous.

## Verification
- Verified by:
  - `pytest tests/unit/core/test_command_safety.py`
  - `pytest tests/unit/cli/test_hooks_lifecycle.py`
  - `pytest tests/unit/core/test_static_invariants.py`
  - `pytest tests/unit/core/test_documentation_accuracy.py`

