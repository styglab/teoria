from __future__ import annotations

import io
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from openpyxl import load_workbook
from pypdf import PdfReader


PARSER_VERSION = "1.0.0"


class UnsupportedDocumentError(ValueError):
    pass


def parse_document(value: bytes, file_name: str | None, media_type: str | None) -> tuple[str, dict[str, Any]]:
    suffix = Path(file_name or "").suffix.lower()
    if value.startswith(b"%PDF") or suffix == ".pdf":
        return "pdf", _parse_pdf(value)
    if suffix == ".hwpx" or _is_hwpx(value):
        return "hwpx", _parse_hwpx(value)
    if suffix in {".xlsx", ".xlsm"}:
        return "xlsx", _parse_xlsx(value)
    if suffix == ".hwp":
        return "hwp-libreoffice", _parse_hwp(value)
    if (media_type or "").startswith("text/"):
        text = value.decode("utf-8", errors="replace")
        return "text", {"blocks": [_block("b1", None, None, "paragraph", text)]}
    raise UnsupportedDocumentError(f"unsupported_document_type:{suffix or media_type or 'unknown'}")


def _block(block_id: str, page: int | None, section: str | None,
           block_type: str, text: str) -> dict[str, Any]:
    return {"block_id": block_id, "page": page, "section": section,
            "type": block_type, "text": text.strip()}


def _parse_pdf(value: bytes) -> dict[str, Any]:
    blocks = []
    for index, page in enumerate(PdfReader(io.BytesIO(value)).pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            blocks.append(_block(f"p{index}", index, None, "page", text))
    return {"blocks": blocks, "requires_ocr": not blocks}


def _is_hwpx(value: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(value)) as archive:
            return any(name.startswith("Contents/section") for name in archive.namelist())
    except zipfile.BadZipFile:
        return False


def _parse_hwpx(value: bytes) -> dict[str, Any]:
    blocks = []
    with zipfile.ZipFile(io.BytesIO(value)) as archive:
        sections = sorted(name for name in archive.namelist()
                          if name.startswith("Contents/section") and name.endswith(".xml"))
        for section_index, name in enumerate(sections, start=1):
            root = ElementTree.fromstring(archive.read(name))
            for paragraph_index, paragraph in enumerate(root.iter(), start=1):
                if not paragraph.tag.endswith("}p"):
                    continue
                text = "".join(node.text or "" for node in paragraph.iter()
                               if node.tag.endswith("}t")).strip()
                if text:
                    blocks.append(_block(f"s{section_index}p{paragraph_index}", None,
                                         f"section-{section_index}", "paragraph", text))
    return {"blocks": blocks}


def _parse_xlsx(value: bytes) -> dict[str, Any]:
    workbook = load_workbook(io.BytesIO(value), read_only=True, data_only=True)
    blocks = []
    for sheet in workbook.worksheets:
        for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            cells = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
            if cells:
                blocks.append(_block(f"{sheet.title}!{row_index}", None, sheet.title,
                                     "table_row", " | ".join(cells)))
    return {"blocks": blocks}


def _parse_hwp(value: bytes) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "document.hwp"
        source.write_bytes(value)
        try:
            subprocess.run(
                ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(root), str(source)],
                check=True, capture_output=True, timeout=120,
            )
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            raise UnsupportedDocumentError("hwp_conversion_failed") from exc
        target = root / "document.pdf"
        if not target.exists():
            raise UnsupportedDocumentError("hwp_conversion_failed")
        return _parse_pdf(target.read_bytes())
