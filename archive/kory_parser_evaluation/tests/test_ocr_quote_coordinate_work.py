"""Only punctuation-bearing lines need expensive character coordinate conversion."""

from dataclasses import dataclass

from kory_parser.ocr_punctuation import quote_word_boxes


@dataclass
class Recognition:
    txts: tuple
    scores: list
    word_results: tuple


class Boxes:
    def __init__(self, rows):
        self.rows = rows

    def __getitem__(self, indices):
        return [self.rows[i] for i in indices]


def test_only_quoted_lines_are_converted_and_all_line_positions_remain_aligned():
    original = Recognition(("plain", "A'B", "last"), [0.8, 0.9, 0.7], ("raw0", "raw1", "raw2"))
    calls = []
    converted = ((("A", 0.9, None), ("'", 0.9, [[1, 2]]), ("B", 0.9, None)),)

    def convert(images, boxes, recognition):
        calls.append((images, boxes, recognition))
        return converted

    words = quote_word_boxes(convert, ["img0", "img1", "img2"], Boxes(["box0", "box1", "box2"]), original)
    assert calls[0][0:2] == (["img1"], ["box1"])
    assert calls[0][2] == Recognition(("A'B",), [0.9], ("raw1",))
    assert words == ((("plain", 0.8, None),), converted[0], (("last", 0.7, None),))
    assert original.word_results == ("raw0", "raw1", "raw2")


def test_plain_text_does_not_request_any_character_coordinates():
    def unexpected(*args):
        raise AssertionError("coordinate conversion is unnecessary")

    assert quote_word_boxes(
        unexpected, ["image"], Boxes(["box"]), Recognition(("plain",), [0.8], ("raw",))
    ) == ((("plain", 0.8, None),),)
