"""aegis_sdk.cells.parse_cell_file must tolerate a UTF-8 BOM (PowerShell 5.1)."""
from aegis_sdk.cells import parse_cell_file


def test_bom_prefixed_cell_parses(tmp_path):
    f = tmp_path / "cell.md"
    f.write_bytes(b"\xef\xbb\xbf---\nid: bom-cell\ntype: trap\n---\n# Body\n")
    fm, body = parse_cell_file(str(f))
    assert fm["id"] == "bom-cell"
    assert "# Body" in body


def test_bomless_cell_unchanged(tmp_path):
    f = tmp_path / "cell.md"
    f.write_text("---\nid: plain\n---\n# Body\n", encoding="utf-8")
    fm, body = parse_cell_file(str(f))
    assert fm["id"] == "plain"
    assert "# Body" in body


def test_stdlib_parse_frontmatter_nested(monkeypatch):
    import pytest
    import aegis_sdk.cells as sdk_cells
    monkeypatch.setattr(sdk_cells, "yaml", None)
    yaml_text = "id: test\ntags:\n  - a\n  - b\nfitness:\n  tp: 1\n"
    res = sdk_cells._stdlib_parse_frontmatter(yaml_text)
    assert res["id"] == "test"
    assert res["tags"] == ["a", "b"]
    assert res["fitness"] == {"tp": 1}


def test_stdlib_parse_frontmatter_invalid(monkeypatch):
    import pytest
    import aegis_sdk.cells as sdk_cells
    monkeypatch.setattr(sdk_cells, "yaml", None)
    with pytest.raises(sdk_cells.CellParseError):
        sdk_cells._stdlib_parse_frontmatter("\tkey: invalid tab")

