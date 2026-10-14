---
id: trap-ghost-cli-flags
domain: correctness
type: wall
enforcement: gate
hypothesis: CLI flags registered in the argument parser but not consumed by the handler function create a false contract — users believe the flag does something but it is silently ignored
prediction: "Will fire when argparse registers --flag but the run_* handler never reads args.flag, or reads it but takes no action"
falsification: 0 findings in 10 sessions → prune
target_paths:
  - soma_cli/cli.py
  - "soma_cli/*.py"
triggers:
  - cli_modification
  - new_subcommand
  - flag_registration
minimum_mode: standard
expiry_sessions: 50
expiry_days: 180
created: 2026-09-30
impact_weight: 0.9
tags:
  - correctness
  - cli
  - dead-code
  - contract
fitness:
  score: 0.5
  impact_weight: 0.9
  triggers: 47
  true_positives: 7.543
  false_positives: 5.7814
  last_trigger_date: "2026-10-14T06:50:24Z"
---

Every CLI flag registered in argparse MUST be consumed by the handler function.

Supercell Cycle 2 incident:
`soma_cli/cli.py:93-96` registered `--force` and `--cell` flags for `soma demote`.
However, `run_demote()` in `soma_cli/demote.py` completely ignored `args.force`
and `args.cell`. The command accepted the flags and silently did nothing.

Detection: For each subcommand parser, grep for `add_argument('--flag')` and
verify the handler function reads `args.flag` or `getattr(args, 'flag')`.

Automated check: AST parse cli.py to extract registered flags per subcommand,
then grep each handler for the corresponding attribute access.
