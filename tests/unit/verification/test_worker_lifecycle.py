"""Tests for worker daemon lifecycle, shutdown, and persistence (aegis_core.verification.jobs)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from aegis_core.verification.jobs import (
    create_job,
    get_job,
    list_jobs,
    shutdown_verification_engine,
    persist_jobs_state,
    restore_jobs_state,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_FAILED,
)


class TestWorkerLifecycleAndPersistence:
    """Test suite for clean shutdown and job queue persistence."""

    def test_shutdown_marks_queued_jobs_failed_and_cleans_up(self, tmp_path: Path):
        """Shutting down marks queued/running jobs as server_shutdown."""
        job = create_job(workspace=str(tmp_path), files=["a.py"])
        assert job.status in (JOB_STATUS_QUEUED, JOB_STATUS_RUNNING)

        shutdown_verification_engine(grace_period=1.0)

        updated = get_job(job.job_id)
        assert updated is not None
        assert updated.status == JOB_STATUS_FAILED
        assert "server_shutdown" in (updated.error or "")

    def test_persist_and_restore_jobs_state(self, tmp_path: Path):
        """State of completed and failed jobs can be saved and restored across restarts."""
        job = create_job(workspace=str(tmp_path), files=["b.py"])
        job.status = JOB_STATUS_FAILED
        job.error = "test error"

        saved_path = persist_jobs_state(str(tmp_path))
        assert Path(saved_path).exists()

        loaded_jobs = restore_jobs_state(str(tmp_path))
        assert any(j.job_id == job.job_id for j in loaded_jobs)

    def test_shutdown_during_running_pipeline_preserves_failed_status(self, tmp_path: Path, monkeypatch):
        """Worker thread completing pipeline cannot overwrite status if shutdown already occurred."""
        import threading
        from aegis_core.verification.jobs import submit_verification_job
        from aegis_core.verification import runner

        started_evt = threading.Event()
        proceed_evt = threading.Event()

        def synchronized_run_layer1(*args, **kwargs):
            started_evt.set()
            proceed_evt.wait(timeout=2.0)
            return []

        monkeypatch.setattr(runner, "run_layer1", synchronized_run_layer1)

        job = submit_verification_job(workspace=str(tmp_path), files=[], layer1_only=True)
        assert started_evt.wait(timeout=2.0)

        # Worker is now actively running the pipeline
        shutdown_verification_engine(grace_period=0.1)
        proceed_evt.set()

        # Wait for worker thread to complete
        for _ in range(50):
            time.sleep(0.05)
            j = get_job(job.job_id)
            if j and j.completed_at and j.status != JOB_STATUS_RUNNING:
                break

        updated = get_job(job.job_id)
        assert updated is not None
        assert updated.status == JOB_STATUS_FAILED
        assert "server_shutdown" in (updated.error or "")

    def test_restore_in_flight_jobs_transitions_to_failed(self, tmp_path: Path):
        """Restoring persisted jobs that were queued or running must mark them failed to prevent infinite hangs."""
        from aegis_core.verification.jobs import _JOBS, _JOBS_LOCK
        soma_dir = tmp_path / ".soma"
        soma_dir.mkdir(parents=True, exist_ok=True)
        state_file = soma_dir / "jobs_state.json"

        # Simulate state saved by a process before it was killed
        state_file.write_text(
            json.dumps({
                "job-interrupted-1": {
                    "job_id": "job-interrupted-1",
                    "status": "QUEUED",
                    "created_at": "2026-10-05T12:00:00Z",
                    "workspace": str(tmp_path),
                },
                "job-interrupted-2": {
                    "job_id": "job-interrupted-2",
                    "status": "RUNNING",
                    "created_at": "2026-10-05T12:00:01Z",
                    "workspace": str(tmp_path),
                },
            }),
            encoding="utf-8",
        )

        with _JOBS_LOCK:
            _JOBS.pop("job-interrupted-1", None)
            _JOBS.pop("job-interrupted-2", None)

        restored = restore_jobs_state(str(tmp_path))
        j1 = next(j for j in restored if j.job_id == "job-interrupted-1")
        j2 = next(j for j in restored if j.job_id == "job-interrupted-2")

        assert j1.status == JOB_STATUS_FAILED
        assert "interrupted" in (j1.error or "")
        assert j2.status == JOB_STATUS_FAILED
        assert "interrupted" in (j2.error or "")

    def test_canonical_module_cohesion_paths(self):
        """Verify verification_jobs moved to aegis_core/verification/jobs.py and arbitration renamed to aegis_core/proposals.py."""
        from aegis_core.verification import jobs as v_jobs
        from aegis_core import proposals

        assert hasattr(v_jobs, "submit_verification_job")
        assert hasattr(proposals, "TTCVerifier")
        assert hasattr(proposals, "aegis_propose_change")

        repo_root = Path(__file__).resolve().parents[3]
        assert (repo_root / "aegis_core" / "verification" / "jobs.py").is_file()
        assert (repo_root / "aegis_core" / "proposals.py").is_file()
        assert not (repo_root / "aegis_core" / "verification_jobs.py").exists()
        assert not (repo_root / "aegis_core" / "arbitration.py").exists()



