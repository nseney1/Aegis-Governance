"""Round-trip and safety tests for aegis_core.yaml_engine (review finding M5).

Contract under test: for any mapping with str keys and str / int / finite float / bool / None /
list / dict values, ``parse_yaml_subset(dump_frontmatter(d))`` is identical to ``d`` (same types,
same key order), and the frontmatter entry points preserve both metadata and body. Input the parser
cannot represent makes the serializer raise AegisYAMLError (a ValueError) instead of writing a file
that cannot be read back.
"""
from __future__ import annotations

import random
import string

import pytest

from aegis_core.yaml_engine import (
    AegisDocument,
    AegisYAML,
    AegisYAMLError,
    MAX_DEPTH,
    MAX_DOC_BYTES,
    MAX_LINES,
    MAX_SCALAR_CHARS,
    dump_frontmatter,
    parse_frontmatter,
    parse_rule_frontmatter,
    parse_yaml_subset,
)

try:
    from hypothesis import assume, given, settings, strategies as st
except ImportError:  # the seeded property test below always runs; this one is additive
    given = None


SEED = 20261015
PROPERTY_CASES = 2500
FRONTMATTER_CASES = 500


def assert_identical(expected, actual, path="$"):
    """Strict equality: same types (so True != 1, '1' != 1), same key order, float reprs equal."""
    assert type(actual) is type(expected), (
        f"{path}: expected {type(expected).__name__} {expected!r}, got {type(actual).__name__} {actual!r}"
    )
    if isinstance(expected, dict):
        assert list(actual) == list(expected), f"{path}: keys {list(actual)!r} != {list(expected)!r}"
        for key in expected:
            assert_identical(expected[key], actual[key], f"{path}[{key!r}]")
    elif isinstance(expected, list):
        assert len(actual) == len(expected), f"{path}: length {len(actual)} != {len(expected)}"
        for idx, (exp_item, act_item) in enumerate(zip(expected, actual)):
            assert_identical(exp_item, act_item, f"{path}[{idx}]")
    elif isinstance(expected, float):
        assert repr(actual) == repr(expected), f"{path}: {actual!r} != {expected!r}"
    else:
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"


def roundtrip(data):
    dumped = dump_frontmatter(data)
    # Each logical line must be exactly one physical line: no raw \r, U+2028, U+0085 ... may leak.
    assert dumped.splitlines() == dumped.split("\n")[:-1], f"raw line break leaked into {dumped!r}"
    return parse_yaml_subset(dumped)


LINE_BREAKS_AND_CONTROLS = [
    "\r", "a\rb", "a\r\nb", "\n", "a\nb", "\u2028", "x\u2029y", "\u0085", "a\x0bb", "a\x0cb",
    "\x1c\x1d\x1e", "\x00", "nul\x00byte", "\x01", "\x08", "\x1b[31m", "\x1f", "\x7f", "\x80", "\x9f",
    "\t", "a\tb", " \t",
]
INVISIBLE = ["\ufeff", "\ufeffbom", "a\u200bb", "\u200c", "\u200d", "\u2060", "\u202eevil", "\u00ad", "\U000e0041"]
SURROGATES = ["\ud800", "a\udfffb"]
SYNTAX = [
    "", " ", "  lead", "trail  ", "a: b", "a:b", "#c", "a #c", "a#b", "- x", "-", "? x", "[a]", "{a: 1}",
    "|", ">-", "&anchor", "*alias", "!tag", "%dir", "@at", "`tick`", "'single'", '"double"', "it's",
    "back\\slash", "\\", "\\n", "---", "...", "true", "False", "YES", "on", "off", "no", "null", "NULL", "~",
    "0", "-1", "+7", "007", "1.5", ".5", "1.", "1.0e+5", "1e5", "inf", "nan", "C:\\0", "\\0", "\\u0041",
    "\\UFFFFFFFF", "a: 1\nb: 2", "\u00a0nbsp", "ideo\u3000", "emoji \U0001f600", "\u4e2d\u6587", "\u00e9",
]
ALL_HOSTILE = LINE_BREAKS_AND_CONTROLS + INVISIBLE + SURROGATES + SYNTAX


class TestSerializerValues:
    @pytest.mark.parametrize("value", ALL_HOSTILE)
    def test_mapping_value_roundtrips(self, value):
        assert_identical({"k": value}, roundtrip({"k": value}))

    @pytest.mark.parametrize("value", ALL_HOSTILE)
    def test_sequence_item_roundtrips(self, value):
        data = {"items": [value, "tail"]}
        assert_identical(data, roundtrip(data))

    def test_line_breaks_and_invisible_characters_are_never_written_raw(self):
        dumped = dump_frontmatter({"k": "a\rb\u2028c\x85d\x00e\ufefff\u200bg\u202eh"})
        for raw in ("\r", "\u2028", "\x85", "\x00", "\ufeff", "\u200b", "\u202e"):
            assert raw not in dumped


class TestSerializerKeys:
    def test_key_with_newline_cannot_inject_a_second_key(self):
        data = {"a: 1\nb": "v"}
        parsed = roundtrip(data)
        assert_identical(data, parsed)
        assert "a" not in parsed and "b" not in parsed

    @pytest.mark.parametrize("key", ALL_HOSTILE)
    def test_top_level_key_roundtrips(self, key):
        data = {key: "v", "after": 1}
        assert_identical(data, roundtrip(data))

    @pytest.mark.parametrize("key", ALL_HOSTILE)
    def test_nested_and_list_item_keys_roundtrip(self, key):
        data = {"outer": {key: "v", "z": 1}, "items": [{key: "w", "y": 2}]}
        assert_identical(data, roundtrip(data))

    def test_ordinary_identifier_keys_stay_plain(self):
        dumped = dump_frontmatter({"id": "x", "target_paths": [], "a.b-c_d": 1})
        assert dumped.splitlines() == ["id: x", "target_paths: []", "a.b-c_d: 1"]


class TestSerializerRefusesWhatTheParserRejects:
    def test_value_whose_escaped_form_exceeds_scalar_cap_raises_at_dump(self):
        with pytest.raises(AegisYAMLError, match="MAX_SCALAR_CHARS"):
            dump_frontmatter({"k": "\x01" * (MAX_SCALAR_CHARS // 6 + 1)})

    def test_plain_value_over_scalar_cap_raises_at_dump(self):
        with pytest.raises(AegisYAMLError, match="MAX_SCALAR_CHARS"):
            dump_frontmatter({"k": "a" * (MAX_SCALAR_CHARS + 1)})

    def test_value_at_scalar_cap_roundtrips(self):
        data = {"k": "a" * MAX_SCALAR_CHARS}
        assert_identical(data, roundtrip(data))

    def test_key_over_scalar_cap_raises_at_dump(self):
        with pytest.raises(AegisYAMLError, match="MAX_SCALAR_CHARS"):
            dump_frontmatter({"k" * (MAX_SCALAR_CHARS + 1): 1})

    def test_nesting_at_depth_cap_roundtrips_and_one_deeper_raises_at_dump(self):
        def nest(levels):
            node = {"leaf": "x"}
            for _ in range(levels - 1):
                node = {"n": node}
            return node

        at_cap = nest(MAX_DEPTH + 1)  # root mapping is depth 0; the parser accepts depth == MAX_DEPTH
        assert_identical(at_cap, roundtrip(at_cap))
        with pytest.raises(AegisYAMLError, match="MAX_DEPTH"):
            dump_frontmatter(nest(MAX_DEPTH + 2))
        # The parser rejects the same shape, so the dump-time refusal mirrors a real parse limit.
        too_deep = "".join(f"{'  ' * i}n:\n" for i in range(MAX_DEPTH + 1)) + f"{'  ' * (MAX_DEPTH + 1)}leaf: x\n"
        with pytest.raises(AegisYAMLError, match="nesting depth"):
            parse_yaml_subset(too_deep)

    def test_too_many_lines_raises_at_dump(self):
        with pytest.raises(AegisYAMLError, match="MAX_LINES"):
            dump_frontmatter({f"k{i}": i for i in range(MAX_LINES + 1)})

    def test_too_many_bytes_raises_at_dump(self):
        big = {f"k{i}": "x" * 4000 for i in range(MAX_DOC_BYTES // 4000 + 1)}
        with pytest.raises(AegisYAMLError, match="MAX_DOC_BYTES"):
            dump_frontmatter(big)

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_float_raises_at_dump(self, value):
        with pytest.raises(AegisYAMLError, match="non-finite"):
            dump_frontmatter({"score": value})


class TestSerializerContainersAndNumbers:
    @pytest.mark.parametrize("value", [1e-05, -1e20, 5e-324, 1.7976931348623157e308, -0.0, 0.1, 3.0, 12345678.9])
    def test_finite_floats_roundtrip_as_floats(self, value):
        assert_identical({"f": value, "in_list": [value]}, roundtrip({"f": value, "in_list": [value]}))

    @pytest.mark.parametrize(
        "value",
        [
            [{}],
            [[]],
            [["a", "b"], ["c"]],
            [{"a": {"b": [1, [2, {"c": None}]]}}],
            [[{"x": "y"}]],
        ],
    )
    def test_nested_sequences_roundtrip(self, value):
        assert_identical({"v": value}, roundtrip({"v": value}))


# --- property tests ---------------------------------------------------------------------------

_ALPHABET = list(string.ascii_letters + string.digits + " :#-_.,'\"\\/[]{}|>&*!%@`?~=+") + [
    "\n", "\r", "\t", "\x00", "\x01", "\x0b", "\x0c", "\x1b", "\x1c", "\x1f", "\x7f", "\x80", "\x85",
    "\x9f", "\xa0", "\xad", "\u2028", "\u2029", "\u200b", "\u200c", "\u200d", "\u2060", "\ufeff",
    "\u202e", "\u3000", "\ud800", "\udfff", "\U0001f600", "\U000e0041", "\u00e9", "\u4e2d",
]


def _rand_text(rng):
    roll = rng.random()
    if roll < 0.2:
        return rng.choice(ALL_HOSTILE)
    if roll < 0.3:
        return rng.choice(ALL_HOSTILE) + rng.choice(_ALPHABET) + rng.choice(ALL_HOSTILE)
    return "".join(rng.choice(_ALPHABET) for _ in range(rng.randint(0, 20)))


def _rand_float(rng):
    return rng.choice(
        [rng.uniform(-1e6, 1e6), rng.random() * 10.0 ** rng.randint(-320, 300), -0.0, 5e-324, 1.7976931348623157e308]
    )


def _rand_value(rng, depth):
    roll = rng.random()
    if depth < 3 and roll < 0.12:
        return _rand_mapping(rng, depth + 1)
    if depth < 3 and roll < 0.24:
        return [_rand_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    if roll < 0.30:
        return rng.randint(-(10**12), 10**12)
    if roll < 0.35:
        return _rand_float(rng)
    if roll < 0.38:
        return rng.choice([True, False, None])
    return _rand_text(rng)


def _rand_mapping(rng, depth):
    return {_rand_text(rng): _rand_value(rng, depth) for _ in range(rng.randint(0, 5))}


def test_seeded_property_dump_parse_identity():
    rng = random.Random(SEED)
    checked = 0
    for case in range(PROPERTY_CASES):
        data = _rand_mapping(rng, 0)
        try:
            assert_identical(data, roundtrip(data))
        except Exception as exc:  # report the reproducer, not just the first assertion
            pytest.fail(f"case {case} (seed {SEED}) failed for {data!r}: {type(exc).__name__}: {exc}")
        checked += 1
    assert checked >= 2000


def test_seeded_frontmatter_roundtrip_preserves_metadata_and_body():
    rng = random.Random(SEED + 1)
    for case in range(FRONTMATTER_CASES):
        meta = _rand_mapping(rng, 0)
        body = "# Title\n" + _rand_text(rng) + "\n---\nnot a delimiter for the parser\nEND"
        try:
            content = dump_frontmatter(meta, body=body)
            parsed_meta, parsed_body = parse_rule_frontmatter(content)
            assert_identical(meta, parsed_meta)
            assert parsed_body == body
            assert_identical(meta, parse_frontmatter(content))
            doc = AegisYAML.parse_text(AegisYAML.dump(meta, body=body))
            assert_identical(AegisDocument(meta).metadata, doc.metadata)
            assert doc.body == body
        except Exception as exc:
            pytest.fail(f"case {case} (seed {SEED + 1}) failed for {meta!r} / {body!r}: {type(exc).__name__}: {exc}")


def _depth(value):
    if isinstance(value, dict) and value:
        return 1 + max(_depth(v) for v in value.values())
    if isinstance(value, list) and value:
        return 1 + max(_depth(v) for v in value)
    return 0


if given is not None:
    _keys = st.text(max_size=20)
    _scalars = st.one_of(
        st.text(max_size=30),
        st.integers(min_value=-(10**18), max_value=10**18),
        st.floats(allow_nan=False, allow_infinity=False),
        st.booleans(),
        st.none(),
    )
    _values = st.recursive(
        _scalars,
        lambda children: st.one_of(st.lists(children, max_size=4), st.dictionaries(_keys, children, max_size=4)),
        max_leaves=12,
    )

    @settings(max_examples=500, deadline=None)
    @given(st.dictionaries(_keys, _values, max_size=6))
    def test_hypothesis_dump_parse_identity(data):
        assume(_depth(data) <= MAX_DEPTH)
        assert_identical(data, roundtrip(data))

else:

    def test_hypothesis_dump_parse_identity():
        pytest.skip(
            f"hypothesis is not installed; test_seeded_property_dump_parse_identity still ran {PROPERTY_CASES} cases"
        )
