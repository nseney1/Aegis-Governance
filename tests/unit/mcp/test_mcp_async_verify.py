"""Tests for Asynchronous MCP Layer 2 Verification and Polling (Phase 3).

Verifies:
1. Tool definition registration with m8ven metadata (readOnlyHint).
2. VerificationJob thread-safe store and lifecycle states.
3. soma_verify_changes async_mode execution returning job receipts.
4. soma_poll_verification polling, error handling, and completion responses.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from aegis_core.verification.jobs import (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    clear_all_jobs,
    create_job,
    get_job,
    list_jobs,
    submit_verification_job,
)
from aegis_mcp.server import _READ_TOOLS
from aegis_mcp.tools import TOOL_DEFINITIONS, execute_tool


@pytest.fixture(autouse=True)
def _reset_jobs():
    clear_all_jobs()
    yield
    clear_all_jobs()


class TestAsyncVerificationToolDefinitions:
    """Verify tool metadata, schemas, and m8ven hints."""

    def test_soma_poll_verification_registered(self):
        tool = next((t for t in TOOL_DEFINITIONS if t["name"] == "soma_poll_verification"), None)
        assert tool is not None, "soma_poll_verification must be registered in TOOL_DEFINITIONS"
        assert tool["annotations"]["readOnlyHint"] is True
        assert "job_id" in tool["inputSchema"]["properties"]
        assert "job_id" in tool["inputSchema"]["required"]

    def test_soma_verify_changes_has_async_mode(self):
        tool = next((t for t in TOOL_DEFINITIONS if t["name"] == "soma_verify_changes"), None)
        assert tool is not None, "soma_verify_changes must be registered in TOOL_DEFINITIONS"
        props = tool["inputSchema"]["properties"]
        assert "async_mode" in props
        assert props["async_mode"]["type"] == "boolean"

    def test_poll_tool_is_read_tool_in_server(self):
        assert "soma_poll_verification" in _READ_TOOLS, "soma_poll_verification must be in _READ_TOOLS"


class TestVerificationJobStore:
    """Verify thread-safe job store operations."""

    def test_create_and_get_job(self, tmp_path: Path):
        job = create_job(workspace=str(tmp_path), files=["app.py"], layer1_only=True)
        assert job.job_id.startswith("vjob_")
        assert job.status == JOB_STATUS_QUEUED
        assert job.workspace == str(tmp_path)
        assert job.files == ["app.py"]

        fetched = get_job(job.job_id)
        assert fetched is not None
        assert fetched.job_id == job.job_id

    def test_list_jobs(self, tmp_path: Path):
        j1 = create_job(workspace=str(tmp_path), files=["a.py"])
        j2 = create_job(workspace=str(tmp_path), files=["b.py"])
        all_jobs = list_jobs()
        assert len(all_jobs) == 2
        ids = {j.job_id for j in all_jobs}
        assert j1.job_id in ids and j2.job_id in ids

    def test_submit_verification_job_runs_background_thread(self, tmp_path: Path):
        job = submit_verification_job(workspace=str(tmp_path), files=[], layer1_only=True)
        assert job.job_id.startswith("vjob_")

        # Wait for worker thread to complete
        timeout = 5.0
        start = time.time()
        while time.time() - start < timeout:
            current = get_job(job.job_id)
            if current and current.status in (JOB_STATUS_COMPLETED, JOB_STATUS_FAILED):
                break
            time.sleep(0.05)

        finished = get_job(job.job_id)
        assert finished is not None
        assert finished.status == JOB_STATUS_COMPLETED
        assert finished.result is not None
        assert finished.completed_at is not None


class TestMcpAsyncExecutionAndPolling:
    """Verify end-to-end execution of async verification and polling tools."""

    def test_async_verify_and_poll_flow(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AEGIS_WORKSPACE", str(tmp_path))
        # Create minimal cell structure so workspace passes
        (tmp_path / ".aegis" / "rules").mkdir(parents=True)

        # 1. Enqueue job via soma_verify_changes
        res_queue = execute_tool(
            "soma_verify_changes",
            {
                "workspace": str(tmp_path),
                "files": [],
                "async_mode": True,
                "layer1_only": True,
                "receipt": "mock-receipt-123",
            },
        )
        assert res_queue.get("status") == "QUEUED"
        job_id = res_queue.get("job_id")
        assert job_id is not None
        assert "message" in res_queue

        # 2. Poll job status
        timeout = 5.0
        start = time.time()
        completed = False
        res_poll = None

        while time.time() - start < timeout:
            res_poll = execute_tool("soma_poll_verification", {"job_id": job_id})
            if res_poll.get("status") == "COMPLETED":
                completed = True
                break
            time.sleep(0.05)

        assert completed is True, f"Job did not complete within {timeout}s: {res_poll}"
        assert res_poll is not None
        assert res_poll["status"] == "COMPLETED"
        assert res_poll["job_id"] == job_id
        assert "result" in res_poll
        assert "evidence" in res_poll["result"]
        assert res_poll.get("receipt") == "mock-receipt-123"

    def test_poll_unknown_job_id(self):
        res = execute_tool("soma_poll_verification", {"job_id": "vjob_nonexistent"})
        assert res.get("status") == "FAIL"
        assert "not found" in res.get("error", "").lower()

    def test_poll_missing_job_id_argument(self):
        res = execute_tool("soma_poll_verification", {})
        assert res.get("status") == "FAIL"
        assert "missing required argument" in res.get("error", "").lower()

    def test_sync_mode_still_works_as_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AEGIS_WORKSPACE", str(tmp_path))
        (tmp_path / ".aegis" / "rules").mkdir(parents=True)

        res = execute_tool(
            "soma_verify_changes",
            {
                "workspace": str(tmp_path),
                "files": [],
                "layer1_only": True,
                "receipt": "mock-receipt-sync",
            },
        )
        # Synchronous execution returns immediate PASS/FAIL status, not QUEUED
        assert res.get("status") in ("PASS", "FAIL")
        assert "evidence" in res
        assert "job_id" not in res

    def test_layer2_fails_closed_when_missing_plan(self, tmp_path: Path):
        job = submit_verification_job(
            workspace=str(tmp_path),
            files=[],
            layer1_only=False,
            task_plan="",
        )
        timeout = 5.0
        start = time.time()
        while time.time() - start < timeout:
            current = get_job(job.job_id)
            if current and current.status in (JOB_STATUS_COMPLETED, JOB_STATUS_FAILED):
                break
            time.sleep(0.05)

        finished = get_job(job.job_id)
        assert finished is not None
        assert finished.status == JOB_STATUS_COMPLETED
        assert finished.result is not None
        assert finished.result["status"] == "FAIL"
        assert "missing" in finished.result.get("layer2_error", "").lower()

    def test_max_jobs_prunes_oldest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from aegis_core.verification import jobs as verification_jobs
        monkeypatch.setattr(verification_jobs, "MAX_JOBS", 5)
        created_ids = []
        for i in range(7):
            j = create_job(workspace=str(tmp_path), files=[f"file_{i}.py"])
            created_ids.append(j.job_id)

        all_current = list_jobs()
        assert len(all_current) <= 5
        # Oldest job id should be evicted
        assert get_job(created_ids[0]) is None

    def test_poll_verification_bogus_job_id_does_not_exhaust_rate_limit(self):
        """C-03: Repeated bogus job_ids must roll back rate limit and not lock out legitimate callers."""
        from aegis_mcp.server import handle_request
        import aegis_mcp.server as s_mod

        # Reset rate limit counter for poll tool
        s_mod._tool_call_times["soma_poll_verification"].clear()

        # Initialize server session
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"capabilities": {}}
        }
        handle_request(init_req)

        # Flood 70 requests with non-existent job_ids (rate limit is 60/60s)
        for i in range(70):
            req = {
                "jsonrpc": "2.0",
                "id": 100 + i,
                "method": "tools/call",
                "params": {
                    "name": "soma_poll_verification",
                    "arguments": {"job_id": f"bogus-job-{i}"}
                }
            }
            res = handle_request(req)
            assert "error" in res
            assert res["error"]["code"] == -32602, f"Expected -32602 invalid job_id, got {res}"
            assert "not found" in res["error"]["message"].lower()

        # Legitimate job can still be polled without hitting rate limit
        real_job = create_job(workspace="/tmp", files=[])
        real_req = {
            "jsonrpc": "2.0",
            "id": 999,
            "method": "tools/call",
            "params": {
                "name": "soma_poll_verification",
                "arguments": {"job_id": real_job.job_id}
            }
        }
        real_res = handle_request(real_req)
        assert "result" in real_res, f"Expected successful poll result, got {real_res}"
