"""Canary test verifying dual-brand prefix stripping and type directory mappings."""
from pathlib import Path
from aegis_core.verification.checkpoint_checks import (
    _resolve_canonical_test_candidates,
    DIR_TO_TYPE,
)


def test_prefix_stripping_dual_brand():
    """Verify that both soma_ and aegis_ prefixes are cleanly stripped."""
    root = Path("/dummy/repo")
    soma_candidates = [
        str(c) for c in _resolve_canonical_test_candidates(root, root / "aegis_core" / "scoring.py")
    ]
    aegis_candidates = [
        str(c) for c in _resolve_canonical_test_candidates(root, root / "aegis_core" / "scoring.py")
    ]

    assert str(root / "tests" / "core" / "test_scoring.py") in soma_candidates
    assert str(root / "tests" / "core" / "test_scoring.py") in aegis_candidates

    soma_cli = [
        str(c) for c in _resolve_canonical_test_candidates(root, root / "aegis_cli" / "verify.py")
    ]
    aegis_cli = [
        str(c) for c in _resolve_canonical_test_candidates(root, root / "aegis_cli" / "verify.py")
    ]
    assert str(root / "tests" / "cli" / "test_verify.py") in soma_cli
    assert str(root / "tests" / "cli" / "test_verify.py") in aegis_cli


def test_dir_to_type_dual_mapping():
    """Verify DIR_TO_TYPE maps both biological and engineering directory names."""
    assert "invariant" in DIR_TO_TYPE["walls"]
    assert "invariant" in DIR_TO_TYPE["invariants"]
    assert "trap" in DIR_TO_TYPE["vacuoles"]
    assert "trap" in DIR_TO_TYPE["traps"]
    assert "boundary" in DIR_TO_TYPE["membranes"]
    assert "boundary" in DIR_TO_TYPE["boundaries"]
    assert "persona" in DIR_TO_TYPE["chloroplasts"]
    assert "persona" in DIR_TO_TYPE["personas"]
    assert "contract" in DIR_TO_TYPE["plasmodesmata"]
    assert "contract" in DIR_TO_TYPE["contracts"]
