# Governance Rules

This directory contains Aegis adaptive governance rules. Rules are atomic, modular components that inject specialized constraints, heuristics, or environmental adaptations into the agent's context.

## Rule Types
- **Trap**: Traps and anti-patterns. Prevents the agent from falling into common pitfalls (e.g., using incorrect build tools, deprecated APIs).
- **Persona**: Accelerators and optimizations, usually as repo-specific personas tuned to the domain. Provides fast-paths for common workflows.
- **Invariant**: Boundary conditions and strict invariants. Enforces safety and policy requirements (e.g. things you must never do).
- **Boundary**: Filtering and transformation. Adjusts input/output to conform to expected structures, or defines escalation overrides.
- **Contract**: Cross-repo connections in multi-service architectures. Maps data paths between distinct projects.

## Rule Format Spec
Each rule is a Markdown file starting with YAML frontmatter.
Required fields:
- `type`: trap, persona, invariant, boundary, or contract
- `hypothesis`: What this rule intends to achieve
- `prediction`: Expected measurable outcome
- `falsification`: Conditions under which this rule should be removed
- `expiry_sessions` / `expiry_days`: TTL for the rule
- `fitness`: Tracking block with `triggers`, `true_positives`, `false_positives`

## Fitness Lifecycle & Verification
Rules are actively enforced pre-commit by the **Aegis Verification Pipeline**, which rejects agent proposals that violate them.

Rules undergo evolutionary selection based on their fitness score (Wilson confidence interval):
- **SURVIVE**: High lower bound (Highly effective, kept)
- **ADAPT**: Moderate confidence bound (Needs tuning)
- **EXTINCT**: Low confidence bound (Candidate for pruning during consolidation)
- **DORMANT**: 0 triggers past expiry (Candidate for pruning during consolidation)
- **NEW**: 0 triggers within expiry (Undergoing testing)
