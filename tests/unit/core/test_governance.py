import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from aegis_sdk.governance import Governance

def test_governance_fitness_landscape_in_process(tmp_path):
    _populate_governed_workspace(tmp_path)
    gov = Governance(project_root=tmp_path)
    res = gov.fitness_landscape(bayesian=True)
    assert isinstance(res, list)
    assert len(res) == 5
    cell_names = {c['cell'] for c in res}
    assert "vacuole-test-trap.md" in cell_names


def _populate_governed_workspace(root: Path):
    cells_dir = root / ".aegis" / "rules"
    for d in ["vacuoles", "walls", "chloroplasts", "membranes", "plasmodesmata"]:
        (cells_dir / d).mkdir(parents=True, exist_ok=True)
    (cells_dir / "vacuoles" / "vacuole-test-trap.md").write_text(
        "---\ntype: vacuole\nhypothesis: test trap\n---\nBody\n", encoding="utf-8"
    )
    (cells_dir / "walls" / "wall-test-guard.md").write_text(
        "---\ntype: wall\nhypothesis: test guard\n---\nBody\n", encoding="utf-8"
    )
    (cells_dir / "chloroplasts" / "chloroplast-test-persona.md").write_text(
        "---\ntype: chloroplast\nhypothesis: test persona\n---\nBody\n", encoding="utf-8"
    )
    (cells_dir / "membranes" / "membrane-test-boundary.md").write_text(
        "---\ntype: membrane\nhypothesis: test boundary\n---\nBody\n", encoding="utf-8"
    )
    (cells_dir / "plasmodesmata" / "plasmodesmata-test-bridge.md").write_text(
        "---\ntype: plasmodesmata\nhypothesis: test bridge\n---\nBody\n", encoding="utf-8"
    )


def test_list_cells_with_cell_type_filter(tmp_path):
    _populate_governed_workspace(tmp_path)
    gov = Governance(project_root=tmp_path)

    # 0 args: returns all cells
    all_cells = gov.list_cells()
    assert len(all_cells) == 5

    # Filter by canonical type
    vacuoles = gov.list_cells(cell_type="vacuole")
    assert len(vacuoles) == 1
    assert vacuoles[0]["_name"] == "vacuole-test-trap"

    # Filter by porcelain alias
    traps = gov.list_cells(cell_type="learned-trap")
    assert len(traps) == 1
    assert traps[0]["_name"] == "vacuole-test-trap"


def test_list_rules_porcelain_facade(tmp_path):
    _populate_governed_workspace(tmp_path)
    gov = Governance(project_root=tmp_path)

    all_rules = gov.list_rules()
    assert len(all_rules) == 5

    guards = gov.list_rules(rule_type="safety-guard")
    assert len(guards) == 1
    assert guards[0]["_name"] == "wall-test-guard"

    personas = gov.list_rules(rule_type="agent-persona")
    assert len(personas) == 1
    assert personas[0]["_name"] == "chloroplast-test-persona"

    boundaries = gov.list_rules(rule_type="escalation-boundary")
    assert len(boundaries) == 1
    assert boundaries[0]["_name"] == "membrane-test-boundary"

    bridges = gov.list_rules(rule_type="contract-bridge")
    assert len(bridges) == 1
    assert bridges[0]["_name"] == "plasmodesmata-test-bridge"


def test_record_outcome_in_process(tmp_path):
    import json
    _populate_governed_workspace(tmp_path)
    gov = Governance(project_root=tmp_path)

    res = gov.record_outcome(
        rule_id="vacuole-test-trap",
        success=True,
        metric={"test_metric": 99}
    )
    assert isinstance(res, dict)
    assert res.get("signal") == "tp" or res.get("signal_type") == "tp"

    signals_file = tmp_path / ".aegis" / "evidence" / "signals.jsonl"
    assert signals_file.exists()
    lines = [json.loads(line) for line in signals_file.read_text(encoding="utf-8").strip().splitlines()]
    assert len(lines) >= 1
    assert lines[-1]["cell"] == "vacuole-test-trap"
    assert lines[-1]["signal"] == "tp"


def test_record_outcome_fp_and_source_validation(tmp_path, monkeypatch):
    import json
    _populate_governed_workspace(tmp_path)
    gov = Governance(project_root=tmp_path)

    # Test failure outcome emits fp
    res_fp = gov.record_outcome("vacuole-test-trap", success=False, source="ci")
    assert isinstance(res_fp, dict)
    assert res_fp.get("signal") == "fp"

    # Test invalid source raises ValueError
    with pytest.raises(ValueError, match="Invalid telemetry source"):
        gov.record_outcome("vacuole-test-trap", success=True, source="invalid_src")

    # Test fallback guarantees dict return
    def _raise(*args, **kwargs):
        raise RuntimeError("simulated telemetry failure")

    monkeypatch.setattr("aegis_core.telemetry.append_signal", _raise)
    monkeypatch.setattr(gov, "signal", lambda *a, **k: "legacy stdout string")
    fallback_res = gov.record_outcome("vacuole-test-trap", success=True)
    assert isinstance(fallback_res, dict)
    assert fallback_res["status"] == "fallback_recorded"
    assert fallback_res["signal"] == "tp"
    assert fallback_res["raw"] == "legacy stdout string"


def test_list_cells_corrupted_isolation(tmp_path):
    _populate_governed_workspace(tmp_path)
    gov = Governance(project_root=tmp_path)

    # Add corrupted vacuole cell
    corrupted_file = tmp_path / ".aegis" / "rules" / "vacuoles" / "corrupted_trap.md"
    corrupted_file.write_bytes(b"\xff\xfe\x00\x00")

    # Full list returns diagnostic error record
    all_cells = gov.list_cells()
    assert any(c.get("_name") == "corrupted_trap" and "_error" in c for c in all_cells)

    # Wall filter must isolate and NOT leak corrupted vacuole
    wall_cells = gov.list_cells(cell_type="wall")
    assert not any(c.get("_name") == "corrupted_trap" for c in wall_cells)
    assert len(wall_cells) == 1
    assert wall_cells[0]["_name"] == "wall-test-guard"


def test_record_outcome_idempotency_forwarding(tmp_path):
    import json
    _populate_governed_workspace(tmp_path)
    gov = Governance(project_root=tmp_path)

    res = gov.record_outcome(
        rule_id="vacuole-test-trap",
        success=True,
        metric={"test_metric": 42},
        principal="test-agent",
        idempotency_scope="session-1",
        idempotency_key="msg-100",
    )
    assert res.get("event_id") is not None
    assert res.get("payload_digest") is not None

    signals_file = tmp_path / ".aegis" / "evidence" / "signals.jsonl"
    lines = [json.loads(line) for line in signals_file.read_text(encoding="utf-8").strip().splitlines()]
    last = lines[-1]
    assert last["cell"] == "vacuole-test-trap"
    assert last["event_id"] == res["event_id"]
    assert last["payload_digest"] == res["payload_digest"]


def test_record_outcome_unknown_rule_warning(tmp_path):
    import warnings
    _populate_governed_workspace(tmp_path)
    gov = Governance(project_root=tmp_path)

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        res = gov.record_outcome("non-existent-cell", success=True)
        assert res.get("signal") == "tp"
        assert any("not found in active inventory" in str(w.message) for w in recorded)


def test_create_rule_and_type_translation(tmp_path):
    _populate_governed_workspace(tmp_path)
    gov = Governance(project_root=tmp_path)
    created = gov.create_rule("Safety check test", type="safety-guard")
    assert Path(created).exists()
    assert "/walls/" in Path(created).as_posix()


def test_rule_fitness_alias(tmp_path, monkeypatch):
    gov = Governance(project_root=tmp_path)
    called = []
    monkeypatch.setattr(gov, "fitness_landscape", lambda bayesian=False: called.append(bayesian) or {})
    gov.rule_fitness(bayesian=True)
    assert called == [True]


def test_sdk_exports():
    from aegis_sdk import Governance, Cell, CellFitness, SomaError
    assert Governance is not None
    assert Cell is not None
    assert CellFitness is not None
    assert issubclass(SomaError, Exception)


def test_sdk_scoring_reexports():
    from aegis_sdk.scoring import calculate_snr, calculate_composite_fitness, compute_cell_fitness
    assert calculate_snr(10, 2) is not None
    assert calculate_composite_fitness is compute_cell_fitness


def test_cell_fitness_snr_db_delegation():
    from aegis_sdk.rules import CellFitness
    from aegis_core.scoring import calculate_snr

    cf = CellFitness(true_positives=10, false_positives=2)
    assert cf.snr_db == calculate_snr(10, 2)

    cf_inf = CellFitness(true_positives=5, false_positives=0)
    assert cf_inf.snr_db is None

    cf_zero = CellFitness(true_positives=0, false_positives=5)
    assert cf_zero.snr_db == -99.0


def test_write_cell_frontmatter_zero_dep_fallback(tmp_path, monkeypatch):
    import aegis_sdk.rules as sdk_cells
    monkeypatch.setattr(sdk_cells, "yaml", None)

    target_file = tmp_path / "cell_zero_dep.md"
    sdk_cells.write_cell_frontmatter(
        str(target_file),
        {"name": "test-cell", "type": "wall"},
        "## Hypothesis\nZero dep fallback.\n",
    )
    content = target_file.read_text(encoding="utf-8")
    assert "name: test-cell" in content
    assert "type: wall" in content
    assert "Zero dep fallback" in content



