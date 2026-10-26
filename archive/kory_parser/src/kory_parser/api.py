"""Public synchronous parsing API; CPU work belongs in a Prefect task/process."""

from __future__ import annotations

import hashlib
import io
import struct
import zlib
from dataclasses import replace
from importlib import import_module
from pathlib import Path
from xml.etree.ElementTree import ParseError as XmlParseError
from zipfile import BadZipFile

import olefile
from defusedxml.common import DefusedXmlException

from .document_io import DocumentZip
from .markdown import blocks_to_markdown
from .models import Diagnostic, ParseError, ParseOptions, ParseResult, has_contents_title

READERS = {
    "hwpx": ("hangul_xml", "parse_hwpx"),
    "hwpml": ("hangul_xml", "parse_hwpml"),
    "hwp": ("hwp_binary", "parse_hwp"),
    "hwp3": ("hwp_legacy", "parse_hwp3"),
    "docx": ("office", "parse_docx"),
    "pptx": ("office", "parse_pptx"),
    "xlsx": ("office", "parse_xlsx"),
    "xls": ("office", "parse_xls"),
    "pdf": ("pdf", "parse_pdf"),
    "image": ("ocr", "parse_image"),
}


def detect_format(data: bytes, options: ParseOptions) -> str:
    if data.startswith(b"%PDF-") or b"%PDF-" in data[:1024]:
        return "pdf"
    if data.startswith(b"HWP Document File V3.00"):
        return "hwp3"
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        with olefile.OleFileIO(io.BytesIO(data)) as archive:
            if archive.exists("FileHeader"):
                return "hwp"
            if archive.exists("Workbook") or archive.exists("Book"):
                return "xls"
            if archive.exists("EncryptedPackage"):
                raise ParseError("ENCRYPTED", "Encrypted Office package")
        raise ParseError("UNSUPPORTED_FORMAT", "Unknown OLE document")
    if data.startswith(b"PK"):
        with DocumentZip(data, options) as archive:
            for part, kind in (
                ("Contents/content.hpf", "hwpx"),
                ("Contents/header.xml", "hwpx"),
                ("word/document.xml", "docx"),
                ("xl/workbook.xml", "xlsx"),
                ("ppt/presentation.xml", "pptx"),
            ):
                if part in archive.names:
                    return kind
        raise ParseError("UNSUPPORTED_FORMAT", "Unknown ZIP document")
    if (
        data.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"BM", b"II*\x00", b"MM\x00*"))
        or data[:4] == b"RIFF"
    ):
        return "image"
    if b"HWPML" in data[:4096].upper():
        return "hwpml"
    raise ParseError("UNSUPPORTED_FORMAT", "Document signature is not supported")


def parse(source: str | Path | bytes, options: ParseOptions | None = None) -> ParseResult:
    options = options or ParseOptions()
    kind, digest = "unknown", ""
    try:
        if isinstance(source, (str, Path)):
            with Path(source).open("rb") as stream:
                data = stream.read(options.max_input_bytes + 1)
        elif isinstance(source, bytes):
            data = source
        else:
            raise TypeError("source must be a path or bytes")
        if len(data) > options.max_input_bytes:
            raise ParseError("RESOURCE_LIMIT", "Input exceeds byte budget")
        digest = hashlib.sha256(data).hexdigest()
        kind = detect_format(data, options)
        if options.keep_trailing_empty_cols is None:
            options = replace(options, keep_trailing_empty_cols=kind in ("hwp", "hwpx", "hwp3"))
        module, function = READERS[kind]
        reader = getattr(import_module(f".{module}", __package__), function)
        result = reader(data, options)
        if options.recover_numbered_structure and kind == "hwpx":
            from .numbered_structure import recover_numbered_structure

            recover_numbered_structure(result.blocks)
        if (
            options.extract_contents
            and kind in {"hwp", "hwp3", "hwpx", "hwpml", "docx"}
            and has_contents_title(result.blocks)
        ):
            from .document_contents import recover_contents

            result.contents = recover_contents(result.blocks)
        result.sha256 = digest
        result.markdown = blocks_to_markdown(result.blocks)
        return result
    except ParseError as error:
        return ParseResult(
            False, kind, error_code=error.code, sha256=digest, warnings=[Diagnostic(error.code, str(error))]
        )
    except (KeyError, IndexError) as error:
        return ParseResult(
            False,
            kind,
            error_code="INTERNAL_ERROR",
            sha256=digest,
            warnings=[Diagnostic("INTERNAL_ERROR", f"{type(error).__name__}: {error}")],
        )
    except (
        OSError,
        ValueError,
        BadZipFile,
        XmlParseError,
        DefusedXmlException,
        zlib.error,
        struct.error,
    ) as error:
        return ParseResult(
            False,
            kind,
            error_code="INVALID_FILE",
            sha256=digest,
            warnings=[Diagnostic("INVALID_FILE", f"{type(error).__name__}: {error}")],
        )
