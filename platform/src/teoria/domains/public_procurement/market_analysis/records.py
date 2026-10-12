"""Internal Data DB row contracts, independent of Ontology and Runtime objects."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, cast
from typing_extensions import TypedDict

from pydantic import BaseModel, ConfigDict, ValidationError


class ProfileActivityRow(TypedDict):
    activity_type: Literal['participation', 'award', 'contract']
    event_key: str
    activity_date: date | None
    event_amount: Decimal | None
    attributed_contract_amount: Decimal | None
    amount_completeness: Literal['complete', 'partial', 'unknown']


class _ProfileActivitySchema(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True)
    activity_type: Literal['participation', 'award', 'contract']
    event_key: str
    activity_date: date | None
    event_amount: Decimal | None
    attributed_contract_amount: Decimal | None
    amount_completeness: Literal['complete', 'partial', 'unknown']


class ParticipationRow(TypedDict):
    bid_notice_id: str
    participation_date: datetime | None
    rank: int | None
    participant_count: int | None
    bid_amount: Decimal | None
    winning_amount: Decimal | None
    result: str | None


class _ParticipationSchema(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True)
    bid_notice_id: str
    participation_date: datetime | None
    rank: int | None
    participant_count: int | None
    bid_amount: Decimal | None
    winning_amount: Decimal | None
    result: str | None


class MarketDataError(RuntimeError):
    pass


def profile_activity_row(row: dict) -> ProfileActivityRow:
    _validate(_ProfileActivitySchema, row)
    return cast(ProfileActivityRow, row)


def participation_row(row: dict) -> ParticipationRow:
    _validate(_ParticipationSchema, row)
    return cast(ParticipationRow, row)


def _validate(schema: type[BaseModel], row: dict) -> None:
    try:
        schema.model_validate(row)
    except ValidationError as exc:
        # Report fields and error types, never private row values.
        fields = ', '.join(f"{'.'.join(str(p) for p in item['loc'])}:{item['type']}"
                           for item in exc.errors(include_input=False))
        raise MarketDataError(f'Invalid {schema.__name__} row: {fields}') from None
