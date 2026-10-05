from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class MetadataTargetRef(BaseModel):
    """Non-owning value reference to one authoritative OpenMetadata entity."""

    system: Literal["openmetadata"] = "openmetadata"
    entity_id: str
    entity_type: str
    fully_qualified_name: str | None = None
    version: float | None = None


class MetadataEntity(BaseModel):
    reference: MetadataTargetRef
    name: str
    display_name: str | None = None
    description: str | None = None
    owners: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[dict[str, Any]] = Field(default_factory=list)
    domains: list[dict[str, Any]] = Field(default_factory=list)


class MetadataPage(BaseModel):
    items: list[MetadataEntity]
    total: int
    after: str | None = None
    before: str | None = None


class TableDetail(MetadataEntity):
    database: dict[str, Any] | None = None
    database_schema: dict[str, Any] | None = None
    columns: list[dict[str, Any]] = Field(default_factory=list)
    glossary_terms: list[dict[str, Any]] = Field(default_factory=list)


class MetadataStatus(BaseModel):
    enabled: bool
    available: bool
    provider: Literal["openmetadata"] = "openmetadata"
    base_url: str | None = None
    database_service: str | None = None
    reason: str | None = None
