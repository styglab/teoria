from __future__ import annotations

from datetime import date
from xml.etree import ElementTree as ET

from teoria_pipelines.domains.legal_information.laws.models import LawVersion, ParsedLaw

PARSER_VERSION = "1.0.0"
MAX_XML_BYTES = 32 * 1024 * 1024


class LawValidationError(ValueError):
    """Safe diagnostic code; never include provider bodies or request secrets."""


def parse_xml(raw: bytes, expected_root: str) -> ET.Element:
    if len(raw) > MAX_XML_BYTES:
        raise LawValidationError("law_response_too_large")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise LawValidationError("law_xml_dtd_not_allowed")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise LawValidationError("law_invalid_xml") from None
    if root.tag != expected_root:
        raise LawValidationError("law_unexpected_root")
    return root


def text(node: ET.Element, tag: str, *, required: bool = False) -> str:
    value = node.findtext(tag, "").strip()
    if required and not value:
        raise LawValidationError("law_missing_required_field")
    return value


def provider_id(value: str) -> str:
    if not value or not value.isascii() or not value.isdigit():
        raise LawValidationError("law_invalid_identifier")
    return str(int(value))


def provider_date(value: str) -> date:
    if len(value) != 8 or not value.isascii() or not value.isdigit():
        raise LawValidationError("law_invalid_date")
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    except ValueError:
        raise LawValidationError("law_invalid_date") from None


def parse_listing(raw: bytes) -> tuple[int, int, list[LawVersion]]:
    root = parse_xml(raw, "LawSearch")
    try:
        total, page = int(text(root, "totalCnt", required=True)), int(text(root, "page", required=True))
    except ValueError:
        raise LawValidationError("law_invalid_pagination") from None
    if total < 0 or page < 1:
        raise LawValidationError("law_invalid_pagination")
    versions = []
    for node in root.findall("law"):
        values = {child.tag: (child.text or "").strip() for child in node}
        versions.append(LawVersion(
            law_id=provider_id(text(node, "법령ID", required=True)),
            mst=provider_id(text(node, "법령일련번호", required=True)),
            effective_date=provider_date(text(node, "시행일자", required=True)),
            name=text(node, "법령명한글", required=True),
            promulgation_date=provider_date(text(node, "공포일자", required=True)),
            promulgation_number=text(node, "공포번호"),
            amendment_type=text(node, "제개정구분명"), listing=values,
        ))
    return total, page, versions


def parse_law(raw: bytes, version: LawVersion) -> ParsedLaw:
    root = parse_xml(raw, "법령")
    basic = root.find("기본정보")
    if basic is None:
        raise LawValidationError("law_missing_basic_information")
    # Effective-date XML does not always echo MST (it can expose 법령키 instead).
    # Match the publication identity and date, and MST when it is present.
    mst = root.get("법령일련번호") or text(basic, "법령일련번호")
    law_id = provider_id(text(basic, "법령ID", required=True))
    effective = provider_date(text(basic, "시행일자", required=True))
    promulgation = provider_date(text(basic, "공포일자", required=True))
    if (law_id != version.law_id or effective != version.effective_date
            or promulgation != version.promulgation_date
            or text(basic, "공포번호", required=True) != version.promulgation_number
            or (mst and provider_id(mst) != version.mst)):
        raise LawValidationError("law_version_mismatch")
    metadata = {child.tag: "".join(child.itertext()).strip() for child in basic}
    provisions: list[dict] = []

    def add(node: ET.Element, kind: str, path: str, parent: str | None,
            number: str, title: str, content_tag: str, effective_tag: str | None = None):
        contents = ["".join(c.itertext()).strip() for c in node.findall(content_tag)]
        provisions.append({
            "path": path, "parent_path": parent, "kind": kind, "number": number,
            "title": title, "content": "\n".join(contents),
            "effective_date": provider_date(text(node, effective_tag))
                if effective_tag and text(node, effective_tag) else None,
            "source_xml": ET.tostring(node, encoding="unicode"),
        })

    levels = [("항", "paragraph", "항번호", "항내용"),
              ("호", "subparagraph", "호번호", "호내용"),
              ("목", "item", "목번호", "목내용")]

    def descend(node: ET.Element, parent_path: str):
        # Some articles have 호 directly without a numbered 항.
        for tag, kind, number_tag, content_tag in levels:
            for index, child in enumerate(node.findall(tag), 1):
                path = f"{parent_path}/{tag}[{index}]"
                add(child, kind, path, parent_path, text(child, number_tag), "", content_tag)
                descend(child, path)

    articles = root.findall("조문/조문단위")
    for index, article in enumerate(articles, 1):
        path = f"/법령/조문/조문단위[{index}]"
        number = text(article, "조문번호")
        branch = text(article, "조문가지번호")
        marker = text(article, "조문여부", required=True)
        if marker not in {"조문", "전문"}:
            raise LawValidationError("law_unknown_article_marker")
        kind = "article" if marker == "조문" else "heading"
        if kind == "article":
            number = provider_id(number)
        if branch and int(provider_id(branch)) > 0:
            number += f"의{provider_id(branch)}"
        add(article, kind, path, None, number, text(article, "조문제목"), "조문내용", "조문시행일자")
        descend(article, path)
    for index, node in enumerate(root.findall("부칙/부칙단위"), 1):
        add(node, "addendum", f"/법령/부칙/부칙단위[{index}]", None,
            text(node, "부칙공포번호"), "", "부칙내용")
    if not any(p["kind"] == "article" for p in provisions):
        raise LawValidationError("law_missing_articles")
    attachments = []
    for index, node in enumerate(root.findall("별표/별표단위"), 1):
        # Preserve all wire fields (including nested links) without inventing an
        # attachment version from a current-law name search.
        attachments.append({"path": f"/법령/별표/별표단위[{index}]",
            "number": text(node, "별표번호"), "branch": text(node, "별표가지번호"),
            "kind": text(node, "별표구분"), "title": text(node, "별표제목"),
            "source_xml": ET.tostring(node, encoding="unicode")})
    return ParsedLaw(version, PARSER_VERSION, metadata, provisions, attachments)
