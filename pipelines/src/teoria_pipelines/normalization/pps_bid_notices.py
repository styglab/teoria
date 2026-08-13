from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from teoria_pipelines.models import ExtractedBatch, NormalizedBidNoticeBatch, RawProviderRecord

NOTICE_TYPES = {
    "list_construction_bid_notices": "construction",
    "list_service_bid_notices": "service",
    "list_foreign_bid_notices": "foreign",
    "list_goods_bid_notices": "goods",
    "list_other_bid_notices": "other",
}

PARTICIPATION_REGION_CODES = {
    "전국": "00", "서울특별시": "11", "부산광역시": "26", "대구광역시": "27",
    "인천광역시": "28", "광주광역시": "29", "대전광역시": "30", "울산광역시": "31",
    "세종특별자치시": "36", "경기도": "41", "강원도": "42", "충청북도": "43",
    "충청남도": "44", "전라북도": "45", "전라남도": "46", "경상북도": "47",
    "경상남도": "48", "제주도": "50", "제주특별자치도": "50",
    "강원특별자치도": "51", "전북특별자치도": "52", "기타": "99",
}


class BidNoticeNormalizationError(ValueError):
    pass


def parse_industry_reference(value: Any) -> dict[str, str | None] | None:
    """Parse the provider's documented ``industry name/industry code`` notation."""
    text = str(value or "").strip().strip("[]").strip()
    if not text:
        return None
    match = re.fullmatch(r"(?:(?P<name>.+?)\s*/\s*)?(?P<code>\d+)", text)
    if match:
        name = str(match.group("name") or "").strip() or None
        return {"name": name, "code": match.group("code"), "text": text}
    return {"name": text, "code": None, "text": text}


def parse_permitted_industries(value: Any) -> list[dict[str, str | None]]:
    """Split ``[name/code],[name/code]`` without guessing unprovided codes."""
    text = str(value or "").strip()
    if not text:
        return []
    bracketed = re.findall(r"\[([^\[\]]+)\]", text)
    parts = bracketed or [part for part in re.split(r"\s*,\s*", text) if part.strip()]
    return [item for part in parts if (item := parse_industry_reference(part)) is not None]


def parse_industry_main_field_groups(value: Any) -> list[dict[str, Any]]:
    """Parse PPS main-field syntax: ``^`` is AND and bracket groups are OR."""
    text = str(value or "").strip()
    if not text:
        return []
    bracketed = re.findall(r"\[([^\[\]]+)\]", text)
    parts = bracketed or [part for part in re.split(r"\s*,\s*", text) if part.strip()]
    groups: list[dict[str, Any]] = []
    for index, part in enumerate(parts, start=1):
        tokens = [token.strip() for token in part.split("^") if token.strip()]
        if not tokens:
            continue
        sequence = tokens.pop(0) if tokens[0].isdigit() else str(index)
        if tokens:
            groups.append({"sequence": sequence, "operator": "all", "fields": tokens})
    return groups


def participation_region_code(name: Any) -> str | None:
    """Resolve only provider-documented province-level region names and aliases."""
    return PARTICIPATION_REGION_CODES.get(str(name or "").strip())


def normalize_bid_notice_batch(batch: ExtractedBatch) -> NormalizedBidNoticeBatch:
    normalized = NormalizedBidNoticeBatch()
    for record in batch.records:
        if record.operation_id in NOTICE_TYPES:
            notice, documents = normalize_bid_notice(record)
            normalized.notices.append(notice)
            normalized.documents.extend(documents)
        elif record.operation_id == "list_license_restrictions":
            normalized.license_restrictions.append(normalize_license_restriction(record))
        elif record.operation_id == "list_participation_regions":
            normalized.participation_regions.append(normalize_participation_region(record))
        else:
            raise BidNoticeNormalizationError(f"unsupported operation '{record.operation_id}'")
    return normalized


def normalize_bid_notice(record: RawProviderRecord) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    value = record.payload
    notice_number, notice_order = _notice_identity(value, record.operation_id)
    notice = {
        "notice_number": notice_number, "notice_order": notice_order,
        "work_type": NOTICE_TYPES[record.operation_id],
        "notice_name": _text(value.get("bidNtceNm")),
        "notice_kind_name": _text(value.get("ntceKindNm")),
        "registration_type_name": _text(value.get("rgstTyNm")),
        "is_re_notice": _boolean(value.get("reNtceYn")),
        "notice_published_at": _datetime(value.get("bidNtceDt")),
        "bid_begin_at": _datetime(value.get("bidBeginDt")),
        "bid_deadline_at": _datetime(value.get("bidClseDt")),
        "opening_at": _datetime(value.get("opengDt")),
        "notice_organization_code": _text(value.get("ntceInsttCd")),
        "notice_organization_name": _text(value.get("ntceInsttNm")),
        "demand_organization_code": _text(value.get("dminsttCd")),
        "demand_organization_name": _text(value.get("dminsttNm")),
        "bid_method_name": _text(value.get("bidMethdNm")),
        "contract_method_name": _text(value.get("cntrctCnclsMthdNm")),
        "estimated_price": _decimal(value.get("presmptPrce")),
        "allocated_budget": _decimal(value.get("asignBdgtAmt") or value.get("bdgtAmt")),
        "detail_url": _text(value.get("bidNtceDtlUrl")),
        "notice_url": _text(value.get("bidNtceUrl")),
        "standard_document_url": _text(value.get("stdNtceDocUrl")),
        "participation_restriction_region_code": _text(value.get("prtcptLmtRgnCd")),
        "participation_restriction_region_name": _text(value.get("prtcptLmtRgnNm")),
        "source_registered_at": _datetime(value.get("rgstDt")),
        "source_changed_at": _datetime(value.get("chgDt")),
        "source_record_hash": record.source_record_hash,
        "source_payload": value,
    }
    return notice, _documents(value, notice_number, notice_order)


def normalize_license_restriction(record: RawProviderRecord) -> dict[str, Any]:
    value = record.payload
    number, order = _notice_identity(value, record.operation_id)
    return {
        "notice_number": number, "notice_order": order,
        "restriction_group_number": _text(value.get("lmtGrpNo")) or "0",
        "restriction_sequence": _text(value.get("lmtSno")) or "0",
        "license_restriction_name": _text(value.get("lcnsLmtNm")),
        "permitted_industry_list": _text(value.get("permsnIndstrytyList")),
        "industry_main_field_list": _text(value.get("indstrytyMfrcFldList")),
        "business_type_name": _text(value.get("bsnsDivNm")),
        "source_registered_at": _datetime(value.get("rgstDt")),
        "source_record_hash": record.source_record_hash,
    }


def normalize_participation_region(record: RawProviderRecord) -> dict[str, Any]:
    value = record.payload
    number, order = _notice_identity(value, record.operation_id)
    region_name = _text(value.get("prtcptPsblRgnNm"))
    return {
        "notice_number": number, "notice_order": order,
        "restriction_sequence": _text(value.get("lmtSno")) or "0",
        "participation_region_code": participation_region_code(region_name),
        "participation_region_name": region_name,
        "business_type_name": _text(value.get("bsnsDivNm")),
        "source_registered_at": _datetime(value.get("rgstDt")),
        "source_record_hash": record.source_record_hash,
    }


def _documents(value: dict[str, Any], number: str, order: str) -> list[dict[str, Any]]:
    candidates = [
        (f"notice_spec_{i}", _text(value.get(f"ntceSpecFileNm{i}")), _text(value.get(f"ntceSpecDocUrl{i}")))
        for i in range(1, 11)
    ]
    candidates.append(("standard_notice", "표준공고서", _text(value.get("stdNtceDocUrl"))))
    candidates.extend(
        (f"site_explanation_{i}", f"현장설명서{i}", _text(value.get(f"sptDscrptDocUrl{i}")))
        for i in range(1, 6)
    )
    records = []
    for slot, file_name, source_url in candidates:
        if not source_url:
            continue
        records.append({
            "document_id": uuid5(NAMESPACE_URL, f"pps-bid-document:{number}:{order}:{slot}:{source_url}"),
            "notice_number": number, "notice_order": order, "document_slot": slot,
            "file_name": file_name or Path(source_url).name or None, "source_url": source_url,
        })
    return records


def _notice_identity(value: dict[str, Any], operation_id: str) -> tuple[str, str]:
    number, order = _text(value.get("bidNtceNo")), _text(value.get("bidNtceOrd"))
    if not number or order is None:
        raise BidNoticeNormalizationError(f"{operation_id} record is missing bidNtceNo or bidNtceOrd")
    return number, order


def _text(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _boolean(value: Any) -> bool | None:
    text = (_text(value) or "").upper()
    if not text: return None
    if text in {"Y", "YES", "TRUE", "1"}: return True
    if text in {"N", "NO", "FALSE", "0"}: return False
    raise BidNoticeNormalizationError(f"invalid boolean value {value!r}")


def _decimal(value: Any) -> Decimal | None:
    text = _text(value)
    if text is None: return None
    try: return Decimal(text.replace(",", ""))
    except InvalidOperation as exc: raise BidNoticeNormalizationError(f"invalid decimal value {value!r}") from exc


def _datetime(value: Any) -> datetime | None:
    text = _text(value)
    if text is None: return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y-%m-%dT%H:%M:%S"):
        try: return datetime.strptime(text, pattern)
        except ValueError: continue
    raise BidNoticeNormalizationError(f"invalid datetime value {value!r}")
