"""Behavioral tests for structured forbid_ast call predicates, delta evaluation, and Python security pack."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aegis_core.ast.drivers.python import _call_args, _render_arg, parse_python_ast
from aegis_core.ast.policy import (
    evaluate_forbid_ast,
    evaluate_forbid_ast_delta,
    evaluate_forbid_ast_structured,
    extract_normalized_ast,
)
from aegis_core.ast.schema import CallSiteNode, NormalizedAST
from aegis_core.packs import import_pack, validate_pack
from aegis_core.rule_integrity import _forbid_patterns, _forbid_tokens
from aegis_core.verification.runner import _forbid_ast_spec_error
from aegis_core.verification.security_pack import (
    PYTHON_SECURITY_RULES,
    build_python_security_pack,
    evaluate_security_pack,
    is_test_path,
)

PACK_SPEC = {
    "calls": [
        {"name": "eval", "builtin": True},
        {"name": "exec", "builtin": True},
        "os.system",
        "os.popen",
        "pickle.loads",
        "pickle.load",
        "marshal.loads",
        "marshal.load",
        "tempfile.mktemp",
        "yaml.unsafe_load",
        {"name": "hashlib.md5", "where": {"usedforsecurity": {"not_equals": False}}},
        {"name": "hashlib.sha1", "where": {"usedforsecurity": {"not_equals": False}}},
        {"name": "subprocess.run", "where": {"shell": True}},
        {"name": "subprocess.Popen", "where": {"shell": True}},
        {"name": "subprocess.call", "where": {"shell": True}},
        {"name": "subprocess.check_output", "where": {"shell": True}},
        {"name": "yaml.load", "where": {"Loader|#1": {"in": ["Loader", "UnsafeLoader", "FullLoader"]}}},
        {"name": "hashlib.new", "where": {"name|#0": {"in": ["'md5'", "'sha1'"]}}},
        {"name": "requests.get", "where": {"verify": False}},
        {"name": "requests.post", "where": {"verify": False}},
    ]
}

UNK_FLAG_SPEC = {"calls": [{"name": "subprocess.run", "where": {"shell": True}, "unknown": "flag"}]}

# 36 probe cases covering forbid_probe2.py + predicate operators
PROBE_CASES = [
    ("eval bare TP", "x = eval(s)\n", PACK_SPEC, True),
    ("exec bare TP", "exec(code)\n", PACK_SPEC, True),
    ("builtins.eval TP", "import builtins\nbuiltins.eval(s)\n", PACK_SPEC, True),
    ("builtins alias b.eval TP", "import builtins as b\nb.eval(s)\n", PACK_SPEC, True),
    ("torch model.eval() safe", "model.eval()\n", PACK_SPEC, False),
    ("redis r.eval safe", "r.eval(script, 0)\n", PACK_SPEC, False),
    ("sqlmodel session.exec safe", "session.exec(select(User))\n", PACK_SPEC, False),
    ("self.tk.eval safe", "self.tk.eval('x')\n", PACK_SPEC, False),
    ("ast.literal_eval safe", "import ast\nast.literal_eval(s)\n", PACK_SPEC, False),
    ("shadowed eval via import", "from mylib import eval\neval(x)\n", PACK_SPEC, False),
    ("shadowed eval via local def", "def eval(x):\n    return x\neval(1)\n", PACK_SPEC, False),
    ("os.system TP", "import os\nos.system(c)\n", PACK_SPEC, True),
    ("pickle.loads TP", "import pickle\npickle.loads(b)\n", PACK_SPEC, True),
    ("import pickle as p alias TP", "import pickle as p\np.loads(b)\n", PACK_SPEC, True),
    ("json.loads safe", "import json\njson.loads(b)\n", PACK_SPEC, False),
    ("tempfile.mktemp TP", "import tempfile\ntempfile.mktemp()\n", PACK_SPEC, True),
    ("md5 default TP", "import hashlib\nhashlib.md5(b)\n", PACK_SPEC, True),
    ("md5 usedforsecurity=False safe", "import hashlib\nhashlib.md5(b, usedforsecurity=False)\n", PACK_SPEC, False),
    ("md5 usedforsecurity=True TP", "import hashlib\nhashlib.md5(b, usedforsecurity=True)\n", PACK_SPEC, True),
    ("md5 usedforsecurity=var unknown", "import hashlib\nhashlib.md5(b, usedforsecurity=flag)\n", PACK_SPEC, False),
    ("subprocess shell=True TP", "import subprocess\nsubprocess.run(c, shell=True)\n", PACK_SPEC, True),
    ("subprocess list safe", "import subprocess\nsubprocess.run(['ls'])\n", PACK_SPEC, False),
    ("subprocess shell=var ignored", "import subprocess\nsubprocess.run(c, shell=flag)\n", PACK_SPEC, False),
    ("subprocess shell=var + unknown:flag", "import subprocess\nsubprocess.run(c, shell=flag)\n", UNK_FLAG_SPEC, True),
    ("subprocess **opts + unknown:flag", "import subprocess\nsubprocess.run(c, **opts)\n", UNK_FLAG_SPEC, True),
    ("alias sp.run shell=True TP", "import subprocess as sp\nsp.run(c, shell=True)\n", PACK_SPEC, True),
    ("from subprocess import run shell=True TP", "from subprocess import run\nrun(c, shell=True)\n", PACK_SPEC, True),
    ("from subprocess import Popen as P TP", "from subprocess import Popen as P\nP(c, shell=True)\n", PACK_SPEC, True),
    ("yaml.load unsafe Loader TP", "import yaml\nyaml.load(f, Loader=yaml.Loader)\n", PACK_SPEC, True),
    ("yaml.load positional UnsafeLoader TP", "import yaml\nyaml.load(f, yaml.UnsafeLoader)\n", PACK_SPEC, True),
    ("yaml.load SafeLoader safe", "import yaml\nyaml.load(f, Loader=yaml.SafeLoader)\n", PACK_SPEC, False),
    ("yaml.load variable loader unknown", "import yaml\nyaml.load(f, self.loader)\n", PACK_SPEC, False),
    ("yaml.unsafe_load TP", "import yaml\nyaml.unsafe_load(f)\n", PACK_SPEC, True),
    ("requests verify=False TP", "import requests\nrequests.get(u, verify=False)\n", PACK_SPEC, True),
    ("requests default safe", "import requests\nrequests.get(u)\n", PACK_SPEC, False),
    ("requests verify=ca_path safe", "import requests\nrequests.get(u, verify=CA)\n", PACK_SPEC, False),
    ("hashlib.new('md5') positional TP", "import hashlib\nhashlib.new('md5')\n", PACK_SPEC, True),
]


class TestCallSiteArgsAndPredicates:
    def test_call_site_node_args_serialization_roundtrip(self):
        plain = CallSiteNode(target="foo", line=3)
        assert plain.args == {}
        assert "args" not in plain.to_dict()
        assert CallSiteNode.from_dict(plain.to_dict()) == plain

        with_args = CallSiteNode(target="subprocess.run", line=7, args={"#0": "'ls'", "shell": "True"})
        d = with_args.to_dict()
        assert d["args"] == {"#0": "'ls'", "shell": "True"}
        assert CallSiteNode.from_dict(d) == with_args

        norm = parse_python_ast("import subprocess\nsubprocess.run('ls', shell=True)\n", file_path="x.py")
        assert norm.call_sites[0].args == {"#0": "'ls'", "shell": "True"}
        assert NormalizedAST.from_json(norm.to_json()) == norm

    @pytest.mark.parametrize("label,src,spec,expected", PROBE_CASES, ids=[c[0] for c in PROBE_CASES])
    def test_forbid_probe_cases(self, label, src, spec, expected):
        norm = extract_normalized_ast("x.py", code=src)
        got = bool(evaluate_forbid_ast(norm, spec))
        assert got is expected, f"{label}: expected {expected}, got {got}"

    def test_where_operators_comprehensive(self):
        # present / absent
        spec_present = {"calls": [{"name": "f", "where": {"k": {"present": True}}}]}
        spec_absent = {"calls": [{"name": "f", "where": {"k": {"absent": True}}}]}
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="f(k=1)\n"), spec_present)) is True
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="f()\n"), spec_present)) is False
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="f()\n"), spec_absent)) is True
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="f(k=1)\n"), spec_absent)) is False

        # is_literal / not_literal
        spec_lit = {"calls": [{"name": "f", "where": {"#0": {"is_literal": True}}}]}
        spec_not_lit = {"calls": [{"name": "f", "where": {"#0": {"not_literal": True}}}]}
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="f('const')\n"), spec_lit)) is True
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="f(var)\n"), spec_lit)) is False
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="f(var)\n"), spec_not_lit)) is True
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="f(42)\n"), spec_not_lit)) is False

        # matches / contains / not_contains / not_in
        spec_matches = {"calls": [{"name": "f", "where": {"#0": {"matches": r"^(md5|sha1)$"}}}]}
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="f('md5')\n"), spec_matches)) is True
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="f('sha256')\n"), spec_matches)) is False

        spec_contains = {"calls": [{"name": "f", "where": {"#0": {"contains": "unsafe"}}}]}
        spec_not_contains = {"calls": [{"name": "f", "where": {"#0": {"not_contains": "safe"}}}]}
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="f('my_unsafe_mode')\n"), spec_contains)) is True
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="f('clean')\n"), spec_contains)) is False
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="f('raw')\n"), spec_not_contains)) is True
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="f('safe_mode')\n"), spec_not_contains)) is False

        spec_not_in = {"calls": [{"name": "yaml.load", "where": {"Loader|#1": {"not_in": ["SafeLoader", "CSafeLoader"]}}}]}
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="import yaml\nyaml.load(s, yaml.Loader)\n"), spec_not_in)) is True
        assert bool(evaluate_forbid_ast(extract_normalized_ast("x.py", code="import yaml\nyaml.load(s, yaml.SafeLoader)\n"), spec_not_in)) is False

    def test_three_valued_unknown_report_vs_skip(self):
        src_kwargs = "import subprocess\nsubprocess.run(cmd, **kwargs)\n"
        src_star = "import hashlib\nhashlib.new(*args)\n"
        norm_kw = extract_normalized_ast("x.py", code=src_kwargs)
        norm_star = extract_normalized_ast("x.py", code=src_star)

        spec_report = {"calls": [{"name": "subprocess.run", "where": {"shell": True}, "unknown": "report"}]}
        spec_skip = {"calls": [{"name": "subprocess.run", "where": {"shell": True}, "unknown": "skip"}]}
        confirmed, unverified = evaluate_forbid_ast_structured(norm_kw, spec_report, rule_id="sec-sub")
        assert confirmed == []
        assert len(unverified) == 1
        assert unverified[0]["rule_id"] == "sec-sub"

        confirmed_skip, unverified_skip = evaluate_forbid_ast_structured(norm_kw, spec_skip, rule_id="sec-sub")
        assert confirmed_skip == []
        assert unverified_skip == []

        spec_star_report = {"calls": [{"name": "hashlib.new", "where": {"#0": "'md5'"}, "unknown": "report"}]}
        c_star, u_star = evaluate_forbid_ast_structured(norm_star, spec_star_report, rule_id="sec-hash")
        assert c_star == []
        assert len(u_star) == 1


class TestDeltaEvaluationAndRunnerIntegrity:
    def test_delta_vs_base_multiset_semantics(self):
        spec = {"calls": [{"name": "subprocess.run", "where": {"shell": True}}]}
        base_code = "import subprocess\nsubprocess.run('echo 1', shell=True)\n"
        # Shifting line numbers without adding a new violation does not block
        head_shifted = "# comment\n# comment 2\nimport subprocess\nsubprocess.run('echo 1', shell=True)\n"
        base_ast = extract_normalized_ast("app.py", code=base_code)
        head_shifted_ast = extract_normalized_ast("app.py", code=head_shifted)
        assert evaluate_forbid_ast_delta(spec, head_shifted_ast, base_ast, rule_id="r1") == []

        # Adding a second identical call site increases multiset count by 1 -> blocks
        head_added = (
            "import subprocess\n"
            "subprocess.run('echo 1', shell=True)\n"
            "subprocess.run('echo 1', shell=True)\n"
        )
        delta_added = evaluate_forbid_ast_delta(
            spec, extract_normalized_ast("app.py", code=head_added), base_ast, rule_id="r1"
        )
        assert len(delta_added) == 1
        assert delta_added[0]["line"] == 3

        # Changing arguments on existing call site changes args_signature -> blocks
        head_changed_arg = "import subprocess\nsubprocess.run('rm -rf /', shell=True)\n"
        delta_changed = evaluate_forbid_ast_delta(
            spec, extract_normalized_ast("app.py", code=head_changed_arg), base_ast, rule_id="r1"
        )
        assert len(delta_changed) == 1

    def test_runner_spec_validation_and_rule_integrity_tokens(self):
        valid_spec = {
            "calls": [
                "os.system",
                {"name": "eval", "builtin": True},
                {"name": "subprocess.run", "where": {"shell": True}, "unknown": "report"},
            ]
        }
        assert _forbid_ast_spec_error(valid_spec) is None
        assert _forbid_ast_spec_error({"calls": [{}]}) is not None
        assert _forbid_ast_spec_error({"calls": [{"name": ""}]}) is not None
        assert _forbid_ast_spec_error({"calls": [{"name": "eval", "unknown": "invalid"}]}) is not None

        tokens = _forbid_tokens(valid_spec, "calls")
        assert tokens == ["os.system", "eval", "subprocess.run"]
        assert _forbid_patterns(valid_spec, "calls") == ["os.system", "eval", "subprocess.run"]
        assert _forbid_tokens(valid_spec["calls"]) == ["os.system", "eval", "subprocess.run"]


class TestPythonSecurityPack:
    def test_eight_rules_metadata_and_pack_validation(self, tmp_path: Path):
        expected_ids = {
            "sec-py-eval-exec",
            "sec-py-pickle-loads",
            "sec-py-yaml-unsafe-load",
            "sec-py-subprocess-shell",
            "sec-py-xml-etree",
            "sec-py-weak-hash-md5-sha1",
            "sec-py-tempfile-mktemp",
            "sec-py-requests-verify-false",
        }
        assert len(PYTHON_SECURITY_RULES) == 8
        assert {r["id"] for r in PYTHON_SECURITY_RULES} == expected_ids
        for rule in PYTHON_SECURITY_RULES:
            assert rule["tier"] == "invariant"
            assert rule["severity"] == "high"
            assert _forbid_ast_spec_error(rule["forbid_ast"]) is None

        pack = build_python_security_pack()
        entries = validate_pack(pack)
        assert len(entries) == 8

        # Verify pack can also be dry-run imported into an Aegis workspace
        (tmp_path / ".aegis" / "rules" / "invariants").mkdir(parents=True)
        res = import_pack(tmp_path, pack, dry_run=True)
        assert len(res.rules) == 8

    def test_is_test_path_classification(self):
        assert is_test_path("tests/unit/test_foo.py") is True
        assert is_test_path("test_example.py") is True
        assert is_test_path("pkg/foo_test.py") is True
        assert is_test_path("conftest.py") is True
        assert is_test_path("src/conftest.py") is True
        assert is_test_path("src/service.py") is False

    def test_evaluate_security_pack_delta_and_test_exemptions(self, tmp_path: Path):
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@e.st"], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True)

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        legacy_file = src_dir / "legacy.py"
        legacy_file.write_text("import tempfile\ntempfile.mktemp()\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "base"], check=True)

        # Shift legacy line without adding new violation, add a new violation in app.py, and add a hit in tests/
        legacy_file.write_text("# header\nimport tempfile\ntempfile.mktemp()\n", encoding="utf-8")
        app_file = src_dir / "app.py"
        app_file.write_text(
            "import xml.etree.ElementTree as ET\n"
            "ET.fromstring('<root/>')\n",
            encoding="utf-8",
        )
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_eval.py").write_text("eval('1+1')\n", encoding="utf-8")

        report = evaluate_security_pack(tmp_path, base_ref="HEAD")
        assert report["passed"] is False
        # legacy.py's untouched mktemp is suppressed by delta; app.py's xml.etree is flagged
        assert [v["rule_id"] for v in report["violations"]] == ["sec-py-xml-etree"]
        assert report["violations"][0]["file"] == "src/app.py"
        # tests/test_eval.py is not silently dropped: it appears in exempted_test_findings
        assert len(report["exempted_test_findings"]) == 1
        assert report["exempted_test_findings"][0]["rule_id"] == "sec-py-eval-exec"
        assert report["exempted_test_findings"][0]["file"] == "tests/test_eval.py"
