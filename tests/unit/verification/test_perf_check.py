"""Behavioral tests for paired interleaved performance regression check."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aegis_core.verification import perf_check


class TestEvaluatePairedSamples:
    def test_rejects_fewer_than_15_rounds(self) -> None:
        with pytest.raises(ValueError, match="15"):
            perf_check.evaluate_paired_samples([0.01] * 14, [0.01] * 14, threshold=0.05)

    def test_aa_noise_floor_marks_noisy_benchmark_unverified(self) -> None:
        # Even indices ~10ms, odd indices ~12ms -> ~20% A/A drift > threshold / 2 (2.5%)
        base_samples = [0.010 if i % 2 == 0 else 0.012 for i in range(16)]
        head_samples = [0.015 for _ in range(16)]
        res = perf_check.evaluate_paired_samples(base_samples, head_samples, threshold=0.05)
        assert res["noisy"] is True
        assert res["status"] == "unverified"
        assert res["regressed"] is False
        assert res["aa_drift"] > 0.025

    def test_flags_regression_only_when_not_noisy_and_both_min_and_median_regress(self) -> None:
        # Stable base around 10.0ms, head around 11.0ms (+10% > 5% threshold)
        base_samples = [0.0100 + (0.00002 if i % 2 else 0.0) for i in range(15)]
        head_samples = [0.0110 + (0.00002 if i % 2 else 0.0) for i in range(15)]
        res = perf_check.evaluate_paired_samples(base_samples, head_samples, threshold=0.05)
        assert res["noisy"] is False
        assert res["regressed"] is True
        assert res["status"] == "fail"

    def test_passes_when_min_does_not_exceed_threshold_even_if_median_drifts(self) -> None:
        # min(head) == min(base) == 0.0100, even though median(head) is higher
        base_samples = [0.0100] * 15
        head_samples = [0.0100] + [0.0110] * 14
        res = perf_check.evaluate_paired_samples(base_samples, head_samples, threshold=0.05)
        assert res["noisy"] is False
        assert res["regressed"] is False
        assert res["status"] == "pass"


class TestRunPerfCheck:
    def test_rejects_rounds_below_15(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="15"):
            perf_check.run_perf_check(tmp_path, rounds=10, command=["python3", "-c", "pass"])

    def test_reads_command_only_from_user_scope_never_repo_config(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        (repo_root / ".aegis").mkdir(parents=True)
        # Untrusted repo config tries to smuggle a perf command
        (repo_root / ".aegis" / "config.json").write_text(
            json.dumps({"v": 1, "perf": {"command": ["echo", "pwned"]}}),
            encoding="utf-8",
        )
        empty_user_cfg = tmp_path / "user_config.json"
        empty_user_cfg.write_text(json.dumps({"v": 1}), encoding="utf-8")

        executed: list[list[str]] = []

        def spy_runner(argv, cwd, env=None, timeout=60):
            executed.append(list(argv))
            return {"returncode": 0, "stdout": "", "stderr": "", "missing_binary": False, "timed_out": False, "duration_s": 0.01}

        res = perf_check.run_perf_check(
            repo_root,
            rounds=15,
            runner=spy_runner,
            user_config_path=empty_user_cfg,
        )
        assert res["status"] == "unverified"
        assert executed == []

    def test_interleaved_paired_execution_with_user_config_and_no_baseline_file(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        user_cfg = tmp_path / "user_aegis" / "config.json"
        user_cfg.parent.mkdir(parents=True)
        user_cfg.write_text(
            json.dumps({"v": 1, "perf": {"command": ["pytest", "-q"]}}),
            encoding="utf-8",
        )

        calls: list[str] = []

        def fake_runner(argv, cwd, env=None, timeout=60):
            is_head = Path(cwd).resolve() == repo_root.resolve()
            calls.append("head" if is_head else "base")
            dur = 0.020 if is_head else 0.010
            return {
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "missing_binary": False,
                "timed_out": False,
                "duration_s": dur,
            }

        res = perf_check.run_perf_check(
            repo_root,
            rounds=15,
            threshold=0.05,
            runner=fake_runner,
            user_config_path=user_cfg,
        )
        assert res["status"] == "fail"
        assert res["regressed"] is True
        assert calls.count("base") == 15
        assert calls.count("head") == 15
        # Verify interleaved pairs (each pair has 1 base and 1 head)
        for i in range(0, 30, 2):
            assert set(calls[i : i + 2]) == {"base", "head"}
        # Never writes a persistent baseline file
        assert list(repo_root.rglob("*baseline*")) == []
