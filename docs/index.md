# Aegis Guardrails Documentation

> Adaptive governance, deterministic AST verification, and Model Context Protocol (MCP) server for AI coding agents.

## Documentation by Audience

### 👤 Guides & Core Workflows
- [Quickstart](../QUICKSTART.md) — Installation, `aegis init`, and core CLI workflow
- [Rule Lifecycle](guides/rule_lifecycle.md) — 4 canonical rule types (`invariant`, `trap`, `gate`, `method`), `AegisYAML`, and Bayesian fitness
- [MCP Gateway Guide](guides/mcp_gateway.md) — Dual-plane architecture, all 17 `aegis_*` tools, cryptographic receipts, and `RuleCache`
- [Verification Pipeline](guides/verification_pipeline.md) — Layer 1 `DeterministicVerifier`, Layer 2 `AdversarialVerifier`, `Arbiter`, and Release Gate 4.5
- [Polyglot AST Analysis](guides/polyglot_ast.md) — `NormalizedAST`, `ASTDriverRunner`, `aegis detect --fix`, and `.aegis/drivers/`
- [Skill Graph & Handoffs](guides/skill_graph.md) — Horizontal `SkillGraph`, `.aegis/slots.yaml` fail-closed interpolation, and `<150` token `HandoffTicket`

### 🏗️ Architecture & Design
- [Mechanism Design](architecture/mechanism_design.md) — Formal incentive and Bayesian governance mapping
- [Phylogeny](architecture/phylogeny.md) — Phase-by-phase architectural evolution
- [Scripts & Modules](architecture/scripts.md) — Complete `aegis_core`, `aegis_mcp`, `aegis_cli`, and `aegis_sdk` module catalog

### 🤝 Contributors, Security & Maintainers
- [Contributing Guide](../CONTRIBUTING.md) — Dev setup, Gitflow review gate, Release Gate 4.5, and rule/skill authoring
- [Security Policy](../SECURITY.md) — Vulnerability reporting, `confine_path_internal`, `ReceiptManager`, and signed manifests
- [Privacy Policy](../PRIVACY.md) — Local-first air-gapped MCP guarantees and `.aegis/` data boundaries
- [Compatibility Guarantee](project/COMPATIBILITY.md) — SemVer 2.0 stability and deprecation policy
- [Changelog](project/CHANGELOG.md) — Full release history
- [Roadmap](project/ROADMAP.md) — Phased milestones and claim tracking
- [Release Workflow](project/RELEASE_WORKFLOW.md) — Gitflow, artifact verification, and release checklist
- [Claim Registry](project/CLAIM_REGISTRY.json) — Machine-readable verified claims
- [Bug Registry](project/BUG_REGISTRY.json) — Fixed and tracked defects
- [Metrics](project/METRICS.md) — Empirical measurement methodology
- [Known Issues — Windows](KNOWN_ISSUES_WINDOWS.md) — Platform-specific notes and resolved Windows defects

### 📄 Research & Evaluation
- [Abstract](research/abstract.md) — Research paper abstract
- [Benchmark](research/benchmark.md) — Cross-domain benchmark protocol
- [Experiments](research/experiments.md) — Active and completed experiment log
- [Peer Reviews](research/peer_reviews.md) — Review record

### 📦 Archive
- [Historical Audit Evidence](archive/) — Genesis reports, postmortems, and review records
