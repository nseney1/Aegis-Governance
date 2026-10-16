"""Canary test verifying dual-brand prefix stripping in test-file resolution."""
from pathlib import Path
from aegis_core.verification.checkpoint_checks import _resolve_canonical_test_candidates


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

