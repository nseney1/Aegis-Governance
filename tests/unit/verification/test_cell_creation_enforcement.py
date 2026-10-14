"""Tests for cell creation schema enforcement (BUG-083).

Ensures that cells generated via create_cell include the required 'enforcement'
frontmatter field, preventing pre-commit soma checkpoint cell_conventions failures.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aegis_core.yaml import parse_frontmatter
from aegis_core.lifecycle.creation import create_cell


class TestCellCreationEnforcement:
    """Tests for enforcement frontmatter in create_cell."""

    def test_create_vacuole_defaults_to_advisory_enforcement(self, tmp_path: Path):
        """create_cell for trap defaults to enforcement: advisory."""
        cell_path = create_cell(
            cell_type="trap",
            hypothesis="When coordinates invert, render pipelines fail silently",
            workspace=tmp_path,
        )
        assert cell_path.is_file()
        content = cell_path.read_text(encoding="utf-8")
        meta = parse_frontmatter(content)
        assert meta is not None
        assert meta.get("enforcement") == "advisory"
        assert meta.get("type") == "trap"

    def test_create_wall_defaults_to_gate_enforcement(self, tmp_path: Path):
        """create_cell for invariant defaults to enforcement: gate."""
        cell_path = create_cell(
            cell_type="invariant",
            hypothesis="Direct network calls outside sandbox are forbidden",
            workspace=tmp_path,
        )
        assert cell_path.is_file()
        content = cell_path.read_text(encoding="utf-8")
        meta = parse_frontmatter(content)
        assert meta is not None
        assert meta.get("enforcement") == "gate"
        assert meta.get("type") == "invariant"

    def test_create_cell_honors_explicit_enforcement(self, tmp_path: Path):
        """Explicit enforcement argument is honored."""
        cell_path = create_cell(
            cell_type="trap",
            hypothesis="Custom enforced trap",
            enforcement="gate",
            workspace=tmp_path,
        )
        content = cell_path.read_text(encoding="utf-8")
        meta = parse_frontmatter(content)
        assert meta is not None
        assert meta.get("enforcement") == "gate"

    def test_invalid_enforcement_raises_value_error(self, tmp_path: Path):
        """Invalid enforcement tier raises ValueError."""
        with pytest.raises(ValueError, match="Invalid enforcement"):
            create_cell(
                cell_type="trap",
                hypothesis="Should fail on invalid enforcement",
                enforcement="strictly_forbidden",
                workspace=tmp_path,
            )

    def test_generated_cells_pass_checkpoint_cell_conventions(self, tmp_path: Path):
        """Cells created via create_cell pass checkpoint cell_conventions checks."""
        from aegis_core.verification.checkpoint_checks import check_cell_conventions

        # Create one trap and one invariant
        create_cell(
            cell_type="trap",
            hypothesis="Coordinate inversion trap",
            id_override="trap-coord-inv",
            workspace=tmp_path,
        )
        create_cell(
            cell_type="invariant",
            hypothesis="Network sandbox invariant",
            id_override="invariant-network-sandbox",
            workspace=tmp_path,
        )

        issues = check_cell_conventions(tmp_path)
        assert issues == []
