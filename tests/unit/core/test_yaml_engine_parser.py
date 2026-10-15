"""Parser safety tests for aegis_core.yaml_engine (review finding M5, parser half).

Covers: backslash-zero text is data (U+0000 itself is rejected, raw or in any escape spelling),
zero-width characters inside values survive (only a leading document BOM is stripped), list items
keep their structure (compact "- key: v" maps with any key shape, "- - x" nested sequences, block
scalars) or raise, and out-of-range unicode escapes raise the engine error type.
"""
from __future__ import annotations

import pytest

from aegis_core.yaml_engine import AegisYAML, AegisYAMLError, parse_yaml_subset


class TestParserBackslashZero:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("p: C:\\0", {"p": "C:\\0"}),
            ("p: 'C:\\0'", {"p": "C:\\0"}),
            ('p: "C:\\\\0"', {"p": "C:\\0"}),
            ("p:\n  - C:\\0", {"p": ["C:\\0"]}),
            ("p: [C:\\0]", {"p": ["C:\\0"]}),
            ("'C:\\0': 1", {"C:\\0": 1}),
        ],
    )
    def test_backslash_zero_text_is_ordinary_data(self, text, expected):
        assert parse_yaml_subset(text) == expected

    def test_real_nul_is_still_rejected(self):
        with pytest.raises(AegisYAMLError, match="Control character 0x00"):
            parse_yaml_subset("p: a\x00b")
        with pytest.raises(AegisYAMLError, match="Escape sequence"):
            parse_yaml_subset('p: "a\\0b"')

    @pytest.mark.parametrize(
        "text",
        [
            'p: "a\\u0000b"',
            'p: "\\U00000000"',
            'p: ["\\u0000"]',
            'p: {"k\\u0000": 1}',
            '"\\u0000": 1',
            'p:\n  - "x\\u0000"',
        ],
    )
    def test_escaped_nul_is_rejected_in_every_spelling(self, text):
        # Review M5 follow-up: a decoded NUL is rejected however it is spelled, matching the raw-NUL
        # and \0 rejections, so no parsed value or key can carry U+0000.
        with pytest.raises(AegisYAMLError, match="NUL"):
            parse_yaml_subset(text)

    def test_backslash_u_zero_text_in_single_quotes_is_data(self):
        assert parse_yaml_subset("p: 'a\\u0000b'") == {"p": "a\\u0000b"}


class TestParserInvisibleCharacters:
    @pytest.mark.parametrize("ch", ["\u200b", "\u200c", "\u200d", "\ufeff"])
    def test_zero_width_and_bom_inside_values_are_preserved(self, ch):
        assert parse_yaml_subset(f"k: a{ch}b") == {"k": f"a{ch}b"}
        assert parse_yaml_subset(f'k: "a{ch}b"') == {"k": f"a{ch}b"}
        assert parse_yaml_subset(f"k:\n  - {ch}x") == {"k": [f"{ch}x"]}

    def test_only_a_leading_document_bom_is_stripped(self):
        assert parse_yaml_subset("\ufeffk: v") == {"k": "v"}
        assert parse_yaml_subset("\ufeffk: \ufeffv") == {"k": "\ufeffv"}

    @pytest.mark.parametrize("text", ["\u200bid: v", "i\u200dd: v", "id\ufeff: v", "\u202eid: v", "m: {\u200bk: 1}"])
    def test_raw_invisible_character_in_key_is_rejected(self, text):
        with pytest.raises(AegisYAMLError, match="invisible"):
            parse_yaml_subset(text)

    def test_escaped_invisible_character_in_quoted_key_is_accepted(self):
        assert parse_yaml_subset('"\\u200Bid": v') == {"\u200bid": "v"}

    def test_parse_text_preserves_zero_width_in_metadata_and_body(self):
        doc = AegisYAML.parse_text("---\nid: a\u200bb\n---\nbody\u200c text")
        assert doc["id"] == "a\u200bb"
        assert doc.body == "body\u200c text"

    def test_raw_lone_surrogate_raises_engine_error(self):
        with pytest.raises(AegisYAMLError, match="surrogate"):
            parse_yaml_subset("k: \ud800")


class TestParserListItemMappings:
    def test_nested_map_and_sequences_under_compact_list_item(self):
        text = (
            "items:\n"
            "  - name: x\n"
            "    opts:\n"
            "      a: 1\n"
            "      b: [2, 3]\n"
            "    tags:\n"
            "      - t1\n"
            "    same_col:\n"
            "    - s1\n"
            "  - name: y\n"
        )
        expected = {
            "items": [
                {"name": "x", "opts": {"a": 1, "b": [2, 3]}, "tags": ["t1"], "same_col": ["s1"]},
                {"name": "y"},
            ]
        }
        assert parse_yaml_subset(text) == expected

    def test_empty_valued_key_opens_nested_map_under_list_item(self):
        assert parse_yaml_subset("items:\n  - opts:\n      a: 1\n") == {"items": [{"opts": {"a": 1}}]}

    def test_block_scalar_under_compact_list_item(self):
        text = "items:\n  - run: |\n      echo hi # not a comment\n      second\n    name: x\n"
        assert parse_yaml_subset(text) == {"items": [{"run": "echo hi # not a comment\nsecond\n", "name": "x"}]}

    def test_plain_continuation_under_compact_list_item_is_folded(self):
        text = "items:\n  - desc: long\n      text continues\n    name: x\n"
        assert parse_yaml_subset(text) == {"items": [{"desc": "long text continues", "name": "x"}]}

    def test_wider_spacing_after_dash_anchors_at_key_column(self):
        assert parse_yaml_subset("items:\n  -   a: 1\n      b: 2\n") == {"items": [{"a": 1, "b": 2}]}

    @pytest.mark.parametrize(
        "text, message",
        [
            ("items:\n  - name: x\n      extra: y\n", "unexpected indentation"),  # deeper than the key column
            ("items:\n  - name: x\n   extra: y\n", "unexpected indentation"),  # between dash and key column
            ("items:\n  - name: x\n    stray line\n", "expected 'key: value'"),  # was silently dropped
            ("items:\n  - name: x\n    - y\n", "unexpected sequence item"),
        ],
    )
    def test_misindented_list_item_content_raises(self, text, message):
        with pytest.raises(AegisYAMLError, match=message):
            parse_yaml_subset(text)

    @pytest.mark.parametrize(
        "text, expected",
        [
            ('l:\n  - "k": "v"\n', [{"k": "v"}]),
            ("l:\n  - 'k': 'v'\n", [{"k": "v"}]),
            ("l:\n  - my key: v\n", [{"my key": "v"}]),
            ("l:\n  - a/b: c\n", [{"a/b": "c"}]),
            ("l:\n  - 2024: x\n", [{"2024": "x"}]),
            ("l:\n  - k : v\n", [{"k": "v"}]),
            ("l:\n  - k:\tv\n", [{"k": "v"}]),
            ('l:\n  - "a: b": c\n', [{"a: b": "c"}]),
            ("l:\n  - 'it''s': x\n", [{"it's": "x"}]),
            ('l:\n  - "a #b": c # trailing\n', [{"a #b": "c"}]),
            ('l:\n  - "my key": 1\n    "other key": [a]\n  - x\n', [{"my key": 1, "other key": ["a"]}, "x"]),
            ("l:\n  - my key:\n      n: 1\n", [{"my key": {"n": 1}}]),
            ("l:\n  - my key: |\n      line # kept\n    next: 2\n", [{"my key": "line # kept\n", "next": 2}]),
        ],
    )
    def test_compact_map_with_any_key_shape_under_list_item(self, text, expected):
        assert parse_yaml_subset(text) == {"l": expected}

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("l:\n  - - a\n", [["a"]]),
            ("l:\n  - - a: 1\n", [[{"a": 1}]]),
            ("l:\n  - - a\n    - b\n  - c\n", [["a", "b"], "c"]),
            ("l:\n  - - a: 1\n      b: 2\n", [[{"a": 1, "b": 2}]]),
            ("l:\n  - - - x\n", [[["x"]]]),
            ("l:\n  - -\n", [[None]]),
            ("l:\n- - a\n", [["a"]]),
            ('l:\n  - - "q: r"\n', [["q: r"]]),
        ],
    )
    def test_compact_nested_sequence_under_list_item(self, text, expected):
        assert parse_yaml_subset(text) == {"l": expected}

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("l:\n  - C:\\0\n", ["C:\\0"]),
            ("l:\n  - http://x.y/z\n", ["http://x.y/z"]),
            ("l:\n  - a:b\n", ["a:b"]),
            ("l:\n  - 'a: b'\n", ["a: b"]),
            ('l:\n  - "a: b"\n', ["a: b"]),
            ("l:\n  - {a: 1}\n", [{"a": 1}]),
            ("l:\n  - -1\n", [-1]),
            ("l:\n  - -x\n", ["-x"]),
        ],
    )
    def test_scalar_and_flow_items_stay_scalars(self, text, expected):
        assert parse_yaml_subset(text) == {"l": expected}

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("l:\n  - |\n    a\n    b\n  - x\n", ["a\nb\n", "x"]),
            ("l:\n  - >-\n    a\n    b\n", ["a b"]),
            ("l:\n  - |\n", [""]),
            ("l:\n  - - |\n      x # kept\n", [["x # kept\n"]]),
        ],
    )
    def test_block_scalar_as_list_item(self, text, expected):
        assert parse_yaml_subset(text) == {"l": expected}

    @pytest.mark.parametrize(
        "text, message",
        [
            ("l:\n  - a:b: c\n", "ambiguous sequence item"),
            ("l:\n  - http://x: y\n", "ambiguous sequence item"),
            ("l:\n  - a:b:\n", "ambiguous sequence item"),
            ("l:\n  - : v\n", "missing key"),
            ('l:\n  - "k" x: v\n', "unterminated quoted scalar"),
        ],
    )
    def test_list_item_that_cannot_be_read_unambiguously_raises(self, text, message):
        with pytest.raises(AegisYAMLError, match=message):
            parse_yaml_subset(text)

    def test_compact_nesting_beyond_depth_cap_raises_without_quadratic_work(self):
        with pytest.raises(AegisYAMLError, match="nesting depth"):
            parse_yaml_subset("l:\n  " + "- " * 100_000 + "x\n")

    @pytest.mark.parametrize(
        "sibling, expected",
        [
            ("    name: x # c\n", {"name": "x"}),
            ("    # a comment line\n    name: x\n", {"name": "x"}),
            ("    name: 'a # b' # c\n", {"name": "a # b"}),
        ],
    )
    def test_sibling_after_block_scalar_in_compact_item_is_parsed_as_a_key(self, sibling, expected):
        # The block scalar is anchored at the key column, not the dash column: a sibling key at the
        # key column ends it and gets normal comment and quote handling (review low finding 2).
        text = "items:\n  - run: |\n      echo\n" + sibling
        assert parse_yaml_subset(text) == {"items": [{"run": "echo\n", **expected}]}


class TestParserUnicodeEscapes:
    @pytest.mark.parametrize("escape", ["\\UFFFFFFFF", "\\U80000000", "\\U00110000"])
    def test_out_of_range_code_point_raises_engine_error(self, escape):
        with pytest.raises(AegisYAMLError, match="outside the Unicode range"):
            parse_yaml_subset(f'k: "{escape}"')

    def test_in_range_escapes_decode(self):
        parsed = parse_yaml_subset('k: "\\U0010FFFF\\U0001F600\\uD800\\u00e9"')
        assert parsed == {"k": "\U0010ffff\U0001f600\ud800\u00e9"}
