"""Regression coverage for packaging and Python MCP initialization."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from conftest import REPO_ROOT, read


def test_python_init_mcp_merge_targets_project(tmp_path):
    from aegis_cli.init import generate_mcp_config

    config = tmp_path / ".mcp.json"
    config.write_text(
        json.dumps({
            "unrelated": "preserve",
            "mcpServers": {"other": {"command": "keep"}},
        }),
        encoding="utf-8",
    )
    generate_mcp_config(tmp_path)
    merged = json.loads(config.read_text(encoding="utf-8"))
    assert merged["unrelated"] == "preserve"
    assert merged["mcpServers"]["other"] == {"command": "keep"}
    aegis = merged["mcpServers"]["aegis"]
    assert aegis["cwd"] == str(tmp_path)
    assert aegis["env"] == {"AEGIS_WORKSPACE": str(tmp_path)}
    assert "soma" not in merged["mcpServers"]


def test_python_init_invalid_mcp_json_is_unchanged(tmp_path):
    from aegis_cli.init import generate_mcp_config

    config = tmp_path / ".mcp.json"
    invalid = b"{ definitely not json\n"
    config.write_bytes(invalid)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        generate_mcp_config(tmp_path)
    assert config.read_bytes() == invalid


def test_packaging_excludes_private_soma_state_and_includes_genome_package():
    manifest = read(os.path.join(REPO_ROOT, "MANIFEST.in"))
    assert "recursive-include .soma" not in manifest
    assert "prune .soma" in manifest
    assert ".aegis/evidence" not in manifest
    assert ".aegis/dreams" not in manifest

    pyproject = read(os.path.join(REPO_ROOT, "pyproject.toml"))
    assert '"rules*"' in pyproject or '"genome*"' in pyproject
    assert re.search(r"(?m)^(rules|genome)\s*=\s*\[", pyproject)
    assert '"*.md"' in pyproject and '".oracles/*.md"' in pyproject
    assert os.path.isfile(os.path.join(REPO_ROOT, "rules", "__init__.py")) or os.path.isfile(os.path.join(REPO_ROOT, "genome", "__init__.py"))
