---
id: no-pre-existing-excuse
domain: governance
activation: |
  Agent identifies a defect in a file it is actively modifying
  and labels it "pre-existing", "out of scope", or "not introduced
  by this change".
enforcement: gate
---

# No Pre-Existing Excuse

> **Role**: Prevents agents from dismissing defects in files they are actively
> modifying by labeling them "pre-existing" or "out of scope."

## 1. The Rule

If you are modifying a file and discover a defect in that file, **you own it**.
You may not classify it as "pre-existing" to avoid fixing it.

## 2. Why

The classification "pre-existing" is itself an unverifiable claim. The agent
asserting a bug is pre-existing is the same agent that might have introduced it.
Without independent version-control forensics (`git blame`, `git log`), the
claim has zero evidentiary weight.

This is the gentleman's agreement problem applied to scope: trusting the agent
to honestly classify which bugs are "theirs" is exactly the kind of honor-system
governance that Soma exists to replace.

## 3. Exceptions

- **Explicitly out-of-scope files**: If the agent is modifying `foo.py` and
  finds a bug in `bar.py` (which it is NOT modifying), it may flag the bug
  without fixing it — but must log it as a tracked finding.
- **User-directed scope limits**: If the user explicitly says "only fix X,
  don't touch Y," the agent may defer Y with a logged rationale.

## 4. Evidence

Session 2026-09-30: Agent dismissed broken `import yaml` and collision
vulnerabilities as "pre-existing / out of scope" in files it was actively
editing. User had to intervene: *"The point of governance is that we can't
even trust the verdict that this is 'pre-existing'."*
