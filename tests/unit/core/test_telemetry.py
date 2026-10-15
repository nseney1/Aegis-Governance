"""Grade and credit-weight helpers used by the ledger's writers and readers.

The ledger itself is covered by test_ledger.py.
"""
from aegis_core.metrics import letter_grade
from aegis_core.outcomes.fitness import compute_credit_weights


def test_telemetry_letter_grade():
    assert letter_grade(98) == "A+"
    assert letter_grade(85) == "B"
    assert letter_grade(50) == "F"


def test_telemetry_credit_weights():
    cells = [
        {"id": "cell-a", "target_paths": ["src/*.py"]},
        {"id": "cell-b", "target_paths": ["tests/*.py"]},
    ]
    weights = compute_credit_weights(cells, ["src/app.py"])
    assert weights["cell-a"] == 1.0
    assert weights["cell-b"] == 0.0
