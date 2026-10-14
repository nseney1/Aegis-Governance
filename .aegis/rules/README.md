# Governance Cells

This directory contains Soma governance cells. Cells are atomic, modular components that inject specialized constraints, heuristics, or environmental adaptations into the agent's context.

## Cell Types
- **Vacuole**: Traps and anti-patterns. Prevents the agent from falling into common pitfalls (e.g., using incorrect build tools, deprecated APIs).
- **Chloroplast**: Accelerators and optimizations, usually as repo-specific personas tuned to the domain. Provides fast-paths for common workflows.
- **Wall**: Boundary conditions and strict invariants. Enforces safety and policy requirements (e.g. things you must never do).
- **Membrane**: Filtering and transformation. Adjusts input/output to conform to expected structures, or defines escalation overrides.
- **Plasmodesmata**: Cross-repo connections in multi-service architectures. Maps data paths between distinct projects.

## Cell Format Spec
Each cell is a Markdown file starting with YAML frontmatter.
Required fields:
- `type`: vacuole, chloroplast, wall, membrane, or plasmodesmata
- `hypothesis`: What this cell intends to achieve
- `prediction`: Expected measurable outcome
- `falsification`: Conditions under which this cell should be removed
- `expiry_sessions` / `expiry_days`: TTL for the cell
- `fitness`: Tracking block with `triggers`, `true_positives`, `false_positives`

## Fitness Lifecycle & Verification (v0.25)
Cells are actively enforced pre-commit by the **Test-Time Compute (TTC) Verifier**, which rejects agent proposals that violate them. 

Cells undergo evolutionary selection based on their fitness score (TP / Triggers * Weight). Evolutionary pruning and structural changes (like apoptosis or crossover) occur during the organism's **Sleep** phase:
- **SURVIVE**: Score > 0.7 (Highly effective, kept)
- **ADAPT**: Score 0.3 - 0.7 (Needs tuning)
- **EXTINCT**: Score < 0.3 (Candidate for pruning during Sleep)
- **DORMANT**: 0 triggers past expiry (Candidate for pruning during Sleep)
- **NEW**: 0 triggers within expiry (Undergoing testing)
