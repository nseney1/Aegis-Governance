"""forbid_ast hardening (review H2).

H2: import aliasing must not change a forbid_ast verdict. ``import subprocess as sp;
sp.run()`` is judged exactly like ``import subprocess; subprocess.run()``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aegis_core.ast.drivers.python import parse_python_ast
from aegis_core.ast.policy import evaluate_forbid_ast, extract_normalized_ast
from aegis_core.ast.schema import CallSiteNode, ImportNode, NormalizedAST


def _violations(code: str, spec: dict) -> list[str]:
    return evaluate_forbid_ast(extract_normalized_ast("mod.py", code=code), spec)


# Canonical patterns only: every pattern names a real module, symbol or dotted API,
# never a local alias.
CANONICAL_SPEC = {
    "imports": [
        "subprocess", "subprocess.run", "os.path", "pickle", "run", "path",
        "xml.etree", "datetime.datetime", "pytest",
    ],
    "calls": [
        "subprocess.run", "subprocess.Popen", "run", "os.system", "system", "os.path.join",
        "join", "pickle.loads", "loads", "eval", "exec", "datetime.now",
        "datetime.datetime.now", "xml.etree.ElementTree.parse",
    ],
    "decorators": [
        "pytest.mark.xfail", "mark.xfail", "xfail", "functools.lru_cache", "lru_cache",
        "dataclass", "dataclasses.dataclass",
    ],
}


# ── H2: alias forms ≡ plain forms ─────────────────────────────────────────────

ALIAS_EQUIVALENCE = [
    pytest.param(
        "import subprocess\nsubprocess.run(['ls'])\n",
        "import subprocess as sp\nsp.run(['ls'])\n",
        "Forbidden call 'subprocess.run' matched rule forbid_ast.calls",
        id="import-module-as",
    ),
    pytest.param(
        "from subprocess import run\nrun(['ls'])\n",
        "from subprocess import run as r\nr(['ls'])\n",
        "Forbidden call 'subprocess.run' matched rule forbid_ast.calls",
        id="from-import-symbol-as",
    ),
    pytest.param(
        "import os.path\nos.path.join('a', 'b')\n",
        "import os.path as osp\nosp.join('a', 'b')\n",
        "Forbidden call 'os.path.join' matched rule forbid_ast.calls",
        id="import-dotted-module-as",
    ),
    pytest.param(
        "from os import path\npath.join('a', 'b')\n",
        "from os import path as p\np.join('a', 'b')\n",
        "Forbidden call 'os.path.join' matched rule forbid_ast.calls",
        id="from-import-submodule-as",
    ),
    pytest.param(
        "import os\nos.system('ls')\n",
        "import os as operating_system\noperating_system.system('ls')\n",
        "Forbidden call 'os.system' matched rule forbid_ast.calls",
        id="import-as-long-alias",
    ),
    pytest.param(
        "from pickle import loads\nloads(b'')\n",
        "from pickle import loads as decode\ndecode(b'')\n",
        "Forbidden call 'pickle.loads' matched rule forbid_ast.calls",
        id="from-import-as-unrelated-name",
    ),
    pytest.param(
        "import xml.etree.ElementTree\nxml.etree.ElementTree.parse('f')\n",
        "import xml.etree.ElementTree as ET\nET.parse('f')\n",
        "Forbidden call 'xml.etree.ElementTree.parse' matched rule forbid_ast.calls",
        id="import-deep-module-as",
    ),
    pytest.param(
        "from os import path, system\nsystem('ls')\npath.join('a')\n",
        "from os import path as p, system\nsystem('ls')\np.join('a')\n",
        "Forbidden import 'path' matched rule forbid_ast.imports",
        id="mixed-aliased-and-plain-names",
    ),
    pytest.param(
        "from . import sibling\nsibling.run()\n",
        "from . import sibling as s\ns.run()\n",
        "Forbidden call 'run' matched rule forbid_ast.calls",
        id="relative-import-as",
    ),
    pytest.param(
        "def f():\n    import subprocess\n    subprocess.run([])\n",
        "def f():\n    import subprocess as sp\n    sp.run([])\n",
        "Forbidden call 'subprocess.run' matched rule forbid_ast.calls",
        id="function-scoped-import-as",
    ),
    pytest.param(
        "import pytest\n@pytest.mark.xfail\ndef test_a():\n    pass\n",
        "import pytest as pt\n@pt.mark.xfail\ndef test_a():\n    pass\n",
        "Forbidden decorator 'pytest.mark.xfail' matched rule forbid_ast.decorators",
        id="decorator-module-as",
    ),
    pytest.param(
        "from functools import lru_cache\n@lru_cache(maxsize=1)\ndef f():\n    return 1\n",
        "from functools import lru_cache as memo\n@memo(maxsize=1)\ndef f():\n    return 1\n",
        "Forbidden decorator 'functools.lru_cache' matched rule forbid_ast.decorators",
        id="decorator-symbol-as",
    ),
]


class TestAliasBypassClosed:
    @pytest.mark.parametrize("plain, aliased, expected", ALIAS_EQUIVALENCE)
    def test_alias_form_yields_exactly_the_plain_form_violations(self, plain, aliased, expected):
        plain_violations = _violations(plain, CANONICAL_SPEC)
        assert expected in plain_violations
        assert _violations(aliased, CANONICAL_SPEC) == plain_violations

    @pytest.mark.parametrize(
        "code, expected",
        [
            ("import subprocess as sp\nsp.run()\n", ["Forbidden call 'subprocess.run' matched rule forbid_ast.calls"]),
            (
                "from subprocess import run as r\nr()\n",
                [
                    "Forbidden import 'subprocess.run' matched rule forbid_ast.imports",
                    "Forbidden call 'subprocess.run' matched rule forbid_ast.calls",
                ],
            ),
            (
                "import os.path as osp\nosp.join()\n",
                [
                    "Forbidden import 'os.path' matched rule forbid_ast.imports",
                    "Forbidden call 'os.path.join' matched rule forbid_ast.calls",
                ],
            ),
            (
                "from os import path as p\np.join()\n",
                [
                    "Forbidden import 'os.path' matched rule forbid_ast.imports",
                    "Forbidden call 'os.path.join' matched rule forbid_ast.calls",
                ],
            ),
        ],
        ids=["sp.run", "r", "osp.join", "p.join"],
    )
    def test_review_reproductions_report_the_forbidden_api(self, code, expected):
        spec = {"calls": ["subprocess.run", "os.path.join"], "imports": ["subprocess.run", "os.path"]}
        assert _violations(code, spec) == expected

    def test_alias_convention_call_patterns_still_match(self):
        """Patterns written against a conventional alias keep matching the literal call text."""
        code = "import numpy as np\nnp.load('weights.npy')\n"
        assert _violations(code, {"calls": ["np.load", "numpy.load"]}) == [
            "Forbidden call 'np.load' matched rule forbid_ast.calls",
            "Forbidden call 'numpy.load' matched rule forbid_ast.calls",
        ]

    def test_alias_survives_json_round_trip_for_external_drivers(self):
        """External drivers hand back NormalizedAST JSON; the alias binding must survive it."""
        original = parse_python_ast("import subprocess as sp\nsp.run([])\n", file_path="mod.py")
        restored = NormalizedAST.from_json(original.to_json())
        assert evaluate_forbid_ast(restored, {"calls": ["subprocess.run"]}) == [
            "Forbidden call 'subprocess.run' matched rule forbid_ast.calls"
        ]

    def test_alias_bound_by_mapping_import_node(self):
        norm_ast = NormalizedAST(
            file_path="mod.ts",
            language="typescript",
            imports=[{"source": "child_process", "imported_symbols": ["run"], "aliases": [["run", "execSync"]]}],
            calls=["run"],
        )
        assert evaluate_forbid_ast(norm_ast, {"calls": ["child_process.execSync"], "imports": ["execSync"]}) == [
            "Forbidden import 'execSync' matched rule forbid_ast.imports",
            "Forbidden call 'child_process.execSync' matched rule forbid_ast.calls",
        ]


# ── H2 guard: plain forms are byte-identical to the pre-fix engine ────────────

# Golden outputs recorded on base add1dbf (before this change) with CANONICAL_SPEC.
PLAIN_FORM_GOLDEN = [
    ("import subprocess\nsubprocess.run(['ls'])\n", ["Forbidden import 'subprocess' matched rule forbid_ast.imports", "Forbidden call 'subprocess.run' matched rule forbid_ast.calls", "Forbidden call 'run' matched rule forbid_ast.calls"]),
    ("import subprocess\nsubprocess.Popen(['ls'])\n", ["Forbidden import 'subprocess' matched rule forbid_ast.imports", "Forbidden call 'subprocess.Popen' matched rule forbid_ast.calls"]),
    ("from subprocess import run\nrun(['ls'])\n", ["Forbidden import 'subprocess' matched rule forbid_ast.imports", "Forbidden import 'subprocess.run' matched rule forbid_ast.imports", "Forbidden import 'run' matched rule forbid_ast.imports", "Forbidden call 'subprocess.run' matched rule forbid_ast.calls", "Forbidden call 'run' matched rule forbid_ast.calls"]),
    ("from subprocess import run, Popen\nPopen(['ls'])\n", ["Forbidden import 'subprocess' matched rule forbid_ast.imports", "Forbidden import 'subprocess.run' matched rule forbid_ast.imports", "Forbidden import 'run' matched rule forbid_ast.imports", "Forbidden call 'subprocess.Popen' matched rule forbid_ast.calls"]),
    ("import os\nos.system('ls')\n", ["Forbidden call 'os.system' matched rule forbid_ast.calls", "Forbidden call 'system' matched rule forbid_ast.calls"]),
    ("import os.path\nos.path.join('a', 'b')\n", ["Forbidden import 'os.path' matched rule forbid_ast.imports", "Forbidden call 'os.path.join' matched rule forbid_ast.calls", "Forbidden call 'join' matched rule forbid_ast.calls"]),
    ("from os import path\npath.join('a', 'b')\n", ["Forbidden import 'os.path' matched rule forbid_ast.imports", "Forbidden import 'path' matched rule forbid_ast.imports", "Forbidden call 'os.path.join' matched rule forbid_ast.calls", "Forbidden call 'join' matched rule forbid_ast.calls"]),
    ("from os import system\nsystem('ls')\n", ["Forbidden call 'os.system' matched rule forbid_ast.calls", "Forbidden call 'system' matched rule forbid_ast.calls"]),
    ("import pickle\npickle.loads(b'')\n", ["Forbidden import 'pickle' matched rule forbid_ast.imports", "Forbidden call 'pickle.loads' matched rule forbid_ast.calls", "Forbidden call 'loads' matched rule forbid_ast.calls"]),
    ("from pickle import loads\nloads(b'')\n", ["Forbidden import 'pickle' matched rule forbid_ast.imports", "Forbidden call 'pickle.loads' matched rule forbid_ast.calls", "Forbidden call 'loads' matched rule forbid_ast.calls"]),
    ("eval('1')\n", ["Forbidden call 'eval' matched rule forbid_ast.calls"]),
    ("exec('x = 1')\n", ["Forbidden call 'exec' matched rule forbid_ast.calls"]),
    ("import builtins\nbuiltins.eval('1')\n", ["Forbidden call 'eval' matched rule forbid_ast.calls"]),
    ("from . import sibling\nsibling.run()\n", ["Forbidden call 'run' matched rule forbid_ast.calls"]),
    ("from .pkg import helper\nhelper()\n", []),
    ("from datetime import datetime\ndatetime.now()\n", ["Forbidden import 'datetime.datetime' matched rule forbid_ast.imports", "Forbidden call 'datetime.now' matched rule forbid_ast.calls"]),
    ("import pytest\n@pytest.mark.xfail\ndef test_a():\n    pass\n", ["Forbidden import 'pytest' matched rule forbid_ast.imports", "Forbidden decorator 'pytest.mark.xfail' matched rule forbid_ast.decorators", "Forbidden decorator 'mark.xfail' matched rule forbid_ast.decorators", "Forbidden decorator 'xfail' matched rule forbid_ast.decorators"]),
    ("from pytest import mark\n@mark.xfail\ndef test_a():\n    pass\n", ["Forbidden import 'pytest' matched rule forbid_ast.imports", "Forbidden decorator 'mark.xfail' matched rule forbid_ast.decorators", "Forbidden decorator 'xfail' matched rule forbid_ast.decorators"]),
    ("from functools import lru_cache\n@lru_cache(maxsize=1)\ndef f():\n    return 1\n", ["Forbidden decorator 'functools.lru_cache' matched rule forbid_ast.decorators", "Forbidden decorator 'lru_cache' matched rule forbid_ast.decorators"]),
    ("from dataclasses import dataclass\n@dataclass\nclass A:\n    x: int = 0\n", ["Forbidden decorator 'dataclass' matched rule forbid_ast.decorators", "Forbidden decorator 'dataclasses.dataclass' matched rule forbid_ast.decorators"]),
    ("import json\njson.loads('{}')\n", ["Forbidden call 'loads' matched rule forbid_ast.calls"]),
    ("from os import *\nsystem('ls')\n", ["Forbidden call 'system' matched rule forbid_ast.calls"]),
    ("import xml.etree.ElementTree\nxml.etree.ElementTree.parse('f')\n", ["Forbidden import 'xml.etree' matched rule forbid_ast.imports", "Forbidden call 'xml.etree.ElementTree.parse' matched rule forbid_ast.calls"]),
    ("def run():\n    pass\nrun()\n", ["Forbidden call 'run' matched rule forbid_ast.calls"]),
    ("class A:\n    def m(self):\n        self.run()\n", ["Forbidden call 'run' matched rule forbid_ast.calls"]),
]

HANDBUILT_GOLDEN = [
    (
        NormalizedAST(file_path="m.py", imports=[{"module": "pickle", "imported_names": ["loads"]}], calls=["loads"]),
        ["Forbidden import 'pickle' matched rule forbid_ast.imports", "Forbidden call 'pickle.loads' matched rule forbid_ast.calls", "Forbidden call 'loads' matched rule forbid_ast.calls"],
    ),
    (
        NormalizedAST(file_path="m.py", imports=["subprocess.run"], calls=["run", "subprocess.run"]),
        ["Forbidden import 'subprocess' matched rule forbid_ast.imports", "Forbidden import 'subprocess.run' matched rule forbid_ast.imports", "Forbidden import 'run' matched rule forbid_ast.imports", "Forbidden call 'subprocess.run' matched rule forbid_ast.calls", "Forbidden call 'run' matched rule forbid_ast.calls"],
    ),
    (
        NormalizedAST(
            file_path="m.py",
            imports=[ImportNode(source="os", imported_symbols=("path", "system"))],
            call_sites=[CallSiteNode(target="path.join"), CallSiteNode(target="system")],
        ),
        ["Forbidden import 'os.path' matched rule forbid_ast.imports", "Forbidden import 'path' matched rule forbid_ast.imports", "Forbidden call 'os.system' matched rule forbid_ast.calls", "Forbidden call 'system' matched rule forbid_ast.calls", "Forbidden call 'os.path.join' matched rule forbid_ast.calls", "Forbidden call 'join' matched rule forbid_ast.calls"],
    ),
    (
        NormalizedAST(file_path="m.py", imports=[ImportNode(source="", imported_symbols=("run",))], calls=["run"]),
        ["Forbidden import 'run' matched rule forbid_ast.imports", "Forbidden call 'run' matched rule forbid_ast.calls"],
    ),
]


class TestPlainFormsUnchanged:
    @pytest.mark.parametrize("code, expected", PLAIN_FORM_GOLDEN)
    def test_plain_form_violations_match_pre_fix_golden(self, code, expected):
        assert _violations(code, CANONICAL_SPEC) == expected

    @pytest.mark.parametrize("norm_ast, expected", HANDBUILT_GOLDEN)
    def test_handbuilt_ast_violations_match_pre_fix_golden(self, norm_ast, expected):
        assert evaluate_forbid_ast(norm_ast, CANONICAL_SPEC) == expected

    @pytest.mark.parametrize("code", [c for c, _ in PLAIN_FORM_GOLDEN])
    def test_plain_form_serialization_carries_no_alias_key(self, code):
        assert '"aliases"' not in parse_python_ast(code, file_path="mod.py").to_json()
