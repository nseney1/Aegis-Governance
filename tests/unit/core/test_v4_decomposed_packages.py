"""Unit tests for v4.0.0 Wave 1 Lane A: Canonical WorkspaceLayout, Native AST Policy, and YAML/Telemetry Engine Decomposition."""
from __future__ import annotations

import inspect
from pathlib import Path
import pytest

from aegis_core.ast import (
    NormalizedAST,
    SymbolDef,
    evaluate_forbid_ast,
    extract_normalized_ast,
    match as ast_match,
    policy as ast_policy,
    schema as ast_schema,
    synthesize_planned_ast,
)
from aegis_core import telemetry, telemetry_engine, yaml, yaml_engine
from aegis_core.telemetry_engine import compaction, ledger, rollup
from aegis_core.workspace.layout import LockResource, WorkspaceLayout
from aegis_core.yaml_engine import document, frontmatter, parser, serializer


class TestWorkspaceLayoutV4:
    """Verify canonical v4.0 WorkspaceLayout properties and LockResource constants."""

    def test_v4_layout_properties_and_locks(self, tmp_path: Path):
        layout = WorkspaceLayout(tmp_path)
        assert layout.checkpoint_rollup_file == layout.evidence_dir / "checkpoint_rollup.json"
        assert layout.evidence_archive_dir == layout.evidence_dir / "archive"
        assert layout.evidence_outcomes_file == layout.evidence_dir / "outcomes.jsonl"
        assert layout.swarm_dir == layout.aegis_dir / "swarm"
        assert layout.handoffs_dir == layout.swarm_dir / "handoffs"
        assert layout.leases_file == layout.swarm_dir / "leases.json"

        assert LockResource.SWARM == "swarm"
        assert LockResource.PACKS == "packs"
        assert layout.lock_file(LockResource.SWARM) == layout.locks_dir / "swarm.lock"
        assert layout.lock_file(LockResource.PACKS) == layout.locks_dir / "packs.lock"


class TestNativeNormalizedASTAndPolicy:
    """Verify NormalizedAST native initialization without monkeypatching and ast.policy extraction."""

    def test_no_monkeypatching_in_ast_match(self):
        match_src = inspect.getsource(ast_match)
        assert "NormalizedAST.__init__ =" not in match_src
        assert "_ORIG_NORM_AST_INIT" not in match_src
        assert len(match_src.splitlines()) < 250
        assert len(inspect.getsource(ast_policy).splitlines()) < 300

    def test_native_normalized_ast_defaults_and_validation(self):
        default_ast = NormalizedAST(
            imports=["pickle", "os.path"],
            calls=["eval()", "os.system()"],
            decorators=["@pytest.mark.xfail", "dataclass"],
            symbols=[SymbolDef(name="run_job", kind="function", line=10)],
        )
        assert default_ast.file_path == "<unknown>"
        assert default_ast.language == "python"
        assert default_ast.calls == ("eval", "os.system")
        assert default_ast.decorators == ("pytest.mark.xfail", "dataclass")
        assert len(default_ast.symbols) == 1
        assert default_ast.symbols[0].name == "run_job"
        assert default_ast.find_definition("run_job") is not None

        with pytest.raises(ValueError, match="file_path cannot be empty"):
            NormalizedAST(file_path="", language="python")
        with pytest.raises(ValueError, match="language cannot be empty"):
            NormalizedAST(file_path="sample.py", language="")

    def test_ast_policy_evaluation_and_helpers(self, tmp_path: Path):
        norm_ast = NormalizedAST(
            imports=["pickle", "subprocess"],
            calls=["eval", "subprocess.Popen"],
            decorators=["@pytest.mark.xfail"],
        )
        assert ast_policy._match_ImportNode_against_pattern(norm_ast.imports[0], "pickle") is True
        assert ast_policy._match_call_against_pattern(norm_ast.call_sites[0], "eval") is True
        assert ast_policy._match_decorator_against_pattern("pytest.mark.xfail", "pytest.mark.xfail") is True

        violations = evaluate_forbid_ast(
            norm_ast,
            {
                "imports": ["pickle"],
                "calls": ["eval"],
                "decorators": ["pytest.mark.xfail"],
            },
        )
        assert len(violations) == 3

        planned = synthesize_planned_ast(["subprocess.run", "pickle"])
        planned_violations = evaluate_forbid_ast(
            planned,
            {"imports": ["pickle"], "calls": ["subprocess.run"]},
        )
        assert len(planned_violations) == 2

        py_file = tmp_path / "mod.py"
        py_file.write_text("@my_dec\ndef fn():\n    return eval('1')\n", encoding="utf-8")
        extracted = extract_normalized_ast(py_file)
        assert extracted is not None
        assert "my_dec" in extracted.decorators


class TestYAMLEngineDecomposition:
    """Verify aegis_core.yaml facade and aegis_core.yaml_engine module decomposition."""

    def test_yaml_module_line_limits(self):
        assert len(inspect.getsource(yaml).splitlines()) < 120
        for mod in (parser, serializer, document, frontmatter, yaml_engine):
            assert len(inspect.getsource(mod).splitlines()) < 350, f"{mod.__name__} exceeds 350 lines"
        assert len(inspect.getsource(serializer).splitlines()) < 250
        assert len(inspect.getsource(document).splitlines()) < 250
        assert len(inspect.getsource(frontmatter).splitlines()) < 250

    def test_yaml_roundtrip_parsing_and_serialization(self, tmp_path: Path):
        raw = "---\nid: rule-v4\ntype: invariant\ntarget_paths:\n  - src/*.py\n---\n# Rule Body\n"
        doc = yaml.AegisYAML.parse_text(raw)
        assert doc.id == "rule-v4"
        assert doc.kind == "rule"
        assert doc.target_paths == ["src/*.py"]
        assert doc.body == "# Rule Body"

        dumped = yaml.AegisYAML.dump(doc)
        reparsed_meta, reparsed_body = yaml.parse_rule_frontmatter(dumped)
        assert reparsed_meta["id"] == "rule-v4"
        assert reparsed_body.strip() == "# Rule Body"


class TestTelemetryEngineDecomposition:
    """Verify aegis_core.telemetry facade and aegis_core.telemetry_engine module decomposition."""

    def test_telemetry_module_line_limits(self):
        assert len(inspect.getsource(telemetry).splitlines()) < 150
        for mod in (ledger, rollup, compaction, telemetry_engine):
            assert len(inspect.getsource(mod).splitlines()) < 350, f"{mod.__name__} exceeds 350 lines"
        assert len(inspect.getsource(rollup).splitlines()) < 250
        assert len(inspect.getsource(compaction).splitlines()) < 250

    def test_signal_rule_id_and_cell_normalization_and_fitness(self, tmp_path: Path, monkeypatch):
        ws = str(tmp_path)
        rec = telemetry.append_signal(ws, "rule-norm-1", "tp", "session")
        assert rec["rule_id"] == "rule-norm-1"
        assert rec["cell"] == "rule-norm-1"

        loaded = telemetry.read_signals(ws)
        assert len(loaded) == 1
        assert loaded[0]["rule_id"] == "rule-norm-1"
        assert loaded[0]["cell"] == "rule-norm-1"

        fitness_single = telemetry.get_workspace_rule_fitness(tmp_path, "rule-norm-1")
        assert isinstance(fitness_single, float)
        assert fitness_single > 0.5

        fitness_map = telemetry.get_workspace_rule_fitness(tmp_path)
        assert isinstance(fitness_map, dict)
        assert fitness_map["rule-norm-1"] == pytest.approx(fitness_single)

        # Verify monkeypatching SIGNALS_FILENAME on aegis_core.telemetry propagates to ledger
        monkeypatch.setattr(telemetry, "SIGNALS_FILENAME", "custom_signals.jsonl")
        telemetry.append_signal(ws, "rule-custom", "fp", "ci")
        assert (tmp_path / ".aegis" / "evidence" / "custom_signals.jsonl").is_file()
        custom_loaded = telemetry.read_signals(ws)
        assert len(custom_loaded) == 1
        assert custom_loaded[0]["rule_id"] == "rule-custom"
