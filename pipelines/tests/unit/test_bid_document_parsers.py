import io
import zipfile

from openpyxl import Workbook

from teoria_pipelines.document_parsers import parse_document


def test_parses_hwpx_paragraphs() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            "Contents/section0.xml",
            '<hs:sec xmlns:hs="urn:test"><hp:p xmlns:hp="urn:p"><hp:t>입찰참가자격</hp:t></hp:p></hs:sec>',
        )
    parser, result = parse_document(stream.getvalue(), "공고.hwpx", None)
    assert parser == "hwpx"
    assert result["blocks"][0]["text"] == "입찰참가자격"


def test_parses_xlsx_rows() -> None:
    workbook = Workbook()
    workbook.active.append(["조건", "중소기업"])
    stream = io.BytesIO()
    workbook.save(stream)
    parser, result = parse_document(stream.getvalue(), "조건.xlsx", None)
    assert parser == "xlsx"
    assert result["blocks"][0]["text"] == "조건 | 중소기업"
