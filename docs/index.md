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
- [Why Aegis is built this way](why-aegis.md) — Evidence, mistakes, and what changed in v4
- [Decision records](adr/) — ADRs 0003, 0005 and 0012–0016

### 🤝 Contributors, Security & Maintainers
- [Contributing Guide](../CONTRIBUTING.md) — Dev setup, Gitflow review gate, Release Gate 4.5, and rule/skill authoring
- [Security Policy](../SECURITY.md) — Vulnerability reporting, `confine_path_internal`, `ReceiptManager`, and signed manifests
- [Privacy Policy](../PRIVACY.md) — Local-first air-gapped MCP guarantees and `.aegis/` data boundaries
- [Changelog](project/CHANGELOG.md) — Full release history
- [Roadmap](project/ROADMAP.md) — Phased milestones and claim tracking
- [Release Workflow](project/RELEASE_WORKFLOW.md) — Gitflow, artifact verification, and release checklist
