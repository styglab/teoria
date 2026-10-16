from datetime import datetime
from decimal import Decimal
from typing import cast

from pydantic import BaseModel, ConfigDict
from typing_extensions import TypedDict

from ..row_validation import _validate


class ParticipationRow(TypedDict):
    bid_notice_id: str
    participation_date: datetime | None
    rank: int | None
    participant_count: int | None
    bid_amount: Decimal | None
    winning_amount: Decimal | None
    result: str | None


class _ParticipationSchema(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    bid_notice_id: str
    participation_date: datetime | None
    rank: int | None
    participant_count: int | None
    bid_amount: Decimal | None
    winning_amount: Decimal | None
    result: str | None


def participation_row(row: dict) -> ParticipationRow:
    _validate(_ParticipationSchema, row)
    return cast(ParticipationRow, row)
