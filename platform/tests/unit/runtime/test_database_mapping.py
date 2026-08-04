from datetime import datetime, timezone
from pathlib import Path

import pytest

from teoria.registry.loader import RegistryLoader
from teoria.runtime.mapping.decoder import MappingDecoder
from teoria.runtime.mapping.materializer import OntologyMaterializer
from teoria.runtime.capability.runner import CapabilityRunner


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
