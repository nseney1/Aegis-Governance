"""aegis_scan over MCP serves the reviewed BASE versions of rank 2+ rules (v4.3 spec T3, section 9
"Local edits don't bind") and keeps mandatory rules to two slots.

The acceptance contract drives aegis_core.scan directly; these cases go through the MCP tool
dispatcher (execute_tool), so the projection and rendering layers cannot drop or rewrite what
the scan established.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from aegis_core import scan as scan_mod
from aegis_mcp.registry import TOOL_DEFINITIONS
from aegis_mcp.tools import execute_tool
from tests import helpers_humangate as hg

needs_git = pytest.mark.skipif(not hg.git_ok(), reason="needs git")

INVARIANT = ".aegis/rules/invariants/inv-sample.md"


def _rule(rid: str, rtype: str, hypothesis: str, paths: str = "src/*.py", enforcement: str = "advisory") -> str:
    return (f"---\nid: {rid}\ntype: {rtype}\nenforcement: {enforcement}\nhypothesis: {hypothesis}\n"
            f"target_paths:\n  - '{paths}'\n---\n# {rid} title\n\nA body long enough to be a rule body.\n")


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    scan_mod.RULE_CACHE.invalidate()
    yield
    scan_mod.RULE_CACHE.invalidate()


def make_repo(tmp_path: Path) -> hg.Repo:
    repo = hg.Repo(tmp_path / "project", hg.Home(tmp_path / "home"))
    repo.write("src/app.py", "x = 1\n")
    repo.write(INVARIANT, _rule("inv-sample", "invariant", "Never do the thing"))
    repo.commit("base")
    repo.git("update-ref", "refs/remotes/origin/main", "HEAD")
    repo.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    repo.branch("work")
    return repo


def mcp_scan(repo: hg.Repo, **extra: object) -> dict:
    scan_mod.RULE_CACHE.invalidate()
    return execute_tool("aegis_scan", {"workspace": str(repo.root), "files": ["src/app.py"], **extra})


@needs_git
def test_over_mcp_a_branch_local_edit_does_not_bind_and_is_listed(tmp_path):
    repo = make_repo(tmp_path)
    repo.write(INVARIANT, _rule("inv-sample", "invariant", "Anything goes now"))
    result = mcp_scan(repo)
    assert "Never do the thing" in result["guidance"] and "Anything goes now" not in result["guidance"]
    assert result["unreviewed_rules"] == [{"id": "inv-sample", "title": "inv-sample title", "change": "changed"}]
    assert result["rules_base"]["witnessed"] is True


@needs_git
def test_over_mcp_the_ids_view_still_names_the_unreviewed_rules(tmp_path):
    repo = make_repo(tmp_path)
    repo.write(INVARIANT, _rule("inv-sample", "invariant", "Anything goes now"))
    ids = mcp_scan(repo, view="ids")
    assert ids["unreviewed_rules"] == ["inv-sample"]
    assert "inv-sample" in ids["relevant_rules"]


@needs_git
def test_over_mcp_a_new_local_gate_is_never_served(tmp_path):
    repo = make_repo(tmp_path)
    repo.write(".aegis/rules/gates/gate-new.md", _rule("gate-new", "gate", "Self-declared gate", enforcement="gate"))
    result = mcp_scan(repo)
    assert "gate-new" not in [r["name"] for r in result["relevant_rules"]]
    assert [(u["id"], u["change"]) for u in result["unreviewed_rules"]] == [("gate-new", "new")]


@needs_git
def test_over_mcp_mandatory_rules_take_at_most_two_slots(tmp_path):
    repo = make_repo(tmp_path)
    for rid in ("inv-b", "inv-c"):
        repo.write(f".aegis/rules/invariants/{rid}.md", _rule(rid, "invariant", f"{rid} says so", paths="**"))
    repo.write(".aegis/rules/traps/trap-a.md", _rule("trap-a", "trap", "An advisory trap"))
    repo.commit("three mandatory rules reach src/app.py")
    repo.git("update-ref", "refs/remotes/origin/main", "HEAD")
    result = mcp_scan(repo)
    served = [r for r in result["relevant_rules"] if r["type"] == "invariant"]
    assert len(served) == 2
    assert [o["reason"] for o in result["omitted_mandatory"]] == ["slot_cap"]
    assert "trap-a" in [r["name"] for r in result["relevant_rules"]]


def test_the_tool_description_tells_the_agent_its_edits_do_not_bind():
    (scan_tool,) = [t for t in TOOL_DEFINITIONS if t["name"] == "aegis_scan"]
    assert "unreviewed_rules" in scan_tool["description"]
    assert "at most two slots" in scan_tool["description"]


def test_outside_git_nothing_is_anchored(tmp_path):
    root = tmp_path / "plain"
    (root / "src").mkdir(parents=True)
    (root / "src/app.py").write_text("x = 1\n", encoding="utf-8")
    target = root / INVARIANT
    target.parent.mkdir(parents=True)
    target.write_text(_rule("inv-sample", "invariant", "Never do the thing"), encoding="utf-8")
    result = execute_tool("aegis_scan", {"workspace": str(root), "files": ["src/app.py"]})
    assert "unreviewed_rules" not in result and "rules_base" not in result
    assert os.path.isdir(root)
