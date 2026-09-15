from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from teoria_pipelines.models import ExtractedBatch, NormalizedBidResultBatch, RawProviderRecord


AWARD_TYPES = {
    "list_goods_bid_awards": "goods",
    "list_construction_bid_awards": "construction",
    "list_service_bid_awards": "service",
    "list_foreign_bid_awards": "foreign",
}
KST = ZoneInfo("Asia/Seoul")


class BidResultNormalizationError(ValueError):
    pass


def normalize_bid_result_batch(batch: ExtractedBatch) -> NormalizedBidResultBatch:
    result = NormalizedBidResultBatch()
    for record in batch.records:
        if record.operation_id in AWARD_TYPES:
            result.awards.append(normalize_bid_award_record(record))
        elif record.operation_id == "list_completed_opening_results":
            result.opening_participants.append(normalize_opening_participant_record(record))
        else:
            raise BidResultNormalizationError(f"unsupported operation '{record.operation_id}'")
    return result


def normalize_bid_award_record(record: RawProviderRecord) -> dict[str, Any]:
    value = record.payload
    key = _notice_key(value, record.operation_id)
    return {
        **key,
        "work_type": AWARD_TYPES[record.operation_id],
        "notice_division_code": _text(value.get("ntceDivCd")),
        "notice_name": _text(value.get("bidNtceNm")),
        "participant_count": _integer(value.get("prtcptCnum")),
        "winner_name": _text(value.get("bidwinnrNm")),
        "winner_business_registration_number": _business_number(value.get("bidwinnrBizno")),
        "winner_representative_name": _text(value.get("bidwinnrCeoNm")),
        "winner_address": _text(value.get("bidwinnrAdrs")),
        "winner_telephone_number": _text(value.get("bidwinnrTelNo")),
        "winning_amount": _decimal(value.get("sucsfbidAmt")),
        "winning_rate": _decimal(value.get("sucsfbidRate")),
        "opening_at": _kst_datetime(value.get("rlOpengDt")),
        "demand_organization_code": _text(value.get("dminsttCd")),
        "demand_organization_name": _text(value.get("dminsttNm")),
        "source_registered_at": _kst_datetime(value.get("rgstDt")),
        "final_award_date": _date(value.get("fnlSucsfDate") or value.get("FnlSucsfDate")),
        "winner_manager_name": _text(value.get("fnlSucsfCorpOfcl")),
        "source_record_hash": record.source_record_hash,
    }


def normalize_opening_participant_record(record: RawProviderRecord) -> dict[str, Any]:
    value = record.payload
    business_number = _business_number(value.get("prcbdrBizno"))
    if not business_number:
        raise BidResultNormalizationError(
            f"{record.operation_id} record is missing prcbdrBizno"
        )
    return {
        **_notice_key(value, record.operation_id),
        "business_registration_number": business_number,
        "opening_result_type_name": _text(value.get("opengRsltDivNm")),
        "opening_rank": _integer(value.get("opengRank")),
        "participant_name": _text(value.get("prcbdrNm")),
        "representative_name": _text(value.get("prcbdrCeoNm")),
        "bid_amount": _decimal(value.get("bidprcAmt")),
        "bid_rate": _decimal(value.get("bidprcrt")),
        "remark": _text(value.get("rmrk")),
        "trade_bid_amount_url": _text(value.get("cnsttyAccotBidAmtUrl")),
        "draw_number_1": _text(value.get("drwtNo1")),
        "draw_number_2": _text(value.get("drwtNo2")),
        "bid_at": _kst_datetime(value.get("bidprcDt")),
        "bid_price_evaluation_score": _decimal(value.get("bidPrceEvlVal")),
        "technical_evaluation_raw_score": _decimal(value.get("techEvlNaturVal")),
        "technical_evaluation_score": _decimal(value.get("techEvlVal")),
        "total_evaluation_score": _decimal(value.get("totalEvlAmtVal")),
        "source_record_hash": record.source_record_hash,
    }


def _notice_key(value: dict[str, Any], operation_id: str) -> dict[str, str]:
    fields = {
        "notice_number": _text(value.get("bidNtceNo")),
        "notice_order": _text(value.get("bidNtceOrd")),
        "bid_classification_number": _text(value.get("bidClsfcNo")),
        "rebid_number": _text(value.get("rbidNo")),
    }
    missing = [name for name, item in fields.items() if item is None]
    if missing:
        raise BidResultNormalizationError(
            f"{operation_id} record is missing {', '.join(missing)}"
        )
    return fields  # type: ignore[return-value]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _business_number(value: Any) -> str | None:
    text = _text(value)
    return re.sub(r"\D", "", text) or None if text else None


def _integer(value: Any) -> int | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return int(text.replace(",", ""))
    except ValueError as exc:
        raise BidResultNormalizationError(f"invalid integer value {value!r}") from exc


def _decimal(value: Any) -> Decimal | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation as exc:
        raise BidResultNormalizationError(f"invalid decimal value {value!r}") from exc


def _date(value: Any) -> date | None:
    text = _text(value)
    if text is None:
        return None
    for pattern in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise BidResultNormalizationError(f"invalid date value {value!r}")


def _kst_datetime(value: Any) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=KST)
        except ValueError:
            continue
    raise BidResultNormalizationError(f"invalid datetime value {value!r}")
