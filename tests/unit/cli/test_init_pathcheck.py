"""Unit tests for soma init proactive PATH guidance integration."""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from aegis_cli.init import run_init


class TestInitPathGuidance:
    def test_init_displays_path_hint_when_soma_missing_from_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        target = tmp_path / "project"
        target.mkdir()

        # Monkeypatch build_hint in aegis_cli.pathcheck to return a simulated diagnostic
        monkeypatch.setattr(
            "aegis_cli.pathcheck.build_hint",
            lambda **kwargs: "ℹ️  'soma' was installed to ~/.local/bin, which is not on your zsh PATH.\n      export PATH=\"$HOME/.local/bin:$PATH\"",
        )

        args = argparse.Namespace(
            project=str(target),
            platform="gemini",
            rules="minimal",
            force=True,
            yes=True,
            dry_run=False,
            mcp=False,
            _project_root=str(target),
        )

        ret = run_init(args)
        assert ret == 0

        captured = capsys.readouterr().out
        assert "ℹ️  'soma' was installed to ~/.local/bin, which is not on your zsh PATH." in captured
        assert "export PATH=\"$HOME/.local/bin:$PATH\"" in captured

    def test_init_silent_when_soma_already_on_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        target = tmp_path / "project2"
        target.mkdir()

        # Monkeypatch build_hint to return None (meaning soma is already on PATH)
        monkeypatch.setattr("aegis_cli.pathcheck.build_hint", lambda **kwargs: None)

        args = argparse.Namespace(
            project=str(target),
            platform="gemini",
            rules="minimal",
            force=True,
            yes=True,
            dry_run=False,
            mcp=False,
            _project_root=str(target),
        )

        ret = run_init(args)
        assert ret == 0

        captured = capsys.readouterr().out
        assert "which is not on your" not in captured
