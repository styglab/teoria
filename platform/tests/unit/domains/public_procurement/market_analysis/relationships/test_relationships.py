from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from teoria.domains.public_procurement.market_analysis.profiles.service import (
    execute_company_procurement_profile,
    execute_organization_procurement_profile,
)
from teoria.domains.public_procurement.market_analysis.relationships.organization_metrics import (
    _organization_field_event_analysis,
)
from teoria.domains.public_procurement.market_analysis.relationships.organization_relationship import (
    execute_organization_company_field_relationship,
    execute_organization_company_relationship,
)
from teoria.registry.loader import RegistryLoader
from teoria.runtime.capability.runner import CapabilityExecutionError

REGISTRIES = Path(__file__).parents[6] / "registries"


class OrganizationFieldEventReader:
    async def find(self, catalog, *, organization_code, work_type, as_of):
        return [
            {
                "source_kind": "award",
                "notice_number": "R25EVENT",
                "notice_order": "000",
                "bid_classification_number": "0",
                "rebid_number": "0",
                "bid_notice_id": "R25EVENT:000",
                "notice_name": "정보시스템 구축",
                "event_date": date(2025, 3, 1),
                "notice_published_date": date(2025, 2, 20),
                "event_amount": Decimal("200000000"),
                "company_number": "1234567890",
                "company_name": "기관분야업체",
            }
        ]

    async def context(
        self,
        catalog,
        *,
        organization_code,
        business_registration_number,
        reference_bid_notice_id,
    ):
        return {
            "organization": {
                "organization_code": organization_code,
                "organization_name": "기관",
            },
            "company": {
                "business_registration_number": business_registration_number,
                "company_name": "기관분야업체",
            },
            "reference_notice": {
                "bid_notice_id": reference_bid_notice_id,
                "notice_name": "정보시스템 구축 및 유지관리 사업",
                "work_type": "service",
                "estimated_price": Decimal("200000000"),
                "allocated_budget": None,
                "industry_codes": ["1468", "0036"],
                "as_of": datetime(2026, 9, 23, tzinfo=timezone.utc),
            }
            if reference_bid_notice_id
            else None,
        }


@pytest.mark.asyncio
async def test_organization_company_field_relationship_returns_event_distributions() -> (
    None
):
    result = await execute_organization_company_field_relationship(
        RegistryLoader(REGISTRIES).load(),
        "get_organization_company_field_relationship",
        {
            "organization_code": "ORG-1",
            "business_registration_number": "1234567890",
            "field_code": "information_system",
            "work_type": "service",
            "reference_bid_notice_id": "R26TEST:000",
            "period_years": 10,
            "page": 1,
            "page_size": 20,
        },
        reader=OrganizationFieldEventReader(),
    )

    assert result.outcome["summary"]["award_event_count"] == 1
    assert result.outcome["summary"]["attributed_award_event_count"] == 1
    assert (
        sum(item["event_count"] for item in result.outcome["project_type_distribution"])
        == 1
    )
    assert (
        sum(item["event_count"] for item in result.outcome["amount_distribution"]) == 1
    )
    assert sum(item["event_count"] for item in result.outcome["yearly_activity"]) == 1
    assert result.outcome["events"][0]["is_similar_amount"] is True
    assert result.outcome["events"][0]["notice_published_date"] == date(2025, 2, 20)
    assert result.outcome["events"][0]["award_date"] == date(2025, 3, 1)
    assert result.outcome["events"][0]["contract_date"] is None
    assert (
        result.outcome["events"][0]["attributed_contract_amount_completeness"]
        == "unknown"
    )
    assert result.outcome["events"][0]["company_role"] == "sole"
    assert result.outcome["summary"]["total_attributed_contract_amount"] == 0
    assert result.outcome["summary"]["amount_completeness"] == "unknown"
    assert result.outcome["pagination"]["total_items"] == 1


@pytest.mark.asyncio
async def test_organization_company_relationship_does_not_apply_field_filter() -> None:
    result = await execute_organization_company_relationship(
        RegistryLoader(REGISTRIES).load(),
        "get_organization_company_relationship",
        {
            "organization_code": "ORG-1",
            "business_registration_number": "1234567890",
            "work_type": "service",
            "period_years": 10,
            "page": 1,
            "page_size": 20,
        },
        reader=OrganizationFieldEventReader(),
    )

    assert result.outcome["relationship_type"] == "organization_history"
    assert result.outcome["analysis_basis"]["field_filter_applied"] is False
    assert result.outcome["analysis_basis"]["similarity_assessment_applied"] is False
    assert result.outcome["events"][0]["organization_match"] is True
    assert "field_match_reasons" not in result.outcome["events"][0]
    assert result.objects[0].object_type == "organization_company_relationship"


@pytest.mark.asyncio
async def test_organization_company_relationship_applies_procurement_hierarchy_filters() -> (
    None
):
    class Reader(OrganizationFieldEventReader):
        received = None

        async def find(self, catalog, **kwargs):
            self.received = kwargs
            return await super().find(
                catalog,
                organization_code=kwargs["organization_code"],
                work_type=kwargs["work_type"],
                as_of=kwargs["as_of"],
            )

    reader = Reader()
    result = await execute_organization_company_relationship(
        RegistryLoader(REGISTRIES).load(),
        "get_organization_company_relationship",
        {
            "organization_code": "ORG-1",
            "business_registration_number": "1234567890",
            "work_type": "service",
            "large_category": "ICT 서비스",
            "middle_category": "SW 및 시스템 개발",
            "field_code": "81111599",
            "period_years": 10,
            "page": 1,
            "page_size": 20,
        },
        reader=reader,
    )

    assert reader.received["large_category"] == "ICT 서비스"
    assert reader.received["middle_category"] == "SW 및 시스템 개발"
    assert reader.received["procurement_field_code"] == "81111599"
    assert result.outcome["analysis_basis"]["field_filter_applied"] is True
    assert result.outcome["analysis_basis"]["field_filter"] == {
        "large_category": "ICT 서비스",
        "middle_category": "SW 및 시스템 개발",
        "field_code": "81111599",
    }


@pytest.mark.asyncio
async def test_organization_company_relationship_limits_metrics_and_separates_versions() -> (
    None
):
    class Reader(OrganizationFieldEventReader):
        async def find(self, catalog, *, organization_code, work_type, as_of):
            rows = []
            for contract_number, event_date, amount in (
                ("C-OLD", date(2021, 5, 1), Decimal("80")),
                ("C-V1", date(2023, 5, 1), Decimal("90")),
                ("C-V2", date(2025, 5, 1), Decimal("100")),
            ):
                rows.append(
                    {
                        "source_kind": "contract",
                        "notice_number": "N1",
                        "unified_contract_number": contract_number,
                        "original_contract_number": contract_number,
                        "bid_notice_id": "N1:000",
                        "notice_name": "정보시스템 유지관리",
                        "event_date": event_date,
                        "event_amount": amount,
                        "notice_published_date": date(2023, 2, 1),
                        "attribution_date": date(2023, 2, 1),
                        "attribution_date_basis": "notice_published_at",
                        "first_contract_date": date(2021, 5, 1),
                        "latest_contract_version_date": date(2025, 5, 1),
                        "contract_amount": amount,
                        "contract_currency": "KRW",
                        "company_number": "1234567890",
                        "company_name": "기관분야업체",
                        "participation_share_rate": Decimal("100"),
                        "supplier_role_name": "단독",
                    }
                )
            return rows

    result = await execute_organization_company_relationship(
        RegistryLoader(REGISTRIES).load(),
        "get_organization_company_relationship",
        {
            "organization_code": "ORG-1",
            "business_registration_number": "1234567890",
            "period_years": 5,
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )

    summary = result.outcome["summary"]
    assert summary["unique_project_count"] == 1
    assert summary["contract_event_count"] == 1
    assert summary["contract_version_count"] == 3
    assert summary["total_attributed_contract_amount"] == 100
    assert summary["active_years"] == [2023]
    assert result.outcome["yearly_activity"] == [
        {
            "year": 2023,
            "award_event_count": 1,
            "attributed_contract_amount": 100,
            "amount_completeness": "complete",
            "sole_count": 1,
            "consortium_lead_count": 0,
            "consortium_member_count": 0,
        }
    ]
    assert result.outcome["events"][0]["first_contract_date"] == date(2021, 5, 1)
    assert result.outcome["events"][0]["latest_contract_version_date"] == date(
        2025, 5, 1
    )


@pytest.mark.asyncio
async def test_organization_company_relationship_validates_explicit_year_range() -> (
    None
):
    catalog = RegistryLoader(REGISTRIES).load()
    base = {
        "organization_code": "ORG-1",
        "business_registration_number": "1234567890",
    }
    with pytest.raises(CapabilityExecutionError, match="must be provided together"):
        await execute_organization_company_relationship(
            catalog,
            "get_organization_company_relationship",
            {**base, "period_from_year": 2023},
        )
    with pytest.raises(CapabilityExecutionError, match="less than or equal"):
        await execute_organization_company_relationship(
            catalog,
            "get_organization_company_relationship",
            {**base, "period_from_year": 2025, "period_to_year": 2023},
        )
    with pytest.raises(CapabilityExecutionError, match="cannot be later"):
        await execute_organization_company_relationship(
            catalog,
            "get_organization_company_relationship",
            {**base, "period_from_year": 2026, "period_to_year": 2027},
        )


def test_award_event_analysis_merges_contract_and_preserves_joint_members() -> None:
    rows = [
        {
            "source_kind": "award",
            "notice_number": "R25A",
            "notice_order": "000",
            "bid_classification_number": "0",
            "rebid_number": "0",
            "bid_notice_id": "R25A:000",
            "notice_name": "정보시스템 구축",
            "event_date": date(2025, 3, 1),
            "event_amount": Decimal("200000000"),
            "company_number": "1111111111",
            "company_name": "대표사",
        },
        {
            "source_kind": "contract",
            "notice_number": "R25A",
            "unified_contract_number": "C1-1",
            "original_contract_number": "C1",
            "bid_notice_id": "R25A:000",
            "notice_name": "정보시스템 구축",
            "event_date": date(2025, 3, 10),
            "event_amount": Decimal("200000000"),
            "contract_amount": Decimal("200000000"),
            "contract_currency": "KRW",
            "company_number": "1111111111",
            "company_name": "대표사",
            "participation_share_rate": Decimal("60"),
            "supplier_role_name": "대표사",
        },
        {
            "source_kind": "contract",
            "notice_number": "R25A",
            "unified_contract_number": "C1-1",
            "original_contract_number": "C1",
            "bid_notice_id": "R25A:000",
            "notice_name": "정보시스템 구축",
            "event_date": date(2025, 3, 10),
            "event_amount": Decimal("200000000"),
            "contract_amount": Decimal("200000000"),
            "contract_currency": "KRW",
            "company_number": "2222222222",
            "company_name": "구성사",
            "participation_share_rate": Decimal("40"),
            "supplier_role_name": "구성사",
        },
    ]
    notice = {
        "notice_name": "차세대 정보시스템 구축",
        "estimated_price": Decimal("200000000"),
        "allocated_budget": None,
        "as_of": datetime(2026, 9, 1, tzinfo=timezone.utc),
    }

    result = _organization_field_event_analysis(rows, notice, 5)

    assert result["event_deduplication"]["merged_award_contract_count"] == 1
    assert result["market_structure"]["award_event_count"] == 1
    assert result["market_structure"]["company_count"] == 2
    assert result["market_structure"]["top_1_share"] == 0.6
    assert result["company_metrics"]["1111111111"]["same_field_event_count"] == 1
    assert (
        result["company_metrics"]["2222222222"]["same_field_contract_amount"]
        == 80000000
    )
    assert result["company_metrics"]["1111111111"]["annual_activity"] == [
        {
            "year": 2025,
            "award_event_count": 1,
            "attributed_contract_amount": 120000000,
            "amount_completeness": "complete",
            "sole_count": 0,
            "consortium_lead_count": 1,
            "consortium_member_count": 0,
        }
    ]
    assert (
        result["company_metrics"]["2222222222"]["annual_activity"][0][
            "consortium_member_count"
        ]
        == 1
    )
    event = result["events"][0]
    assert event["award_date"] == date(2025, 3, 1)
    assert event["contract_date"] == date(2025, 3, 10)


@pytest.mark.asyncio
async def test_company_profile_organization_search_is_relationship_list_only() -> None:
    class Reader:
        async def activities(self, catalog, **kwargs):
            return [
                {
                    "activity_type": "contract",
                    "event_key": f"C{index}",
                    "bid_notice_id": f"N{index}:000",
                    "notice_name": "정보시스템 계약",
                    "organization_code": organization_code,
                    "organization_name": organization_name,
                    "company_number": "1111111111",
                    "company_name": "업체",
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "work_type": "service",
                    "activity_date": date(2025, index, 1),
                    "event_amount": Decimal(str(amount)),
                    "attributed_contract_amount": Decimal(str(amount)),
                    "amount_completeness": "complete",
                }
                for index, (organization_code, organization_name, amount) in enumerate(
                    (
                        ("ORG-1", "근로 복지 공단", 300),
                        ("ORG-2", "한국사회보장정보원", 200),
                        ("ORG-3", "근로 복지 연구원", 100),
                    ),
                    start=1,
                )
            ]

    catalog = RegistryLoader(REGISTRIES).load()
    base_inputs = {
        "business_registration_number": "1111111111",
        "period_from_year": 2025,
        "period_to_year": 2025,
        "page": 1,
        "page_size": 1,
    }
    baseline = await execute_company_procurement_profile(
        catalog,
        "analyze_company_procurement_profile",
        base_inputs,
        reader=Reader(),
    )
    page_one = await execute_company_procurement_profile(
        catalog,
        "analyze_company_procurement_profile",
        {**base_inputs, "organization_query": "  근로 복지  "},
        reader=Reader(),
    )
    page_two = await execute_company_procurement_profile(
        catalog,
        "analyze_company_procurement_profile",
        {**base_inputs, "organization_query": "근로 복지", "page": 2},
        reader=Reader(),
    )

    assert page_one.outcome["pagination"]["total_items"] == 2
    assert page_one.outcome["pagination"]["total_pages"] == 2
    assert page_two.outcome["pagination"]["total_items"] == 2
    assert page_two.outcome["pagination"]["total_pages"] == 2
    assert page_one.outcome["organization_relationships"][0]["organization_name"] == (
        "근로 복지 공단"
    )
    assert page_two.outcome["organization_relationships"][0]["organization_name"] == (
        "근로 복지 연구원"
    )
    assert page_one.outcome["summary"] == baseline.outcome["summary"]
    assert page_one.outcome["yearly_activity"] == baseline.outcome["yearly_activity"]
    assert (
        page_one.outcome["field_distribution"] == baseline.outcome["field_distribution"]
    )
    assert page_one.outcome["analysis_basis"]["organization_query"] == "근로 복지"
    assert page_one.objects[0].properties["relationship_count"] == 2

    empty = await execute_organization_procurement_profile(
        catalog,
        "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "field_code": "00000000"},
        reader=Reader(),
    )
    assert empty.outcome["summary"]["notice_count"] == 0
    assert empty.outcome["company_relationships"] == []
