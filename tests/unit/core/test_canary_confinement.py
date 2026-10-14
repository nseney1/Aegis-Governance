"""Canary test verifying workspace confinement and discovery for .aegis and .soma."""
from pathlib import Path
from aegis_core.workspace.confinement import validate_workspace_path, confine_path_internal
from aegis_core.workspace.discovery import is_aegis_repo, is_aegis_repo, resolve_workspace_root
from aegis_core.workspace.base import Workspace


def test_confinement_accepts_aegis_rules(tmp_path: Path):
    """Verify validate_workspace_path accepts .aegis/rules/ workspace."""
    ws = tmp_path / "my_project"
    ws.mkdir()
    aegis_rules = ws / ".aegis" / "rules" / "invariants"
    aegis_rules.mkdir(parents=True)
    rule_file = aegis_rules / "test-rule.md"
    rule_file.write_text("---\nname: test\n---\n")

    # Should validate without error
    validated = validate_workspace_path(ws)
    assert validated == ws.resolve()

    resolved_abs, rel = confine_path_internal(ws, ".aegis/rules/invariants/test-rule.md")
    assert resolved_abs == str(rule_file.resolve())


def test_confinement_accepts_soma_cells(tmp_path: Path):
    """Verify validate_workspace_path accepts .aegis/rules/ workspace."""
    ws = tmp_path / "my_project_soma"
    ws.mkdir()
    soma_cells = ws / ".aegis" / "rules" / "walls"
    soma_cells.mkdir(parents=True)
    cell_file = soma_cells / "test-cell.md"
    cell_file.write_text("---\nname: test\n---\n")

    validated = validate_workspace_path(ws)
    assert validated == ws.resolve()

    resolved_abs, rel = confine_path_internal(ws, ".aegis/rules/walls/test-cell.md")
    assert resolved_abs == str(cell_file.resolve())


def test_workspace_discovery_dual_brand(tmp_path: Path):
    """Verify discovery detects .aegis as valid workspace and repository fingerprinting."""
    ws_aegis = tmp_path / "ws_aegis"
    ws_aegis.mkdir()
    (ws_aegis / ".aegis" / "rules").mkdir(parents=True)
    assert resolve_workspace_root(ws_aegis) == ws_aegis

    ws_obj = Workspace(ws_aegis)
    assert ws_obj.aegis_dir == ws_aegis / ".aegis"
    assert ws_obj.rules_dir == ws_aegis / ".aegis" / "rules"

    # Fingerprinting for Aegis repo
    (ws_aegis / "pyproject.toml").write_text('[project]\nname = "aegis-governance"\n')
    (ws_aegis / "aegis_core").mkdir()
    (ws_aegis / "aegis_cli").mkdir()
    assert is_aegis_repo(ws_aegis)
    assert is_aegis_repo(ws_aegis)
