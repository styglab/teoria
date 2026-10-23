"""Small, original fixtures with explicit expected structure; no procurement document contents."""

import io
import struct
from zipfile import ZIP_DEFLATED, ZipFile


def zip_document(parts: dict[str, str | bytes]) -> bytes:
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return stream.getvalue()


def hwpx(section: str) -> bytes:
    return zip_document(
        {
            "Contents/header.xml": '<head><charPr id="0"/></head>',
            "Contents/section0.xml": "<sec>" + section + "</sec>",
        }
    )


def hwpx_cell(text: str, row=0, col=0, rs=1, cs=1) -> str:
    return (
        f"<tc><subList><p><run><t>{text}</t></run></p></subList>"
        f'<cellAddr rowAddr="{row}" colAddr="{col}"/>'
        f'<cellSpan rowSpan="{rs}" colSpan="{cs}"/></tc>'
    )


def docx(body: str) -> bytes:
    return zip_document(
        {
            "word/document.xml": '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>" + body + "</w:body></w:document>"
        }
    )


def hwp_record(tag: int, level: int, data: bytes) -> bytes:
    return struct.pack("<I", tag | (level << 10) | (len(data) << 20)) + data


def hwp5(body: bytes) -> bytes:
    """Minimal valid CFB, with large streams so no mini-FAT is required."""
    header = bytearray(512)
    header[:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<HHHHH", header, 24, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<IIIIIIIII", header, 40, 0, 1, 1, 0, 4096, 0xFFFFFFFE, 0, 0xFFFFFFFE, 0)
    struct.pack_into("<109I", header, 76, 0, *([0xFFFFFFFF] * 108))
    fat = [0xFFFFFFFF] * 128
    fat[0], fat[1] = 0xFFFFFFFD, 0xFFFFFFFE
    for begin in (2, 10):
        for n in range(begin, begin + 7):
            fat[n] = n + 1
        fat[begin + 7] = 0xFFFFFFFE

    def entry(name, kind, start=0xFFFFFFFE, size=0, right=0xFFFFFFFF, child=0xFFFFFFFF):
        data = bytearray(128)
        name_bytes = (name + "\0").encode("utf-16le")
        data[: len(name_bytes)] = name_bytes
        struct.pack_into("<HBBIII", data, 64, len(name_bytes), kind, 1, 0xFFFFFFFF, right, child)
        struct.pack_into("<IQ", data, 116, start, size)
        return data

    directory = (
        entry("Root Entry", 5, child=1)
        + entry("FileHeader", 2, 2, 4096, right=2)
        + entry("BodyText", 1, child=3)
        + entry("Section0", 2, 10, 4096)
    )
    file_header = bytearray(4096)
    file_header[:18] = b"HWP Document File\0"
    file_header[35] = 5
    assert len(body) <= 4096
    body += hwp_record(0, 0, bytes(4096 - len(body) - 4))
    return bytes(header) + struct.pack("<128I", *fat) + directory + bytes(file_header) + body


def hwp3(text: str) -> bytes:
    header = bytearray(1166)
    header[:24] = b"HWP Document File V3.00 "
    content = struct.pack("<7HH", *([0] * 8))
    para = struct.pack("<BHHB", 1, len(text) + 1, 0, 0) + bytes(37)
    content += para + "".join(text + "\r").encode("utf-16le")
    content += bytes(43)
    return bytes(header) + content


def simple_pdf() -> bytes:
    """An ASCII PDF with text above and inside a 2x2 ruled table."""
    stream = (
        b"BT /F1 12 Tf 40 250 Td (Heading) Tj ET\n"
        b"40 100 m 240 100 l S 40 150 m 240 150 l S 40 200 m 240 200 l S\n"
        b"40 100 m 40 200 l S 140 100 m 140 200 l S 240 100 m 240 200 l S\n"
        b"BT /F1 12 Tf 50 175 Td (CPU) Tj ET\n"
        b"BT /F1 12 Tf 150 175 Td (32) Tj ET\n"
        b"BT /F1 12 Tf 50 125 Td (RAM) Tj ET\n"
        b"BT /F1 12 Tf 150 125 Td (64) Tj ET\n"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{n} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)
