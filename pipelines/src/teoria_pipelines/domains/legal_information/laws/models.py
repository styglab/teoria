from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from pydantic import Field, field_validator
from teoria_provider_api.schema import ContractModel, SNAKE_CASE_PATTERN


class LawTarget(ContractModel):
    id: str
    name: str = Field(min_length=1)
    law_id: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not SNAKE_CASE_PATTERN.fullmatch(value):
            raise ValueError("law target id must be snake_case")
        return value

    @field_validator("law_id")
    @classmethod
    def validate_law_id(cls, value: str | None) -> str | None:
        if value is not None and (not value.isascii() or not value.isdigit()):
            raise ValueError("law_id must be a provider numeric identifier")
        return str(int(value)) if value is not None else None


@dataclass(frozen=True, slots=True)
class LawVersion:
    law_id: str
    mst: str
    effective_date: date
    name: str
    promulgation_date: date
    promulgation_number: str
    amendment_type: str
    listing: dict[str, str]

    @property
    def key(self) -> tuple[str, str, date]:
        return self.law_id, self.mst, self.effective_date


@dataclass(frozen=True, slots=True)
class LawResponse:
    operation_id: str
    query: dict[str, Any]
    fetched_at: datetime
    content_type: str
    raw_body: bytes = field(repr=False)


@dataclass(slots=True)
class LawCatalog:
    law_id: str
    versions: list[LawVersion]
    responses: list[LawResponse]


@dataclass(slots=True)
class ParsedLaw:
    version: LawVersion
    parser_version: str
    metadata: dict[str, Any]
    provisions: list[dict[str, Any]]
    attachments: list[dict[str, Any]]
