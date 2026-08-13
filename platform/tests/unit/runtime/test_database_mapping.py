from datetime import datetime, timezone
from pathlib import Path

import pytest

from teoria.registry.loader import RegistryLoader
from teoria.runtime.mapping.decoder import MappingDecoder
from teoria.runtime.mapping.materializer import OntologyMaterializer
from teoria.runtime.capability.runner import CapabilityRunner
from teoria.runtime.capability.binder import CapabilityBinder
from teoria.runtime.capability.presentation import serialize_capability_result
from teoria.runtime.source.database import DatabaseQueryResult


REGISTRIES = Path(__file__).parents[3] / "registries"


class FakeDatabaseExecutor:
    def execute(self, catalog, source_id, relation_id, query):
        assert source_id == "teoria_public_procurement"
        assert relation_id == "contracts"
        assert query == {"filters": [{
            "field": "unified_contract_number",
            "operator": "eq",
            "value": "R26TE17086494",
        }]}
        return [{
            "unified_contract_number": "R26TE17086494",
            "contract_type": "service",
            "contract_name": "테스트 계약",
            "contracting_organization_code": "B550554",
        }]


def test_materializes_contract_participation_from_database_relation() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    fragments = MappingDecoder().decode_database_rows(
        catalog,
        "teoria_public_procurement",
        "contract_suppliers",
        [{
            "unified_contract_number": "R26TE17086494",
            "supplier_sequence": 1,
            "business_registration_number": "1234567890",
            "supplier_name": "테스트 업체",
            "supplier_role_name": "주계약업체",
            "joint_contract_method_name": "공동",
            "participation_share_rate": 80,
        }],
    )

    objects, links = OntologyMaterializer().materialize(
        catalog,
        fragments,
        datetime.now(timezone.utc),
        {"business_registration", "contract", "contract_participation"},
        {
            "business_registration_has_contract_participation",
            "contract_participation_is_for_contract",
        },
    )

    contract = next(item for item in objects if item.object_type == "contract")
    participation = next(
        item for item in objects if item.object_type == "contract_participation"
    )
    assert contract.properties["unified_contract_number"] == "R26TE17086494"
    assert participation.properties["supplier_sequence"] == 1
    assert participation.properties["participation_share_rate"] == 80
    assert participation.properties["participation_id"] == participation.object_id
    registration = next(
        item for item in objects if item.object_type == "business_registration"
    )
    assert registration.ontology == "company"
    assert registration.properties["business_registration_number"] == "1234567890"
    participation_link = next(
        item for item in links if item.link_type == "business_registration_has_contract_participation"
    )
    contract_link = next(
        item for item in links if item.link_type == "contract_participation_is_for_contract"
    )
    assert participation_link.source_object_id == registration.object_id
    assert participation_link.target_object_id == participation.object_id
    assert contract_link.source_object_id == participation.object_id
    assert contract_link.target_object_id == contract.object_id


@pytest.mark.asyncio
async def test_capability_runner_queries_database_and_materializes_relationships() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    result = await CapabilityRunner(database_executor=FakeDatabaseExecutor()).run(
        catalog,
        "get_public_procurement_contract",
        {"unified_contract_number": "R26TE17086494"},
    )

    assert {item.object_type for item in result.objects} == {
        "contract",
        "public_organization",
    }
    assert [item.link_type for item in result.links] == [
        "public_organization_awards_contract"
    ]


class PaginatedBidNoticeExecutor:
    def execute(self, catalog, source_id, relation_id, query):
        assert source_id == "teoria_public_procurement"
        assert relation_id == "bid_notices"
        assert query == {
            "filters": [
                {"field": "notice_published_at", "operator": "gte",
                 "value": datetime(2026, 8, 1, tzinfo=timezone.utc)},
                {"field": "notice_published_at", "operator": "lte",
                 "value": datetime(2026, 8, 31, tzinfo=timezone.utc)},
                {"field": "work_type", "operator": "eq", "value": "service"},
            ],
            "search": {
                "fields": ["notice_name", "notice_number", "notice_organization_name",
                           "demand_organization_name"],
                "value": "정보시스템",
            },
            "order_by": [
                {"field": "bid_deadline_at", "direction": "asc", "nulls": "last"},
                {"field": "bid_notice_id", "direction": "asc", "nulls": None},
            ],
            "pagination": {"page": 2, "page_size": 20, "root_field": "bid_notice_id"},
        }
        return DatabaseQueryResult([{
            "bid_notice_id": "R26TEST:000",
            "notice_number": "R26TEST",
            "notice_order": "000",
            "notice_name": "정보시스템 운영 용역",
            "work_type": "service",
            "notice_organization_code": "B000001",
            "notice_organization_name": "테스트기관",
        }], {"page": 2, "page_size": 20, "total_items": 41, "total_pages": 3})


@pytest.mark.asyncio
async def test_search_bid_notices_returns_root_object_pagination() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    result = await CapabilityRunner(database_executor=PaginatedBidNoticeExecutor()).run(
        catalog,
        "search_bid_notices",
        {
            "notice_published_at_from": datetime(2026, 8, 1, tzinfo=timezone.utc),
            "notice_published_at_to": datetime(2026, 8, 31, tzinfo=timezone.utc),
            "query": "정보시스템",
            "work_type": "service",
            "sort": "deadline_asc",
            "page": 2,
            "page_size": 20,
        },
    )

    response = serialize_capability_result(result, max_objects=1)

    assert response["pagination"] == {
        "page": 2, "page_size": 20, "total_items": 41, "total_pages": 3,
    }
    assert response["truncated"] is False
    assert {item["type"] for item in response["objects"]} == {
        "bid_notice", "public_organization",
    }


def test_bid_notice_search_uses_declared_query_defaults() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    capability = catalog.capabilities["search_bid_notices"]

    query = CapabilityBinder().bind(
        catalog,
        capability,
        capability.steps[0],
        {
            "notice_published_at_from": datetime(2026, 8, 1, tzinfo=timezone.utc),
            "notice_published_at_to": datetime(2026, 8, 31, tzinfo=timezone.utc),
        },
    )

    assert query["order_by"] == [
        {"field": "notice_published_at", "direction": "desc", "nulls": "last"},
        {"field": "bid_notice_id", "direction": "desc", "nulls": None},
    ]
    assert query["pagination"] == {
        "page": 1, "page_size": 20, "root_field": "bid_notice_id",
    }
