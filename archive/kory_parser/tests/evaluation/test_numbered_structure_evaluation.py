from xml.etree import ElementTree as E

from evaluations.numbered_structure import grade_numbered_paragraphs, paragraph_text
from evaluations.runner import score


def test_literal_inline_break_and_tail_are_source_text():
    root = E.fromstring('<p><run><t>  가. item<br/>   1) child<tab/>tail</t></run><ctrl><p><t>footer</t></p></ctrl></p>')
    assert paragraph_text(root) == '  가. item\n   1) child\ttail'


def test_occurrence_identity_survives_extra_empty_blocks_but_checks_depth():
    expected = [{"text": " 가. item", "occurrence": 1, "type": "list", "level": 3}]
    actual = {"blocks": [{"type": "image"}, {"type": "paragraph", "text": "가. item"},
                         {"type": "paragraph", "text": ""}, {"type": "list", "text": "가. item", "level": 3}]}
    assert grade_numbered_paragraphs(expected, actual) == {"passed": 1, "total": 1}
    actual['blocks'][-1]['level'] = 4
    assert grade_numbered_paragraphs(expected, actual)['passed'] == 0


def test_full_output_contract_can_require_block_types_and_depth():
    expected = {"success": True, "require_block_structure": True,
                "blocks": [{"type": "list", "text": "Ⅰ. Scope", "level": 1}]}
    old = {"success": True, "blocks": [{"type": "paragraph", "text": "Ⅰ. Scope"}]}
    assert score(expected, old)['block_structure'] == 0
    assert score(expected, expected)['block_structure'] == 1
    assert score(expected, old)['text_recall'] == 1
