"""Unit tests for Phase 3.3.2: Declarative forbid_ast & Pre-Edit planned_symbols in aegis_scan."""
from __future__ import annotations

from pathlib import Path
import pytest

from aegis_core.ast.match import (
    evaluate_forbid_ast,
    extract_normalized_ast,
    synthesize_planned_ast,
)
from aegis_core.ast.schema import CallSiteNode, ImportNode, NormalizedAST
from aegis_core.verification import DeterministicVerifier
from aegis_core.verification.runner import gate_verdict, run_layer1
from aegis_mcp.handlers.core import handle_scan
from aegis_mcp.jit_engine import express, match_cells_to_files
from aegis_mcp.registry import TOOL_DEFINITIONS
from aegis_mcp.tools import execute_tool


class TestEvaluateForbidAST:
    """Behavioral tests for evaluate_forbid_ast across imports, calls, and decorators."""

    def test_forbid_ast_imports_matches_module_prefix_and_symbol(self):
        norm_ast = NormalizedAST(
            file_path="src/loader.py",
            language="python",
            imports=(
                ImportNode(source="pickle", imported_symbols=("loads",)),
                ImportNode(source="urllib.request", imported_symbols=("urlopen",)),
            ),
        )
        violations = evaluate_forbid_ast(
            norm_ast,
            {"imports": ["pickle", "urllib", "subprocess"]},
        )
        assert len(violations) == 2
        assert "Forbidden import 'pickle' matched rule forbid_ast.imports" in violations
        assert "Forbidden import 'urllib' matched rule forbid_ast.imports" in violations

    def test_forbid_ast_calls_matches_direct_and_dotted_calls(self):
        norm_ast = NormalizedAST(
            file_path="src/runner.py",
            language="python",
            call_sites=(
                CallSiteNode(target="eval", line=5),
                CallSiteNode(target="os.system", line=8),
                CallSiteNode(target="safe_evaluate", line=10),
            ),
        )
        violations = evaluate_forbid_ast(
            norm_ast,
            {"calls": ["eval", "os.system", "exec"]},
        )
        assert len(violations) == 2
        assert "Forbidden call 'eval' matched rule forbid_ast.calls" in violations
        assert "Forbidden call 'os.system' matched rule forbid_ast.calls" in violations

    def test_forbid_ast_decorators_matches_normalized_ast_decorators(self):
        norm_ast = NormalizedAST(
            file_path="tests/test_sample.py",
            language="python",
            decorators=["@pytest.mark.xfail", "dataclass"],
        )
        violations = evaluate_forbid_ast(
            norm_ast,
            {"decorators": ["pytest.mark.xfail", "flaky"]},
        )
        assert violations == [
            "Forbidden decorator 'pytest.mark.xfail' matched rule forbid_ast.decorators"
        ]

    def test_forbid_ast_clean_returns_empty_list(self):
        norm_ast = NormalizedAST(
            file_path="src/clean.py",
            language="python",
            imports=(ImportNode(source="json", imported_symbols=("loads",)),),
            call_sites=(CallSiteNode(target="json.loads", line=3),),
            decorators=["dataclass"],
        )
        violations = evaluate_forbid_ast(
            norm_ast,
            {
                "imports": ["pickle", "subprocess"],
                "calls": ["eval", "exec"],
                "decorators": ["pytest.mark.xfail"],
            },
        )
        assert violations == []


class TestLayer1DeterministicVerifierForbidAST:
    """Layer 1 DeterministicVerifier tests with workspace rules declaring forbid_ast."""

    def _setup_workspace_with_rule(self, tmp_path: Path) -> Path:
        rules_dir = tmp_path / ".aegis" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        rule_md = (
            "---\n"
            "id: no-unsafe-exec-or-pickle\n"
            "type: invariant\n"
            "enforcement: gate\n"
            "hypothesis: Never use eval() or pickle in production code.\n"
            "target_paths:\n"
            "  - src/*.py\n"
            "forbid_ast:\n"
            "  calls:\n"
            "    - eval\n"
            "  imports:\n"
            "    - pickle\n"
            "  decorators:\n"
            "    - pytest.mark.xfail\n"
            "---\n"
            "# No Unsafe Exec or Pickle\n"
        )
        (rules_dir / "no-unsafe-exec-or-pickle.md").write_text(rule_md, encoding="utf-8")
        (tmp_path / "src").mkdir(parents=True, exist_ok=True)
        return tmp_path

    def test_deterministic_verifier_fails_on_forbidden_eval_and_pickle(self, tmp_path: Path):
        ws = self._setup_workspace_with_rule(tmp_path)
        bad_file = ws / "src" / "unsafe.py"
        bad_file.write_text(
            "import pickle\n\n"
            "def main(payload: str):\n"
            "    return eval(payload)\n",
            encoding="utf-8",
        )

        verifier = DeterministicVerifier(fast_mode=True)
        evidence = verifier.verify(changed_files=["src/unsafe.py"], workspace=ws)

        assert not gate_verdict(evidence)
        forbid_results = [e for e in evidence if e.tool == "forbid_ast:no-unsafe-exec-or-pickle"]
        assert len(forbid_results) == 1
        assert forbid_results[0].verdict is False
        assert forbid_results[0].target == "src/unsafe.py"
        assert "Forbidden import 'pickle'" in forbid_results[0].detail
        assert "Forbidden call 'eval'" in forbid_results[0].detail

    def test_deterministic_verifier_passes_when_clean_and_skips_tests_dir(self, tmp_path: Path):
        ws = self._setup_workspace_with_rule(tmp_path)
        clean_file = ws / "src" / "safe.py"
        clean_file.write_text(
            "import json\n\n"
            "def main(payload: str):\n"
            "    return json.loads(payload)\n",
            encoding="utf-8",
        )
        test_dir = ws / "tests"
        test_dir.mkdir(parents=True, exist_ok=True)
        test_file = test_dir / "test_unsafe_allowed.py"
        test_file.write_text(
            "import pickle\n"
            "def test_something():\n"
            "    eval('1 + 1')\n",
            encoding="utf-8",
        )

        verifier = DeterministicVerifier(fast_mode=True)
        evidence = verifier.verify(
            changed_files=["src/safe.py", "tests/test_unsafe_allowed.py"],
            workspace=ws,
        )
        assert gate_verdict(evidence) is True
        forbid_results = [e for e in evidence if e.tool.startswith("forbid_ast:")]
        assert forbid_results == []


class TestPlannedSymbolsInAegisScan:
    """Tests for pre-edit planned_symbols in aegis_scan and match_cells_to_files."""

    def test_registry_schema_exposes_planned_symbols(self):
        scan_def = next(t for t in TOOL_DEFINITIONS if t["name"] == "aegis_scan")
        props = scan_def["inputSchema"]["properties"]
        assert "planned_symbols" in props
        assert props["planned_symbols"]["type"] == "array"
        assert props["planned_symbols"]["items"] == {"type": "string"}

    def test_match_cells_to_files_matches_planned_symbols_without_existing_file(self, tmp_path: Path):
        cells = [
            {
                "_name": "no-subprocess-shell",
                "type": "invariant",
                "enforcement": "gate",
                "hypothesis": "Avoid raw subprocess execution without confinement.",
                "ast_triggers": {"calls": ["subprocess.run", "subprocess.Popen"]},
            },
            {
                "_name": "forbid-pickle-serialization",
                "type": "trap",
                "enforcement": "advisory",
                "hypothesis": "Never deserialize untrusted pickle streams.",
                "forbid_ast": {"imports": ["pickle"]},
            },
            {
                "_name": "unrelated-css-rule",
                "type": "persona",
                "target_paths": ["styles/*.css"],
            },
        ]

        # Target file src/future_worker.py does NOT exist on disk yet
        matched = match_cells_to_files(
            cells,
            changed_files=["src/future_worker.py"],
            workspace=str(tmp_path),
            planned_symbols=["subprocess.run", "pickle"],
        )
        matched_names = {c["_name"] for c in matched}
        assert "no-subprocess-shell" in matched_names
        assert "forbid-pickle-serialization" in matched_names
        assert "unrelated-css-rule" not in matched_names
        for m in matched:
            assert m["match_type"] == "ast_match"

    def test_aegis_scan_handler_matches_planned_symbols_pre_edit(self, tmp_path: Path):
        rules_dir = tmp_path / ".aegis" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "subprocess-guard.md").write_text(
            "---\n"
            "id: subprocess-guard\n"
            "type: invariant\n"
            "enforcement: gate\n"
            "hypothesis: Subprocess calls must set explicit timeouts.\n"
            "ast_triggers:\n"
            "  calls:\n"
            "    - subprocess.run\n"
            "---\n"
            "Always set timeout on subprocess.run.\n",
            encoding="utf-8",
        )
        (rules_dir / "ban-pickle.md").write_text(
            "---\n"
            "id: ban-pickle\n"
            "type: trap\n"
            "enforcement: advisory\n"
            "hypothesis: Do not use pickle for untrusted inputs.\n"
            "forbid_ast:\n"
            "  imports:\n"
            "    - pickle\n"
            "---\n"
            "Use json instead of pickle.\n",
            encoding="utf-8",
        )

        # Call via handle_scan and execute_tool when src/not_yet_created.py does not exist
        res = handle_scan(
            {
                "workspace": str(tmp_path),
                "files": ["src/not_yet_created.py"],
                "planned_symbols": ["subprocess.run", "pickle"],
            },
            None,
        )
        rule_names = {r["name"] for r in res["relevant_rules"]}
        assert "subprocess-guard" in rule_names
        assert "ban-pickle" in rule_names

        res_via_tool = execute_tool(
            "aegis_scan",
            {
                "workspace": str(tmp_path),
                "files": ["src/not_yet_created.py"],
                "planned_symbols": ["subprocess.run", "pickle"],
            },
        )
        tool_rule_names = {r["name"] for r in res_via_tool["relevant_rules"]}
        assert "subprocess-guard" in tool_rule_names
        assert "ban-pickle" in tool_rule_names
