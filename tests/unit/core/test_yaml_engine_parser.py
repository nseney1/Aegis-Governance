"""Parser safety tests for aegis_core.yaml_engine (review finding M5, parser half).

Covers: backslash-zero text is data (only a real NUL is rejected), zero-width characters inside
values survive (only a leading document BOM is stripped), mappings nested under list items parse
with their full structure or raise, and out-of-range unicode escapes raise the engine error type.
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


class TestParserUnicodeEscapes:
    @pytest.mark.parametrize("escape", ["\\UFFFFFFFF", "\\U80000000", "\\U00110000"])
    def test_out_of_range_code_point_raises_engine_error(self, escape):
        with pytest.raises(AegisYAMLError, match="outside the Unicode range"):
            parse_yaml_subset(f'k: "{escape}"')

    def test_in_range_escapes_decode(self):
        parsed = parse_yaml_subset('k: "\\U0010FFFF\\U0001F600\\uD800\\u00e9"')
        assert parsed == {"k": "\U0010ffff\U0001f600\ud800\u00e9"}
