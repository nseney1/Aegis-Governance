"""Legacy-vocabulary ratchet (ADR 0005 AD-6, defense #45).

Aegis grew out of "Soma", whose biology metaphor (cells, genome, walls, membranes,
enzymes...) still names some code. ``legacy_ratchet.json`` records how often each
legacy word occurs, and the count may only go down:

- a word counts once per occurrence in an identifier (a name, attribute, function,
  class, parameter, keyword or import) or in a string literal that is not a docstring
  (output text, JSON keys, file names), across aegis_core, aegis_cli, aegis_mcp and
  aegis_sdk; ``cell_id`` and ``"Soma Governance"`` each count once;
- ``contract_snapshots`` counts the same words in the public contract snapshots
  (tests/contract/cli_tree.json and mcp_tools.json);
- three rows have a floor of 0 and stay there: imports of ``soma_*`` modules,
  ``Soma*`` class or alias definitions (both across the packages, rules/, skills/ and
  tests/), and v2 organelle rule-type words outside the one legacy table
  (taxonomy.LEGACY_TYPE_NAMES, which aegis migrate converts with).

A count above its record fails. A count below its record also fails, so the lower
number is recorded with the change that earned it and cannot creep back:

    PYTHONPATH=. python3 tests/contract/test_legacy_ratchet.py --write

The writer only lowers records; it refuses while any count is above its record.
"""
from __future__ import annotations

import ast
import functools
import json
from pathlib import Path
import re
import sys
from typing import Callable, Dict, Iterator, List

REPO = Path(__file__).resolve().parents[2]
RECORD = Path(__file__).with_name("legacy_ratchet.json")
PACKAGES = ("aegis_core", "aegis_cli", "aegis_mcp", "aegis_sdk")
SNAPSHOTS = ("cli_tree.json", "mcp_tools.json")
LEGACY_TABLE = "aegis_core/taxonomy.py"

# Rows that must exist; the record may add words but never drop one of these.
REQUIRED_WORDS = (
    "soma", "cell", "genome", "enzyme", "wall", "membrane", "vacuole", "organ", "organelle",
    "telomere", "chloroplast", "plasmodesmata", "immune", "phylogeny", "mitosis", "apoptosis",
    "spore", "mycelium", "thorn", "bedrock", "mulch", "nucleus", "cytoplasm", "ribosome",
    "symbiosis", "germline", "phenotype", "genotype", "organism", "metabolism", "homeostasis",
)
ZERO_ROWS = ("soma_imports", "soma_classes", "organelle_type_literals")
SNAPSHOT_ROW = "contract_snapshots"

_PARTS = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")
_ORGANELLE_TYPES = re.compile(r"\b(vacuoles?|chloroplasts?|plasmodesmata)\b", re.IGNORECASE)


def word_parts(text: str) -> List[str]:
    """``LEGACY_SOMA_DIRNAME`` -> legacy, soma, dirname; ``SomaCell`` -> soma, cell."""
    return [p.lower() for p in _PARTS.findall(text)]


def _is(part: str, word: str) -> bool:
    return part == word or part == word + "s"


def _python_files(dirs) -> Iterator[Path]:
    for directory in dirs:
        for path in sorted((REPO / directory).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


def _docstrings(tree: ast.AST) -> set:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _texts(tree: ast.AST) -> Iterator[str]:
    """Every identifier and every non-docstring string literal of a module."""
    docstrings = _docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.name
        elif isinstance(node, ast.arg):
            yield node.arg
        elif isinstance(node, ast.keyword) and node.arg:
            yield node.arg
        elif isinstance(node, ast.alias):
            yield node.name
            if node.asname:
                yield node.asname
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            yield from node.names
        elif isinstance(node, ast.ExceptHandler) and node.name:
            yield node.name
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.value


def _json_texts(value) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _json_texts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _json_texts(item)
    elif isinstance(value, str):
        yield value


def _word_counts(texts: Iterator[str], words) -> Dict[str, int]:
    counts = {word: 0 for word in words}
    for text in texts:
        for part in word_parts(text):
            for word in words:
                if _is(part, word):
                    counts[word] += 1
    return counts


def _soma_imports() -> List[str]:
    found = []
    for path in _python_files((*PACKAGES, "rules", "skills", "tests")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            found.extend(f"{path.relative_to(REPO).as_posix()}:{node.lineno} {n}" for n in names if n.startswith("soma_"))
    return found


def _soma_classes() -> List[str]:
    found = []
    for path in _python_files((*PACKAGES, "rules", "skills", "tests")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.ClassDef):
                names = [node.name]
            elif isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            found.extend(f"{path.relative_to(REPO).as_posix()}:{node.lineno} {n}" for n in names if n.startswith("Soma"))
    return found


def _organelle_type_literals() -> List[str]:
    found = []
    for path in _python_files(PACKAGES):
        rel = path.relative_to(REPO).as_posix()
        if rel == LEGACY_TABLE:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _ORGANELLE_TYPES.search(line):
                found.append(f"{rel}:{lineno}: {line.strip()}")
    return found


_ZERO_ROW_FINDERS: Dict[str, Callable[[], List[str]]] = {
    "soma_imports": _soma_imports,
    "soma_classes": _soma_classes,
    "organelle_type_literals": _organelle_type_literals,
}


@functools.lru_cache(maxsize=None)
def _cached_counts(words: tuple) -> Dict[str, int]:
    return current_counts(words)


def current_counts(words) -> Dict[str, int]:
    words = list(words)

    def code_texts() -> Iterator[str]:
        for path in _python_files(PACKAGES):
            yield from _texts(ast.parse(path.read_text(encoding="utf-8")))

    def snapshot_texts() -> Iterator[str]:
        for name in SNAPSHOTS:
            yield from _json_texts(json.loads((RECORD.parent / name).read_text(encoding="utf-8")))

    counts = _word_counts(code_texts(), words)
    counts[SNAPSHOT_ROW] = sum(_word_counts(snapshot_texts(), words).values())
    for row, finder in _ZERO_ROW_FINDERS.items():
        counts[row] = len(finder())
    return counts


def _record() -> Dict[str, int]:
    return json.loads(RECORD.read_text(encoding="utf-8"))["counts"]


def _words(record: Dict[str, int]) -> List[str]:
    return [row for row in record if row not in ZERO_ROWS and row != SNAPSHOT_ROW]


def test_the_record_keeps_every_required_row():
    record = _record()
    missing = [row for row in (*REQUIRED_WORDS, *ZERO_ROWS, SNAPSHOT_ROW) if row not in record]
    assert missing == [], f"legacy_ratchet.json dropped rows: {missing}"
    assert all(record[row] == 0 for row in ZERO_ROWS), "the soma import/class and organelle rows stay at 0"


def test_no_legacy_count_rose():
    record = _record()
    counts = _cached_counts(tuple(_words(record)))
    rose = {row: f"{record[row]} -> {counts[row]}" for row in record if counts[row] > record[row]}
    detail = "\n".join(
        f"  {row}: " + "; ".join(_ZERO_ROW_FINDERS[row]()[:10]) for row in rose if row in _ZERO_ROW_FINDERS
    )
    assert rose == {}, (
        "legacy vocabulary grew; use the rule vocabulary (rule, rule type, ledger, gate...) instead:\n"
        f"{rose}\n{detail}"
    )


def test_every_lowered_count_is_recorded():
    record = _record()
    counts = _cached_counts(tuple(_words(record)))
    fell = {row: f"{record[row]} -> {counts[row]}" for row in record if counts[row] < record[row]}
    assert fell == {}, (
        f"legacy counts fell {fell}: record them so they cannot rise again:\n"
        "    PYTHONPATH=. python3 tests/contract/test_legacy_ratchet.py --write"
    )


# The counter itself.
def test_word_parts_split_snake_camel_and_text():
    assert word_parts("LEGACY_SOMA_DIRNAME") == ["legacy", "soma", "dirname"]
    assert word_parts("SomaCellRegistry") == ["soma", "cell", "registry"]
    assert word_parts("<!-- SOMA:START -->") == ["soma", "start"]
    assert word_parts("prune_cells") == ["prune", "cells"]


def test_counting_sees_identifiers_and_strings_but_not_docstrings():
    tree = ast.parse(
        '"""A soma docstring."""\n'
        "import soma_x as cell_y\n"
        "def promote_cell(cell_id, *, genome=None):\n"
        '    """Cell docs."""\n'
        '    return {"cell": f"{cell_id} wall", "firewall": cancel}\n'
    )
    counts = _word_counts(_texts(tree), ("soma", "cell", "genome", "wall"))
    # soma: the import name; cell: alias, function, parameter twice, key; genome: keyword-only param;
    # wall: the f-string text (not "firewall").
    assert counts == {"soma": 1, "cell": 5, "genome": 1, "wall": 1}


def write_record() -> int:
    data = json.loads(RECORD.read_text(encoding="utf-8"))
    record = data["counts"]
    counts = current_counts(_words(record))
    rose = {row: (record[row], counts[row]) for row in record if counts[row] > record[row]}
    if rose:
        print(f"refusing to raise records: {rose}", file=sys.stderr)
        return 1
    data["counts"] = {row: min(record[row], counts[row]) for row in record}
    RECORD.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {RECORD}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        sys.exit("usage: PYTHONPATH=. python3 tests/contract/test_legacy_ratchet.py --write")
    sys.exit(write_record())
