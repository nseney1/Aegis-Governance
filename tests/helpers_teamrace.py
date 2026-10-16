"""Worker for the lease race tests (tests/unit/core/test_team.py).

Importable by module and name because the racers start with the ``spawn`` method,
which pickles the target; pytest's importlib mode does not make test modules
importable that way.
"""
from __future__ import annotations


def claim(cwd: str, lane: str, paths, owner: str, barrier, results) -> None:
    """Wait for every racer, then claim ``lane``. Puts ``(owner, outcome, oid)`` on
    ``results``: outcome is the change's action, ``refused:<reason>`` or ``error``."""
    from aegis_core import team

    try:
        barrier.wait(timeout=60)
        try:
            change = team.claim(cwd, lane, paths, owner=owner)
        except team.LeaseRefused as exc:
            results.put((owner, f"refused:{exc.reason}", exc.current))
            return
        results.put((owner, change.action, change.oid))
    except BaseException as exc:  # reported to the parent, which fails the test
        results.put((owner, "error", repr(exc)))
