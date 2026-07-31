from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CollectionWindow:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("collection window end must not precede start")


@dataclass(frozen=True, slots=True)
class RawProviderRecord:
    raw_record_id: UUID
    execution_id: UUID
    connector_id: str
    operation_id: str
    window: CollectionWindow
    fetched_at: datetime
    source_record_hash: str
    payload: dict[str, Any]


@dataclass(slots=True)
class ExtractedBatch:
    execution_id: UUID
    window: CollectionWindow
    records: list[RawProviderRecord] = field(default_factory=list)
    pages: int = 0


@dataclass(slots=True)
class NormalizedBatch:
    contracts: list[dict[str, Any]] = field(default_factory=list)
    suppliers: list[dict[str, Any]] = field(default_factory=list)
    organizations: list[dict[str, Any]] = field(default_factory=list)
    demand_organizations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class LoadSummary:
    raw_records: int = 0
    contracts: int = 0
    suppliers: int = 0
    organizations: int = 0
    demand_organizations: int = 0
