"""Native DOCX numbering contracts, independent of document subject matter."""

import pytest

from teoria_docparse import parse

from .document_fixtures import zip_document

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def document(paragraphs, levels, *, numbers=None, styles=""):
    numbering = f'<w:numbering {NS}><w:abstractNum w:abstractNumId="0">{levels}</w:abstractNum>{numbers or num("1")}</w:numbering>'
    return zip_document(
        {
            "word/document.xml": f"<w:document {NS}><w:body>{paragraphs}</w:body></w:document>",
            "word/numbering.xml": numbering,
            "word/styles.xml": f"<w:styles {NS}>{styles}</w:styles>",
        }
    )


def num(number_id, override=""):
    return f'<w:num w:numId="{number_id}"><w:abstractNumId w:val="0"/>{override}</w:num>'


def level(index=0, fmt="decimal", template="%1.", restart=None):
    reset = f'<w:lvlRestart w:val="{restart}"/>' if restart is not None else ""
    return f'<w:lvl w:ilvl="{index}"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/><w:lvlText w:val="{template}"/>{reset}</w:lvl>'


def paragraph(text, number_id="1", index=0, style=None):
    properties = (
        f'<w:numPr><w:ilvl w:val="{index}"/><w:numId w:val="{number_id}"/></w:numPr>'
        if number_id is not None
        else ""
    )
    if style:
        properties += f'<w:pStyle w:val="{style}"/>'
    return f"<w:p><w:pPr>{properties}</w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>"


def test_multilevel_numbers_restart_and_resume_from_the_native_definition():
    parts = [("First", 0), ("Child", 1), ("Child again", 1), ("Second", 0), ("Child restart", 1)]
    data = document(
        "".join(paragraph(t, index=i) for t, i in parts), level() + level(1, "lowerLetter", "%1.%2)")
    )
    result = parse(data)
    assert result.success
    assert [b.text for b in result.blocks] == [
        "1. First",
        "1.a) Child",
        "1.b) Child again",
        "2. Second",
        "2.a) Child restart",
    ]
    assert [b.level for b in result.blocks] == [1, 2, 2, 1, 2]


def test_explicit_never_restart_is_preserved():
    data = document(
        paragraph("Parent") + paragraph("Child", index=1) + paragraph("Parent") + paragraph("Child", index=1),
        level() + level(1, "lowerRoman", "%2)", restart=0),
    )
    assert [b.text for b in parse(data).blocks] == ["1. Parent", "i) Child", "2. Parent", "ii) Child"]


def test_start_overrides_and_independent_list_ids():
    numbers = num("1") + num("2", '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="7"/></w:lvlOverride>')
    data = document(paragraph("A") + paragraph("B", "2") + paragraph("C"), level(), numbers=numbers)
    assert [b.text for b in parse(data).blocks] == ["1. A", "7. B", "2. C"]


def test_style_inheritance_restores_numbering_and_heading_outline():
    styles = '<w:style w:styleId="Base"><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr></w:style><w:style w:styleId="Derived"><w:basedOn w:val="Base"/></w:style><w:style w:styleId="Heading"><w:pPr><w:outlineLvl w:val="2"/></w:pPr></w:style><w:style w:styleId="ChildHeading"><w:basedOn w:val="Heading"/></w:style>'
    data = document(
        paragraph("Inherited", None, style="Derived")
        + paragraph("Heading", None, style="ChildHeading")
        + paragraph("Disabled", "0", style="Derived"),
        level(),
        styles=styles,
    )
    result = parse(data)
    assert [(b.type, b.level, b.text) for b in result.blocks] == [
        ("list", 1, "1. Inherited"),
        ("heading", 3, "Heading"),
        ("paragraph", None, "Disabled"),
    ]


def test_letters_beyond_z_and_numbering_suffix_nothing():
    override = '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="26"/></w:lvlOverride>'
    data = document(paragraph("A") + paragraph("B"), level(fmt="upperLetter"), numbers=num("1", override))
    assert [b.text for b in parse(data).blocks] == ["Z. A", "AA. B"]


def test_unsupported_numbering_is_reported_without_inventing_a_number():
    data = document(paragraph("Preserved"), level(fmt="unimplementedNativeFormat"))
    result = parse(data)
    assert result.success and result.blocks[0].text == "%1. Preserved"
    assert "UNSUPPORTED_DOCX_NUMBER_FORMAT" in [w.code for w in result.warnings]


def test_style_cycles_fail_explicitly():
    styles = '<w:style w:styleId="A"><w:basedOn w:val="B"/></w:style><w:style w:styleId="B"><w:basedOn w:val="A"/></w:style>'
    result = parse(document(paragraph("Text", None, style="A"), level(), styles=styles))
    assert not result.success and result.error_code == "INVALID_FILE"


@pytest.mark.parametrize("missing", ["9", "999"])
def test_missing_numbering_definition_keeps_the_paragraph(missing):
    result = parse(document(paragraph("Text", missing), level()))
    assert result.success and result.blocks[0].text == "Text"
    assert "UNRESOLVED_DOCX_NUMBERING" in [w.code for w in result.warnings]
