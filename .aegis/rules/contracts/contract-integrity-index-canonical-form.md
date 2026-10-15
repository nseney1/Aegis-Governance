---
id: contract-integrity-index-canonical-form
domain: security
type: contract
enforcement: advisory
hypothesis: "A rule integrity index that is regenerated wholesale, hashed in a different canonical form than its verifier reads, or skipped by some rule-file writers either launders tampered rules or rejects valid ones"
prediction: "Index generation and verification share one canonical function, and roundtrip tests cover CRLF, tampering, corruption and every rule-file writer"
falsification: "0 findings in 15 sessions: prune"
expiry_sessions: 15
expiry_days: 60
created: "2026-10-15T16:11:59Z"
impact_weight: 1.0
tags: ["debrief", "citadel", "integrity", "manifest"]
target_paths: ["aegis_core/integrity.py", "aegis_mcp/rule_cache.py", "aegis_core/lifecycle/creation.py", "aegis_core/lifecycle/promotion.py", "aegis_core/lifecycle/selection.py", "aegis_core/outcomes/fitness.py", "aegis_cli/init.py", "tests/unit/core/**", "tests/integration/**"]
lineage:
  parent_id: null
  created_by: "manual"
  generation: 0
  siblings: []
---
# Contract: one canonical form for the rule integrity index

**Rule**: The rule integrity index (`.aegis/rules/manifest.json`; in v4.0 the
sha256 index that `aegis sync` writes, D3) is generated and verified by one
canonical function: LF-normalized content, relative POSIX path keys, a digest
covering exactly the mapping the consumer reads, and no volatile fields. It is
updated incrementally for only the touched entry under the RULES lock, refuses
to re-attest when verify reports other drift, and has roundtrip tests covering
CRLF, tampering, corruption and every rule-file writer.

## Incident (v4 Citadel review)

- `sync_manifest_if_present` rehashed and re-signed the whole rules tree, which
  laundered tampered or planted rules into a valid signature, and a corrupt
  manifest skipped the HMAC guard.
- The HMAC signed only `cells` while the loader preferred an unsigned `rules`
  mirror. `generate_manifest` hashed raw bytes, so a CRLF tree served 0 of 49
  rules to LF consumers.
- Fitness, tier and transfer writers rewrote rule files without resyncing, so
  RuleCache dropped them as tampered. `lstrip('./')` ate the leading dot of
  `.aegis` and basename keys collided. `generated_at` plus the mirror made every
  merge conflict, and exclusions were visible only on stderr.
- It was missed because no test ran the generate-to-verify roundtrip across
  line endings, ran two lifecycle operations concurrently, or ran a writer other
  than create, promote or demote with a manifest present. Deleting both LF
  fallbacks left 222 tests green.

## Check

1. Exactly one function computes a rule file's digest; a second hashing path for
   rule files fails review.
2. Roundtrip tests: generate on a CRLF tree and verify on LF; flip one byte;
   corrupt the JSON; run every rule-file writer with an index present.
3. Every rule-file writer either updates its own entry under the RULES lock or
   tells the operator the index is stale (as `aegis rule create` does today).
