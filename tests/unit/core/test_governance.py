from pathlib import Path
from aegis_sdk.governance import Governance

def test_governance_fitness_landscape_in_process(tmp_path):
    _populate_governed_workspace(tmp_path)
    gov = Governance(project_root=tmp_path)
    res = gov.fitness_landscape(bayesian=True)
    assert isinstance(res, list)
    assert len(res) == 5
    cell_names = {c['cell'] for c in res}
    assert "trap-test-trap.md" in cell_names


def _populate_governed_workspace(root: Path):
    cells_dir = root / ".aegis" / "rules"
    for d in ["traps", "invariants", "personas", "boundaries", "contracts"]:
        (cells_dir / d).mkdir(parents=True, exist_ok=True)
    (cells_dir / "traps" / "trap-test-trap.md").write_text(
        "---\ntype: trap\nhypothesis: test trap\n---\nBody\n", encoding="utf-8"
    )
    (cells_dir / "invariants" / "invariant-test-guard.md").write_text(
        "---\ntype: invariant\nhypothesis: test guard\n---\nBody\n", encoding="utf-8"
    )
    (cells_dir / "personas" / "persona-test-persona.md").write_text(
        "---\ntype: persona\nhypothesis: test persona\n---\nBody\n", encoding="utf-8"
    )
    (cells_dir / "boundaries" / "boundary-test-boundary.md").write_text(
        "---\ntype: boundary\nhypothesis: test boundary\n---\nBody\n", encoding="utf-8"
    )
    (cells_dir / "contracts" / "contract-test-bridge.md").write_text(
        "---\ntype: contract\nhypothesis: test bridge\n---\nBody\n", encoding="utf-8"
    )


def test_list_rules_with_rule_type_filter(tmp_path):
    _populate_governed_workspace(tmp_path)
    gov = Governance(project_root=tmp_path)

    # 0 args: returns all cells
    all_cells = gov.list_rules()
    assert len(all_cells) == 5

    # Filter by canonical type
    traps = gov.list_rules(rule_type="trap")
    assert len(traps) == 1
    assert traps[0]["_name"] == "trap-test-trap"

    # Filter by porcelain alias
    traps_alias = gov.list_rules(rule_type="learned-trap")
    assert len(traps_alias) == 1
    assert traps_alias[0]["_name"] == "trap-test-trap"


def test_list_rules_porcelain_facade(tmp_path):
    _populate_governed_workspace(tmp_path)
    gov = Governance(project_root=tmp_path)

    all_rules = gov.list_rules()
    assert len(all_rules) == 5

    guards = gov.list_rules(rule_type="safety-guard")
    assert len(guards) == 1
    assert guards[0]["_name"] == "invariant-test-guard"

    personas = gov.list_rules(rule_type="agent-persona")
    assert len(personas) == 1
    assert personas[0]["_name"] == "persona-test-persona"

    boundaries = gov.list_rules(rule_type="escalation-boundary")
    assert len(boundaries) == 1
    assert boundaries[0]["_name"] == "boundary-test-boundary"

    bridges = gov.list_rules(rule_type="contract-bridge")
    assert len(bridges) == 1
    assert bridges[0]["_name"] == "contract-test-bridge"


def test_list_rules_corrupted_isolation(tmp_path):
    _populate_governed_workspace(tmp_path)
    gov = Governance(project_root=tmp_path)

    # Add corrupted trap cell
    corrupted_file = tmp_path / ".aegis" / "rules" / "traps" / "corrupted_trap.md"
    corrupted_file.write_bytes(b"\xff\xfe\x00\x00")

    # Full list returns diagnostic error record
    all_cells = gov.list_rules()
    assert any(c.get("_name") == "corrupted_trap" and "_error" in c for c in all_cells)

    # Invariant filter must isolate and NOT leak corrupted trap
    inv_cells = gov.list_rules(rule_type="invariant")
    assert not any(c.get("_name") == "corrupted_trap" for c in inv_cells)
    assert len(inv_cells) == 1
    assert inv_cells[0]["_name"] == "invariant-test-guard"


