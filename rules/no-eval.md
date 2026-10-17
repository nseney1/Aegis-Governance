---
id: no-eval
type: invariant
domain: security
enforcement: gate
name: No eval or exec
description: Bans eval() and exec() in Python files; aegis check and the pre-commit hook fail a change that calls them.
trigger: model_decision
hypothesis: Agents reach for eval() or exec() to parse or run data, which runs whatever the data holds
prediction: aegis check fails a change that adds an eval() or exec() call to a Python file
falsification: Most of the calls it stops over 20 verdicts are reviewed, safe uses
target_paths:
  - "**/*.py"
forbid_ast:
  calls:
    - name: eval
      builtin: true
    - name: exec
      builtin: true
---
# No eval or exec

Never call `eval` or `exec` on data: they run whatever the string holds. Parse data with
`json.loads` or `ast.literal_eval`, and dispatch on a dict of functions instead of building
code as text.

`aegis init` seeds this rule into a new workspace so that `aegis check` and the pre-commit
hook enforce something on day one.
Because `builtin: true` is set, only Python's builtin `eval()` and `exec()` (including
`builtins.eval` and `__builtins__.eval`) fail the check; method calls like pandas
`df.eval()`, PyTorch `model.eval()`, and SQLModel `session.exec()` are allowed. Test files are not checked unless `target_paths` names
them. If this repository needs `eval` somewhere, narrow `target_paths` or delete this file.
Add rules for your own code with `aegis rule create`.
