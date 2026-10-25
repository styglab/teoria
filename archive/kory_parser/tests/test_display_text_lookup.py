"""Ordinary text avoids private-glyph work without changing contextual conversions."""

from kory_parser.character_maps import HANCOM_PUA, map_display_text


def test_ordinary_unicode_avoids_python_character_indexing():
    class CountedText(str):
        reads = 0

        def __getitem__(self, key):
            type(self).reads += 1
            return super().__getitem__(key)

    text = CountedText("일반 문서 ABC 123 π 😀\n\t<&> e\u0301 " * 80)
    assert map_display_text(text) == str(text)
    assert CountedText.reads < 4


def test_authoritative_private_glyph_entries_still_convert():
    for code, expected in HANCOM_PUA.items():
        assert map_display_text(chr(code)) == expected


def test_contextual_number_pairs_still_combine_inside_ordinary_text():
    assert map_display_text("A\U000f0289\U000f0294B \U000f029b \U000f02b1") == "A⑫B 9 ①"


def test_unmapped_private_characters_and_other_unicode_remain_unchanged():
    text = "A\ue001\uf8ff\U000f1000\U0010fffd😀\U000e0100"
    assert map_display_text(text) == text
    assert map_display_text("") == ""
