"""Source-backed basic Korean Ganada labels and existing numbering boundaries."""

import pytest

from kory_parser import parse

from .test_office_numbering import document, level, num, paragraph


def test_basic_ganada_sequence_preserves_all_fourteen_labels():
    data = document(
        "".join(paragraph(f"Item {i}") for i in range(1, 15)),
        level(fmt="ganada"),
    )
    result = parse(data)
    assert result.success
    assert [b.text for b in result.blocks] == [
        f"{label}. Item {i}" for i, label in enumerate("가나다라마바사아자차카타파하", 1)
    ]
    assert not result.warnings


def test_ganada_start_override_retains_explicit_warning_beyond_supported_range():
    override = '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="14"/></w:lvlOverride>'
    data = document(
        paragraph("Last basic label") + paragraph("Extended label"),
        level(fmt="ganada", template="(%1)"),
        numbers=num("1", override),
    )
    result = parse(data)
    assert [b.text for b in result.blocks] == ["(하) Last basic label", "(%1) Extended label"]
    assert [w.code for w in result.warnings] == ["UNSUPPORTED_DOCX_NUMBER_FORMAT"]


def test_nested_ganada_references_restart_and_list_ids_count_independently():
    data = document(
        paragraph("Parent")
        + paragraph("First child", index=1)
        + paragraph("Second child", index=1)
        + paragraph("Other list", number_id="2")
        + paragraph("Next parent")
        + paragraph("Restarted child", index=1),
        level(fmt="ganada") + level(1, "decimal", "%1.%2)"),
        numbers=num("1") + num("2"),
    )
    result = parse(data)
    assert [b.text for b in result.blocks] == [
        "가. Parent",
        "가.1) First child",
        "가.2) Second child",
        "가. Other list",
        "나. Next parent",
        "나.1) Restarted child",
    ]
    assert not result.warnings


def test_legal_numbering_keeps_decimal_for_ganada_ancestor():
    child = level(1, "decimal", "%1.%2)").replace("</w:lvl>", "<w:isLgl/></w:lvl>")
    result = parse(document(paragraph("Legal child", index=1), level(fmt="ganada") + child))
    assert result.blocks[0].text == "1.1) Legal child"
    assert not result.warnings


@pytest.mark.parametrize("start", [0, -1, 15])
def test_unverified_ganada_values_keep_native_placeholder_and_warning(start):
    override = f'<w:lvlOverride w:ilvl="0"><w:startOverride w:val="{start}"/></w:lvlOverride>'
    result = parse(document(paragraph("Preserved"), level(fmt="ganada"), numbers=num("1", override)))
    assert result.blocks[0].text == "%1. Preserved"
    assert [w.code for w in result.warnings] == ["UNSUPPORTED_DOCX_NUMBER_FORMAT"]
