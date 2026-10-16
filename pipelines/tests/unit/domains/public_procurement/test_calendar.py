from datetime import date, datetime, timezone

import pytest

from teoria_pipelines.domains.public_procurement import calendar
from teoria_pipelines.domains.public_procurement.bid_notices.ingestion_tasks import (
    determine_bid_notice_window,
)
from teoria_pipelines.execution.tasks import determine_incremental_window


@pytest.mark.parametrize(
    ("utc_hour", "expected"),
    [(14, date(2026, 10, 15)), (15, date(2026, 10, 16)), (23, date(2026, 10, 16))],
)
def test_procurement_day_changes_at_korean_midnight(monkeypatch, utc_hour, expected):
    instant = datetime(2026, 10, 15, utc_hour, 0, tzinfo=timezone.utc)

    class FixedDateTime:
        @classmethod
        def now(cls, tz):
            return instant.astimezone(tz)

    monkeypatch.setattr(calendar, "datetime", FixedDateTime)

    assert calendar.procurement_today() == expected
    notice_window = determine_bid_notice_window.fn(lookback_days=1)
    contract_window = determine_incremental_window.fn(
        lookback_days=1, today=calendar.procurement_today()
    )
    assert notice_window.start == notice_window.end == expected
    assert contract_window == notice_window
