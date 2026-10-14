"""Unit and behavioral tests for MCP response projection and SOMA-V01 security guards."""
from __future__ import annotations

import pytest
from aegis_mcp.projection import DENYLIST, project_response


class TestResponseProjection:
    """Test opt-in view and field projection."""

    def test_full_view_backwards_compatibility(self):
        payload = {
            "id": "cell-1",
            "body": "# Extensive guidance markdown\n" * 100,
            "status": "active",
        }
        res = project_response(payload, view="full")
        assert res == payload

        res_none = project_response(payload, view=None)
        assert res_none == payload

    def test_ids_view_projection(self):
        payload = {
            "cells": [
                {"id": "cell-1", "type": "wall", "body": "text"},
                {"id": "cell-2", "type": "membrane", "body": "text"},
            ],
            "total": 2,
        }
        res = project_response(payload, view="ids")
        assert res == {"cells": ["cell-1", "cell-2"]}

    def test_summary_view_projection(self):
        payload = {
            "id": "run-42",
            "status": "passed",
            "score": 0.95,
            "verbose_logs": "Detailed debug traces line 1\nline 2\n" * 50,
            "cells": [
                {"id": "c1", "status": "survive", "body": "lots of instructions"},
            ],
        }
        res = project_response(payload, view="summary")
        assert res["id"] == "run-42"
        assert res["status"] == "passed"
        assert res["score"] == 0.95
        assert "verbose_logs" not in res
        assert res["cells_count"] == 1
        assert res["cells"][0]["id"] == "c1"
        assert "body" not in res["cells"][0]

    def test_custom_fields_projection(self):
        payload = {
            "cell": {
                "id": "cell-123",
                "meta": {
                    "tier": "guardrail",
                    "secret": "hide_me",
                },
                "instructions": "large markdown body",
            },
            "status": "ok",
        }
        res = project_response(payload, fields=["cell.id", "cell.meta.tier", "status"])
        assert res == {
            "cell": {
                "id": "cell-123",
                "meta": {
                    "tier": "guardrail",
                },
            },
            "status": "ok",
        }

    def test_soma_v01_security_scrubbing(self):
        payload = {
            "id": "audit-1",
            "task_plan": "Sensitive reasoning and internal attack vectors",
            "prompt": "Raw system prompt with instructions",
            "raw_prompt": "Hidden prompt",
            "__class__": "Introspection exploit",
            "verdict": "valid",
        }
        # Even with view='full', denylisted fields must be scrubbed
        res = project_response(payload, view="full")
        assert "task_plan" not in res
        assert "prompt" not in res
        assert "raw_prompt" not in res
        assert "__class__" not in res
        assert res["verdict"] == "valid"

    def test_soma_v01_denied_field_request_rejected(self):
        payload = {
            "id": "audit-1",
            "task_plan": "Sensitive reasoning",
            "status": "ok",
        }
        res = project_response(payload, fields=["id", "task_plan"])
        assert "task_plan" not in res
        assert res == {"id": "audit-1"}

    def test_execute_tool_with_projection(self, tmp_path, monkeypatch):
        from aegis_mcp.tools import execute_tool

        (tmp_path / ".soma" / "cells").mkdir(parents=True, exist_ok=True)
        monkeypatch.chdir(tmp_path)
        # Test audit tool with fields projection
        res = execute_tool(
            "soma_audit_security",
            {
                "proposed_content": "x = 1\n",
                "file_path": "test.py",
                "fields": ["status"],
            },
        )
        assert res == {"status": "PASS"}

    def test_projection_empty_and_all_denied_fields(self):
        res = project_response({"a": 1}, fields=["", "  "])
        assert res == {}
        res2 = project_response({"a": 1}, fields=["task_plan", "prompt"])
        assert res2 == {}
        # Payload with empty string key - empty string in fields must NOT project the empty key
        res3 = project_response({"": "secret_empty", "valid": 123}, fields=["", "valid"])
        assert res3 == {"valid": 123}
        assert "" not in res3
        # Missing dict key covers line 59
        res4 = project_response({"a": 1}, fields=["missing_key", "a.missing_sub"])
        assert res4 == {}

    def test_ids_view_items_with_only_id_or_only_name(self):
        res_id = project_response([{"id": "cell-id-only"}], view="ids")
        assert res_id == ["cell-id-only"]
        res_name = project_response([{"name": "cell-name-only"}], view="ids")
        assert res_name == ["cell-name-only"]
        res_neither = project_response([{"foo": "bar"}], view="ids")
        assert res_neither == ["{'foo': 'bar'}"]

    def test_nested_lookup_lists_and_primitives(self):
        payload = {"items": [{"name": "first"}, {"name": "second"}]}
        res = project_response(payload, fields=["items.0.name", "items.5.name", "items.bad.name", "items.0.name.extra"])
        assert res == {"items": {"0": {"name": "first"}}}

    def test_projection_primitives_and_lists(self):
        assert project_response("hello", view="ids") == "hello"
        assert project_response(123, fields=["a"]) == 123
        assert project_response("unknown", view="nonexistent_view") == "unknown"

        # list with non-dict items in summary
        assert project_response(["string_item", {"id": "c1", "status": "ok"}], view="summary") == ["string_item", {"id": "c1", "status": "ok"}]

        # list with non-dict items in custom fields
        assert project_response(["string_item", {"id": "c1"}], fields=["id"]) == ["string_item", {"id": "c1"}]

        # mapping with single 'id' in ids view
        assert project_response({"id": "only-id"}, view="ids") == {"id": "only-id"}

        # mapping without id or containers in ids view
        assert project_response({"other": 1, "value": 2}, view="ids") == {"keys": ["other", "value"]}


