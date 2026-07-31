#!/usr/bin/env python3
"""Extract provider reference documents into reviewable JSON using stdlib tools."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

TEXT_SUFFIXES = {".txt", ".md", ".json", ".yaml", ".yml", ".xml", ".csv"}
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def word_text(element: ElementTree.Element) -> str:
    return "".join(node.text or "" for node in element.iter(f"{{{WORD_NS}}}t")).strip()


def extract_docx(path: Path) -> list[dict[str, object]]:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    body = root.find(f"{{{WORD_NS}}}body")
    if body is None:
        return []

    blocks: list[dict[str, object]] = []
    table_index = 0
    for child in body:
        if child.tag == f"{{{WORD_NS}}}p":
            value = word_text(child)
            if value:
                blocks.append({"type": "paragraph", "text": value})
        elif child.tag == f"{{{WORD_NS}}}tbl":
            rows: list[list[str]] = []
            for row in child.findall(f"{{{WORD_NS}}}tr"):
                rows.append([word_text(cell) for cell in row.findall(f"{{{WORD_NS}}}tc")])
            blocks.append({"type": "table", "index": table_index, "rows": rows})
            table_index += 1
    return blocks


def extract_pdf(path: Path) -> list[dict[str, object]]:
    executable = shutil.which("pdftotext")
    if executable is None:
        raise RuntimeError("PDF extraction requires the 'pdftotext' executable")
    result = subprocess.run(
        [executable, str(path), "-"], check=True, capture_output=True, text=True
    )
    return [{"type": "text", "text": result.stdout}]


def extract(path: Path) -> dict[str, object]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        blocks = extract_docx(path)
        document_format = "docx"
    elif suffix == ".pdf":
        blocks = extract_pdf(path)
        document_format = "pdf"
    elif suffix in TEXT_SUFFIXES:
        blocks = [{"type": "text", "text": path.read_text(encoding="utf-8-sig")}]
        document_format = suffix.removeprefix(".")
    else:
        raise ValueError(f"unsupported reference format: {path}")
    return {"path": str(path), "format": document_format, "blocks": blocks}


def resolve_files(inputs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for input_path in inputs:
        if input_path.is_dir():
            files.extend(path for path in input_path.rglob("*") if path.is_file())
        elif input_path.is_file():
            files.append(input_path)
        else:
            raise FileNotFoundError(input_path)
    return sorted(set(files))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract DOCX, PDF, and text provider references as JSON."
    )
    parser.add_argument("paths", nargs="+", type=Path, help="Reference files or directories")
    args = parser.parse_args()

    try:
        documents = [extract(path) for path in resolve_files(args.paths)]
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    json.dump({"documents": documents}, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
