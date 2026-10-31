import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from teoria.features.access_control.auth import AdminAuthorizer
from teoria.features.metadata_management.catalog.admin_router import (
    create_metadata_router,
)
from teoria.integrations.openmetadata.catalog_search import search_tables, table_query
from teoria.integrations.openmetadata.client import (
    OpenMetadataClient,
    OpenMetadataError,
)
from teoria.integrations.openmetadata.service import OpenMetadataService
from teoria.settings import Settings


def response(total=51):
    return {
        "hits": {
            "total": {"value": total, "relation": "eq"},
            "hits": [
                {
                    "_source": {
                        "id": "table-1",
                        "name": "hidden",
                        "owners": [{"name": "Metadata Team"}],
                    }
                }
            ],
        }
    }


@pytest.mark.asyncio
async def test_search_forwards_bounded_page_and_literal_query_without_scanning_tables():
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.path == "/api/v1/search/query"
        params = request.url.params
        assert params["index"] == "table_search_index"
        assert params["from"] == "25" and params["size"] == "25"
        assert params["sort_field"] == "name.keyword" and params["sort_order"] == "desc"
        assert params["track_total_hits"] == "true"
        assert params.get_list("include_source_fields") == [
            "id",
            "name",
            "displayName",
            "fullyQualifiedName",
            "description",
            "version",
            "owners",
            "tags",
            "domains",
        ]
        filters = json.loads(params["query_filter"])["query"]["bool"]["filter"]
        assert {
            "term": {"databaseSchema.fullyQualifiedName.keyword": "service.db.schema"}
        } in filters
        assert {"term": {"descriptionStatus": "INCOMPLETE"}} in filters
        text = filters[2]["bool"]["should"][0]["simple_query_string"]
        assert text["query"] == "name:(private) OR *" and text["flags"] == "NONE"
        return httpx.Response(200, json=response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = OpenMetadataClient(
            "https://example.test/api",
            None,
            timeout_seconds=2,
            verify_ssl=True,
            client=http,
        )
        result = await search_tables(
            client,
            database_schema="service.db.schema",
            query="name:(private) OR *",
            missing="description",
            offset=25,
            limit=25,
            sort="desc",
        )
    assert len(requests) == 1 and result.total == 51
    assert result.items[0].reference.entity_type == "table"
    assert result.items[0].owners == [{"name": "Metadata Team"}]


def test_missing_owner_uses_nested_index_and_tags_use_tag_fqn():
    owner = table_query(None, "", "owner")["query"]["bool"]["filter"][-1]
    assert owner["bool"]["must_not"][0]["nested"]["path"] == "owners"
    tags = table_query(None, "", "tags")["query"]["bool"]["filter"][-1]
    assert tags == {"bool": {"must_not": [{"exists": {"field": "tags.tagFQN"}}]}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"hits": {}},
        {**response(), "timed_out": True},
        {**response(), "_shards": {"failed": 1}},
        {"hits": {"total": {"value": 10000, "relation": "gte"}, "hits": []}},
    ],
)
async def test_partial_or_invalid_search_does_not_become_an_empty_catalog(payload):
    client = AsyncMock()
    client.get.return_value = payload
    with pytest.raises(OpenMetadataError, match="incomplete or invalid"):
        await search_tables(client)


@pytest.mark.asyncio
async def test_counts_are_fixed_count_only_queries_without_entity_collection():
    client = AsyncMock()
    client.get.return_value = {
        "hits": {"total": {"value": 7, "relation": "eq"}, "hits": []}
    }
    service = OpenMetadataService(
        client, base_url="https://example.test/api", database_service="service"
    )
    counts = await service.table_counts(
        database_schema="service.db.schema", query="server"
    )
    assert counts == {"all": 7, "description": 7, "owner": 7, "tags": 7}
    assert client.get.await_count == 4
    assert all(
        call.kwargs["params"]["size"] == 0 for call in client.get.await_args_list
    )


def test_search_routes_enforce_authentication_and_bounds_and_preserve_filters():
    service = AsyncMock()
    service.search_tables.return_value = {
        "items": [],
        "total": 500,
        "after": None,
        "before": None,
    }
    service.table_counts.return_value = {
        "all": 500,
        "description": 20,
        "owner": 3,
        "tags": 4,
    }
    settings = Settings(
        admin_auth_mode="bearer",
        admin_api_token="test-token",
        admin_api_roles="metadata_admin",
    )
    app = FastAPI()
    app.include_router(create_metadata_router(service, AdminAuthorizer(settings)))
    client = TestClient(app)
    path = "/v1/admin/metadata/table-search"
    assert client.get(path).status_code == 401
    headers = {"Authorization": "Bearer test-token"}
    for query in (
        "?missing=invalid",
        "?sort=score",
        "?offset=-1",
        "?offset=9975&limit=50",
        "?limit=100",
        "?q=" + "a" * 201,
    ):
        assert client.get(path + query, headers=headers).status_code == 422
    service.search_tables.assert_not_called()
    result = client.get(
        path + "?q=server&missing=owner&sort=desc&offset=25&limit=25", headers=headers
    )
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert result.json()["total"] == 500
    service.search_tables.assert_awaited_once_with(
        database_schema=None,
        query="server",
        missing="owner",
        sort="desc",
        offset=25,
        limit=25,
    )
    assert client.get(path + "/counts?q=server", headers=headers).json()["all"] == 500
    service.table_counts.assert_awaited_once_with(database_schema=None, query="server")
