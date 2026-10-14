"""Unit and behavioral tests for the Horizontal Skill Graph and Swarm Handoff system."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import subprocess
import pytest

from aegis_core.errors import HandoffAuthorizationError, InvalidHandoffPayloadError, AegisValidationError
from aegis_core.schemas.artifacts import (
    ArtifactEnvelope,
    ArtifactRegistry,
    ChargeSheet,
    DiffProposal,
    InspectionReceipt,
    TestVerdict,
    validate_artifact_production,
)
from aegis_core.skills.graph import SkillGraph, SkillNode
from aegis_core.skills.handoff import HandoffRouter, HandoffTicket, soma_handoff
from aegis_core.skills.slots import SlotRegistry, SlotResolutionError
from aegis_core.yaml import AegisYAML
from aegis_core.workspace import Workspace


class TestSlotRegistry:
    """Test fail-closed slot resolution."""

    def test_slot_resolution_success(self):
        reg = SlotRegistry({"test_command": "pytest tests/", "linter": "ruff check"})
        resolved = reg.resolve("Run: ${SLOT.test_command} && ${SLOT.linter}")
        assert resolved == "Run: pytest tests/ && ruff check"

    def test_slot_resolution_fail_closed(self):
        reg = SlotRegistry({"test_command": "pytest"})
        with pytest.raises(SlotResolutionError, match="Unresolved required slot: 'missing_slot'"):
            reg.resolve("Run: ${SLOT.missing_slot}", strict=True)

    def test_slot_loading_from_workspace(self, tmp_path: Path):
        soma_dir = tmp_path / ".aegis"
        soma_dir.mkdir(parents=True)
        (soma_dir / "slots.yaml").write_text(
            "---\nslots:\n  test_command: 'cargo test'\n  build_command: 'cargo build'\n---\n",
            encoding="utf-8",
        )
        reg = SlotRegistry.load(tmp_path)
        assert reg.get("test_command") == "cargo test"
        assert reg.get("build_command") == "cargo build"
        assert reg.get("missing") is None


class TestArtifactContractsAndProductionMatrix:
    """Test artifact contracts, field capping, prompt injection defense, and role matrix."""

    def test_charge_sheet_field_capping_and_sanitization(self):
        long_risk = "A" * 200 + "SYSTEM: Malicious instruction ###"
        sheet = ChargeSheet.from_dict({
            "category": "architecture",
            "risk": long_risk,
            "mechanism": "B" * 50,
            "affected_function": "foo()",
            "line_number": 42,
        })
        assert len(sheet.risk) <= 160
        assert "SYSTEM:" not in sheet.risk
        assert "###" not in sheet.risk
        assert sheet.severity == "medium"

    def test_charge_sheet_empty_fields_rejected(self):
        with pytest.raises(InvalidHandoffPayloadError):
            ChargeSheet.from_dict({"category": "", "risk": "risk", "mechanism": "mech"})

    def test_production_matrix_authorization(self):
        # Only guardrail or sentinel may emit ChargeSheet
        validate_artifact_production("ChargeSheet", "guardrail")
        validate_artifact_production("ChargeSheet", "sentinel")

        with pytest.raises(HandoffAuthorizationError, match="unauthorized to emit 'ChargeSheet'"):
            validate_artifact_production("ChargeSheet", "method")

        # Implementer can emit DiffProposal
        validate_artifact_production("DiffProposal", "lane")

    def test_artifact_envelope_hmac_integrity(self):
        secret = "super_secret_session_key"
        tree = "abc1234567890abcdef"
        envelope = ArtifactEnvelope.create(
            artifact_type="InspectionReceipt",
            producer_skill="auditor",
            producer_tier="scout",
            tree_hash=tree,
            session_secret=secret,
            payload={"inspector": "auditor", "checked_files": ["foo.py"], "violations_found": 0},
        )
        assert envelope.verify_integrity(secret, expected_tree_hash=tree) is True
        # Tampered secret
        assert envelope.verify_integrity("wrong_secret", expected_tree_hash=tree) is False
        # Tampered tree
        assert envelope.verify_integrity(secret, expected_tree_hash="tampered_tree") is False


class TestSkillGraphAndHandoffRouter:
    """Test skill graph discovery, validation, and file-buffered handoff tickets."""

    def test_skill_discovery_and_routing(self, tmp_path: Path):
        skills_dir = tmp_path / ".aegis" / "skills"
        skills_dir.mkdir(parents=True)

        spec_skill = skills_dir / "spec_scout.md"
        spec_skill.write_text(
            "---\nid: spec_scout\ntier: scout\nproduces: [ChargeSheet]\nhandoff_targets: [fixer_lane]\n---\n# Spec Scout Instructions\n",
            encoding="utf-8",
        )

        fixer_skill = skills_dir / "fixer_lane.md"
        fixer_skill.write_text(
            "---\nid: fixer_lane\ntier: lane\nconsumes: [ChargeSheet]\nproduces: [DiffProposal]\n---\n# Fixer Lane Instructions\n",
            encoding="utf-8",
        )

        graph = SkillGraph.discover([skills_dir])
        assert len(graph) == 2
        assert "spec_scout" in graph
        assert "fixer_lane" in graph

        node = graph["spec_scout"]
        assert node.load_instructions() == "# Spec Scout Instructions"
        assert node.decay is False

        # Validate legal path
        graph.validate_handoff_path("spec_scout", "fixer_lane", "ChargeSheet")

        # Validate illegal target
        with pytest.raises(AegisValidationError, match="cannot handoff to 'unknown'"):
            graph.validate_handoff_path("spec_scout", "unknown", "ChargeSheet")

    def test_file_buffered_soma_handoff(self, tmp_path: Path):
        ws = Workspace(tmp_path)
        ws.scaffold()

        skills_dir = tmp_path / ".aegis" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "guardian.md").write_text(
            "---\nid: guardian\ntier: guardrail\nproduces: [ChargeSheet]\nhandoff_targets: [worker]\n---\n",
            encoding="utf-8",
        )
        (skills_dir / "worker.md").write_text(
            "---\nid: worker\ntier: lane\nconsumes: [ChargeSheet]\n---\n",
            encoding="utf-8",
        )

        ticket = soma_handoff(
            workspace=ws,
            from_skill="guardian",
            to_skill="worker",
            artifact_type="ChargeSheet",
            payload={
                "category": "security",
                "risk": "Buffer overflow risk",
                "mechanism": "Unbounded read",
                "affected_function": "parse()",
            },
        )

        assert isinstance(ticket, HandoffTicket)
        assert ticket.producer_skill == "guardian"
        assert ticket.target_skill == "worker"
        assert Path(ticket.file_path).exists()

        # Verify envelope contents on disk
        stored = json.loads(Path(ticket.file_path).read_text(encoding="utf-8"))
        assert stored["artifact_type"] == "ChargeSheet"
        assert stored["payload"]["risk"] == "Buffer overflow risk"

        # Verify disk telemetry
        telemetry_file = tmp_path / ".aegis" / "telemetry" / "skills.jsonl"
        assert telemetry_file.exists()
        telemetry_lines = telemetry_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(telemetry_lines) == 1
        entry = json.loads(telemetry_lines[0])
        assert entry["event"] == "handoff"
        assert entry["from_skill"] == "guardian"

        # Verify minimal prompt block
        block = ticket.format_prompt_block()
        assert "<!-- AEGIS_HANDOFF_TICKET -->" in block
        assert len(block.split()) < 50  # Well under 150 tokens!

    def test_cli_skill_and_handoff_commands(self, tmp_path: Path, monkeypatch, capsys):
        import argparse
        from aegis_cli.skills import run_skill, run_handoff
        monkeypatch.chdir(tmp_path)
        ws = Workspace(tmp_path)
        ws.scaffold()
        skills_dir = tmp_path / ".aegis" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "scout.md").write_text(
            "---\nid: scout\ntier: guardrail\nproduces: [Finding]\nhandoff_targets: [fixer]\n---\n",
            encoding="utf-8",
        )
        (skills_dir / "fixer.md").write_text(
            "---\nid: fixer\ntier: lane\nconsumes: [Finding]\n---\n",
            encoding="utf-8",
        )

        # Test skill list
        args_skill = argparse.Namespace(skill_action="list", ws=ws, json=True)
        rc = run_skill(args_skill)
        assert rc == 0
        out = capsys.readouterr().out
        assert "scout" in out

        # Test handoff
        args_handoff = argparse.Namespace(
            ws=ws,
            from_skill="scout",
            to_skill="fixer",
            artifact="Finding",
            payload='{"issue": "test"}',
            cycle_id=None,
            json=False,
        )
        rc = run_handoff(args_handoff)
        assert rc == 0
        out = capsys.readouterr().out
        assert "AEGIS_HANDOFF_TICKET" in out


class TestArtifactsAndSkillsBranchHardening:
    """Comprehensive branch and mutation hardening for artifacts, skills, handoff, and slots."""

    def test_chargesheet_and_receipt_validation_branches(self):
        # ChargeSheet empty risk / mechanism
        with pytest.raises(InvalidHandoffPayloadError, match="risk"):
            ChargeSheet(category="cat", risk="", mechanism="mech")
        with pytest.raises(InvalidHandoffPayloadError, match="mechanism"):
            ChargeSheet(category="cat", risk="risk", mechanism="")

        # Non-mapping
        with pytest.raises(InvalidHandoffPayloadError, match="mapping"):
            ChargeSheet.from_dict("not-a-dict")  # type: ignore
        with pytest.raises(InvalidHandoffPayloadError, match="Missing required field"):
            ChargeSheet.from_dict({"category": "c"})

        cs = ChargeSheet.from_dict({
            "category": "cat",
            "risk": "r",
            "mechanism": "m",
            "affected_function": "fn",
            "line_number": 42,
            "severity": "high",
        })
        d = cs.to_dict()
        assert d == {
            "category": "cat",
            "risk": "r",
            "mechanism": "m",
            "affected_function": "fn",
            "line_number": 42,
            "severity": "high",
        }

        # InspectionReceipt validation
        with pytest.raises(InvalidHandoffPayloadError, match="mapping"):
            InspectionReceipt.from_dict([1, 2, 3])  # type: ignore
        with pytest.raises(InvalidHandoffPayloadError, match="inspector"):
            InspectionReceipt.from_dict({})

        ir = InspectionReceipt.from_dict({
            "inspector": "linter",
            "checked_files": ["a.py"],
            "violations_found": 1,
            "passed": False,
            "details": ["err"],
        })
        ir_dict = ir.to_dict()
        assert ir_dict["inspector"] == "linter"
        assert ir_dict["checked_files"] == ["a.py"]
        assert ir_dict["violations_found"] == 1
        assert ir_dict["passed"] is False
        assert ir_dict["details"] == ["err"]

        # DiffProposal validation
        with pytest.raises(InvalidHandoffPayloadError, match="mapping"):
            DiffProposal.from_dict("invalid")  # type: ignore
        with pytest.raises(InvalidHandoffPayloadError, match="summary"):
            DiffProposal.from_dict({})

        dp = DiffProposal.from_dict({"summary": "sum", "proposed_files": ["b.py"], "risk_tier": "low"})
        dp_dict = dp.to_dict()
        assert dp_dict == {"summary": "sum", "proposed_files": ["b.py"], "risk_tier": "low"}

        # TestVerdict validation
        with pytest.raises(InvalidHandoffPayloadError, match="mapping"):
            TestVerdict.from_dict("bad")  # type: ignore
        with pytest.raises(InvalidHandoffPayloadError, match="test_suite"):
            TestVerdict.from_dict({})

        tv = TestVerdict.from_dict({
            "test_suite": "pytest",
            "passed": 10,
            "failed": 0,
            "skipped": 1,
            "execution_time_seconds": 1.5,
        })
        tv_dict = tv.to_dict()
        assert tv_dict["test_suite"] == "pytest"
        assert tv_dict["passed"] == 10
        assert tv_dict["failed"] == 0
        assert tv_dict["skipped"] == 1
        assert tv_dict["duration_ms"] == 0.0

    def test_artifact_registry_and_envelope(self):
        # Register custom schema
        class CustomArtifact:
            @classmethod
            def from_dict(cls, d):
                return cls()
            def to_dict(self):
                return {"custom": True}

        ArtifactRegistry.register("Custom", CustomArtifact)
        assert ArtifactRegistry.validate("Custom", {}) == {"custom": True}

        # Unregistered
        assert ArtifactRegistry.validate("Unknown", {"x": 1}) == {"x": 1}
        with pytest.raises(InvalidHandoffPayloadError):
            ArtifactRegistry.validate("Unknown", "non-dict")

        # ArtifactEnvelope
        env = ArtifactEnvelope(
            artifact_type="ChargeSheet",
            producer_skill="sec",
            producer_tier="orchestrator",
            tree_hash="abc",
            session_hmac="hmac",
            payload={"category": "sec", "risk": "r", "mechanism": "m"},
            timestamp="2026-01-01",
        )
        env_dict = env.to_dict()
        assert env_dict["producer_skill"] == "sec"
        assert env_dict["producer_tier"] == "orchestrator"
        assert env_dict["tree_hash"] == "abc"
        assert env_dict["session_hmac"] == "hmac"
        assert env_dict["timestamp"] == "2026-01-01"

        from_env = ArtifactEnvelope.from_dict(env_dict)
        assert from_env.producer_skill == "sec"
        assert from_env.verify_integrity("wrong_secret") is False
        assert from_env.verify_integrity("wrong_secret", expected_tree_hash="mismatch") is False

    def test_skill_node_and_graph(self, tmp_path: Path):
        node = SkillNode(
            id="builder",
            tier="lane",
            consumes=("DiffProposal",),
            produces=("TestVerdict",),
            handoff_targets=("tester",),
            instructions_file=None,
            decay=True,
            description="Builds code",
            slot_constraints={"test_cmd": "pytest"},
        )
        assert node.load_instructions() == ""

        # Nonexistent instructions file
        node_bad_file = SkillNode(id="b", instructions_file=str(tmp_path / "missing.md"))
        assert node_bad_file.load_instructions() == ""

        # Existing instructions file
        instr_file = tmp_path / "instr.md"
        instr_file.write_text("---\nid: b\n---\n# Instructions Body", encoding="utf-8")
        node_good = SkillNode(id="b", instructions_file=str(instr_file))
        assert node_good.load_instructions() == "# Instructions Body"

        nd = node.to_dict()
        assert nd["id"] == "builder"
        assert nd["tier"] == "lane"
        assert nd["consumes"] == ["DiffProposal"]
        assert nd["produces"] == ["TestVerdict"]
        assert nd["handoff_targets"] == ["tester"]
        assert nd["decay"] is True
        assert nd["description"] == "Builds code"
        assert nd["slot_constraints"] == {"test_cmd": "pytest"}

        # Graph operations
        graph = SkillGraph({"builder": node})
        assert len(graph) == 1
        assert "builder" in list(iter(graph))
        assert graph["builder"].id == "builder"
        assert graph.get("builder").id == "builder"
        assert graph.get("nonexistent") is None
        assert graph.get_downstream("nonexistent") == []
        assert graph.get_downstream("builder") == []  # "tester" not in graph

        tester_node = SkillNode(id="tester", consumes=("TestVerdict",))
        graph2 = SkillGraph({"builder": node, "tester": tester_node})
        assert len(graph2.get_downstream("builder")) == 1
        assert graph2.get_downstream("builder")[0].id == "tester"

        # validate_handoff_path errors
        with pytest.raises(AegisValidationError, match="does not produce"):
            graph2.validate_handoff_path("builder", "tester", "WrongArtifact")

        with pytest.raises(AegisValidationError, match="cannot handoff to"):
            graph2.validate_handoff_path("builder", "other", "TestVerdict")

        with pytest.raises(AegisValidationError, match="does not consume"):
            other_tester = SkillNode(id="other_tester", consumes=("ChargeSheet",))
            graph3 = SkillGraph({"builder": SkillNode(id="builder", produces=("TestVerdict",), handoff_targets=("other_tester",)), "other_tester": other_tester})
            graph3.validate_handoff_path("builder", "other_tester", "TestVerdict")

        # SkillGraph.discover with file, dir, and malformed file
        dir_skills = tmp_path / "skills_discovery"
        dir_skills.mkdir()
        (dir_skills / "README.md").write_text("# Readme", encoding="utf-8")
        (dir_skills / "valid.md").write_text("---\nid: disc1\ntier: organ\n---\nBody", encoding="utf-8")
        (dir_skills / "malformed.md").write_text("invalid : : yaml [", encoding="utf-8")
        single_file = tmp_path / "single_skill.md"
        single_file.write_text("---\nid: disc2\ntier: organ\n---\nBody", encoding="utf-8")

        disc_graph = SkillGraph.discover([str(dir_skills), str(single_file), str(tmp_path / "nonexistent_dir")])
        assert "disc1" in disc_graph
        assert "disc2" in disc_graph

    def test_handoff_ticket_and_router(self, tmp_path: Path, monkeypatch):
        ticket = HandoffTicket(
            ticket_id="ticket-123",
            artifact_type="ChargeSheet",
            producer_skill="auditor",
            target_skill="fixer",
            file_path="/path/ticket.json",
            tree_hash="tree-abc",
            session_hmac="hmac-123456789012345",
            summary="A" * 200,
            created_at="2026-01-01T00:00:00Z",
        )
        td = ticket.to_dict()
        assert td == {
            "ticket_id": "ticket-123",
            "artifact_type": "ChargeSheet",
            "producer_skill": "auditor",
            "target_skill": "fixer",
            "file_path": "/path/ticket.json",
            "tree_hash": "tree-abc",
            "session_hmac": "hmac-123456789012345",
            "summary": "A" * 200,
            "created_at": "2026-01-01T00:00:00Z",
        }

        block = ticket.format_prompt_block()
        assert "ticket-123" in block
        assert "ChargeSheet" in block
        assert "auditor" in block
        assert "fixer" in block
        assert "tree-abc" in block
        assert "hmac-1234567" in block
        assert "A" * 100 in block

        # _get_tree_hash returncode == 0
        from aegis_core.skills.handoff import _get_tree_hash
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess([], 0, stdout="treehash12345\n"))
        assert _get_tree_hash(tmp_path) == "treehash12345"

        # _get_tree_hash fallback on failure
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess([], 1))
        assert _get_tree_hash(tmp_path) == "0000000000000000000000000000000000000000"
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        assert _get_tree_hash(tmp_path) == "0000000000000000000000000000000000000000"

        # ArtifactRegistry dataclass without from_dict branch and failure
        @dataclass
        class CustomRawItem:
            val: str
        ArtifactRegistry.register("CustomRawItem", CustomRawItem)
        assert ArtifactRegistry.validate("CustomRawItem", CustomRawItem(val="ok")) == {"val": "ok"}
        with pytest.raises(InvalidHandoffPayloadError, match="Cannot validate payload"):
            ArtifactRegistry.validate("CustomRawItem", "invalid_type")

        # HandoffRouter payload string parsing (json and plain string) and summary truncation
        skills_dir = tmp_path / ".aegis" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "a.md").write_text("---\nid: a\ntier: sentinel\nproduces: [ChargeSheet]\nhandoff_targets: [b]\n---\n", encoding="utf-8")
        (skills_dir / "b.md").write_text("---\nid: b\nconsumes: [ChargeSheet, DiffProposal]\n---\n", encoding="utf-8")
        (skills_dir / "c.md").write_text("---\nid: c\ntier: method\nproduces: [DiffProposal]\nhandoff_targets: [b]\n---\n", encoding="utf-8")
        (skills_dir / "corrupted.md").write_text("---\nid: [unclosed\n---\n", encoding="utf-8")

        # discover handles corrupted doc gracefully
        g = SkillGraph.discover([skills_dir])
        assert "a" in g._nodes
        assert "c" in g._nodes

        res_ticket = HandoffRouter.execute_handoff(
            workspace=str(tmp_path),
            from_skill="a",
            to_skill="b",
            artifact_type="ChargeSheet",
            payload='{"category": "cat", "risk": "long risk ' + ('x' * 200) + '", "mechanism": "mech"}',
        )
        assert res_ticket.summary.endswith("...")
        assert len(res_ticket.summary) == 160

        # Non-json string payload fallback to {"summary": payload}
        res_ticket2 = HandoffRouter.execute_handoff(
            workspace=str(tmp_path),
            from_skill="c",
            to_skill="b",
            artifact_type="DiffProposal",
            payload="plain text non-json summary",
        )
        assert res_ticket2.artifact_type == "DiffProposal"

    def test_slot_registry_branches(self, tmp_path: Path):
        # Nonexistent file returns empty
        reg = SlotRegistry.load(tmp_path)
        assert reg.to_dict() == {}

        # Invalid yaml syntax raises SlotResolutionError
        soma_dir = tmp_path / ".aegis"
        soma_dir.mkdir(parents=True, exist_ok=True)
        (soma_dir / "slots.yaml").write_text("a: [unclosed", encoding="utf-8")
        with pytest.raises(SlotResolutionError, match="Failed to parse"):
            SlotRegistry.load(tmp_path)

        # slots not a mapping
        (soma_dir / "slots.yaml").write_text("---\nslots: 'not-a-map'\n---\n", encoding="utf-8")
        assert SlotRegistry.load(tmp_path).to_dict() == {}

        # resolve with strict=False returns token
        reg2 = SlotRegistry({"existing": "val"})
        assert reg2.resolve("Hello ${existing} and ${missing}", strict=False) == "Hello val and ${missing}"
        assert reg2.to_dict() == {"existing": "val"}

        # resolve default strict=True raises SlotResolutionError when slot is missing
        with pytest.raises(SlotResolutionError, match="Unresolved required slot: 'missing'"):
            reg2.resolve("Hello ${missing}")

    def test_skill_node_from_doc_mutant_kills(self):
        from aegis_core.skills.graph import SkillNode
        from aegis_core.yaml import AegisDocument
        doc = AegisDocument(metadata={"id": "skill-custom", "tier": "specialist", "description": "desc"})
        node = SkillNode.from_doc(doc)
        assert node.tier == "specialist"
        assert node.tier != "method"

    def test_handoff_ticket_format_prompt_block_slice(self):
        from aegis_core.skills.handoff import HandoffTicket
        ticket = HandoffTicket(
            ticket_id="t1",
            artifact_type="diff",
            producer_skill="s1",
            target_skill="s2",
            file_path="/tmp/f.json",
            tree_hash="abcdef123456",
            session_hmac="0123456789abcdef0123456789abcdef",
            summary="sum",
            created_at="now",
        )
        block = ticket.format_prompt_block()
        assert "[HMAC]: 0123456789ab..." in block
        assert "[HMAC]: 0123456789abc..." not in block

    def test_get_ast_driver_branch_coverage_and_mutant_kills(self):
        from aegis_core.skills.slots import SlotRegistry
        reg = SlotRegistry({
            "ast_driver_ts": "node install/drivers/ts_ast.js",
            "ast_driver": "default-runner",
        })
        # .py returns None
        assert reg.get_ast_driver("py") is None
        assert reg.get_ast_driver(".py") is None
        assert reg.get_ast_driver("PY") is None

        # specific extension
        assert reg.get_ast_driver("ts") == "node install/drivers/ts_ast.js"
        assert reg.get_ast_driver(".ts") == "node install/drivers/ts_ast.js"

        # fallback to default ast_driver
        assert reg.get_ast_driver("go") == "default-runner"
        assert reg.get_ast_driver(".go") == "default-runner"

        # empty registry
        empty_reg = SlotRegistry()
        assert empty_reg.get_ast_driver("ts") is None
        assert empty_reg.get_ast_driver("py") is None




