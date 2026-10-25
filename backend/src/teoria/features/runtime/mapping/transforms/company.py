from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation


_KOREAN_TENURE_PATTERN = re.compile(
    r"^(?:(?P<years>\d+)\s*년)?\s*(?:(?P<months>\d+)\s*개월)?$"
)


def parse_korean_tenure_years(
    value: str | int | float | Decimal | None,
) -> Decimal | None:
    """Convert an FSC tenure value such as ``5년 5개월`` to decimal years."""
    if value is None or str(value).strip() == "":
        return None
    normalized = str(value).replace(",", "").strip()
    try:
        return Decimal(normalized)
    except InvalidOperation:
        match = _KOREAN_TENURE_PATTERN.fullmatch(normalized)
        if match is None or not any(match.groupdict().values()):
            raise ValueError(f"unsupported employee tenure value: {value!r}")
        years = Decimal(match.group("years") or 0)
        months = Decimal(match.group("months") or 0)
        return (years + months / Decimal(12)).quantize(Decimal("0.000001"))


def normalize_representative_names(value: str | None) -> list[str]:
    if not value:
        return []
    return list(dict.fromkeys(name.strip() for name in value.split(",") if name.strip()))


def combine_korean_address(*, base_address: str | None, detail_address: str | None) -> str | None:
    parts = [value.strip() for value in (base_address, detail_address) if value and value.strip()]
    return " ".join(parts) or None


def collect_representative_names(*, primary_name: str | None, alternate_name: str | None) -> list[str]:
    names: list[str] = []
    for value in (primary_name, alternate_name):
        names.extend(normalize_representative_names(value))
    return list(dict.fromkeys(names))
def resolve_listing_status(*, listed_date: str | None, delisted_date: str | None) -> str | None:
    if delisted_date and delisted_date.strip():
        return "delisted"
    if listed_date and listed_date.strip():
        return "listed"
    return None


def resolve_financial_statement_scope(*, code: str | None, name: str | None) -> str | None:
    text = " ".join(value for value in (code, name) if value).lower()
    if "consolidated" in text or "연결" in text or code == "110":
        return "consolidated"
    if "separate" in text or "별도" in text or code == "120":
        return "separate"
    return None


def resolve_venture_company_disclosure_status(business_registration_number: str | None) -> str | None:
    return "currently_disclosed" if business_registration_number else None


def certification_period_start(value: str | None) -> date | None:
    if not value or "~" not in value:
        return None
    raw = value.split("~", 1)[0].strip()
    return date.fromisoformat(raw) if raw else None


def certification_period_end(value: str | None) -> date | None:
    if not value or "~" not in value:
        return None
    raw = value.split("~", 1)[1].strip()
    return date.fromisoformat(raw) if raw else None


def innobiz_certification_kind(_: str | None) -> str:
    return "innobiz"


def mainbiz_certification_kind(_: str | None) -> str:
    return "mainbiz"
