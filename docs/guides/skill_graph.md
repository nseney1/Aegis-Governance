# Horizontal Skill Graph, Slots & Swarm Handoffs

> Reusable capability nodes (`SkillGraph`), fail-closed slot interpolation (`SlotRegistry`), and file-buffered swarm handoffs (`HandoffRouter`) under 150 tokens.

---

## 1. Horizontal Skills as Slots (`SkillGraph` & `SkillNode`)

While adaptive **Rules** (`.aegis/rules/`) evolve via Bayesian outcome feedback, **Skills** (`skills/<name>/SKILL.md`) represent deterministic, reusable agent capabilities (`decay=False`) organized in a directed **Horizontal Skill Graph** (`aegis_core/skills/graph.py`):

- **`SkillNode`**: Immutable dataclass capturing `id`, `tier` (default `"method"`), `consumes` (accepted input artifact schemas), `produces` (emitted output artifact schemas), `handoff_targets` (downstream skill IDs), `instructions_file`, and `slot_constraints`.
- **`SkillGraph`**: Scale-to-zero graph discovered lazily from `skills/` and `.aegis/skills/`. Markdown bodies are loaded on demand via `SkillNode.load_instructions()` rather than held in resident memory.

### Fail-Closed Slot Interpolation (`SlotRegistry` in `.aegis/slots.yaml`)

Skills stay portable across languages and repositories by referencing abstract slot variables (`${SLOT.test_cmd}`, `${SLOT.lint_cmd}`, `${SLOT.ast_driver_rs}`). `SlotRegistry` (`aegis_core/skills/slots.py`) loads repository-specific bindings from `.aegis/slots.yaml`:

```yaml
# .aegis/slots.yaml
slots:
  test_cmd: "python3 -m pytest -q"
  lint_cmd: "aegis check"
  ast_driver_rs: "python3 .aegis/drivers/rust_ast.py"
  ast_driver_ts: "node .aegis/drivers/ts_ast.js"
```

When `SkillNode.load_instructions(workspace_root, strict_slots=True)` or `SlotRegistry.resolve(template, strict=True)` evaluates a skill template, any unresolved `${SLOT.*}` placeholder immediately raises `SlotResolutionError` (fail-closed) rather than allowing an agent to guess or hallucinate shell commands.

---

## 2. File-Buffered Swarm Handoffs (`HandoffRouter` & `HandoffTicket`)

To prevent context window exhaustion when subagents collaborate, `HandoffRouter` (`aegis_core/skills/handoff.py`) replaces inline multi-thousand-token message dumps with **file-buffered tickets**:

1. **Edge & Schema Validation**: `HandoffRouter.execute_handoff()` verifies that `from_skill -> to_skill` is a valid edge in `SkillGraph` and wraps the payload in a cryptographically signed `ArtifactEnvelope` (`aegis_core/schemas/artifacts.py`).
2. **Disk Persistence**: The full validated envelope is written atomically to `.aegis/swarm/handoffs/{cycle_id}_{artifact_type}.json`.
3. **Compact Ticket (`HandoffTicket` < 150 Tokens)**: The router returns an ultra-compact `HandoffTicket` bound to `git rev-parse HEAD^{tree}` and an HMAC session signature:

```text
<!-- AEGIS_HANDOFF_TICKET -->
[TICKET]: 8f3a1c9e | [TYPE]: ChargeSheet
[FROM]: adaptive-reviewer -> [TO]: spec-synthesizer
[PAYLOAD]: file:///path/to/repo/.aegis/swarm/handoffs/cycle1_ChargeSheet.json
[TREE]: 4b825dc642cb6eb9a060e54bf8d69288fbee4904 | [HMAC]: a91f04c83e2b...
[SUMMARY]: 2 high-severity findings in verification pipeline
<!-- END_HANDOFF_TICKET -->
```

### Registered `ArtifactEnvelope` Schemas (`aegis_core/schemas/artifacts.py`)

- `ChargeSheet`: Information-partitioned prosecution charges with length caps and XML sanitization (`AEGIS-V01`).
- `InspectionReceipt`: Deterministic static analysis and review findings.
- `DiffProposal`: Scoped unified diff proposal with target file digests.
- `TestVerdict`: Structured test suite and mutation execution report.

---

## 3. CLI & MCP Handoff Interfaces

### CLI Commands (`aegis skill` & `aegis handoff`)

```bash
# List all discovered skills in the SkillGraph
aegis skill list

# Inspect a skill's consumes/produces contracts, handoff targets, and slots
aegis skill inspect staff-review

# View active .aegis/slots.yaml bindings and resolution status
aegis skill slots

# Execute a file-buffered handoff from the CLI
aegis handoff --from adaptive-reviewer --to spec-synthesizer \
  --type InspectionReceipt --payload '{"summary": "Audit complete", "passed": true}'
```

### MCP Tool (`aegis_handoff`)

Subagents connected to `aegis_mcp` invoke `aegis_handoff` (Write Tier, receipt required):
1. Request receipt: `aegis_request_receipt(operation="aegis_handoff", args={...})`
2. Execute handoff: `aegis_handoff(from_skill="...", to_skill="...", artifact_type="...", payload={...}, receipt="...")`
