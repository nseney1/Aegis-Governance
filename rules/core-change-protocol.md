---
id: core-change-protocol
domain: governance
activation: |
  Changes touching: aegis_core/outcomes/*, aegis_core/lifecycle/*,
  aegis_mcp/jit_engine.py, aegis_core/verification/*, install/hooks/*
enforcement: gate
---

# Core Change Protocol

Sensitive governance systems **must** follow the full TDD Protocol
(see `rules/.oracles/tdd-protocol.md`) without exception.

These files control cell fitness scoring, rule lifecycle, and verification verdicts.
A bug here doesn't just break a feature — it corrupts the governance layer's ability
to detect future bugs. The blast radius is recursive.

No trivial-change exemption applies to files in this activation list.
