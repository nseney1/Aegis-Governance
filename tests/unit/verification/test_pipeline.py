"""Test suite for soma_core/verification/pipeline.py conforming to strict checkpoint conventions."""
from __future__ import annotations


from aegis_core.verification import Verdict
from aegis_core.verification.pipeline import VerificationPipeline


class FakeUnparseableBackend:
    """Backend returning malformed or error string instead of JSON list."""

    def __init__(self, response: str):
        self.response = response

    def generate(self, prompt: str) -> str:
        return self.response


class TestPipelineFailClosed:
    """Verifies the pipeline writes no evidence, calls the backend only when needed and fails closed."""

    def test_no_changed_files_never_calls_the_backend(self, tmp_path):
        calls = []
        res = VerificationPipeline().run(
            changed_files=[],
            workspace=tmp_path,
            task_plan="Clean run",
            backend=lambda prompt: calls.append(prompt) or "[]",
        )
        assert res.verdict == Verdict.SHIP
        assert res.arbitration_result is None
        assert calls == []

    def test_layer1_only_never_calls_the_backend_or_writes_evidence(self, tmp_path):
        (tmp_path / "mod.py").write_text("def main():\n    return 1\n", encoding="utf-8")
        calls = []
        res = VerificationPipeline().run(
            changed_files=["mod.py"],
            workspace=tmp_path,
            task_plan="None",
            layer1_only=True,
            backend=lambda prompt: calls.append(prompt) or "[]",
        )
        assert res.arbitration_result is None
        assert calls == []
        assert not (tmp_path / ".aegis").exists()

    def test_spec_agent_unparseable_json_fails_closed_to_block(self, tmp_path):
        """When Spec Agent returns malformed JSON or error text, pipeline must FAIL-CLOSED with BLOCK."""
        f = tmp_path / "module.py"
        f.write_text("def run():\n    return 42\n", encoding="utf-8")

        pipeline = VerificationPipeline()
        bad_backend = FakeUnparseableBackend("Internal Server Error: 500 API Gateway Timeout")

        res = pipeline.run(
            changed_files=["module.py"],
            workspace=tmp_path,
            task_plan="Implement run",
            backend=bad_backend,
        )

        assert res.verdict == Verdict.BLOCK, (
            f"Expected Verdict.BLOCK on Spec Agent parse failure, got {res.verdict}"
        )
        assert not res.passed

    def test_spec_agent_dict_instead_of_list_fails_closed_to_block(self, tmp_path):
        """When Spec Agent returns a JSON dictionary instead of a list of predictions, fail-closed."""
        f = tmp_path / "module.py"
        f.write_text("def run():\n    return 42\n", encoding="utf-8")

        pipeline = VerificationPipeline()
        dict_backend = FakeUnparseableBackend('{"error": "rate limit exceeded", "retry_after": 60}')

        res = pipeline.run(
            changed_files=["module.py"],
            workspace=tmp_path,
            task_plan="Implement run",
            backend=dict_backend,
        )

        assert res.verdict == Verdict.BLOCK
        assert not res.passed

    def test_pipeline_reusable_layer1_evidence_and_discovery(self, tmp_path):
        from aegis_core.verification import ToolEvidence
        f = tmp_path / "module.py"
        f.write_text("def run():\n    return 42\n", encoding="utf-8")
        test_f = tmp_path / "test_module.py"
        test_f.write_text("def test_run():\n    assert True\n", encoding="utf-8")

        pipeline = VerificationPipeline()
        backend = lambda p: "[]"
        l1_ev = [ToolEvidence("call_graph", "module.py", True, "ok")]

        res = pipeline.run(
            changed_files=["module.py"],
            workspace=tmp_path,
            task_plan="Implement run",
            backend=backend,
            layer1_evidence=l1_ev,
        )
        assert res.verdict == Verdict.SHIP
        assert res.passed is True
        assert res.layer1_evidence == l1_ev

    def test_pipeline_explicit_test_evidence_skips_discovery(self, tmp_path, monkeypatch):
        from aegis_core.verification import ToolEvidence
        f = tmp_path / "module.py"
        f.write_text("def run():\n    return 42\n", encoding="utf-8")

        discovered = []
        def _mock_disc(*a, **kw):
            discovered.append(True)
            return ([], "")
        monkeypatch.setattr("aegis_core.verification.test_runner.discover_test_evidence", _mock_disc)

        pipeline = VerificationPipeline()
        backend = lambda p: "[]"
        res = pipeline.run(
            changed_files=["module.py"],
            workspace=tmp_path,
            task_plan="Implement run",
            backend=backend,
            test_names=["test_custom"],
            test_results="1 passed in 0.01s",
            layer1_evidence=[ToolEvidence("call_graph", "module.py", True, "ok")],
        )
        assert res.verdict == Verdict.SHIP
        assert len(discovered) == 0, "Explicit test_names/test_results must skip discover_test_evidence"

    def test_pipeline_test_evidence_discovery_exception_handled_gracefully(self, tmp_path, monkeypatch):
        from aegis_core.verification import ToolEvidence
        f = tmp_path / "module.py"
        f.write_text("def run():\n    return 42\n", encoding="utf-8")

        def _raise_err(*a, **kw):
            raise RuntimeError("test discovery failure simulation")
        monkeypatch.setattr("aegis_core.verification.test_runner.discover_test_evidence", _raise_err)

        pipeline = VerificationPipeline()
        backend = lambda p: "[]"
        res = pipeline.run(
            changed_files=["module.py"],
            workspace=tmp_path,
            task_plan="Implement run",
            backend=backend,
            layer1_evidence=[ToolEvidence("call_graph", "module.py", True, "ok")],
        )
        assert res.verdict == Verdict.SHIP

    def test_pipeline_partial_test_evidence_triggers_discovery_for_missing(self, tmp_path, monkeypatch):
        from aegis_core.verification import ToolEvidence
        f = tmp_path / "module.py"
        f.write_text("def run():\n    return 42\n", encoding="utf-8")

        discovered = []
        def _mock_disc(*a, **kw):
            discovered.append(True)
            return (["disc_test"], "discovered test output")
        monkeypatch.setattr("aegis_core.verification.test_runner.discover_test_evidence", _mock_disc)

        captured_kwargs = {}
        def mock_verify(**kwargs):
            captured_kwargs.update(kwargs)
            return ([], [], False)

        pipeline = VerificationPipeline()
        monkeypatch.setattr(pipeline.adversarial_verifier, "verify", mock_verify)

        # Pass test_names but leave test_results None
        res = pipeline.run(
            changed_files=["module.py"],
            workspace=tmp_path,
            task_plan="Plan",
            backend=lambda p: "[]",
            test_names=["provided_test"],
            test_results=None,
            layer1_evidence=[ToolEvidence("call_graph", "module.py", True, "ok")],
        )
        assert len(discovered) == 1, "Partial test evidence (test_results=None) must trigger discovery for missing results"
        assert captured_kwargs["test_names"] == ["provided_test"]
        assert captured_kwargs["test_results"] == "discovered test output"


def test_layer2_reads_only_the_changed_source_modules(tmp_path):
    """Tests and package markers are not the implementation under review; neither are
    deleted files or non-Python ones."""
    from aegis_core.verification.pipeline import AdversarialVerifier

    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("def exported():\n    return 0\n", encoding="utf-8")
    (tmp_path / "pkg" / "mod.py").write_text("def transfer(amount: int) -> int:\n    return amount\n", encoding="utf-8")
    (tmp_path / "tests" / "test_mod.py").write_text("def test_transfer():\n    assert True\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("def nothing(): pass\n", encoding="utf-8")

    signatures, implementation = AdversarialVerifier().extract_target_data(
        ["pkg/__init__.py", "tests/test_mod.py", "pkg/mod.py", "notes.md", "pkg/deleted.py"], tmp_path,
    )

    assert implementation == "def transfer(amount: int) -> int:\n    return amount\n"
    assert len(signatures) == 1 and "def transfer(" in signatures[0]
