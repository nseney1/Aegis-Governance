"""aegis_sdk.parse_rule_file must tolerate a UTF-8 BOM (PowerShell 5.1)."""
from aegis_sdk import parse_rule_file


def test_bom_prefixed_cell_parses(tmp_path):
    f = tmp_path / "cell.md"
    f.write_bytes(b"\xef\xbb\xbf---\nid: bom-cell\ntype: trap\n---\n# Body\n")
    fm, body = parse_rule_file(str(f))
    assert fm["id"] == "bom-cell"
    assert "# Body" in body


def test_bomless_cell_unchanged(tmp_path):
    f = tmp_path / "cell.md"
    f.write_text("---\nid: plain\n---\n# Body\n", encoding="utf-8")
    fm, body = parse_rule_file(str(f))
    assert fm["id"] == "plain"
    assert "# Body" in body


