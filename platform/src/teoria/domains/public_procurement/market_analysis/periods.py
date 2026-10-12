from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from teoria.runtime.capability.contracts import CapabilityExecutionError


def _fiscal_period_start(as_of: date | datetime, period_years: int) -> date:
    """Return January 1 of the oldest included calendar fiscal year."""
    as_of_date = as_of.date() if isinstance(as_of, datetime) else as_of
    return date(as_of_date.year - period_years + 1, 1, 1)


def _shift_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def _resolve_profile_period(
    inputs: dict[str, Any], *, capability_id: str,
) -> tuple[date, date, int, str, int | None, int | None]:
    """Resolve a profile window as a half-open date range.

    Explicit years override ``period_years`` and represent complete calendar
    years.  The current year is capped at today so a response never claims to
    cover future activity.
    """
    from_value = inputs.get("period_from_year")
    to_value = inputs.get("period_to_year")
    if (from_value is None) != (to_value is None):
        raise CapabilityExecutionError(
            "invalid_period_range",
            "period_from_year and period_to_year must be provided together",
            capability_id=capability_id,
        )
    today = date.today()
    if from_value is not None:
        from_year = int(from_value)
        to_year = int(to_value)
        if from_year > to_year:
            raise CapabilityExecutionError(
                "invalid_period_range",
                "period_from_year must be less than or equal to period_to_year",
                capability_id=capability_id,
            )
        if to_year > today.year:
            raise CapabilityExecutionError(
                "invalid_period_range",
                "period_to_year cannot be later than the current year",
                capability_id=capability_id,
            )
        return (
            date(from_year, 1, 1),
            min(date(to_year + 1, 1, 1), today + timedelta(days=1)),
            to_year - from_year + 1,
            "explicit_calendar_year_range",
            from_year,
            to_year,
        )
    period_years = int(inputs.get("period_years", 5))
    return (
        _fiscal_period_start(today, period_years), today + timedelta(days=1),
        period_years, "calendar_fiscal_years", None, None,
    )
