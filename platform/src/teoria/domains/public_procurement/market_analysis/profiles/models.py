from datetime import date
from decimal import Decimal
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict
from typing_extensions import TypedDict

from ..row_validation import _validate


class ProfileActivityRow(TypedDict):
    activity_type: Literal["participation", "award", "contract"]
    event_key: str
    activity_date: date | None
    event_amount: Decimal | None
    attributed_contract_amount: Decimal | None
    amount_completeness: Literal["complete", "partial", "unknown"]


class _ProfileActivitySchema(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    activity_type: Literal["participation", "award", "contract"]
    event_key: str
    activity_date: date | None
    event_amount: Decimal | None
    attributed_contract_amount: Decimal | None
    amount_completeness: Literal["complete", "partial", "unknown"]


def profile_activity_row(row: dict) -> ProfileActivityRow:
    _validate(_ProfileActivitySchema, row)
    return cast(ProfileActivityRow, row)
