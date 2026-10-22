"""Bounded ZIP/XML and DEFLATE input; never extract archive members to disk."""

from __future__ import annotations

import io
import zlib
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree

from .models import ParseError, ParseOptions


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def xml(data: bytes, options: ParseOptions):
    root = ElementTree.fromstring(data)
    count = 0
    stack = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > options.max_xml_nodes or depth > options.max_depth * 8:
            raise ParseError("RESOURCE_LIMIT", "XML nesting or node limit exceeded")
        stack.extend((child, depth + 1) for child in node)
    return root


class DocumentZip:
    def __init__(self, data: bytes, options: ParseOptions):
        self.options = options
        try:
            self.archive = ZipFile(io.BytesIO(data))
        except BadZipFile as error:
            raise ParseError("INVALID_FILE", "Invalid ZIP container") from error
        entries = self.archive.infolist()
        names = [i.filename for i in entries]
        if len(set(names)) != len(names):
            self.archive.close()
            raise ParseError("INVALID_FILE", "Duplicate ZIP member names")
        if len(entries) > 100_000 or sum(i.file_size for i in entries) > options.max_expanded_bytes:
            self.archive.close()
            raise ParseError("RESOURCE_LIMIT", "Expanded ZIP exceeds budget")
        if any(i.flag_bits & 1 for i in entries):
            self.archive.close()
            raise ParseError("ENCRYPTED", "Encrypted ZIP container")
        if any(PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts for n in names):
            self.archive.close()
            raise ParseError("INVALID_FILE", "Unsafe ZIP member path")
        self.names = set(names)

    def read(self, name: str) -> bytes:
        try:
            return self.archive.read(name)
        except KeyError as error:
            raise ParseError("INVALID_FILE", f"Missing ZIP member: {name}") from error

    def xml(self, name: str):
        return xml(self.read(name), self.options)

    def close(self) -> None:
        self.archive.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def inflate(data: bytes, options: ParseOptions, raw: bool = True) -> bytes:
    decoder = zlib.decompressobj(-15 if raw else 15)
    out = decoder.decompress(data, options.max_expanded_bytes + 1)
    if len(out) > options.max_expanded_bytes or decoder.unconsumed_tail:
        raise ParseError("RESOURCE_LIMIT", "DEFLATE output exceeds budget")
    if not decoder.eof:
        raise ParseError("INVALID_FILE", "Truncated DEFLATE stream")
    return out
