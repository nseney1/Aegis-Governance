"""Worker for the shared-ledger race tests (tests/unit/core/test_shared_ledger.py).

Importable by module and name because the racers start with the ``spawn`` method,
which pickles the target; pytest's importlib mode does not make test modules
importable that way.
"""
from __future__ import annotations


def append_events(cwd: str, worker: str, count: int, shared_keys, barrier, results) -> None:
    """Wait for every racer, then append ``count`` events of its own and one event per
    ``shared_keys`` entry (the same key from every racer). Puts ``(worker, "ok", [seq…])``
    or ``(worker, "error", repr)`` on ``results``."""
    from aegis_core.telemetry_engine import ledger

    try:
        barrier.wait(timeout=60)
        seqs = []
        for index in range(count):
            (row,) = ledger.append(cwd, [{"rule": "trap-x", "outcome": "tp", "source": "ci",
                                          "key": f"{worker}-{index}"}])
            seqs.append(row["seq"])
        for key in shared_keys:
            (row,) = ledger.append(cwd, [{"rule": "trap-x", "outcome": "tp", "source": "ci", "key": key}])
            seqs.append(row["seq"])
        ledger.append(cwd, [{"rule": "trap-y", "outcome": "trigger", "source": "ci"}])  # keyless
        results.put((worker, "ok", seqs))
    except BaseException as exc:  # reported to the parent, which fails the test
        results.put((worker, "error", repr(exc)))


def merge(cwd: str, sources, barrier, results) -> None:
    """Wait for every racer, then merge ``sources`` into the shared ledger of ``cwd``.
    Puts ``(rows written, duplicates)`` or ``("error", repr)`` on ``results``."""
    from aegis_core.telemetry_engine import ledger

    try:
        barrier.wait(timeout=60)
        written, duplicates = ledger.merge_rows(cwd, sources)
        results.put((len(written), duplicates))
    except BaseException as exc:  # reported to the parent, which fails the test
        results.put(("error", repr(exc)))
