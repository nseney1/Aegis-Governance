"""The grade helper used by the governance report card.

Credit weights are covered by test_match.py, the ledger by test_ledger.py.
"""
from aegis_core.metrics import letter_grade


def test_telemetry_letter_grade():
    assert letter_grade(98) == "A+"
    assert letter_grade(85) == "B"
    assert letter_grade(50) == "F"

