"""TDD tests for HUMAN_INSIGHT detection in transcript_verifier.py.

Gate 1 of Core Change Protocol.
"""
import json
import os
import pytest


def _write_transcript(path, steps):
    """Helper: write a list of transcript step dicts to JSONL."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for step in steps:
            f.write(json.dumps(step) + "\n")


class TestHumanInsightDetection:
    """Tests for HUMAN_INSIGHT event detection in transcript verifier."""

    def test_counts_human_insight_events(self, tmp_path):
        """Transcript steps containing [HUMAN_INSIGHT] are counted."""
        from aegis_core.verification.transcript_verifier import extract_metrics

        transcript_path = str(tmp_path / "transcript.jsonl")
        _write_transcript(transcript_path, [
            {"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT",
             "content": "[HUMAN_INSIGHT] Check the aspect ratio", "status": "DONE"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "source": "MODEL",
             "content": "Understood, checking aspect ratio.", "status": "DONE"},
            {"step_index": 2, "type": "USER_INPUT", "source": "USER_EXPLICIT",
             "content": "[HUMAN_INSIGHT] Also verify the color depth", "status": "DONE"},
        ])

        metrics = extract_metrics(transcript_path)
        assert metrics.human_insights_received == 2

    def test_zero_insights_when_none_present(self, tmp_path):
        """Normal transcripts without HUMAN_INSIGHT have count 0."""
        from aegis_core.verification.transcript_verifier import extract_metrics

        transcript_path = str(tmp_path / "transcript.jsonl")
        _write_transcript(transcript_path, [
            {"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT",
             "content": "Fix the bug in handler.py", "status": "DONE"},
            {"step_index": 1, "type": "RUN_COMMAND", "source": "MODEL",
             "content": "pytest tests/ -v", "status": "DONE", "exit_code": 0},
        ])

        metrics = extract_metrics(transcript_path)
        assert metrics.human_insights_received == 0

    def test_insight_in_system_message_not_counted(self, tmp_path):
        """Only USER_INPUT type steps count as human insights."""
        from aegis_core.verification.transcript_verifier import extract_metrics

        transcript_path = str(tmp_path / "transcript.jsonl")
        _write_transcript(transcript_path, [
            {"step_index": 0, "type": "SYSTEM_MESSAGE", "source": "SYSTEM",
             "content": "[HUMAN_INSIGHT] This is from system, not human", "status": "DONE"},
        ])

        metrics = extract_metrics(transcript_path)
        assert metrics.human_insights_received == 0

    def test_partial_tag_not_counted(self, tmp_path):
        """Mentions of 'HUMAN_INSIGHT' without brackets are not counted."""
        from aegis_core.verification.transcript_verifier import extract_metrics

        transcript_path = str(tmp_path / "transcript.jsonl")
        _write_transcript(transcript_path, [
            {"step_index": 0, "type": "USER_INPUT", "source": "USER_EXPLICIT",
             "content": "We should implement a HUMAN_INSIGHT system", "status": "DONE"},
        ])

        metrics = extract_metrics(transcript_path)
        assert metrics.human_insights_received == 0
