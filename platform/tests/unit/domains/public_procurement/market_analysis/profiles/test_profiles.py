from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from teoria.domains.public_procurement.market_analysis.profiles.service import (
    execute_company_procurement_profile,
    execute_organization_procurement_profile,
    execute_organization_supplier_entry_search,
)
from teoria.registry.loader import RegistryLoader
from teoria.runtime.capability.runner import CapabilityExecutionError

REGISTRIES = Path(__file__).parents[6] / "registries"


@pytest.mark.asyncio
async def test_procurement_profiles_keep_event_types_and_attributed_amounts_separate() -> (
    None
):
    class Reader:
        async def activities(self, catalog, **kwargs):
            return [
                {
                    "activity_type": "participation",
                    "event_key": "N1:C1",
                    "bid_notice_id": "N1:000",
                    "notice_name": "정보시스템 구축",
                    "organization_code": "ORG-1",
                    "organization_name": "기관",
                    "company_number": "1111111111",
                    "company_name": "업체",
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "work_type": "service",
                    "activity_date": date(2025, 1, 1),
                    "event_amount": Decimal("90"),
                    "attributed_contract_amount": None,
                    "amount_completeness": "unknown",
                },
                {
                    "activity_type": "award",
                    "event_key": "N1:000:0:0",
                    "bid_notice_id": "N1:000",
                    "notice_name": "정보시스템 구축",
                    "organization_code": "ORG-1",
                    "organization_name": "기관",
                    "company_number": "1111111111",
                    "company_name": "업체",
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "work_type": "service",
                    "activity_date": date(2025, 2, 1),
                    "event_amount": Decimal("90"),
                    "attributed_contract_amount": None,
                    "amount_completeness": "unknown",
                },
                {
                    "activity_type": "contract",
                    "event_key": "C1",
                    "bid_notice_id": "N1:000",
                    "notice_name": "정보시스템 구축",
                    "organization_code": "ORG-1",
                    "organization_name": "기관",
                    "company_number": "1111111111",
                    "company_name": "업체",
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "work_type": "service",
                    "activity_date": date(2025, 3, 1),
                    "event_amount": Decimal("100"),
                    "attributed_contract_amount": Decimal("60"),
                    "amount_completeness": "complete",
                },
            ]

    catalog = RegistryLoader(REGISTRIES).load()
    organization = await execute_organization_procurement_profile(
        catalog,
        "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "period_years": 5},
        reader=Reader(),
    )
    company = await execute_company_procurement_profile(
        catalog,
        "analyze_company_procurement_profile",
        {"business_registration_number": "1111111111", "period_years": 5},
        reader=Reader(),
    )

    assert organization.outcome["summary"]["participation_count"] == 1
    assert organization.outcome["summary"]["award_event_count"] == 1
    assert organization.outcome["summary"]["contract_event_count"] == 1
    assert organization.outcome["summary"]["total_attributed_contract_amount"] == 60
    assert (
        organization.outcome["analysis_basis"]["period_type"] == "calendar_fiscal_years"
    )
    assert organization.outcome["analysis_basis"]["period_from"] == date(
        date.today().year - 4,
        1,
        1,
    )
    assert (
        organization.outcome["company_relationships"][0]["major_fields"][0][
            "event_count"
        ]
        == 1
    )
    assert organization.outcome["field_distribution_level"] == "large"
    assert (
        organization.outcome["field_distribution"][0]["large_category"] == "ICT 서비스"
    )
    assert (
        organization.outcome["project_type_distribution"][0]["project_type"] == "build"
    )
    assert organization.outcome["work_type_distribution"] == [
        {
            "work_type": "service",
            "work_type_name": "용역",
            "event_count": 3,
            "participation_count": 1,
            "award_event_count": 1,
            "contract_event_count": 1,
            "attributed_contract_amount": 60,
        }
    ]
    assert organization.outcome["field_distribution"][0]["work_types"] == ["service"]
    assert company.outcome["organization_relationships"][0]["active_years"] == [2025]

    filtered = await execute_organization_procurement_profile(
        catalog,
        "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1",
            "period_years": 5,
            "large_category": " ICT   서비스 ",
            "middle_category": "SW 및 시스템 개발",
            "field_code": "81111599",
            "work_type": "service",
        },
        reader=Reader(),
    )
    assert filtered.outcome["summary"]["contract_event_count"] == 1
    assert (
        filtered.outcome["company_relationships"][0]["company_number"] == "1111111111"
    )
    assert filtered.outcome["field_distribution_level"] == "detail"
    assert filtered.outcome["field_distribution"][0]["field_code"] == "81111599"
    assert filtered.outcome["analysis_basis"]["field_filter"]["field_name"] == (
        "정보시스템개발서비스"
    )


@pytest.mark.asyncio
async def test_company_profile_filters_complete_target_year_organization_entry_set() -> (
    None
):
    class Reader:
        async def activities(self, catalog, **kwargs):
            base = {
                "activity_type": "contract",
                "company_number": "1111111111",
                "company_name": "업체",
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "work_type": "service",
                "amount_completeness": "complete",
                "attribution_date_basis": "first_contract_date",
                "contract_method_name": "일반경쟁",
            }
            definitions = (
                ("NEW-A", "ORG-NEW-A", "신규 기관 A", 2026, 1, 100),
                ("NEW-B", "ORG-NEW-B", "신규 기관 B", 2026, 2, 200),
                ("RETURN-OLD", "ORG-RETURN", "재진입 기관", 2021, 1, 50),
                ("RETURN-NOW", "ORG-RETURN", "재진입 기관", 2026, 3, 300),
                ("CURRENT-OLD", "ORG-CURRENT", "기존 기관", 2024, 1, 70),
                ("CURRENT-NOW", "ORG-CURRENT", "기존 기관", 2026, 4, 400),
                ("NO-TARGET", "ORG-NO-TARGET", "대상연도 계약 없음", 2025, 1, 80),
            )
            return [
                {
                    **base,
                    "event_key": event_key,
                    "bid_notice_id": f"{event_key}:000",
                    "notice_name": f"{organization_name} 계약",
                    "organization_code": organization_code,
                    "organization_name": organization_name,
                    "activity_date": date(year, month, 1),
                    "notice_published_date": date(year, month, 1),
                    "first_contract_date": date(year, month, 1),
                    "latest_contract_version_date": date(year, month, 1),
                    "event_amount": Decimal(amount),
                    "attributed_contract_amount": Decimal(amount),
                }
                for (
                    event_key,
                    organization_code,
                    organization_name,
                    year,
                    month,
                    amount,
                ) in definitions
            ]

    catalog = RegistryLoader(REGISTRIES).load()
    base_inputs = {
        "business_registration_number": "1111111111",
        "period_from_year": 2021,
        "period_to_year": 2026,
        "target_year": 2026,
        "organization_entry_status": "first_observed",
        "work_type": "service",
        "large_category": "ICT 서비스",
        "middle_category": "SW 및 시스템 개발",
        "field_code": "81111599",
        "page_size": 1,
    }
    page_one = await execute_company_procurement_profile(
        catalog,
        "analyze_company_procurement_profile",
        {**base_inputs, "page": 1},
        reader=Reader(),
    )
    page_two = await execute_company_procurement_profile(
        catalog,
        "analyze_company_procurement_profile",
        {**base_inputs, "page": 2},
        reader=Reader(),
    )

    entry = page_one.outcome["organization_entry"]
    assert entry["first_observed_organization_count"] == 2
    assert entry["reentering_organization_count"] == 1
    assert entry["incumbent_organization_count"] == 1
    assert entry["total_organization_count"] == 4
    assert entry["first_observed_organization_rate"] == 0.5
    assert page_one.outcome["summary"]["organization_entry"] == entry
    assert page_one.outcome["pagination"]["total_items"] == 2
    assert page_one.outcome["pagination"]["total_pages"] == 2
    assert page_two.outcome["pagination"]["total_items"] == 2
    returned = (
        page_one.outcome["organization_relationships"]
        + page_two.outcome["organization_relationships"]
    )
    assert {item["organization_code"] for item in returned} == {
        "ORG-NEW-A",
        "ORG-NEW-B",
    }
    assert all(
        item["organization_entry_status"] == "first_observed" for item in returned
    )
    assert all(
        item["organization_entry"]["organization_entry_status"] == "first_observed"
        for item in returned
    )
    assert page_one.outcome["summary"]["organization_count"] == 5
    assert page_one.outcome["analysis_basis"]["organization_entry_target_year"] == 2026
    assert page_one.outcome["analysis_basis"]["organization_entry_status"] == (
        "first_observed"
    )

    reentering = await execute_company_procurement_profile(
        catalog,
        "analyze_company_procurement_profile",
        {**base_inputs, "organization_entry_status": "reentering", "page": 1},
        reader=Reader(),
    )
    incumbent = await execute_company_procurement_profile(
        catalog,
        "analyze_company_procurement_profile",
        {**base_inputs, "organization_entry_status": "incumbent", "page": 1},
        reader=Reader(),
    )
    assert reentering.outcome["pagination"]["total_items"] == 1
    assert (
        reentering.outcome["organization_relationships"][0]["organization_code"]
        == "ORG-RETURN"
    )
    assert incumbent.outcome["pagination"]["total_items"] == 1
    assert (
        incumbent.outcome["organization_relationships"][0]["organization_code"]
        == "ORG-CURRENT"
    )


@pytest.mark.asyncio
async def test_procurement_profile_merges_contract_versions_by_project() -> None:
    class Reader:
        async def activities(self, catalog, **kwargs):
            return [
                {
                    "activity_type": "contract",
                    "event_key": event_key,
                    "bid_notice_id": "N1:000",
                    "notice_name": "정보시스템 유지관리",
                    "organization_code": "ORG-1",
                    "organization_name": "기관",
                    "company_number": "1111111111",
                    "company_name": "업체",
                    "procurement_classification_number": "81111899",
                    "procurement_classification_name": "정보시스템유지관리서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "정보시스템 운영",
                    "work_type": "service",
                    "activity_date": date(2023, 1, 1),
                    "attribution_date_basis": "notice_published_at",
                    "first_contract_date": date(2023, 2, 1),
                    "latest_contract_version_date": activity_date,
                    "event_amount": amount,
                    "attributed_contract_amount": amount,
                    "amount_completeness": "complete",
                }
                for event_key, activity_date, amount in (
                    ("C1", date(2023, 1, 1), Decimal("80")),
                    ("C1", date(2025, 1, 1), Decimal("100")),
                )
            ]

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(),
        "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "period_years": 5},
        reader=Reader(),
    )

    relationship = result.outcome["company_relationships"][0]
    assert relationship["contract_event_count"] == 1
    assert relationship["contract_version_count"] == 2
    assert relationship["unique_project_count"] == 1
    assert relationship["total_attributed_contract_amount"] == 100
    assert relationship["active_years"] == [2023]
    assert relationship["latest_contract_date"] == date(2025, 1, 1)
    assert relationship["yearly_activity"] == [
        {
            "year": 2023,
            "participation_count": 0,
            "award_event_count": 0,
            "result_confirmed_participation_count": 0,
            "successful_participation_count": 0,
            "award_success_rate": None,
            "contract_event_count": 1,
            "attributed_contract_amount": 100,
            "amount_completeness": "complete",
        }
    ]
    representative = relationship["representative_notices"][0]
    assert representative["attribution_date"] == date(2023, 2, 1)
    assert representative["first_contract_date"] == date(2023, 2, 1)
    assert representative["latest_contract_version_date"] == date(2025, 1, 1)
    assert result.outcome["summary"]["contract_event_count"] == 1
    assert result.outcome["summary"]["contract_version_count"] == 2
    assert result.outcome["summary"]["unique_project_count"] == 1


@pytest.mark.asyncio
async def test_procurement_profile_uses_first_contract_year_and_reports_missing_date() -> (
    None
):
    class Reader:
        async def activities(self, catalog, **kwargs):
            common = {
                "activity_type": "contract",
                "bid_notice_id": "N1:000",
                "notice_name": "장기 정보시스템 계약",
                "organization_code": "ORG-1",
                "organization_name": "기관",
                "company_number": "1111111111",
                "company_name": "업체",
                "procurement_classification_number": "81111899",
                "procurement_classification_name": "정보시스템유지관리서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "정보시스템 운영",
                "work_type": "service",
                "attributed_contract_amount": Decimal("120"),
                "event_amount": Decimal("120"),
                "amount_completeness": "complete",
                "contract_version_count": 1,
            }
            return [
                {
                    **common,
                    "event_key": "CONTRACT-1",
                    "activity_date": date(2022, 11, 1),
                    "attribution_date_basis": "notice_published_at",
                    "first_contract_date": date(2023, 2, 1),
                    "latest_contract_version_date": date(2025, 6, 1),
                },
                {
                    **common,
                    "event_key": "CONTRACT-MISSING-DATE",
                    "activity_date": date(2024, 3, 1),
                    "attribution_date_basis": "notice_published_at",
                    "first_contract_date": None,
                    "latest_contract_version_date": None,
                },
            ]

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(),
        "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1",
            "period_from_year": 2023,
            "period_to_year": 2025,
        },
        reader=Reader(),
    )

    assert result.outcome["summary"]["contract_event_count"] == 1
    assert result.outcome["summary"]["missing_first_contract_date_count"] == 1
    assert result.outcome["summary"]["total_attributed_contract_amount"] == 120
    assert (
        "some_contract_events_missing_first_contract_date"
        in result.outcome["data_completeness"]["missing_reasons"]
    )
    assert result.outcome["yearly_activity"][0]["year"] == 2023
    assert result.outcome["yearly_activity"][0]["attributed_contract_amount"] == 120
    assert result.outcome["company_relationships"][0]["latest_contract_date"] == date(
        2025, 6, 1
    )
    assert (
        result.outcome["analysis_basis"]
        | {
            "contract_event_date_basis": "first_contract_date",
            "contract_amount_basis": "latest_version_at_or_before_period_end",
            "contract_amount_year_attribution": "first_contract_year",
            "contract_version_deduplication": "merged_by_contract_event",
        }
        == result.outcome["analysis_basis"]
    )


@pytest.mark.asyncio
async def test_procurement_profile_yearly_metrics_use_separate_date_bases() -> None:
    classification = {
        "procurement_classification_number": "81111599",
        "procurement_classification_name": "정보시스템개발서비스",
        "procurement_large_classification_name": "ICT 서비스",
        "procurement_middle_classification_name": "SW 및 시스템 개발",
        "work_type": "service",
    }

    class Reader:
        async def activities(self, catalog, **kwargs):
            common = {
                "bid_notice_id": "N1:000",
                "notice_name": "연도 기준 검증",
                "notice_published_date": date(2023, 3, 1),
                "organization_code": "ORG-1",
                "organization_name": "기관",
                "company_number": "1111111111",
                "company_name": "업체",
                "event_amount": None,
                "attributed_contract_amount": None,
                "amount_completeness": "unknown",
                **classification,
            }
            return [
                {
                    **common,
                    "activity_type": "participation",
                    "event_key": "N1:000",
                    "activity_date": date(2023, 3, 1),
                    "attribution_date_basis": "notice_published_at",
                    "result_confirmed": True,
                    "participation_successful": True,
                },
                {
                    **common,
                    "activity_type": "award",
                    "event_key": "N1:000:0:0",
                    "activity_date": date(2024, 4, 1),
                    "attribution_date_basis": "final_award_date_or_opening_at",
                    "result_confirmed": True,
                    "participation_successful": True,
                },
                {
                    **common,
                    "activity_type": "contract",
                    "event_key": "C1",
                    "activity_date": date(2025, 5, 1),
                    "first_contract_date": date(2025, 5, 1),
                    "latest_contract_version_date": date(2025, 6, 1),
                    "attribution_date_basis": "first_contract_date",
                    "event_amount": Decimal("130"),
                    "attributed_contract_amount": Decimal("130"),
                    "amount_completeness": "complete",
                    "contract_version_count": 2,
                },
            ]

        async def notice_publications(self, catalog, **kwargs):
            return [
                {
                    "bid_notice_id": "N1:000",
                    "notice_name": "연도 기준 검증",
                    "notice_published_date": date(2023, 3, 1),
                    **classification,
                },
                {
                    "bid_notice_id": "N2:000",
                    "notice_name": "활동 없는 공고",
                    "notice_published_date": date(2024, 7, 1),
                    **classification,
                },
            ]

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(),
        "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1",
            "period_from_year": 2023,
            "period_to_year": 2025,
        },
        reader=Reader(),
    )

    yearly = {item["year"]: item for item in result.outcome["yearly_activity"]}
    assert result.outcome["summary"]["notice_count"] == 2
    assert sum(item["notice_count"] for item in yearly.values()) == 2
    assert yearly[2023]["notice_count"] == 1
    assert yearly[2024]["notice_count"] == 1
    assert yearly[2024]["award_event_count"] == 1
    analysis = result.outcome["participation_analysis"]
    assert analysis["basis"]["maximum_opening_rank"] == 10
    assert analysis["basis"]["all_participants_retained"] is False
    assert analysis["summary"]["overall_success_rate"] is None
    assert yearly[2025]["contract_event_count"] == 1
    assert yearly[2025]["attributed_contract_amount"] == 130
    assert yearly[2025]["company_count"] == 1
    assert yearly[2023]["company_count"] == 0
    assert yearly[2024]["company_count"] == 0
    assert (
        result.outcome["analysis_basis"]
        | {
            "notice_year_basis": "notice_published_at",
            "award_year_basis": "opening_at_or_final_award_date",
            "contract_year_basis": "first_contract_date",
        }
        == result.outcome["analysis_basis"]
    )


@pytest.mark.asyncio
async def test_procurement_profile_applies_explicit_year_range_everywhere() -> None:
    class Reader:
        observed_period = None

        async def activities(self, catalog, **kwargs):
            self.observed_period = (kwargs["period_from"], kwargs["period_to"])
            return [
                {
                    "activity_type": "contract",
                    "event_key": f"C-{year}",
                    "bid_notice_id": f"N-{year}:000",
                    "notice_name": f"사업 {year}",
                    "organization_code": "ORG-1",
                    "organization_name": "기관",
                    "company_number": f"{year:010d}",
                    "company_name": f"업체 {year}",
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "work_type": "service",
                    "activity_date": date(year, 6, 1),
                    "event_amount": Decimal(str(year)),
                    "attributed_contract_amount": Decimal(str(year)),
                    "amount_completeness": "complete",
                }
                for year in (2022, 2023, 2024, 2025, 2026)
                if kwargs["period_from"] <= date(year, 6, 1) < kwargs["period_to"]
            ]

        async def organization_award_history(self, catalog, **kwargs):
            assert kwargs["history_from"] == date(2020, 1, 1)
            assert kwargs["history_to"] == date(2026, 1, 1)
            assert kwargs["work_type"] is None
            assert kwargs["large_category"] is None
            assert kwargs["middle_category"] is None
            assert kwargs["field_code"] is None
            return {}, kwargs["history_from"]

    reader = Reader()
    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(),
        "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1",
            "period_years": 5,
            "period_from_year": 2023,
            "period_to_year": 2025,
        },
        reader=reader,
    )

    assert reader.observed_period == (date(2020, 1, 1), date(2026, 1, 1))
    assert result.outcome["summary"]["contract_event_count"] == 3
    assert result.outcome["pagination"]["total_items"] == 3
    assert [item["year"] for item in result.outcome["yearly_activity"]] == [
        2025,
        2024,
        2023,
    ]
    assert result.outcome["field_distribution"][0]["contract_event_count"] == 3
    assert result.outcome["work_type_distribution"][0]["contract_event_count"] == 3
    assert {
        key: result.outcome["analysis_basis"][key]
        for key in (
            "period_from",
            "period_to",
            "period_from_year",
            "period_to_year",
            "period_years",
            "period_type",
        )
    } == {
        "period_from": date(2023, 1, 1),
        "period_to": date(2025, 12, 31),
        "period_from_year": 2023,
        "period_to_year": 2025,
        "period_years": 3,
        "period_type": "explicit_calendar_year_range",
    }
    rolling = result.outcome["summary"]["rolling_12m_supplier_entry"]
    assert rolling["period_from"] == date(2025, 1, 1)
    assert rolling["period_to"] == date(2026, 1, 1)


@pytest.mark.asyncio
async def test_procurement_profile_rejects_incomplete_or_reversed_year_range() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    with pytest.raises(CapabilityExecutionError, match="must be provided together"):
        await execute_company_procurement_profile(
            catalog,
            "analyze_company_procurement_profile",
            {"business_registration_number": "1111111111", "period_from_year": 2023},
        )
    with pytest.raises(CapabilityExecutionError, match="less than or equal"):
        await execute_company_procurement_profile(
            catalog,
            "analyze_company_procurement_profile",
            {
                "business_registration_number": "1111111111",
                "period_from_year": 2025,
                "period_to_year": 2023,
            },
        )


@pytest.mark.asyncio
async def test_organization_profile_lists_only_contracted_companies() -> None:
    class Reader:
        async def activities(self, catalog, **kwargs):
            base = {
                "notice_name": "조달 사업",
                "organization_code": "ORG-1",
                "organization_name": "기관",
                "work_type": "service",
                "procurement_classification_number": None,
                "procurement_classification_name": None,
                "procurement_large_classification_name": None,
                "procurement_middle_classification_name": None,
                "event_amount": Decimal("100"),
                "amount_completeness": "unknown",
            }
            return [
                {
                    **base,
                    "activity_type": "participation",
                    "event_key": "P-ONLY",
                    "bid_notice_id": "P:000",
                    "company_number": "1111111111",
                    "company_name": "참여만",
                    "activity_date": date(2025, 1, 1),
                    "attributed_contract_amount": None,
                },
                {
                    **base,
                    "activity_type": "award",
                    "event_key": "A-ONLY",
                    "bid_notice_id": "A:000",
                    "company_number": "2222222222",
                    "company_name": "낙찰만",
                    "activity_date": date(2025, 2, 1),
                    "attributed_contract_amount": None,
                },
                {
                    **base,
                    "activity_type": "participation",
                    "event_key": "P-C",
                    "bid_notice_id": "C:000",
                    "company_number": "3333333333",
                    "company_name": "계약업체",
                    "activity_date": date(2025, 3, 1),
                    "attributed_contract_amount": None,
                },
                {
                    **base,
                    "activity_type": "contract",
                    "event_key": "C-0",
                    "bid_notice_id": "C:000",
                    "company_number": "3333333333",
                    "company_name": "계약업체",
                    "activity_date": date(2020, 4, 1),
                    "attributed_contract_amount": Decimal("80"),
                    "amount_completeness": "complete",
                },
                {
                    **base,
                    "activity_type": "contract",
                    "event_key": "C-1",
                    "bid_notice_id": "C:000",
                    "company_number": "3333333333",
                    "company_name": "계약업체",
                    "activity_date": date(2025, 4, 1),
                    "attributed_contract_amount": Decimal("100"),
                    "amount_completeness": "complete",
                },
            ]

        async def organization_award_history(self, catalog, **kwargs):
            return {}, kwargs["history_from"]

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(),
        "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1",
            "period_from_year": 2025,
            "period_to_year": 2025,
        },
        reader=Reader(),
    )

    assert result.outcome["summary"]["participation_count"] == 2
    assert result.outcome["summary"]["award_event_count"] == 1
    assert result.outcome["summary"]["company_count"] == 1
    assert result.outcome["summary"]["company_count_basis"] == "contracted_companies"
    assert result.outcome["pagination"]["total_items"] == 1
    assert len(result.outcome["company_relationships"]) == 1
    relationship = result.outcome["company_relationships"][0]
    assert relationship["company_name"] == "계약업체"
    assert relationship["contract_event_count"] == 1
    assert relationship["participation_count"] == 1
    assert result.outcome["yearly_activity"][0]["company_count"] == 1
    rolling = result.outcome["summary"]["rolling_12m_supplier_entry"]
    assert rolling["total_company_count"] == 1
    assert rolling["classified_company_count"] == 1
    assert (
        sum(
            rolling[key]
            for key in (
                "first_observed_company_count",
                "reentering_company_count",
                "incumbent_company_count",
            )
        )
        == rolling["total_company_count"]
    )


@pytest.mark.asyncio
async def test_organization_profile_company_search_sort_and_pagination_are_list_only() -> (
    None
):
    class Reader:
        async def activities(self, catalog, **kwargs):
            rows = []
            definitions = [
                (
                    "1111111111",
                    "알파 시스템",
                    [("A-1", date(2025, 2, 1), "40"), ("A-2", date(2025, 5, 1), "60")],
                ),
                ("2222222222", "베타정보", [("B-1", date(2025, 3, 1), "300")]),
                ("3333333333", "감마테크", [("C-1", date(2025, 8, 1), "200")]),
            ]
            for company_number, company_name, contracts in definitions:
                for event_key, activity_date, amount in contracts:
                    rows.append(
                        {
                            "activity_type": "contract",
                            "event_key": event_key,
                            "bid_notice_id": f"{event_key}:000",
                            "notice_name": event_key,
                            "organization_code": "ORG-1",
                            "organization_name": "기관",
                            "company_number": company_number,
                            "company_name": company_name,
                            "procurement_classification_number": None,
                            "procurement_classification_name": None,
                            "procurement_large_classification_name": None,
                            "procurement_middle_classification_name": None,
                            "work_type": "service",
                            "activity_date": activity_date,
                            "event_amount": Decimal(amount),
                            "attributed_contract_amount": Decimal(amount),
                            "amount_completeness": "complete",
                        }
                    )
            return rows

    catalog = RegistryLoader(REGISTRIES).load()
    base_inputs = {
        "organization_code": "ORG-1",
        "period_from_year": 2025,
        "period_to_year": 2025,
        "page": 1,
        "page_size": 20,
    }
    baseline = await execute_organization_procurement_profile(
        catalog,
        "analyze_organization_procurement_profile",
        base_inputs,
        reader=Reader(),
    )
    searched = await execute_organization_procurement_profile(
        catalog,
        "analyze_organization_procurement_profile",
        {
            **base_inputs,
            "company_query": "  알파   ",
            "sort": "contract_count_desc",
        },
        reader=Reader(),
    )

    assert searched.outcome["pagination"]["total_items"] == 1
    assert searched.outcome["pagination"]["total_pages"] == 1
    assert searched.outcome["pagination"]["sort"] == "contract_count_desc"
    assert searched.outcome["company_relationships"][0]["company_name"] == "알파 시스템"
    assert searched.outcome["company_relationships"][0]["latest_contract_date"] == date(
        2025,
        5,
        1,
    )
    assert searched.outcome["summary"] == baseline.outcome["summary"]
    assert searched.outcome["yearly_activity"] == baseline.outcome["yearly_activity"]
    assert (
        searched.outcome["field_distribution"] == baseline.outcome["field_distribution"]
    )
    assert (
        searched.outcome["work_type_distribution"]
        == baseline.outcome["work_type_distribution"]
    )
    assert (
        searched.outcome["company_structure"] == baseline.outcome["company_structure"]
    )
    assert (
        searched.outcome["notice_quarter_distribution"]
        == baseline.outcome["notice_quarter_distribution"]
    )
    assert (
        searched.outcome["contract_method_distribution"]
        == baseline.outcome["contract_method_distribution"]
    )
    assert searched.objects[0].properties["relationship_count"] == 3

    expected_orders = {
        "contract_amount_desc": ["베타정보", "감마테크", "알파 시스템"],
        "contract_count_desc": ["알파 시스템", "베타정보", "감마테크"],
        "latest_contract_desc": ["감마테크", "알파 시스템", "베타정보"],
    }
    for sort, expected in expected_orders.items():
        result = await execute_organization_procurement_profile(
            catalog,
            "analyze_organization_procurement_profile",
            {
                **base_inputs,
                "sort": sort,
            },
            reader=Reader(),
        )
        assert [
            item["company_name"] for item in result.outcome["company_relationships"]
        ] == expected


@pytest.mark.asyncio
async def test_organization_profile_market_structure_uses_unique_contract_events() -> (
    None
):
    class Reader:
        async def activities(self, catalog, **kwargs):
            base = {
                "organization_code": "ORG-1",
                "organization_name": "기관",
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "work_type": "service",
                "amount_completeness": "complete",
                "activity_type": "contract",
                "attribution_date_basis": "notice_published_at",
            }
            return [
                {
                    **base,
                    "event_key": "OLD",
                    "bid_notice_id": "OLD:000",
                    "notice_name": "이전 사업",
                    "company_number": "1111111111",
                    "company_name": "A사",
                    "activity_date": date(2024, 2, 1),
                    "notice_published_date": date(2024, 2, 1),
                    "contract_method_name": "일반경쟁",
                    "event_amount": Decimal("100"),
                    "attributed_contract_amount": Decimal("100"),
                },
                {
                    **base,
                    "event_key": "JOINT",
                    "bid_notice_id": "JOINT:000",
                    "notice_name": "공동 사업",
                    "company_number": "1111111111",
                    "company_name": "A사",
                    "activity_date": date(2025, 4, 1),
                    "notice_published_date": date(2025, 4, 1),
                    "contract_method_name": "제한경쟁",
                    "event_amount": Decimal("100"),
                    "attributed_contract_amount": Decimal("60"),
                },
                {
                    **base,
                    "event_key": "JOINT",
                    "bid_notice_id": "JOINT:000",
                    "notice_name": "공동 사업",
                    "company_number": "2222222222",
                    "company_name": "B사",
                    "activity_date": date(2025, 4, 1),
                    "notice_published_date": date(2025, 4, 1),
                    "contract_method_name": "제한경쟁",
                    "event_amount": Decimal("100"),
                    "attributed_contract_amount": Decimal("40"),
                },
                {
                    **base,
                    "event_key": "DIRECT",
                    "bid_notice_id": "DIRECT:000",
                    "notice_name": "수의 사업",
                    "company_number": "1111111111",
                    "company_name": "A사",
                    "activity_date": date(2025, 8, 1),
                    "notice_published_date": date(2025, 8, 1),
                    "contract_method_name": "수의계약",
                    "event_amount": Decimal("200"),
                    "attributed_contract_amount": Decimal("200"),
                },
            ]

        async def organization_award_history(self, catalog, **kwargs):
            return {
                "1111111111": date(2024, 2, 1),
                "2222222222": date(2025, 4, 1),
            }, date(2020, 1, 1)

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(),
        "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1",
            "period_from_year": 2024,
            "period_to_year": 2025,
        },
        reader=Reader(),
    )

    outcome = result.outcome
    assert outcome["summary"]["average_contract_amount"] == 400 / 3
    assert outcome["summary"]["previous_period_comparison"] == {
        "basis": "year_over_year",
        "current_year": 2025,
        "comparison_year": 2024,
        "contract_amount_change_rate": 2.0,
        "contract_event_count_change": 1,
        "comparable": True,
        "comparison_note": None,
    }
    assert (
        sum(item["contract_event_count"] for item in outcome["field_distribution"]) == 3
    )
    assert (
        sum(item["notice_count"] for item in outcome["notice_quarter_distribution"])
        == 3
    )
    assert (
        sum(
            item["contract_event_count"]
            for item in outcome["contract_method_distribution"]
        )
        == 3
    )
    assert outcome["company_structure"]["contracted_company_count"] == 2
    assert outcome["company_structure"]["multi_contract_company_count"] == 1
    assert outcome["company_structure"]["single_contract_company_count"] == 1
    assert outcome["company_structure"]["top_5_company_amount"] == 400
    assert outcome["company_structure"]["top_5_company_amount_share"] == 1.0
    assert outcome["company_relationships"][0]["major_field"] == {
        "field_code": "81111599",
        "field_name": "정보시스템개발서비스",
    }


@pytest.mark.asyncio
async def test_supplier_entry_uses_target_year_and_three_prior_calendar_years() -> None:
    class Reader:
        async def activities(self, catalog, **kwargs):
            base = {
                "activity_type": "contract",
                "organization_code": "ORG-1",
                "organization_name": "기관",
                "notice_name": "정보시스템 사업",
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "work_type": "service",
                "amount_completeness": "complete",
                "attribution_date_basis": "notice_published_at",
            }
            definitions = [
                ("A", "1111111111", "신규", 2026, "100"),
                ("B-OLD", "2222222222", "재진입", 2022, "10"),
                ("B", "2222222222", "재진입", 2026, "200"),
                ("C-OLD", "3333333333", "기존", 2024, "50"),
                ("C", "3333333333", "기존", 2026, "300"),
            ]
            return [
                {
                    **base,
                    "event_key": event,
                    "bid_notice_id": f"{event}:000",
                    "company_number": number,
                    "company_name": name,
                    "activity_date": date(year, 4, 1),
                    "notice_published_date": date(year, 4, 1),
                    "first_contract_date": date(year, 6, 1),
                    "latest_contract_version_date": date(year, 9, 1),
                    "event_amount": Decimal(amount),
                    "attributed_contract_amount": Decimal(amount),
                    "contract_method_name": "일반경쟁",
                }
                for event, number, name, year, amount in definitions
            ]

        async def organization_award_history(self, catalog, **kwargs):
            return {
                "1111111111": date(2026, 4, 1),
                "2222222222": date(2022, 4, 1),
                "3333333333": date(2024, 4, 1),
            }, date(2020, 1, 1)

    catalog = RegistryLoader(REGISTRIES).load()
    inputs = {
        "organization_code": "ORG-1",
        "period_from_year": 2023,
        "period_to_year": 2026,
        "work_type": "service",
        "large_category": "ICT 서비스",
    }
    result = await execute_organization_procurement_profile(
        catalog,
        "analyze_organization_procurement_profile",
        inputs,
        reader=Reader(),
    )
    entry = result.outcome["supplier_entry"]
    assert entry["lookback_from"] == date(2023, 1, 1)
    assert entry["lookback_to"] == date(2025, 12, 31)
    assert entry["first_observed_company_count"] == 1
    assert entry["reentering_company_count"] == 1
    assert entry["incumbent_company_count"] == 1
    assert entry["entry_and_reentry_company_count"] == 2
    assert entry["total_company_count"] == 3
    assert entry["entry_and_reentry_rate"] == pytest.approx(2 / 3, abs=1e-6)
    assert entry["history_complete_for_lookback"] is True
    structure = result.outcome["company_structure"]
    assert (
        structure["single_contract_company_count"]
        + structure["multi_contract_company_count"]
        == structure["contracted_company_count"]
    )
    assert structure["top_5_company_amount"] == 650
    assert structure["total_company_attributed_contract_amount"] == 650
    assert structure["top_5_company_amount_share"] == 1.0
    assert structure["small_supplier_population"] is True
    assert 0 <= structure["hhi"] <= 10000

    search = await execute_organization_supplier_entry_search(
        catalog,
        "search_organization_supplier_entries",
        {
            "organization_code": "ORG-1",
            "target_year": 2026,
            "work_type": "service",
            "large_category": "ICT 서비스",
            "entry_status": "reentering",
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )
    assert search.outcome["pagination"]["total_items"] == 1
    assert search.outcome["items"][0]["company_name"] == "재진입"
    assert search.outcome["items"][0]["target_year_first_contract_date"] == date(
        2026, 6, 1
    )
    assert search.outcome["items"][0]["target_year_latest_contract_date"] == date(
        2026, 6, 1
    )
    assert search.outcome["items"][0]["previous_contract_date"] == date(2022, 6, 1)
    assert search.outcome["items"][0]["reentry_contract_date"] == date(2026, 6, 1)


@pytest.mark.asyncio
async def test_supplier_entry_searches_sorts_and_pages_the_complete_supplier_set() -> (
    None
):
    class Reader:
        async def activities(self, catalog, **kwargs):
            rows = []
            for index in range(105):
                company_number = str(1000000000 + index)
                amount = (
                    None
                    if index == 104
                    else Decimal("0" if index == 103 else index + 1)
                )
                rows.append(
                    {
                        "activity_type": "contract",
                        "organization_code": "ORG-1",
                        "organization_name": "기관",
                        "notice_name": f"정보시스템 사업 {index:03d}",
                        "procurement_classification_number": "81111599",
                        "procurement_classification_name": "정보시스템개발서비스",
                        "procurement_large_classification_name": "ICT 서비스",
                        "procurement_middle_classification_name": "SW 및 시스템 개발",
                        "work_type": "service",
                        "amount_completeness": "unknown"
                        if amount is None
                        else "complete",
                        "attribution_date_basis": "first_contract_date",
                        "event_key": f"CONTRACT-{index:03d}",
                        "bid_notice_id": f"NOTICE-{index:03d}:000",
                        "company_number": company_number,
                        "company_name": (
                            f"한글검색 업체 {index:03d}"
                            if index < 27
                            else f"일반 업체 {index:03d}"
                        ),
                        "activity_date": date(2026, 1, 1) + timedelta(days=index),
                        "notice_published_date": date(2025, 12, 1),
                        "first_contract_date": date(2026, 1, 1) + timedelta(days=index),
                        "latest_contract_version_date": date(2026, 1, 1)
                        + timedelta(days=index),
                        "event_amount": amount,
                        "attributed_contract_amount": amount,
                        "contract_method_name": "일반경쟁",
                    }
                )
            return rows

        async def organization_award_history(self, catalog, **kwargs):
            return {
                str(1000000000 + index): date(2026, 1, 1) + timedelta(days=index)
                for index in range(105)
            }, date(2020, 1, 1)

    catalog = RegistryLoader(REGISTRIES).load()
    base_inputs = {
        "organization_code": "ORG-1",
        "target_year": 2026,
        "entry_status": "first_observed",
        "work_type": "service",
        "large_category": "ICT 서비스",
        "middle_category": "SW 및 시스템 개발",
        "field_code": "81111599",
    }

    observed_numbers = []
    for page in range(1, 12):
        result = await execute_organization_supplier_entry_search(
            catalog,
            "search_organization_supplier_entries",
            {**base_inputs, "page": page, "page_size": 10},
            reader=Reader(),
        )
        assert result.outcome["pagination"]["total_items"] == 105
        assert result.outcome["pagination"]["total_pages"] == 11
        observed_numbers.extend(
            item["company_number"] for item in result.outcome["items"]
        )
    assert len(observed_numbers) == len(set(observed_numbers)) == 105
    assert len(result.outcome["items"]) == 5

    korean = await execute_organization_supplier_entry_search(
        catalog,
        "search_organization_supplier_entries",
        {
            **base_inputs,
            "company_query": "  한글검색  ",
            "sort": "company_name_asc",
            "page": 2,
            "page_size": 10,
        },
        reader=Reader(),
    )
    assert korean.outcome["pagination"] == {
        "page": 2,
        "page_size": 10,
        "total_items": 27,
        "total_pages": 3,
        "sort": "company_name_asc",
    }
    assert korean.outcome["supplier_entry"]["first_observed_company_count"] == 105
    assert korean.outcome["items"][0]["company_name"] == "한글검색 업체 010"

    number = await execute_organization_supplier_entry_search(
        catalog,
        "search_organization_supplier_entries",
        {**base_inputs, "company_query": "100-000-0007", "page": 1, "page_size": 10},
        reader=Reader(),
    )
    assert [item["company_number"] for item in number.outcome["items"]] == [
        "1000000007"
    ]

    latest = await execute_organization_supplier_entry_search(
        catalog,
        "search_organization_supplier_entries",
        {**base_inputs, "sort": "latest_contract_desc", "page": 1, "page_size": 10},
        reader=Reader(),
    )
    assert latest.outcome["items"][0]["company_number"] == "1000000104"

    amount_zero = await execute_organization_supplier_entry_search(
        catalog,
        "search_organization_supplier_entries",
        {**base_inputs, "company_query": "1000000103", "page": 1, "page_size": 10},
        reader=Reader(),
    )
    amount_unknown = await execute_organization_supplier_entry_search(
        catalog,
        "search_organization_supplier_entries",
        {**base_inputs, "company_query": "1000000104", "page": 1, "page_size": 10},
        reader=Reader(),
    )
    assert (
        amount_zero.outcome["items"][0]["target_year_attributed_contract_amount"] == 0
    )
    assert (
        amount_unknown.outcome["items"][0]["target_year_attributed_contract_amount"]
        is None
    )
    assert amount_unknown.outcome["items"][0]["amount_completeness"] == "unknown"


@pytest.mark.asyncio
async def test_rolling_supplier_entry_ignores_start_year_and_filters_history() -> None:
    class Reader:
        history_calls = []

        async def activities(self, catalog, **kwargs):
            return [
                {
                    "activity_type": "contract",
                    "event_key": "C-1",
                    "bid_notice_id": "C:000",
                    "notice_name": "정보시스템 계약",
                    "organization_code": "ORG-1",
                    "organization_name": "기관",
                    "company_number": "3333333333",
                    "company_name": "계약업체",
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "work_type": "service",
                    "activity_date": date(2025, 4, 1),
                    "event_amount": Decimal("100"),
                    "attributed_contract_amount": Decimal("100"),
                    "amount_completeness": "complete",
                }
            ]

        async def organization_award_history(self, catalog, **kwargs):
            self.history_calls.append(kwargs)
            return {"3333333333": date(2025, 4, 1)}, kwargs["history_from"]

    reader = Reader()
    catalog = RegistryLoader(REGISTRIES).load()
    outcomes = []
    supplier_outcomes = []
    for from_year in (2021, 2024):
        result = await execute_organization_procurement_profile(
            catalog,
            "analyze_organization_procurement_profile",
            {
                "organization_code": "ORG-1",
                "period_from_year": from_year,
                "period_to_year": 2025,
                "work_type": "service",
                "large_category": "ICT 서비스",
                "middle_category": "SW 및 시스템 개발",
                "field_code": "81111599",
            },
            reader=reader,
        )
        outcomes.append(result.outcome["summary"]["rolling_12m_supplier_entry"])
        supplier_outcomes.append(result.outcome["supplier_entry"])

    assert outcomes[0] == outcomes[1]
    assert supplier_outcomes[0] == supplier_outcomes[1]
    assert outcomes[0]["history_from"] == date(2020, 1, 1)
    assert outcomes[0]["history_to"] == date(2024, 12, 31)
    for call in reader.history_calls:
        assert call["history_from"] == date(2020, 1, 1)
        assert call["history_to"] == date(2026, 1, 1)
        assert call["work_type"] == "service"
        assert call["large_category"] == "ICT 서비스"
        assert call["middle_category"] == "SW 및 시스템 개발"
        assert call["field_code"] == "81111599"


@pytest.mark.asyncio
async def test_organization_profile_reports_rolling_supplier_entry_without_participation() -> (
    None
):
    class Reader:
        async def activities(self, catalog, **kwargs):
            base = {
                "notice_name": "정보시스템 용역",
                "organization_code": "ORG-1",
                "organization_name": "기관",
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "work_type": "service",
                "event_amount": Decimal("100"),
                "attributed_contract_amount": None,
                "amount_completeness": "unknown",
            }
            return [
                {
                    **base,
                    "activity_type": "participation",
                    "event_key": "P1",
                    "bid_notice_id": "P1:000",
                    "company_number": "9999999999",
                    "company_name": "참여업체",
                    "activity_date": date(2025, 1, 1),
                },
                {
                    **base,
                    "activity_type": "award",
                    "event_key": "A1",
                    "bid_notice_id": "A1:000",
                    "company_number": "1111111111",
                    "company_name": "기존업체",
                    "activity_date": date(2025, 2, 1),
                },
                {
                    **base,
                    "activity_type": "contract",
                    "event_key": "C1",
                    "bid_notice_id": "A1:000",
                    "company_number": "3333333333",
                    "company_name": "공동수급구성원",
                    "activity_date": date(2026, 2, 10),
                    "attributed_contract_amount": Decimal("30"),
                    "amount_completeness": "complete",
                },
                {
                    **base,
                    "activity_type": "award",
                    "event_key": "A2",
                    "bid_notice_id": "A2:000",
                    "company_number": "2222222222",
                    "company_name": "신규업체",
                    "activity_date": date(2025, 3, 1),
                },
                {
                    **base,
                    "activity_type": "award",
                    "event_key": "A3",
                    "bid_notice_id": "A3:000",
                    "company_number": None,
                    "company_name": None,
                    "activity_date": date(2025, 4, 1),
                },
            ]

        async def organization_award_history(self, catalog, **kwargs):
            return {
                "1111111111": date(2022, 1, 1),
                "2222222222": date(2025, 3, 1),
                "3333333333": date(2026, 2, 10),
            }, date(2022, 1, 1)

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(),
        "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "period_years": 5},
        reader=Reader(),
    )

    assert result.outcome["summary"]["rolling_12m_supplier_entry"] == {
        "window_months": 12,
        "period_from": date.today().replace(year=date.today().year - 1),
        "period_to": date.today(),
        "comparison_period_from": date.today().replace(year=date.today().year - 2),
        "comparison_period_to": date.today().replace(year=date.today().year - 1),
        "first_observed_company_count": 1,
        "reentering_company_count": 0,
        "incumbent_company_count": 0,
        "total_company_count": 1,
        "classified_company_count": 1,
        "first_observed_company_rate": 1.0,
        "entry_and_reentry_rate": 1.0,
        "history_from": date(2022, 1, 1),
        "history_to": date.today().replace(year=date.today().year - 1)
        - timedelta(days=1),
        "history_years": 5,
        "history_basis": "five_fiscal_years_before_target_period",
        "minimum_sample_size": 10,
        "sample_sufficient": False,
    }


@pytest.mark.asyncio
async def test_construction_profile_uses_official_field_as_flat_category() -> None:
    class Reader:
        async def activities(self, catalog, **kwargs):
            return [
                {
                    "activity_type": "contract",
                    "event_key": "C1",
                    "bid_notice_id": "N1:000",
                    "notice_name": "청사 내부 공사",
                    "organization_code": "ORG-1",
                    "organization_name": "기관",
                    "company_number": "1111111111",
                    "company_name": "업체",
                    "procurement_classification_number": "72153699",
                    "procurement_classification_name": "실내건축공사",
                    "procurement_large_classification_name": None,
                    "procurement_middle_classification_name": None,
                    "purchase_items": None,
                    "work_type": "construction",
                    "activity_date": date(2025, 3, 1),
                    "event_amount": Decimal("100"),
                    "attributed_contract_amount": Decimal("100"),
                    "amount_completeness": "complete",
                }
            ]

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(),
        "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1",
            "work_type": "construction",
            "large_category": "실내건축공사",
        },
        reader=Reader(),
    )

    assert result.outcome["field_distribution_level"] == "construction_field"
    assert result.outcome["field_hierarchy_depth"] == 1
    assert result.outcome["field_distribution"] == [
        {
            "field_code": "72153699",
            "field_name": "실내건축공사",
            "large_category": "실내건축공사",
            "middle_category": None,
            "detailed_items": [],
            "classification_source": "construction_work_category",
            "work_types": ["construction"],
            "participation_count": 0,
            "result_confirmed_participation_count": 0,
            "successful_participation_count": 0,
            "award_success_rate": None,
            "award_event_count": 0,
            "contract_event_count": 1,
            "event_count": 1,
            "attributed_contract_amount": 100,
            "amount_share": 1.0,
            "display_level": "field_code",
            "display_code": "72153699",
            "display_name": "실내건축공사",
            "has_children": False,
            "selection_filter": {
                "work_type": "construction",
                "large_category": "실내건축공사",
                "field_code": "72153699",
            },
        }
    ]


@pytest.mark.asyncio
async def test_goods_profile_uses_primary_official_purchase_item() -> None:
    class Reader:
        async def activities(self, catalog, **kwargs):
            return [
                {
                    "activity_type": "contract",
                    "event_key": "C1",
                    "bid_notice_id": "N1:000",
                    "notice_name": "장비 구매",
                    "organization_code": "ORG-1",
                    "organization_name": "기관",
                    "company_number": "1111111111",
                    "company_name": "업체",
                    "procurement_classification_number": None,
                    "procurement_classification_name": None,
                    "procurement_large_classification_name": None,
                    "procurement_middle_classification_name": None,
                    "purchase_items": [
                        {"sequence": "2", "code": "4711150301", "name": "세탁물건조기"},
                        {"sequence": "1", "code": "4711150201", "name": "업소용세탁기"},
                    ],
                    "work_type": "goods",
                    "activity_date": date(2025, 3, 1),
                    "event_amount": Decimal("100"),
                    "attributed_contract_amount": Decimal("100"),
                    "amount_completeness": "complete",
                }
            ]

    catalog = RegistryLoader(REGISTRIES).load()
    result = await execute_organization_procurement_profile(
        catalog,
        "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "work_type": "goods"},
        reader=Reader(),
    )

    assert result.outcome["field_distribution_level"] == "field"
    assert result.outcome["field_distribution"] == [
        {
            "field_code": "4711150201",
            "field_name": "업소용세탁기",
            "large_category": "업소용세탁기",
            "middle_category": None,
            "detailed_items": [
                {"sequence": "2", "code": "4711150301", "name": "세탁물건조기"},
                {"sequence": "1", "code": "4711150201", "name": "업소용세탁기"},
            ],
            "classification_source": "purchase_item",
            "work_types": ["goods"],
            "participation_count": 0,
            "award_event_count": 0,
            "result_confirmed_participation_count": 0,
            "successful_participation_count": 0,
            "contract_event_count": 1,
            "event_count": 1,
            "attributed_contract_amount": 100,
            "amount_share": 1.0,
            "award_success_rate": None,
            "display_level": "field_code",
            "display_code": "4711150201",
            "display_name": "업소용세탁기",
            "has_children": False,
            "selection_filter": {
                "work_type": "goods",
                "large_category": "업소용세탁기",
                "field_code": "4711150201",
            },
        }
    ]

    mixed = await execute_organization_procurement_profile(
        catalog,
        "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1"},
        reader=Reader(),
    )
    assert mixed.outcome["field_distribution_level"] == "large"
    assert mixed.outcome["field_distribution"] == [
        {
            "large_category": "업소용세탁기",
            "event_count": 1,
            "participation_count": 0,
            "award_event_count": 0,
            "result_confirmed_participation_count": 0,
            "successful_participation_count": 0,
            "award_success_rate": None,
            "contract_event_count": 1,
            "attributed_contract_amount": 100,
            "work_types": ["goods"],
            "amount_share": 1.0,
            "display_level": "large_category",
            "display_code": "업소용세탁기",
            "display_name": "업소용세탁기",
            "has_children": True,
            "selection_filter": {
                "work_type": "goods",
                "large_category": "업소용세탁기",
            },
        }
    ]


@pytest.mark.asyncio
async def test_profile_includes_and_filters_unclassified_field_bucket() -> None:
    class Reader:
        async def activities(self, catalog, **kwargs):
            base = {
                "activity_type": "contract",
                "organization_code": "ORG-1",
                "organization_name": "기관",
                "company_number": "1111111111",
                "company_name": "업체",
                "work_type": "goods",
                "activity_date": date(2025, 1, 1),
                "amount_completeness": "complete",
            }
            return [
                {
                    **base,
                    "event_key": "C1",
                    "bid_notice_id": "N1:000",
                    "notice_name": "분류 물품",
                    "event_amount": Decimal("20"),
                    "attributed_contract_amount": Decimal("20"),
                    "procurement_classification_number": "82141502",
                    "procurement_classification_name": "그래픽디자인서비스",
                    "procurement_large_classification_name": "매체제작·디자인",
                    "procurement_middle_classification_name": "디자인",
                },
                {
                    **base,
                    "event_key": "C2",
                    "bid_notice_id": "N2:000",
                    "notice_name": "원천 분류 없는 물품",
                    "event_amount": Decimal("80"),
                    "attributed_contract_amount": Decimal("80"),
                    "procurement_classification_number": None,
                    "procurement_classification_name": None,
                    "procurement_large_classification_name": None,
                    "procurement_middle_classification_name": None,
                },
            ]

        async def organization_award_history(self, catalog, **kwargs):
            return {}, None

    catalog = RegistryLoader(REGISTRIES).load()
    result = await execute_organization_procurement_profile(
        catalog,
        "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "work_type": "goods"},
        reader=Reader(),
    )
    distribution = {
        item["large_category"]: item for item in result.outcome["field_distribution"]
    }
    assert result.outcome["summary"]["total_attributed_contract_amount"] == 100
    assert (
        sum(item["attributed_contract_amount"] for item in distribution.values()) == 100
    )
    assert distribution["미분류"] == {
        "large_category": "미분류",
        "field_code": None,
        "field_name": None,
        "middle_category": None,
        "detailed_items": [],
        "classification_source": "unclassified",
        "event_count": 1,
        "participation_count": 0,
        "award_event_count": 0,
        "result_confirmed_participation_count": 0,
        "successful_participation_count": 0,
        "award_success_rate": None,
        "contract_event_count": 1,
        "attributed_contract_amount": 80,
        "work_types": ["goods"],
        "amount_share": 0.8,
        "display_level": "unclassified",
        "display_code": None,
        "display_name": "미분류",
        "has_children": False,
        "selection_filter": {"work_type": "goods", "large_category": "미분류"},
    }

    filtered = await execute_organization_procurement_profile(
        catalog,
        "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1",
            "work_type": "goods",
            "large_category": "미분류",
        },
        reader=Reader(),
    )
    assert filtered.outcome["summary"]["total_attributed_contract_amount"] == 80
    assert filtered.outcome["field_distribution_level"] == "unclassified"
    assert (
        filtered.outcome["field_distribution"][0]["classification_source"]
        == "unclassified"
    )


@pytest.mark.asyncio
async def test_profile_splits_unclassified_buckets_by_work_type() -> None:
    class Reader:
        async def activities(self, catalog, **kwargs):
            return [
                {
                    "activity_type": "contract",
                    "event_key": f"C{index}",
                    "bid_notice_id": f"N{index}:000",
                    "notice_name": "미분류 계약",
                    "organization_code": "ORG-1",
                    "organization_name": "기관",
                    "company_number": f"111111111{index}",
                    "company_name": f"업체{index}",
                    "work_type": work_type,
                    "activity_date": date(2025, 1, index),
                    "event_amount": Decimal(str(amount)),
                    "attributed_contract_amount": Decimal(str(amount)),
                    "amount_completeness": "complete",
                    "procurement_classification_number": None,
                    "procurement_classification_name": None,
                    "procurement_large_classification_name": None,
                    "procurement_middle_classification_name": None,
                }
                for index, (work_type, amount) in enumerate(
                    (("goods", 30), ("service", 70)),
                    start=1,
                )
            ]

        async def organization_award_history(self, catalog, **kwargs):
            return {}, None

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(),
        "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1"},
        reader=Reader(),
    )
    buckets = sorted(
        (
            item
            for item in result.outcome["field_distribution"]
            if item["large_category"] == "미분류"
        ),
        key=lambda item: item["work_types"],
    )
    assert [
        (item["work_types"], item["attributed_contract_amount"]) for item in buckets
    ] == [
        (["goods"], 30),
        (["service"], 70),
    ]

    filtered = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(),
        "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "large_category": "미분류"},
        reader=Reader(),
    )
    assert len(filtered.outcome["field_distribution"]) == 2
