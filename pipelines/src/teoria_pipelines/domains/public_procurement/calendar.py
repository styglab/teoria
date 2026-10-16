"""Calendar dates for Korean procurement; stored audit timestamps remain UTC."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

SEOUL_TIMEZONE = ZoneInfo("Asia/Seoul")


def procurement_today() -> date:
    return datetime.now(SEOUL_TIMEZONE).date()
