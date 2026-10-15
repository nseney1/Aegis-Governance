"""Unit tests for NormalizedAST schema, serialization, and Python native driver."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from aegis_core.ast.schema import (
    CallSiteNode,
    DefinitionNode,
    ImportNode,
    MutationPoint,
    NormalizedAST,
)
from aegis_core.ast.drivers.python import parse_python_ast


def test_schema_roundtrip_dict_and_json():
    ast_obj = NormalizedAST(
        file_path="src/service.ts",
        language="typescript",
        definitions=(
            DefinitionNode(name="login", kind="function", line=10, is_exported=True),
            DefinitionNode(name="validate", kind="method", line=20, is_exported=False, class_name="AuthService"),
        ),
        call_sites=(
            CallSiteNode(target="hashPassword", line=12, caller_scope="login"),
            CallSiteNode(target="db.find", line=14, caller_scope="login"),
        ),
        imports=(
            ImportNode(source="crypto", imported_symbols=("hashPassword",), line=1),
            ImportNode(source="./db", imported_symbols=("db",), line=2),
        ),
        mutation_points=(
            MutationPoint(line=15, col=8, original_op="===", replacement_op="!=="),
        ),
        metadata={"parser": "test"},
    )

    data = ast_obj.to_dict()
    assert data["language"] == "typescript"
    assert data["file_path"] == "src/service.ts"
    assert len(data["definitions"]) == 2
    assert data["definitions"][0]["name"] == "login"
    assert data["definitions"][0]["is_exported"] is True
    assert data["definitions"][1]["class_name"] == "AuthService"
    assert len(data["call_sites"]) == 2
    assert len(data["imports"]) == 2
    assert len(data["mutation_points"]) == 1

    json_str = ast_obj.to_json()
    reconstructed = NormalizedAST.from_json(json_str)
    assert reconstructed == ast_obj
    assert reconstructed.find_definition("login") == ast_obj.definitions[0]
    assert reconstructed.find_definition("nonexistent") is None
    assert len(reconstructed.get_exported_definitions()) == 1
    assert len(reconstructed.get_calls_in_scope("login")) == 2


def test_schema_validation_rejects_malformed_payload():
    with pytest.raises(ValueError, match="file_path cannot be empty"):
        NormalizedAST(file_path="", language="python", definitions=(), call_sites=(), imports=())

    with pytest.raises(ValueError, match="language cannot be empty"):
        NormalizedAST(file_path="test.py", language="", definitions=(), call_sites=(), imports=())


def test_python_driver_extracts_definitions_and_exports(tmp_path):
    code = """
__all__ = ["public_api", "Worker"]

def public_api():
    internal_helper()

def internal_helper():
    pass

class Worker:
    def execute(self):
        public_api()
"""
    py_file = tmp_path / "worker.py"
    py_file.write_text(code, encoding="utf-8")

    norm_ast = parse_python_ast(py_file)
    assert norm_ast.language == "python"
    assert norm_ast.file_path == str(py_file)

    defs = {d.name: d for d in norm_ast.definitions}
    assert "public_api" in defs
    assert defs["public_api"].is_exported is True
    assert defs["public_api"].kind == "function"

    assert "internal_helper" in defs
    assert defs["internal_helper"].is_exported is False

    assert "Worker" in defs
    assert defs["Worker"].is_exported is True
    assert defs["Worker"].kind == "class"

    assert "execute" in defs
    assert defs["execute"].is_method is True
    assert defs["execute"].class_name == "Worker"


def test_python_driver_extracts_calls_and_imports(tmp_path):
    code = """
import os
from sys import exit as sys_exit

def process():
    os.path.join("a", "b")
    sys_exit(0)
"""
    py_file = tmp_path / "processor.py"
    py_file.write_text(code, encoding="utf-8")

    norm_ast = parse_python_ast(py_file)

    # Imports
    imports_by_source = {imp.source: imp for imp in norm_ast.imports}
    assert "os" in imports_by_source
    assert "sys" in imports_by_source
    assert "sys_exit" in imports_by_source["sys"].imported_symbols

    # Calls
    call_targets = {c.target for c in norm_ast.call_sites}
    assert "os.path.join" in call_targets
    assert "sys_exit" in call_targets

    # Check caller scopes
    for c in norm_ast.call_sites:
        assert c.caller_scope == "process"


def test_python_driver_extracts_mutations(tmp_path):
    code = """
def check_value(x):
    if x == 42 and True:
        return x + 1
    return 0
"""
    py_file = tmp_path / "mutate_target.py"
    py_file.write_text(code, encoding="utf-8")

    norm_ast = parse_python_ast(py_file)
    ops = [m.original_op for m in norm_ast.mutation_points]
    assert "==" in ops
    assert "+" in ops


def test_python_driver_records_import_aliases():
    code = "import os.path as osp\nfrom os import sep, path as p\nimport json\n"

    imports = parse_python_ast(code, file_path="mod.py").imports

    assert [(i.source, i.imported_symbols, i.aliases) for i in imports] == [
        ("os.path", ("osp",), (("osp", "os.path"),)),
        ("os", ("sep", "p"), (("p", "path"),)),
        ("json", ("json",), ()),
    ]
