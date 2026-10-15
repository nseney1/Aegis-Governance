---
id: core-change-protocol
domain: governance
trigger: model_decision
description: Requires impact analysis, behavioral test verification, and review gates when modifying core governance rules or skills.
activation: |
  Changes touching: aegis_core/outcomes/*, aegis_core/lifecycle/*,
  aegis_mcp/jit_engine.py, aegis_core/verification/*, aegis_cli/hooks/*
enforcement: gate
---

# Core Rule & Skill Change Protocol

Sensitive governance systems **must** follow the full TDD Protocol
(see `rules/.oracles/tdd-protocol.md`) without exception.

These files control rule fitness scoring, rule lifecycle, and verification verdicts.
A bug here doesn't just break a feature — it corrupts the governance layer's ability
to detect future bugs. The blast radius is recursive.

No trivial-change exemption applies to files in this activation list.
