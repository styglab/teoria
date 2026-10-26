from kory_parser import ParseOptions, parse

from .test_numbered_structure import document


def test_roman_contents_titles_without_page_label_are_not_body_roots():
    lines = ['목 차', '  Ⅰ. Design', '     1. Unit\t 1', '  Ⅱ. Delivery', '     1. Timing\t 2',
             'Ⅰ. Design', '  1. Unit', '    가. Outer', '    나. Inner', 'Ⅱ. Delivery', '  1. Timing']
    result = parse(document(lines), ParseOptions(recover_numbered_structure=True))
    assert [b.level for b in result.blocks] == [None] * 5 + [1,2,3,3,1,2]
    assert all(b.type == 'paragraph' for b in result.blocks[:5])
