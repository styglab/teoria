from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from ..field_identity import _normalized_category
from ..periods import _resolve_profile_period


@dataclass(frozen=True)
class ActivityQuery:
    period_from: date
    period_to: date
    period_type: str
    from_year: int
    to_year: int
    organization_code: str
    company_number: str | None
    page: int
    page_size: int
    requested_stage: str
    view_mode: str
    sort: str
    query: str
    work_type: str | None
    large_category: str | None
    middle_category: str | None
    field_code: str | None
    stage_as_of: datetime

    @classmethod
    def from_inputs(cls, inputs: dict[str, Any], capability_id: str) -> ActivityQuery:
        period_from, period_to, _, period_type, from_year, to_year = (
            _resolve_profile_period(
                inputs,
                capability_id=capability_id,
            )
        )
        organization_code = str(inputs["organization_code"])
        company_number = (
            "".join(
                character
                for character in str(inputs.get("company_number") or "")
                if character.isdigit()
            )
            or None
        )
        page = int(inputs.get("page", 1))
        page_size = int(inputs.get("page_size", 20))
        requested_stage = str(inputs.get("stage", "all"))
        view_mode = str(inputs.get("view_mode", "flat"))
        sort = str(inputs.get("sort", "latest_activity_desc"))
        query = " ".join(str(inputs.get("query") or "").split()).casefold()
        work_type = str(inputs.get("work_type") or "").strip() or None
        large_category = _normalized_category(inputs.get("large_category"))
        middle_category = _normalized_category(inputs.get("middle_category"))
        field_code = str(inputs.get("field_code") or "").strip() or None
        stage_as_of = datetime.now(timezone.utc)
        return cls(
            period_from=period_from,
            period_to=period_to,
            period_type=period_type,
            from_year=from_year,
            to_year=to_year,
            organization_code=organization_code,
            company_number=company_number,
            page=page,
            page_size=page_size,
            requested_stage=requested_stage,
            view_mode=view_mode,
            sort=sort,
            query=query,
            work_type=work_type,
            large_category=large_category,
            middle_category=middle_category,
            field_code=field_code,
            stage_as_of=stage_as_of,
        )
