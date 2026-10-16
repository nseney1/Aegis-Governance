---
id: trap-roadmap-status-drift
domain: documentation
type: trap
enforcement: gate
hypothesis: "Shipping a feature without updating ROADMAP.md status markers causes the roadmap to become a stale document that misleads contributors about what's planned vs what's already shipped"
prediction: "Will fire when a release (version bump, CHANGELOG entry) ships features listed in ROADMAP.md but the roadmap status is not updated to reflect shipped state"
falsification: 0 findings in 20 sessions → prune
target_paths:
  - docs/project/ROADMAP.md
  - docs/project/CHANGELOG.md
  - aegis_core/_version.py
  - pyproject.toml
triggers:
  - release
  - feature_addition
  - version_bump
  - commit_review
minimum_mode: patrol
expiry_sessions: 30
expiry_days: 90
created: 2026-10-01
impact_weight: 1.0
tags:
  - documentation
  - drift
  - roadmap
  - process
---

v0.81 origin: Phase 4 features (Quorum Sensing, Gate Enforcement) shipped in v0.80
but ROADMAP.md still listed them as "Implementation planned (Phase 4)" with status
"(NEXT)". The CI Outcome Reporter shipped in v0.81 but the roadmap had no entry for
Phase 4.5 at all. This rule ensures that every release that ships features listed in
the roadmap also updates their status markers, and that new phases are added to the
roadmap as they are defined.

Detection: when a commit touches aegis_core/_version.py or CHANGELOG.md (release indicators), check
that ROADMAP.md is also in the changeset. If ROADMAP.md is not modified alongside a
release, flag for review.
