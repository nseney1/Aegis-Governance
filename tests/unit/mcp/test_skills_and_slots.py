"""Skill graph discovery and the ${SLOT.*} registry used by aegis_scan.

(The swarm handoff router and its typed artifacts were removed in v4.)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aegis_core.errors import AegisValidationError
from aegis_core.skills.graph import SkillGraph, SkillNode
from aegis_core.skills.slots import SlotRegistry, SlotResolutionError


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


class TestSkillGraph:
    """Skill graph discovery, node loading and handoff-path validation."""

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

    def test_skill_node_from_doc_mutant_kills(self):
        from aegis_core.skills.graph import SkillNode
        from aegis_core.yaml import AegisDocument
        doc = AegisDocument(metadata={"id": "skill-custom", "tier": "specialist", "description": "desc"})
        node = SkillNode.from_doc(doc)
        assert node.tier == "specialist"
        assert node.tier != "method"


class TestSlotRegistryBranches:

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
