from kory_parser import ParseOptions, parse

from .test_numbered_structure import document


def test_printed_contents_page_labels_do_not_seed_body_list_depth():
    lines = ['Ⅰ. Overview\t 1','Ⅱ. Instructions\t 1'] + ['ordinary body'] * 80 + ['  2. Training record']
    result = parse(document(lines), ParseOptions(recover_numbered_structure=True))
    assert result.success
    assert all(b.type == 'paragraph' and b.level is None for b in result.blocks)


def test_distant_body_item_does_not_inherit_an_old_section():
    lines = ['Ⅰ. Design','  1. Unit','Ⅱ. Delivery'] + ['ordinary body'] * 80 + ['  2. Unrelated item']
    result = parse(document(lines), ParseOptions(recover_numbered_structure=True))
    assert [b.level for b in result.blocks[:3]] == [1,2,1]
    assert result.blocks[-1].type == 'paragraph'
    assert result.blocks[-1].level is None


def test_small_padding_variation_does_not_turn_roman_sibling_into_child():
    lines = ['Ⅰ. Design','  1. Unit','    가. Frame','    나. Processor',' Ⅱ. Delivery','  1. Timing','Ⅲ. Support']
    result = parse(document(lines), ParseOptions(recover_numbered_structure=True))
    assert [b.level for b in result.blocks] == [1,2,3,3,1,2,1]
