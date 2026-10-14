from pathlib import Path
import json
import os
import pytest
from aegis_mcp.server import handle_request
import aegis_mcp.server as server_module

@pytest.fixture(autouse=True)
def setup_server_globals(monkeypatch, tmp_path):
    workspace = str(tmp_path)
    os.makedirs(os.path.join(workspace, ".soma", "cells"), exist_ok=True)
    monkeypatch.setattr(server_module, "_session_token", "test-session-123")
    monkeypatch.setattr(server_module, "_canonical_workspace", workspace)
    monkeypatch.setattr(server_module, "_execution_enabled", True)
    
    # Expose PYTHONPATH so Governance engine subprocesses can import aegis_sdk
    repo_root = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
    monkeypatch.setenv("PYTHONPATH", repo_root)
    
    # Create a dummy cell so grade/coverage don't fail due to an empty workspace
    vacuoles_dir = os.path.join(workspace, ".soma", "cells", "vacuoles")
    os.makedirs(vacuoles_dir, exist_ok=True)
    with open(os.path.join(vacuoles_dir, "dummy-test-cell.md"), "w", encoding="utf-8") as f:
        f.write("---\nid: dummy-test-cell\ndomain: vacuoles\n---\n# Dummy cell\n")

def _call(name, args=None):
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": args or {}
        }
    }
    return handle_request(req)

def test_soma_grade_executes_real_governance_engine():
    resp = _call("soma_grade")
    assert "error" not in resp, resp.get("error")
    # Should return a valid JSON string with a grade (likely empty/default for empty workspace)
    result_text = resp["result"]["content"][0]["text"]
    data = json.loads(result_text)
    assert "coverage" in data

def test_soma_coverage_executes_real_governance_engine():
    resp = _call("soma_coverage")
    assert "error" not in resp, resp.get("error")
    result_text = resp["result"]["content"][0]["text"]
    data = json.loads(result_text)
    assert "coverage_pct" in data

def test_soma_list_cells_executes_real_governance_engine():
    resp = _call("soma_list_cells")
    assert "error" not in resp, resp.get("error")
    result_text = resp["result"]["content"][0]["text"]
    data = json.loads(result_text)
    assert isinstance(data, list)
