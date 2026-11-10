"""Table captions must survive rendering with safe text and nested table order."""

from kory_parser import parse
from kory_parser.markdown import blocks_to_markdown
from kory_parser.models import Block, Cell, Table
from tests.document_fixtures import hwpx, hwpx_cell


def test_hwpx_source_caption_survives_parse_to_markdown():
    data = hwpx(
        '<p><run><tbl id="1" rowCnt="1" colCnt="1">'
        "<caption><subList><p><run><t>Schedule A</t></run></p></subList></caption>"
        "<tr>" + hwpx_cell("quantity") + "</tr></tbl></run></p>"
    )
    result = parse(data)
    assert result.success
    assert result.blocks[0].table.caption == "Schedule A"
    assert "<table>\n  <caption>Schedule A</caption>\n  <tr>" in result.markdown
    assert result.markdown.count("Schedule A") == 1


def test_caption_text_is_escaped_and_line_breaks_and_private_glyphs_are_preserved():
    table = Table(1, 1, [[Cell("body")]], caption="A <script>&\n\U000f02b1")
    markdown = blocks_to_markdown([Block("table", table=table)])
    assert "<caption>A &lt;script&gt;&amp;<br>①</caption>" in markdown
    assert "<script>" not in markdown
    assert table.caption == "A <script>&\n\U000f02b1"


def test_nested_captions_stay_attached_to_their_tables():
    inner = Table(1, 1, [[Cell("value")]], caption="Inner")
    outer = Table(1, 1, [[Cell(blocks=[Block("table", table=inner)])]], caption="Outer")
    markdown = blocks_to_markdown([Block("table", table=outer)])
    assert markdown.startswith("<table>\n  <caption>Outer</caption>")
    assert "<td><table>\n  <caption>Inner</caption>" in markdown
    assert markdown.count("<caption>") == 2


def test_uncaptioned_tables_retain_the_existing_markup():
    table = Table(1, 1, [[Cell("value")]])
    assert blocks_to_markdown([Block("table", table=table)]) == (
        "<table>\n  <tr>\n    <td>value</td>\n  </tr>\n</table>"
    )
