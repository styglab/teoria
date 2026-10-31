"""Bounded, transient catalog search over the authoritative OpenMetadata index."""

import json
from typing import Literal

from teoria.features.metadata_management.catalog.models import MetadataPage
from teoria.integrations.openmetadata.client import OpenMetadataError
from teoria.integrations.openmetadata.mapper import entity

MissingMetadata = Literal["all", "description", "owner", "tags"]
SEARCH_RESULT_LIMIT = 10_000


def table_query(
    database_schema: str | None, query: str, missing: MissingMetadata
) -> dict:
    filters = [{"term": {"deleted": False}}]
    if database_schema:
        filters.append(
            {"term": {"databaseSchema.fullyQualifiedName.keyword": database_schema}}
        )
    if query.strip():
        filters.append(
            {
                "bool": {
                    "should": [
                        {
                            "simple_query_string": {
                                "query": query.strip(),
                                "flags": "NONE",
                                "default_operator": "and",
                                "fields": [
                                    "name",
                                    "name.ngram",
                                    "displayName",
                                    "displayName.ngram",
                                    "fullyQualifiedName",
                                    "description",
                                    "tags.tagFQN.text",
                                ],
                            }
                        },
                        {
                            "nested": {
                                "path": "owners",
                                "query": {
                                    "simple_query_string": {
                                        "query": query.strip(),
                                        "flags": "NONE",
                                        "fields": ["owners.name", "owners.displayName"],
                                    }
                                },
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if missing == "description":
        filters.append({"term": {"descriptionStatus": "INCOMPLETE"}})
    elif missing == "owner":
        filters.append(
            {
                "bool": {
                    "must_not": [
                        {
                            "nested": {
                                "path": "owners",
                                "query": {"match_all": {}},
                            }
                        }
                    ]
                }
            }
        )
    elif missing == "tags":
        filters.append({"bool": {"must_not": [{"exists": {"field": "tags.tagFQN"}}]}})
    return {"query": {"bool": {"filter": filters}}}


async def search_tables(
    client,
    *,
    database_schema=None,
    query="",
    missing: MissingMetadata = "all",
    offset=0,
    limit=25,
    sort="asc",
) -> MetadataPage:
    if missing not in {"all", "description", "owner", "tags"} or sort not in {
        "asc",
        "desc",
    }:
        raise ValueError("unsupported catalog filter or sort")
    if not 0 <= limit <= 100 or offset < 0 or offset + limit > SEARCH_RESULT_LIMIT:
        raise ValueError("catalog search exceeds result window")
    # Wire names follow SearchResource.java in deployed OpenMetadata 2.0.5;
    # unknown camelCase parameters are silently ignored by that endpoint.
    payload = await client.get(
        "v1/search/query",
        params={
            "q": "*",
            "index": "table_search_index",
            "from": offset,
            "size": limit,
            "sort_field": "name.keyword",
            "sort_order": sort,
            "track_total_hits": "true",
            "deleted": "false",
            "fetch_source": "true",
            "include_aggregations": "false",
            "include_source_fields": [
                "id",
                "name",
                "displayName",
                "fullyQualifiedName",
                "description",
                "version",
                "owners",
                "tags",
                "domains",
            ],
            "query_filter": json.dumps(table_query(database_schema, query, missing)),
        },
    )
    try:
        if not isinstance(payload, dict) or not isinstance(
            payload.get("_shards", {}), dict
        ):
            raise ValueError("invalid search envelope")
        if payload.get("timed_out") or payload.get("_shards", {}).get("failed", 0):
            raise ValueError("incomplete search")
        hits = payload["hits"]
        if not isinstance(hits, dict) or not isinstance(hits.get("hits"), list):
            raise ValueError("invalid search hits")
        total = hits["total"]
        if isinstance(total, dict):
            if total.get("relation") != "eq":
                raise ValueError("inexact search count")
            total = total["value"]
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ValueError("invalid search count")
        return MetadataPage(
            items=[entity(hit["_source"], "table") for hit in hits["hits"]], total=total
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OpenMetadataError(
            "openmetadata_invalid_response",
            "OpenMetadata search result is incomplete or invalid",
        ) from exc
