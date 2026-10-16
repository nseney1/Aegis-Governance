"""Worker for the gitsafe create-only race test (tests/unit/core/test_gitsafe_refs.py).

It lives in an importable module because the test starts its racers with the
``spawn`` start method, which pickles the target by module and name; pytest's
importlib mode does not make test modules importable by name.
"""
from __future__ import annotations


def claim(cwd: str, ref: str, payload: bytes, barrier, results) -> None:
    """Write ``payload`` as a blob, wait for every racer, then try a create-only claim
    of ``ref``. Puts ``(payload, outcome, oid, current)`` on ``results``."""
    from aegis_core import gitsafe

    try:
        oid = gitsafe.write_blob(cwd, payload)
        barrier.wait(timeout=60)
        try:
            gitsafe.update_ref(cwd, ref, oid, None)
        except gitsafe.RefConflict as exc:
            results.put((payload, "lost", oid, exc.current))
            return
        results.put((payload, "won", oid, oid))
    except BaseException as exc:  # reported to the parent, which fails the test
        results.put((payload, "error", repr(exc), None))
