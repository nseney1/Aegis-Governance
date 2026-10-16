"""Declarative forbid_ast rules: evaluate_forbid_ast and the Layer 1 gate built on it.

The pre-edit planned_symbols scan input was cut in v4 (plan of record: JIT
ast_triggers/planned_symbols, 0 uses); forbid_ast stays as the gate tier's
deterministic mechanism.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aegis_core.ast.policy import evaluate_forbid_ast
from aegis_core.ast.schema import CallSiteNode, ImportNode, NormalizedAST
from aegis_core.verification.pipeline import DeterministicVerifier
from aegis_core.verification.runner import gate_verdict


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


_SUBPROCESS_AST = NormalizedAST(
    file_path="src/runner.py",
    language="python",
    imports=(ImportNode(source="subprocess", imported_symbols=("run",)),),
    call_sites=(CallSiteNode(target="subprocess.run", line=3), CallSiteNode(target="eval", line=4)),
)


class TestSpecsThatForbidNothing:
    """What evaluate_forbid_ast cannot use forbids nothing here; Layer 1 reports such a
    rule itself (runner._forbid_ast_spec_error), so a gate is never silently empty."""

    @pytest.mark.parametrize("spec", [["subprocess"], "subprocess", None, {}])
    def test_a_spec_that_is_not_a_mapping_is_ignored(self, spec):
        assert evaluate_forbid_ast(_SUBPROCESS_AST, spec) == []

    def test_no_ast_means_no_violation(self):
        assert evaluate_forbid_ast(None, {"imports": ["subprocess"], "calls": ["eval"]}) == []

    @pytest.mark.parametrize("key, value", [("imports", "subprocess"), ("calls", "eval"), ("decorators", "x")])
    def test_patterns_given_as_one_string_are_ignored(self, key, value):
        norm_ast = NormalizedAST(
            file_path="src/runner.py",
            imports=(ImportNode(source="subprocess"),),
            call_sites=(CallSiteNode(target="eval"),),
            decorators=["x"],
        )
        assert evaluate_forbid_ast(norm_ast, {key: value}) == []

    def test_an_empty_decorator_list_never_reads_the_file(self, tmp_path):
        broken = tmp_path / "broken.py"
        broken.write_text("def (:\n", encoding="utf-8")
        norm_ast = NormalizedAST(file_path=str(broken), call_sites=(CallSiteNode(target="eval"),))

        assert evaluate_forbid_ast(norm_ast, {"calls": ["eval"], "decorators": []}) == [
            "Forbidden call 'eval' matched rule forbid_ast.calls"
        ]


class TestLayer1DeterministicVerifierForbidAST:
    """Layer 1 DeterministicVerifier tests with workspace rules declaring forbid_ast."""

    def _setup_workspace_with_rule(self, tmp_path: Path) -> Path:
        rules_dir = tmp_path / ".aegis" / "rules" / "invariants"
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
