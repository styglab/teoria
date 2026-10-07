from __future__ import annotations

from typing import Any

from teoria.metadata.models import MetadataEntity, MetadataPage, MetadataTargetRef, TableDetail


def entity_reference(payload: dict[str, Any], entity_type: str) -> MetadataTargetRef:
    return MetadataTargetRef(
        entity_id=str(payload["id"]),
        entity_type=entity_type,
        fully_qualified_name=payload.get("fullyQualifiedName"),
        version=payload.get("version"),
    )


def entity(payload: dict[str, Any], entity_type: str) -> MetadataEntity:
    return MetadataEntity(
        reference=entity_reference(payload, entity_type),
        name=payload.get("name", ""),
        display_name=payload.get("displayName"),
        description=payload.get("description"),
        owners=payload.get("owners") or [],
        tags=payload.get("tags") or [],
        domains=payload.get("domains") or [],
    )


def page(payload: dict[str, Any], entity_type: str) -> MetadataPage:
    paging = payload.get("paging") or {}
    return MetadataPage(
        items=[entity(item, entity_type) for item in payload.get("data", [])],
        total=int(paging.get("total", len(payload.get("data", [])))),
        after=paging.get("after"),
        before=paging.get("before"),
    )


def table_detail(payload: dict[str, Any]) -> TableDetail:
    base = entity(payload, "table")
    tags = payload.get("tags") or []
    return TableDetail(
        **base.model_dump(),
        database=payload.get("database"),
        database_schema=payload.get("databaseSchema"),
        columns=payload.get("columns") or [],
        glossary_terms=[item for item in tags if item.get("source") == "Glossary"],
        test_suite=payload.get("testSuite"),
    )
