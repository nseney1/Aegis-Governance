"""aegis_core.packs: unsigned rule packs (v4.2 #3).

A pack is ``{"v": 1, "rules": [{"path", "text", "sha256"}], "sha256": <bundle digest>}``.
It is unsigned and travels between repositories, so every field of an imported one is
attacker-controlled: the digests prove the pack was not altered after export, never who
made it. These tests hold the import to its contract:

- each ``path`` is parsed strictly as ``<type dir>/<id>.md`` and the write target is built
  from the parsed parts, so no pack can write outside ``.aegis/rules/<type dir>/``;
- every entry must yield exactly one error-free, served rule through the one loader, on a
  staged inventory, with the id and type of its path;
- a collision (an id some rule of the workspace already has) refuses the whole pack unless
  ``rename``; nothing is written unless every entry is accepted;
- ``dry_run`` writes nothing at all, not even the state directory.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from aegis_core import events, packs
from aegis_core.packs import PackError
from aegis_core.rules import load_rules
from aegis_core.taxonomy import RULE_TYPE_DIRS
from aegis_core.yaml_engine.serializer import dump_frontmatter
from tests.helpers_rule import write_evidence


def _text(rule_id: str, rule_type: str = "trap", **extra: Any) -> str:
    meta: Dict[str, Any] = {
        "id": rule_id,
        "type": rule_type,
        "enforcement": "gate" if rule_type in ("invariant", "gate") else "advisory",
        "hypothesis": f"Test rule {rule_id}",
        "target_paths": ["src/**/*.py"],
    }
    meta.update(extra)
    return dump_frontmatter(meta, body=f"# {rule_id}\nBody of {rule_id}.\n")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _entry(path: str, text: str) -> Dict[str, Any]:
    return {"path": path, "text": text, "sha256": _digest(text)}


def _pack(*entries: Dict[str, Any]) -> Dict[str, Any]:
    rules = list(entries)
    return {"v": 1, "rules": rules, "sha256": packs.bundle_digest(rules)}


def _wire(pack: Dict[str, Any]) -> bytes:
    return json.dumps(pack).encode("utf-8")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / ".aegis" / "rules").mkdir(parents=True)
    return root.resolve()


def _put(ws: Path, rule_type: str, rule_id: str, text: str = "") -> Path:
    path = ws / ".aegis" / "rules" / RULE_TYPE_DIRS[rule_type] / f"{rule_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or _text(rule_id, rule_type), encoding="utf-8")
    return path


def _tree(root: Path) -> List[str]:
    """Every path under root with its size: a change anywhere shows up."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames:
            found.append(os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/") + "/")
        for name in filenames:
            full = os.path.join(dirpath, name)
            found.append(f"{os.path.relpath(full, root).replace(os.sep, '/')}:{os.path.getsize(full)}")
    return sorted(found)


def _problems(excinfo: pytest.ExceptionInfo) -> str:
    return "\n".join(excinfo.value.problems)


# ── the path, parsed strictly ────────────────────────────────────────────────

@pytest.mark.parametrize("directory,rule_type", sorted((d, t) for t, d in RULE_TYPE_DIRS.items()))
def test_a_path_is_a_type_directory_and_an_id(directory, rule_type):
    parsed = packs.parse_pack_path(f"{directory}/my-rule_1.v2.md")
    assert (parsed.directory, parsed.type, parsed.id) == (directory, rule_type, "my-rule_1.v2")


@pytest.mark.parametrize("path,reason", [
    ("", "the path is empty"),
    ("x.md", "must be exactly <type dir>/<id>.md"),
    ("traps/", "must be exactly <type dir>/<id>.md"),
    ("traps//x.md", "must be exactly <type dir>/<id>.md"),
    ("/traps/x.md", "must be exactly <type dir>/<id>.md"),
    ("traps/sub/x.md", "must be exactly <type dir>/<id>.md"),
    ("../x.md", "must be exactly <type dir>/<id>.md"),
    ("traps/../x.md", "must be exactly <type dir>/<id>.md"),
    ("../../.github/workflows/x.yml", "must be exactly <type dir>/<id>.md"),
    (".aegis/config.json", "unknown type directory '.aegis'"),
    ("traps\\x.md", "a backslash, a colon or a control character"),
    ("C:/x.md", "a backslash, a colon or a control character"),
    ("traps/x\x00.md", "a backslash, a colon or a control character"),
    ("traps/x\n.md", "a backslash, a colon or a control character"),
    ("walls/x.md", "unknown type directory 'walls'"),
    ("Traps/x.md", "unknown type directory 'Traps'"),
    (".archive/x.md", "unknown type directory '.archive'"),
    ("traps/x.MD", "must end in lowercase .md"),
    ("traps/x.txt", "must end in lowercase .md"),
    ("traps/x.md.md.txt", "must end in lowercase .md"),
    ("traps/.md", "is not a usable rule id"),
    ("traps/.hidden.md", "hidden file"),
    ("traps/README.md", "README"),
    ("traps/readme.md", "README"),
    ("traps/x y.md", "is not a usable rule id"),
    ("traps/caf\u00e9.md", "is not a usable rule id"),
    ("traps/a..b.md", "the id 'a..b' contains a path separator or '..' (path traversal)"),
    ("traps/con.md", "reserved device name"),
    ("traps/NUL.md", "reserved device name"),
    ("traps/com1.md", "reserved device name"),
    ("traps/" + "a" * 129 + ".md", "is not a usable rule id"),
])
def test_a_path_that_is_not_exactly_type_dir_slash_id_md_is_refused(path, reason):
    with pytest.raises(packs.PackPathError) as info:
        packs.parse_pack_path(path)
    assert reason in str(info.value)


def test_a_path_that_is_not_text_is_refused():
    with pytest.raises(packs.PackPathError) as info:
        packs.parse_pack_path(5)
    assert str(info.value) == "the path must be a string, not int"


def test_the_longest_usable_id_is_128_characters():
    assert packs.parse_pack_path("traps/" + "a" * 128 + ".md").id == "a" * 128


# ── export: which rules, and what text ───────────────────────────────────────

def test_export_takes_every_loadable_rule_in_path_order(ws):
    _put(ws, "trap", "b-trap")
    _put(ws, "invariant", "a-inv")
    selection = packs.select_rules(ws)
    pack = packs.build_pack(selection.rules)
    assert [e["path"] for e in pack["rules"]] == ["invariants/a-inv.md", "traps/b-trap.md"]
    assert selection.skipped == ()


def test_the_text_of_an_exported_rule_is_the_file_and_its_digest_covers_that_text(ws):
    path = _put(ws, "trap", "keep-me")
    pack = packs.build_pack(packs.select_rules(ws).rules)
    (entry,) = pack["rules"]
    assert entry["text"] == path.read_text(encoding="utf-8")
    assert entry["sha256"] == _digest(entry["text"])


def test_the_bundle_digest_covers_every_path_text_and_entry_digest(ws):
    _put(ws, "trap", "one")
    _put(ws, "trap", "two")
    pack = packs.build_pack(packs.select_rules(ws).rules)
    assert pack["v"] == 1 and set(pack) == {"v", "rules", "sha256"}
    assert pack["sha256"] == packs.bundle_digest(pack["rules"])
    for field, value in (("path", "traps/other.md"), ("text", "changed"), ("sha256", "0" * 64)):
        tampered = [dict(e) for e in pack["rules"]]
        tampered[0][field] = value
        assert packs.bundle_digest(tampered) != pack["sha256"], field
    assert packs.bundle_digest(list(reversed(pack["rules"]))) != pack["sha256"]


def test_the_same_workspace_exports_the_same_bytes_twice(ws):
    _put(ws, "trap", "one")
    _put(ws, "gate", "two")
    first = packs.dump_pack(packs.build_pack(packs.select_rules(ws).rules))
    second = packs.dump_pack(packs.build_pack(packs.select_rules(ws).rules))
    assert first == second and first.endswith(b"\n")


def test_export_filters_by_type(ws):
    _put(ws, "trap", "a-trap")
    _put(ws, "invariant", "an-invariant")
    _put(ws, "gate", "a-gate")
    rules = packs.select_rules(ws, types=("trap", "gate")).rules
    assert sorted(r.id for r in rules) == ["a-gate", "a-trap"]


def test_export_filters_by_the_fitness_of_the_exporting_ledger(ws):
    _put(ws, "trap", "proven")
    _put(ws, "trap", "unproven")
    write_evidence(ws, "proven", triggers=40, tp=40)
    rules = packs.select_rules(ws, min_fitness=0.5).rules
    assert [r.id for r in rules] == ["proven"]


def test_export_with_a_fitness_floor_leaves_out_a_rule_with_no_evidence(ws):
    _put(ws, "trap", "no-evidence")
    with pytest.raises(PackError) as info:
        packs.select_rules(ws, min_fitness=0.1)
    assert _problems(info) == "no rules to export: none matches the type and fitness filters"


def test_export_refuses_a_rule_the_loader_cannot_serve(ws):
    _put(ws, "trap", "fine")
    _put(ws, "trap", "broken", _text("other-id"))
    with pytest.raises(PackError) as info:
        packs.select_rules(ws)
    assert _problems(info) == (
        ".aegis/rules/traps/broken.md: id 'other-id' does not match the file name 'broken'; "
        "fix or move it, then export again"
    )


def test_export_refuses_a_rule_with_derived_or_retired_keys_and_names_the_fix(ws):
    stale = _text("stale", fitness={"score": 0.9}, enforcement_artifact="x.py")
    _put(ws, "trap", "stale", stale)
    with pytest.raises(PackError) as info:
        packs.build_pack(packs.select_rules(ws).rules)
    assert _problems(info) == (
        "traps/stale.md still has derived or retired keys (enforcement_artifact, fitness): "
        "run aegis migrate --apply, then export again"
    )


def test_export_skips_an_expired_rule_and_says_so(ws):
    _put(ws, "trap", "live")
    _put(ws, "trap", "gone", _text("gone", expired_at="2026-01-01"))
    selection = packs.select_rules(ws)
    assert [r.id for r in selection.rules] == ["live"]
    assert selection.skipped == (("gone", "expired"),)


def test_export_of_an_empty_workspace_is_refused(ws):
    with pytest.raises(PackError) as info:
        packs.select_rules(ws)
    assert _problems(info) == "no rules to export: none matches the type and fitness filters"


def test_export_refuses_an_id_the_importer_would_refuse(ws):
    _put(ws, "trap", "has space", _text("has space"))
    with pytest.raises(PackError) as info:
        packs.build_pack(packs.select_rules(ws).rules)
    assert "traps/has space.md" in _problems(info) and "is not a usable rule id" in _problems(info)


def test_export_refuses_a_rule_too_large_to_import(ws):
    big = _text("big") + "x" * packs.MAX_RULE_BYTES
    _put(ws, "trap", "big", big)
    with pytest.raises(PackError) as info:
        packs.build_pack(packs.select_rules(ws).rules)
    assert f"traps/big.md: {len(big.encode('utf-8'))} bytes exceeds the {packs.MAX_RULE_BYTES} byte limit" in _problems(info)


# ── reading a pack: strict ───────────────────────────────────────────────────

def _good() -> Dict[str, Any]:
    return _pack(_entry("traps/one.md", _text("one")), _entry("invariants/two.md", _text("two", "invariant")))


def test_a_pack_round_trips_through_its_bytes(ws):
    _put(ws, "trap", "one")
    pack = packs.build_pack(packs.select_rules(ws).rules)
    assert packs.load_pack(packs.dump_pack(pack)) == pack


def _refusal(data: bytes) -> str:
    with pytest.raises(PackError) as info:
        packs.load_pack(data)
    return _problems(info)


def test_a_pack_that_is_not_json_is_refused():
    assert _refusal(b"{not json").startswith("the pack is not valid JSON: ")


def test_a_pack_that_is_not_utf8_is_refused():
    assert _refusal(b"\xff\xfe{}") == "the pack is not valid UTF-8"


def test_a_pack_over_the_size_limit_is_refused():
    assert _refusal(b" " * (packs.MAX_PACK_BYTES + 1)) == f"the pack exceeds {packs.MAX_PACK_BYTES} bytes"


def test_a_pack_that_nests_too_deep_is_refused_not_crashed():
    assert _refusal(b"[" * 100000).startswith("the pack is not valid JSON: ")


@pytest.mark.parametrize("raw", [b"[]", b'"x"', b"1", b"null"])
def test_a_pack_that_is_not_an_object_is_refused(raw):
    assert _refusal(raw) == 'a pack is a JSON object with exactly the keys "v", "rules" and "sha256"'


@pytest.mark.parametrize("mutate", [
    lambda p: p.pop("sha256"),
    lambda p: p.pop("v"),
    lambda p: p.update(extra=1),
    lambda p: p.update(signature="deadbeef"),
])
def test_a_pack_with_missing_or_unknown_top_level_keys_is_refused(mutate):
    pack = _good()
    mutate(pack)
    assert _refusal(_wire(pack)) == 'a pack is a JSON object with exactly the keys "v", "rules" and "sha256"'


@pytest.mark.parametrize("version", [0, 2, "1", 1.0, True, None])
def test_a_pack_of_another_version_is_refused(version):
    pack = _good()
    pack["v"] = version
    assert _refusal(_wire(pack)) == f"unsupported pack version {version!r}: this aegis reads version 1"


def test_a_duplicate_key_is_refused_so_the_digest_cannot_hide_a_second_value():
    raw = b'{"v": 1, "v": 1, "rules": [], "sha256": ""}'
    assert _refusal(raw) == "the pack is not valid JSON: duplicate key 'v'"


def test_a_non_finite_number_is_refused():
    raw = b'{"v": NaN, "rules": [], "sha256": ""}'
    assert _refusal(raw) == "the pack is not valid JSON: NaN is not allowed"


@pytest.mark.parametrize("rules", [None, {}, "x", 3])
def test_rules_must_be_a_list(rules):
    pack = _good()
    pack["rules"] = rules
    assert _refusal(_wire(pack)) == '"rules" must be a list'


def test_an_empty_pack_is_refused():
    assert _refusal(_wire(_pack())) == "the pack holds no rules"


def test_a_pack_over_the_rule_count_limit_is_refused():
    entries = [_entry(f"traps/r{i}.md", _text(f"r{i}")) for i in range(packs.MAX_PACK_RULES + 1)]
    assert _refusal(_wire(_pack(*entries))) == f"the pack holds more than {packs.MAX_PACK_RULES} rules"


@pytest.mark.parametrize("entry,message", [
    ("x", "rules[0]: an entry is an object with exactly the keys \"path\", \"text\" and \"sha256\""),
    ({"path": "traps/one.md", "text": "t"}, "rules[0]: an entry is an object with exactly the keys \"path\", \"text\" and \"sha256\""),
    ({"path": "traps/one.md", "text": "t", "sha256": "0" * 64, "mode": "0777"},
     "rules[0]: an entry is an object with exactly the keys \"path\", \"text\" and \"sha256\""),
    ({"path": "traps/one.md", "text": 5, "sha256": "0" * 64}, "rules[0]: \"text\" must be a string"),
    ({"path": "traps/one.md", "text": "t", "sha256": 5}, "rules[0]: \"sha256\" must be 64 lowercase hex digits"),
    ({"path": "traps/one.md", "text": "t", "sha256": "A" * 64}, "rules[0]: \"sha256\" must be 64 lowercase hex digits"),
    ({"path": "traps/one.md", "text": "t", "sha256": "0" * 63}, "rules[0]: \"sha256\" must be 64 lowercase hex digits"),
])
def test_a_malformed_entry_is_refused(entry, message):
    pack = {"v": 1, "rules": [entry], "sha256": "0" * 64}
    assert message in _refusal(_wire(pack)).splitlines()


def test_an_entry_whose_text_does_not_match_its_digest_is_refused():
    pack = _good()
    pack["rules"][0]["text"] += "tampered"
    pack["sha256"] = packs.bundle_digest(pack["rules"])
    assert _refusal(_wire(pack)) == "rules[0] (traps/one.md): the text does not match its sha256"


def test_a_pack_whose_bundle_digest_does_not_match_is_refused():
    pack = _good()
    pack["sha256"] = "0" * 64
    assert _refusal(_wire(pack)) == "the pack sha256 does not match its rules: it was altered after export"


def test_a_pack_with_an_entry_swapped_for_another_is_refused_by_the_bundle_digest():
    pack = _good()
    pack["rules"][0] = _entry("traps/evil.md", _text("evil"))
    assert _refusal(_wire(pack)) == "the pack sha256 does not match its rules: it was altered after export"


def test_an_entry_text_that_is_not_encodable_is_refused():
    entry = {"path": "traps/one.md", "text": "bad \ud800", "sha256": "0" * 64}
    pack = {"v": 1, "rules": [entry], "sha256": "0" * 64}
    raw = json.dumps(pack).encode("ascii")  # json escapes the lone surrogate
    assert "rules[0] (traps/one.md): the text is not valid UTF-8" in _refusal(raw).splitlines()


def test_an_oversize_entry_is_refused():
    text = _text("one") + "x" * packs.MAX_RULE_BYTES
    assert (f"rules[0] (traps/one.md): {len(text.encode('utf-8'))} bytes exceeds the {packs.MAX_RULE_BYTES} byte limit"
            in _refusal(_wire(_pack(_entry("traps/one.md", text)))).splitlines())


def test_the_same_path_twice_is_refused():
    entry = _entry("traps/one.md", _text("one"))
    problems = _refusal(_wire(_pack(entry, dict(entry)))).splitlines()
    assert "rules[1] (traps/one.md): the path appears twice in the pack" in problems


def test_the_same_id_in_two_type_directories_is_refused():
    pack = _pack(_entry("traps/one.md", _text("one")), _entry("gates/one.md", _text("one", "gate")))
    assert "rules[1] (gates/one.md): the id 'one' is also used by traps/one.md" in _refusal(_wire(pack)).splitlines()


def test_every_bad_path_is_reported_and_the_whole_pack_is_refused():
    pack = _pack(_entry("../x.md", "a"), _entry("traps/ok.md", _text("ok")), _entry("walls/y.md", "b"))
    problems = _refusal(_wire(pack)).splitlines()
    assert len(problems) == 2
    assert problems[0].startswith("rules[0] ('../x.md'): the path must be exactly <type dir>/<id>.md")
    assert problems[1].startswith("rules[2] ('walls/y.md'): unknown type directory 'walls'")


# ── import ───────────────────────────────────────────────────────────────────

def _import(ws: Path, pack: Dict[str, Any], **options: Any):
    return packs.import_pack(ws, packs.load_pack(_wire(pack)), **options)


def _refused_import(ws: Path, pack: Dict[str, Any], **options: Any) -> str:
    with pytest.raises(PackError) as info:
        _import(ws, pack, **options)
    return _problems(info)


def test_import_writes_each_rule_where_its_path_says_with_its_exact_bytes(ws):
    result = _import(ws, _good())
    assert (ws / ".aegis/rules/traps/one.md").read_bytes() == _text("one").encode("utf-8")
    assert (ws / ".aegis/rules/invariants/two.md").read_bytes() == _text("two", "invariant").encode("utf-8")
    assert [(r.path, r.id, r.type, r.renamed_from) for r in result.rules] == [
        (".aegis/rules/invariants/two.md", "two", "invariant", None),
        (".aegis/rules/traps/one.md", "one", "trap", None),
    ]
    assert result.dry_run is False and result.pack_sha256 == _good()["sha256"]


def test_imported_rules_load_clean_and_start_with_no_ledger_evidence(ws):
    _import(ws, _good())
    ruleset = load_rules(ws)
    assert [(r.id, r.type, r.error) for r in ruleset.rules] == [("two", "invariant", None), ("one", "trap", None)]
    assert not (ws / ".aegis/state/ledger.jsonl").exists()


def test_a_dry_run_writes_nothing_not_even_the_state_directory(ws):
    before = _tree(ws)
    result = _import(ws, _good(), dry_run=True)
    assert _tree(ws) == before
    assert result.dry_run is True and len(result.rules) == 2
    assert events.read(ws).rows == []


def test_a_real_import_appends_one_pack_import_event(ws):
    _import(ws, _good())
    (row,) = events.read(ws, "pack_import").rows
    assert row["result"] == "imported"
    assert row["detail"] == {"rules": 2, "renamed": 0, "types": {"invariant": 1, "trap": 1}, "pack_sha256": _good()["sha256"]}


def test_a_refused_import_writes_no_event(ws):
    _put(ws, "trap", "one")
    _refused_import(ws, _good())
    assert events.read(ws, "pack_import").rows == []


def test_an_event_that_cannot_be_recorded_does_not_undo_the_import(ws, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(events, "append", broken)
    result = _import(ws, _good())
    assert (ws / ".aegis/rules/traps/one.md").is_file()
    assert result.warnings == ("the pack_import event could not be recorded (OSError: disk full)",)


def test_an_id_a_workspace_rule_already_has_refuses_the_whole_pack_and_writes_nothing(ws):
    _put(ws, "trap", "one", _text("one") + "mine\n")
    before = _tree(ws)
    assert _refused_import(ws, _good()) == (
        "rules[0] (traps/one.md): the id 'one' is already used by .aegis/rules/traps/one.md; "
        "import with --rename to keep both"
    )
    assert _tree(ws) == before
    assert not (ws / ".aegis/rules/invariants").exists()  # the rule that did not collide was not written either
    assert (ws / ".aegis/rules/traps/one.md").read_text(encoding="utf-8").endswith("mine\n")


def test_an_id_used_in_another_type_directory_collides_too(ws):
    _put(ws, "gate", "one")
    assert "the id 'one' is already used by .aegis/rules/gates/one.md" in _refused_import(ws, _good())


def test_an_id_held_by_a_broken_rule_collides_too(ws):
    _put(ws, "trap", "one", "no frontmatter at all\n")
    assert "the id 'one' is already used by .aegis/rules/traps/one.md" in _refused_import(ws, _good())


def test_rename_gives_a_colliding_rule_a_free_id_and_keeps_the_existing_one(ws):
    original = _put(ws, "trap", "one", _text("one") + "mine\n")
    result = _import(ws, _good(), rename=True)
    renamed = ws / ".aegis/rules/traps/one-imported.md"
    assert renamed.is_file() and original.read_text(encoding="utf-8").endswith("mine\n")
    assert renamed.read_text(encoding="utf-8") == _text("one").replace("id: one\n", "id: one-imported\n")
    by_id = {r.id: r for r in result.rules}
    assert by_id["one-imported"].renamed_from == "one" and by_id["two"].renamed_from is None
    assert sorted((r.id, r.error) for r in load_rules(ws).rules if r.id.startswith("one")) == [
        ("one", None), ("one-imported", None)]


def test_rename_counts_up_when_the_renamed_id_is_taken_too(ws):
    _put(ws, "trap", "one")
    _import(ws, _good(), rename=True)
    _import(ws, _good(), rename=True)
    assert sorted(p.name for p in (ws / ".aegis/rules/traps").iterdir()) == [
        "one-imported-2.md", "one-imported.md", "one.md"]
    assert all(r.error is None for r in load_rules(ws).rules)


def test_rename_leaves_a_rule_without_a_frontmatter_id_to_take_its_id_from_the_file_name(ws):
    text = dump_frontmatter({"type": "trap", "enforcement": "advisory", "target_paths": ["a/*.py"]}, body="b\n")
    _put(ws, "trap", "one")
    _import(ws, _pack(_entry("traps/one.md", text)), rename=True)
    assert (ws / ".aegis/rules/traps/one-imported.md").read_text(encoding="utf-8") == text
    assert load_rules(ws).get("one-imported") is not None


def test_rename_does_not_hide_a_pack_that_contradicts_itself(ws):
    _put(ws, "trap", "one")
    pack = _pack(_entry("traps/one.md", _text("liar")))
    assert _refused_import(ws, pack, rename=True) == (
        "rules[0] (traps/one.md): id 'liar' does not match the file name 'one'")


def test_a_dry_run_reports_the_renames_it_would_make(ws):
    _put(ws, "trap", "one")
    before = _tree(ws)
    result = _import(ws, _good(), rename=True, dry_run=True)
    assert _tree(ws) == before
    assert {(r.id, r.renamed_from) for r in result.rules} == {("one-imported", "one"), ("two", None)}


def test_rename_refuses_an_id_too_long_to_extend(ws):
    long_id = "a" * 125
    _put(ws, "trap", long_id)
    pack = _pack(_entry(f"traps/{long_id}.md", _text(long_id)))
    assert _refused_import(ws, pack, rename=True) == (
        f"rules[0] (traps/{long_id}.md): no usable renamed id: '{long_id}-imported' is longer than 128 characters")


@pytest.mark.parametrize("text,reason", [
    ("no frontmatter\n", "no frontmatter metadata"),
    (_text("one", enforcement="loud"), "unknown enforcement 'loud' (expected one of advisory, mechanical, gate)"),
    (_text("one", paths=["a"]), "unknown enforcement-relevant key(s) 'paths' (use target_paths)"),
    (_text("one", type="gate"), "type 'gate' does not match its directory 'traps' (trap)"),
    (_text("one", target_paths=5), "target_paths must be a glob pattern or a list of glob patterns"),
    (_text("one", expired_at="2026-01-01"), "is expired (expired_at), so it would not be served"),
    (_text("one", fitness=0.9), "still has derived or retired keys (fitness)"),
])
def test_a_rule_the_loader_would_not_serve_cleanly_is_refused(ws, text, reason):
    pack = _pack(_entry("traps/one.md", text))
    assert reason in _refused_import(ws, pack)
    assert not (ws / ".aegis/rules/traps").exists()


def test_a_rule_with_an_id_that_disagrees_with_its_path_is_refused(ws):
    assert _refused_import(ws, _pack(_entry("traps/one.md", _text("two")))) == (
        "rules[0] (traps/one.md): id 'two' does not match the file name 'one'")


def test_a_pack_that_is_structurally_valid_but_names_a_traversal_path_writes_nothing_anywhere(ws, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    before = _tree(tmp_path)
    for path in ("../../outside/x.md", "../../../etc/passwd", "/abs/x.md", "traps/../../../outside/x.md"):
        with pytest.raises(PackError):
            packs.load_pack(_wire(_pack(_entry(path, _text("x")))))
    assert _tree(tmp_path) == before


def test_import_refuses_a_type_directory_that_is_a_symlink_and_writes_nothing_through_it(ws, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    try:
        os.symlink(str(outside), str(ws / ".aegis/rules/traps"), target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            raise
        pytest.skip("symlinks are unavailable")
    problems = _refused_import(ws, _good())
    assert problems.startswith("the rules directory cannot be read safely: ")
    assert list(outside.iterdir()) == []


def test_import_refuses_a_workspace_whose_rules_directory_is_a_symlink(ws, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (ws / ".aegis" / "rules").rmdir()
    try:
        os.symlink(str(outside), str(ws / ".aegis/rules"), target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            raise
        pytest.skip("symlinks are unavailable")
    assert _refused_import(ws, _good()).startswith("the rules directory cannot be read safely: ")
    assert list(outside.iterdir()) == []


def test_the_collision_check_runs_inside_the_lock_the_write_holds(ws, monkeypatch):
    """Plan and write are one critical section: a rule another writer created before this one
    got the lock is seen by the plan and never replaced."""
    real = packs.locked
    planted = ws / ".aegis/rules/invariants/two.md"

    class Racing:
        def __init__(self, *args, **kwargs):
            self.inner = real(*args, **kwargs)

        def __enter__(self):
            held = self.inner.__enter__()
            planted.parent.mkdir(parents=True, exist_ok=True)
            planted.write_text("planted\n", encoding="utf-8")
            return held

        def __exit__(self, *exc):
            return self.inner.__exit__(*exc)

    monkeypatch.setattr(packs, "locked", Racing)
    problems = _refused_import(ws, _good())
    assert "the id 'two' is already used by .aegis/rules/invariants/two.md" in problems
    assert planted.read_text(encoding="utf-8") == "planted\n"
    assert not (ws / ".aegis/rules/traps/one.md").exists()


def test_a_target_that_appears_after_the_plan_is_not_replaced(ws, monkeypatch):
    """Belt and braces for a writer that ignores the lock: the write itself refuses to
    replace a file that exists when it gets there."""
    plan = packs._plan
    planted = ws / ".aegis/rules/traps/one.md"
    calls = []

    def plan_then_plant(*args, **kwargs):
        result = plan(*args, **kwargs)
        calls.append(1)
        if len(calls) == 2:  # the plan made under the lock
            planted.parent.mkdir(parents=True, exist_ok=True)
            planted.write_text("planted\n", encoding="utf-8")
        return result

    monkeypatch.setattr(packs, "_plan", plan_then_plant)
    problems = _refused_import(ws, _good())
    assert problems == "rules[0] (traps/one.md): .aegis/rules/traps/one.md already exists"
    assert planted.read_text(encoding="utf-8") == "planted\n"
    assert not (ws / ".aegis/rules/invariants").exists()  # the rule written before it was taken back


def test_a_write_that_fails_part_way_leaves_no_rule_behind(ws, monkeypatch):
    real = packs.atomic_write_bytes
    calls = []

    def failing(path, data, *args, **kwargs):
        calls.append(path)
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        return real(path, data, *args, **kwargs)

    monkeypatch.setattr(packs, "atomic_write_bytes", failing)
    with pytest.raises(PackError) as info:
        _import(ws, _good())
    assert _problems(info) == "writing .aegis/rules/traps/one.md failed (No space left on device); no rule was imported"
    assert len(calls) == 2
    assert sorted(p.name for p in (ws / ".aegis/rules").rglob("*") if p.is_file()) == []
    assert not (ws / ".aegis/rules/invariants").exists() and not (ws / ".aegis/rules/traps").exists()
    assert events.read(ws, "pack_import").rows == []


def test_a_rollback_keeps_a_type_directory_that_existed_before(ws, monkeypatch):
    _put(ws, "trap", "mine")
    real = packs.atomic_write_bytes
    calls = []

    def failing(path, data, *args, **kwargs):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("boom")
        return real(path, data, *args, **kwargs)

    monkeypatch.setattr(packs, "atomic_write_bytes", failing)
    with pytest.raises(PackError):
        _import(ws, _good())
    assert sorted(p.name for p in (ws / ".aegis/rules/traps").iterdir()) == ["mine.md"]


def test_import_into_a_directory_that_is_not_a_workspace_is_refused(tmp_path):
    with pytest.raises(PackError) as info:
        packs.import_pack(tmp_path, packs.load_pack(_wire(_good())))
    assert _problems(info) == f"not an Aegis workspace (no .aegis/ in {tmp_path.resolve()}); run aegis init"


def test_import_creates_the_rules_directory_a_fresh_workspace_lacks(tmp_path):
    root = tmp_path / "fresh"
    (root / ".aegis").mkdir(parents=True)
    _import(root.resolve(), _good())
    assert (root / ".aegis/rules/traps/one.md").is_file()


def test_the_import_result_carries_no_text_a_pack_chose_beyond_ids_and_paths(ws):
    result = _import(ws, _good(), dry_run=True)
    for rule in result.rules:
        assert set(vars(rule)) == {"path", "id", "type", "renamed_from", "sha256"}


def test_an_id_that_differs_only_in_case_collides_on_every_file_system(ws):
    _put(ws, "trap", "One")
    assert "the id 'one' is already used by .aegis/rules/traps/One.md" in _refused_import(ws, _good())


def test_two_entries_whose_ids_differ_only_in_case_are_refused():
    pack = _pack(_entry("traps/Rule.md", _text("Rule")), _entry("traps/rule.md", _text("rule")))
    assert "rules[1] (traps/rule.md): the id 'rule' is also used by traps/Rule.md" in _refusal(_wire(pack)).splitlines()


def test_rename_avoids_an_id_that_differs_only_in_case(ws):
    _put(ws, "trap", "one")
    _put(ws, "trap", "One-Imported")
    result = _import(ws, _good(), rename=True)
    assert {r.id for r in result.rules} == {"one-imported-2", "two"}


def test_a_pack_exactly_at_the_size_limit_is_read_not_refused_for_its_size():
    assert _refusal(b" " * packs.MAX_PACK_BYTES).startswith("the pack is not valid JSON: ")


def test_a_pack_with_the_most_rules_allowed_is_accepted():
    entries = [_entry(f"traps/r{i}.md", _text(f"r{i}")) for i in range(packs.MAX_PACK_RULES)]
    assert len(packs.validate_pack(_pack(*entries))) == packs.MAX_PACK_RULES


def test_an_entry_exactly_at_the_size_limit_is_accepted():
    text = _text("one")
    text += " " * (packs.MAX_RULE_BYTES - len(text.encode("utf-8")))
    assert len(text.encode("utf-8")) == packs.MAX_RULE_BYTES
    assert [e.path for e in packs.validate_pack(_pack(_entry("traps/one.md", text)))] == ["traps/one.md"]


def test_validate_pack_checks_what_load_pack_checks_for_a_caller_that_built_the_pack_itself(ws):
    with pytest.raises(PackError) as info:
        packs.import_pack(ws, {"v": 1, "rules": [_entry("../x.md", "t")], "sha256": "0" * 64})
    assert "the path must be exactly <type dir>/<id>.md" in _problems(info)
    assert _tree(ws) == [".aegis/", ".aegis/rules/"]


def test_a_refused_import_leaves_no_trace_in_a_workspace_without_state(ws):
    _put(ws, "trap", "one")
    before = _tree(ws)
    _refused_import(ws, _good())
    assert _tree(ws) == before  # taking the lock would have created .aegis/state


# ── limits, and the branches a mutation run found untested ───────────────────

def test_the_documented_limits():
    assert (packs.MAX_PACK_BYTES, packs.MAX_PACK_RULES, packs.MAX_RULE_BYTES, packs.MAX_ID_LENGTH) == (
        8 * 1024 * 1024, 500, 128 * 1024, 128)


def test_export_refuses_a_rules_tree_that_cannot_be_read_safely(ws, tmp_path):
    (ws / ".aegis/rules/traps").mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    try:
        os.symlink(str(outside), str(ws / ".aegis/rules/personas"), target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            raise
        pytest.skip("symlinks are unavailable")
    with pytest.raises(PackError) as info:
        packs.select_rules(ws)
    assert _problems(info).startswith("the rules directory cannot be read safely: ")


def test_a_rule_outside_a_type_directory_cannot_be_exported():
    from aegis_core.rules import Rule

    stray = Rule(id="stray", path=".aegis/rules/stray.md", type=None, meta={}, body="", digest="0" * 64, raw=b"x")
    with pytest.raises(PackError) as info:
        packs.build_pack([stray])
    assert _problems(info) == ".aegis/rules/stray.md: it is not in a rule type directory"


def test_a_rule_of_exactly_the_size_limit_is_exported_and_one_byte_more_is_not(ws):
    text = _text("edge")
    padded = text + "x" * (packs.MAX_RULE_BYTES - len(text.encode("utf-8")))
    _put(ws, "trap", "edge", padded)
    (entry,) = packs.build_pack(packs.select_rules(ws).rules)["rules"]
    assert len(entry["text"].encode("utf-8")) == packs.MAX_RULE_BYTES
    _put(ws, "trap", "edge", padded + "x")
    with pytest.raises(PackError) as info:
        packs.build_pack(packs.select_rules(ws).rules)
    assert f"traps/edge.md: {packs.MAX_RULE_BYTES + 1} bytes exceeds" in _problems(info)


def test_every_unexportable_rule_is_reported_not_only_the_first(ws):
    _put(ws, "trap", "has space", _text("has space"))
    _put(ws, "trap", "stale", _text("stale", fitness=0.9))
    with pytest.raises(PackError) as info:
        packs.build_pack(packs.select_rules(ws).rules)
    assert len(info.value.problems) == 2


def test_an_entry_with_a_path_that_is_not_text_is_reported_alone_without_a_bundle_complaint():
    entry = {"path": 5, "text": "t", "sha256": _digest("t")}
    pack = {"v": 1, "rules": [entry], "sha256": packs.bundle_digest([entry])}
    assert _refusal(_wire(pack)).splitlines() == ["rules[0] (5): the path must be a string, not int"]


def test_a_bad_path_with_a_bad_digest_is_reported_twice_under_the_bare_label():
    pack = _pack({"path": "../x.md", "text": "t", "sha256": "0" * 64})
    problems = _refusal(_wire(pack)).splitlines()
    assert problems[0].startswith("rules[0] ('../x.md'): the path must be exactly")
    assert problems[1:] == ["rules[0]: the text does not match its sha256"]


def test_the_same_path_twice_is_reported_once():
    entry = _entry("traps/one.md", _text("one"))
    assert _refusal(_wire(_pack(entry, dict(entry)))).splitlines() == [
        "rules[1] (traps/one.md): the path appears twice in the pack"]


def test_a_rename_keeps_a_byte_order_mark_and_rewrites_the_id(ws):
    _put(ws, "trap", "one")
    bom = "\ufeff" + _text("one")
    result = _import(ws, _pack(_entry("traps/one.md", bom)), rename=True)
    written = (ws / ".aegis/rules/traps/one-imported.md").read_bytes()
    assert written == bom.replace("id: one\n", "id: one-imported\n").encode("utf-8")
    assert written.startswith(b"\xef\xbb\xbf---") and result.rules[0].id == "one-imported"


def test_a_rename_that_cannot_rewrite_the_id_is_refused_not_written(ws):
    """A frontmatter opener the loader accepts and the line editor does not ('----'): the
    id line is left alone, and the staged check after the rename refuses the mismatch."""
    _put(ws, "trap", "one")
    odd = _text("one").replace("---\n", "----\n", 1)
    assert load_rules(ws).get("one") is not None
    pack = _pack(_entry("traps/one.md", odd))
    assert _refused_import(ws, pack, rename=True) == (
        "rules[0] (traps/one.md): id 'one' does not match the file name 'one-imported'")
    assert not (ws / ".aegis/rules/traps/one-imported.md").exists()


def test_a_loader_that_skips_an_entry_fails_closed_instead_of_crashing(ws, monkeypatch):
    from aegis_core.rules import RuleSet

    monkeypatch.setattr(packs, "load_rules", lambda *args, **kwargs: RuleSet(()))
    assert _refused_import(ws, _good()).splitlines() == [
        "rules[0] (traps/one.md): the loader found 0 rules for it, expected exactly one",
        "rules[1] (invariants/two.md): the loader found 0 rules for it, expected exactly one",
    ]


def test_a_rename_that_runs_out_of_candidates_says_so(ws, monkeypatch):
    monkeypatch.setattr(packs, "_RENAME_ATTEMPTS", 2)
    _put(ws, "trap", "one")
    _put(ws, "trap", "one-imported")
    _put(ws, "trap", "one-imported-2")
    assert _refused_import(ws, _pack(_entry("traps/one.md", _text("one"))), rename=True) == (
        "rules[0] (traps/one.md): no usable renamed id: 2 candidates are taken")
