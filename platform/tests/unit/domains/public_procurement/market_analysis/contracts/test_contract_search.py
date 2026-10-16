from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from teoria.domains.public_procurement.market_analysis.contracts.contract_search import (
    enrich_contract_search_objects,
)
from teoria.registry.loader import RegistryLoader
from teoria.runtime.mapping.materializer import MaterializedObject

REGISTRIES = Path(__file__).parents[6] / "registries"


@pytest.mark.asyncio
async def test_contract_search_enrichment_returns_lead_members_and_share_completeness() -> (
    None
):
    class Reader:
        async def find(self, catalog, *, unified_contract_numbers):
            assert unified_contract_numbers == ["C-1"]
            return [
                {
                    "unified_contract_number": "C-1",
                    "is_joint_contract": True,
                    "supplier_sequence": 2,
                    "business_registration_number": "1078700904",
                    "supplier_name": "한국이디에스",
                    "supplier_role_name": "주계약업체",
                    "joint_contract_method_name": "공동",
                    "participation_share_rate": Decimal("60"),
                },
                {
                    "unified_contract_number": "C-1",
                    "is_joint_contract": True,
                    "supplier_sequence": 1,
                    "business_registration_number": "1234567890",
                    "supplier_name": "구성업체",
                    "supplier_role_name": "도급업체",
                    "joint_contract_method_name": "공동",
                    "participation_share_rate": None,
                },
            ]

    contract = MaterializedObject(
        ontology="public_procurement",
        object_type="contract",
        object_id="contract-id",
        properties={"unified_contract_number": "C-1", "is_joint_contract": True},
        provenance=[],
        property_provenance={},
    )
    await enrich_contract_search_objects(
        RegistryLoader(REGISTRIES).load(),
        [contract],
        observed_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        reader=Reader(),
    )

    assert contract.properties["contractor_count"] == 2
    assert contract.properties["lead_contractor"]["company_name"] == "한국이디에스"
    assert contract.properties["contractors"][0]["company_role"] == "consortium_lead"
    assert contract.properties["contractors"][0]["share_percent"] == 60
    assert contract.properties["contractors"][0]["share_completeness"] == "complete"
    assert contract.properties["contractors"][1]["company_role"] == "consortium_member"
    assert contract.properties["contractors"][1]["share_percent"] is None
    assert contract.properties["contractors"][1]["share_completeness"] == "unknown"
    assert (
        contract.property_provenance["contractors"][0].operation == "contract_suppliers"
    )
