"""Unit tests for aegis_core.enforcement (artifacts for promoted rules)."""


def test_gate_assertion_injection_sanitization():
    from aegis_core.enforcement import generate_gate_assertion
    import ast

    malicious_name = "cell\nmalicious_header_injection"
    malicious_hyp = 'Testing """ break out\nand newline injection'
    cell = {
        "name": malicious_name,
        "type": "wall",
        "hypothesis": malicious_hyp,
        "target_paths": ["src/*.py"],
    }
    code = generate_gate_assertion(cell, workspace="/tmp")
    assert "\nmalicious_header_injection" not in code.splitlines()[0]
    tree = ast.parse(code)
    assert tree is not None


def test_enforcement_load_cells(tmp_path):
    from aegis_core.enforcement import load_cells

    cells_dir = tmp_path / ".aegis" / "rules" / "walls"
    cells_dir.mkdir(parents=True)
    (cells_dir / "wall-1.md").write_text(
        "---\nid: wall-1\ntype: wall\nhypothesis: test\n---\nbody",
        encoding="utf-8",
    )
    cells = load_cells(str(tmp_path / ".aegis" / "rules"))
    assert len(cells) == 1
    assert cells[0]["id"] == "wall-1"

