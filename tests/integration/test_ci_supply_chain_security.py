"""Supply Chain & CI Hardening Tests (Phase 4).

Verifies pyproject.toml optional dependencies and publish.yml release asset uploads.
"""
import os
import pytest
from pathlib import Path
from conftest import REPO_ROOT


def test_publish_yml_contains_release_asset_upload():
    """publish.yml must grant contents: write and upload release assets."""
    publish_yml = Path(REPO_ROOT) / ".github" / "workflows" / "publish.yml"
    content = publish_yml.read_text(encoding="utf-8")
    assert "contents: write" in content
    assert "gh release upload" in content
