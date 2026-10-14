"""Canary test verifying release gate allowlist and evidence discovery for .aegis."""
from pathlib import Path
from soma_cli.verify import _is_dirty
from soma_core.verification.review_adapter import get_latest_arbitration_evidence


def test_is_dirty_ignores_aegis_evidence():
    """Verify _is_dirty treats changes under .aegis/evidence as clean."""
    assert not _is_dirty("?? .aegis/evidence/arb-123.json\n")
    assert not _is_dirty(" M .aegis/metrics/history.jsonl\n")
    assert not _is_dirty("?? .aegis/evidence/arb-123.json\n")
    # Real code changes should still register as dirty
    assert _is_dirty(" M soma_core/scoring.py\n")
    assert _is_dirty(" M aegis_core/scoring.py\n")


def test_get_latest_arbitration_evidence_dual_brand(tmp_path: Path):
    """Verify evidence discovery looks in .aegis/evidence before .soma/evidence."""
    aegis_ev = tmp_path / ".aegis" / "evidence"
    aegis_ev.mkdir(parents=True)
    ev_file = aegis_ev / "arbitration_cycle_1.json"
    ev_file.write_text('{"verdict": "pass", "timestamp": "2026-10-14T00:00:00Z"}\n')

    cycle_num, data = get_latest_arbitration_evidence(str(tmp_path))
    assert cycle_num == 1
    assert data is not None
    assert data.get("verdict") == "pass"
