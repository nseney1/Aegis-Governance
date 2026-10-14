---
id: trap-convention-assumption
domain: correctness
type: trap
enforcement: gate
hypothesis: Assuming a schema field value or naming convention without verifying against existing instances causes silent contract violations that pass new tests but fail regression
prediction: "Will fire when new files are created with field values that don't match existing files of the same type"
falsification: 0 findings in 10 sessions → prune
target_paths:
  - ".aegis/rules/**/*.md"
  - "**/*.py"
triggers:
  - cell_creation
  - schema_definition
  - convention_review
minimum_mode: standard
expiry_sessions: 30
expiry_days: 90
created: 2026-09-30
impact_weight: 1.0
tags:
  - correctness
  - convention
  - dogfooding
fitness:
  score: 0.5714
  impact_weight: 1.0
  triggers: 79
  true_positives: 36.1257
  false_positives: 34.4833
  last_trigger_date: "2026-10-14T19:09:13Z"
---

Before creating new instances of a typed artifact (cells, config files, schema
records), ALWAYS read at least one existing instance of the same type to ground
the field values and naming conventions.

Supercell enforcement incident: 5 wall cells were created with `enforcement: blocking`
instead of `enforcement: gate`. The agent assumed the value, wrote new tests that
codified the wrong value (circular self-consistency), and only the pre-existing
`test_rule_metadata.py` caught the mismatch. A 3-second `grep "enforcement"
.aegis/rules/walls/*.md` would have prevented the error.

Detection: When creating N>1 instances of a type, grep existing instances first.
If the new instance's field values don't match, halt and verify.
