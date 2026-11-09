from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def parse_date(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    value = value.strip()
    for pattern in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d", "%y/%m/%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"unsupported date value: {value!r}")


def parse_datetime(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    value = value.strip()
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    raise ValueError(f"unsupported datetime value: {value!r}")


def format_date_yyyymmdd(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        raise ValueError(f"expected date value, got {type(value).__name__}")
    return value.strftime("%Y%m%d")


def format_year(value: int | str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    year = int(str(value).strip())
    if year < 0 or year > 9999:
        raise ValueError(f"unsupported year value: {value!r}")
    return f"{year:04d}"


def to_integer(value: str | int | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(str(value).replace(",", "").strip())


def to_number(value: str | int | float | Decimal | None) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    cleaned = str(value).replace(",", "").replace("%", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"invalid numeric value: {value!r}") from exc


def yes_no_to_boolean(value: str | bool | None) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = value.strip().upper()
    if normalized in {"Y", "YES", "TRUE", "1", "해당"}:
        return True
    if normalized in {"N", "NO", "FALSE", "0", "비해당"}:
        return False
    raise ValueError(f"unsupported boolean value: {value!r}")
