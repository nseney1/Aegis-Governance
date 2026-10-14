"""Unit tests for aegis_core.insights."""
import os
import json
import pytest

from aegis_core.insights import (
    capture_insight,
    cluster_insights,
    generate_cell_candidates,
)


def test_capture_and_cluster_insights(tmp_path):
    ws = str(tmp_path)
    os.makedirs(os.path.join(ws, ".soma", "cells"), exist_ok=True)

    rec = capture_insight(
        workspace=ws,
        insight="Async timeout in event loop",
        context_files=["core/loop.py"],
        category="concurrency",
    )
    assert rec["insight"] == "Async timeout in event loop"
    assert rec["category"] == "concurrency"
    assert "wall_file" not in rec
    assert "wall_id" not in rec

    # Add 2 more to form a cluster
    capture_insight(workspace=ws, insight="Lock contention in threadpool", context_files=["core/loop.py"], category="concurrency")
    capture_insight(workspace=ws, insight="Deadlock on shutdown", context_files=["core/loop.py"], category="concurrency")

    clusters = cluster_insights(ws, min_cluster_size=3)
    assert len(clusters) == 1
    assert clusters[0]["common_category"] == "concurrency"

    candidates = generate_cell_candidates(clusters, ws)
    assert len(candidates) == 1
    assert "concurrency" in candidates[0]["hypothesis"]


def test_load_signal_weight_without_frontmatter(tmp_path):
    from aegis_core.insights import _load_signal_weight

    ws = str(tmp_path)
    soma_dir = os.path.join(ws, ".soma")
    os.makedirs(soma_dir, exist_ok=True)
    with open(os.path.join(soma_dir, "config.yaml"), "w", encoding="utf-8") as f:
        f.write("insight_signal_weight: 0.85\n")
    assert _load_signal_weight(ws) == 0.85


def test_load_signal_weight_with_bom(tmp_path):
    from aegis_core.insights import _load_signal_weight

    ws = str(tmp_path)
    soma_dir = os.path.join(ws, ".soma")
    os.makedirs(soma_dir, exist_ok=True)
    with open(os.path.join(soma_dir, "config.yaml"), "w", encoding="utf-8") as f:
        f.write("\ufeffinsight_signal_weight: 0.95\n")
    assert _load_signal_weight(ws) == 0.95


def test_capture_insight_scaffold_wall(tmp_path):
    ws = str(tmp_path)
    rec = capture_insight(
        workspace=ws,
        insight="Prohibit unhedged subprocess calls in untrusted environments",
        context_files=["soma_core/runner.py"],
        category="security",
        scaffold_wall=True,
        wall_id="wall-unhedged-subprocess",
    )

    assert "wall_file" in rec
    assert "wall_id" in rec
    assert rec["wall_id"] == "wall-unhedged-subprocess"
    assert os.path.exists(rec["wall_file"])

    from aegis_core.yaml import parse_frontmatter
    with open(rec["wall_file"], "r", encoding="utf-8") as f:
        content = f.read()
    meta = parse_frontmatter(content)
    assert meta["id"] == "wall-unhedged-subprocess"
    assert meta["type"] == "wall"
    assert meta["enforcement"] == "gate"
    assert meta["domain"] == "security"
    assert "Prohibit unhedged subprocess" in meta["description"]

    # Verify a second call when walls directory already exists (exist_ok=True)
    rec2 = capture_insight(
        workspace=ws,
        insight="Prohibit unhedged subprocess calls part 2",
        context_files=["soma_core/runner.py"],
        scaffold_wall=True,
        wall_id="wall-unhedged-subprocess-2",
    )
    assert os.path.exists(rec2["wall_file"])


def test_capture_insight_scaffold_wall_default_id(tmp_path):
    import hashlib
    ws = str(tmp_path)
    rec = capture_insight(
        workspace=ws,
        insight="Prohibit unhedged subprocess",
        context_files=["soma_core/test.py"],
        scaffold_wall=True,
    )
    assert "wall_file" in rec
    expected_h = hashlib.sha256("Prohibit unhedged subprocess".encode("utf-8")).hexdigest()[:8]
    assert rec["wall_id"] == f"wall-insight-{expected_h}"
    assert os.path.exists(rec["wall_file"])

    from aegis_core.yaml import parse_frontmatter
    with open(rec["wall_file"], "r", encoding="utf-8") as f:
        meta = parse_frontmatter(f.read())
    assert meta["domain"] == "security"


def test_capture_insight_wall_id_only(tmp_path):
    ws = str(tmp_path)
    rec = capture_insight(
        workspace=ws,
        insight="Custom wall from id only",
        context_files=["soma_core/test.py"],
        wall_id="my-custom-wall",
        category="concurrency",
    )
    assert rec["wall_id"] == "wall-my-custom-wall"
    assert os.path.exists(rec["wall_file"])

    from aegis_core.yaml import parse_frontmatter
    with open(rec["wall_file"], "r", encoding="utf-8") as f:
        meta = parse_frontmatter(f.read())
    assert meta["domain"] == "concurrency"


