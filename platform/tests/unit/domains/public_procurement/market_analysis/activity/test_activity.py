from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from teoria.domains.public_procurement.market_analysis.activity.service import (
    execute_procurement_activity_search,
)
from teoria.registry.loader import RegistryLoader

REGISTRIES = Path(__file__).parents[6] / "registries"


@pytest.mark.asyncio
async def test_procurement_activity_uses_stage_event_period_and_latest_activity_sort() -> (
    None
):
    class Reader:
        async def find(self, catalog, **kwargs):
            classification = {
                "work_type": "service",
                "field_code": "81111599",
                "field_name": "정보시스템개발서비스",
                "large_category": "ICT 서비스",
                "middle_category": "SW 및 시스템 개발",
            }
            notices = [
                {
                    "bid_notice_id": "N1:000",
                    "notice_name": "2023년 게시 사업",
                    "published_at": datetime(2023, 2, 1, tzinfo=timezone.utc),
                    "bid_begin_at": None,
                    "bid_deadline_at": date(2023, 3, 1),
                    "bid_status": "closed",
                    "notice_status": "active",
                    "notice_kind_name": "일반공고",
                    "organization_code": "ORG-1",
                    "organization_name": "기관",
                    **classification,
                },
                {
                    "bid_notice_id": "N2:000",
                    "notice_name": "예정 사업",
                    "published_at": datetime.now(timezone.utc) - timedelta(days=1),
                    "bid_begin_at": datetime.now(timezone.utc) + timedelta(days=1),
                    "bid_deadline_at": datetime.now(timezone.utc) + timedelta(days=2),
                    "bid_status": "scheduled",
                    "notice_status": "active",
                    "notice_kind_name": "일반공고",
                    "organization_code": "ORG-1",
                    "organization_name": "기관",
                    **classification,
                },
            ]
            awards = [
                {
                    "award_id": "N1:000:0:0",
                    "bid_notice_id": "N1:000",
                    "bid_classification_number": "0",
                    "rebid_number": "0",
                    "award_date": date(2024, 1, 1),
                    "winner_name": "수주사",
                    "winner_business_registration_number": "1111111111",
                    "winning_amount": Decimal("90"),
                    "winning_rate": None,
                }
            ]
            contracts = [
                {
                    "contract_event_id": "ROOT-1",
                    "unified_contract_number": "C1",
                    "bid_notice_id": "N1:000",
                    "notice_name": "2023년 게시 사업",
                    "organization_name": "기관",
                    "contract_date": date(2025, 5, 1),
                    "contract_amount": Decimal("100"),
                    "is_joint_contract": False,
                    "supplier_sequence": 1,
                    "business_registration_number": "1111111111",
                    "supplier_name": "수주사",
                    "supplier_role_name": "주계약업체",
                    "participation_share_rate": Decimal("100"),
                    **classification,
                },
                {
                    "contract_event_id": "ROOT-2",
                    "unified_contract_number": "C2",
                    "bid_notice_id": None,
                    "notice_name": "독립 계약",
                    "organization_name": "기관",
                    "contract_date": date(2024, 6, 1),
                    "contract_amount": Decimal("50"),
                    "is_joint_contract": False,
                    "supplier_sequence": 1,
                    "business_registration_number": "2222222222",
                    "supplier_name": "계약사",
                    "supplier_role_name": "주계약업체",
                    "participation_share_rate": Decimal("100"),
                    **classification,
                },
            ]
            return notices, awards, contracts, set()

    catalog = RegistryLoader(REGISTRIES).load()
    first = await execute_procurement_activity_search(
        catalog,
        "search_procurement_activity",
        {
            "organization_code": "ORG-1",
            "period_from_year": 2023,
            "period_to_year": 2026,
            "stage": "all",
            "page": 1,
            "page_size": 2,
        },
        reader=Reader(),
    )
    second = await execute_procurement_activity_search(
        catalog,
        "search_procurement_activity",
        {
            "organization_code": "ORG-1",
            "period_from_year": 2023,
            "period_to_year": 2026,
            "stage": "all",
            "page": 2,
            "page_size": 2,
        },
        reader=Reader(),
    )

    assert first.outcome["pagination"] == {
        "page": 1,
        "page_size": 2,
        "total_items": 3,
        "total_pages": 2,
    }
    assert second.outcome["pagination"]["total_items"] == 3
    assert first.outcome["stage_counts"] == second.outcome["stage_counts"]
    assert first.outcome["stage_counts"]["all"] == 3
    assert first.outcome["linkage_counts"] == {"linked": 2, "unlinked": 1}
    assert (
        sum(
            first.outcome["stage_counts"][key]
            for key in (
                "scheduled",
                "open",
                "closed",
                "award",
                "contract",
                "failed",
                "cancelled",
            )
        )
        == 3
    )
    assert first.outcome["items"][0]["activity_id"] == "N2:000"
    assert first.outcome["items"][0]["stage"] == "open"
    assert first.outcome["items"][1]["activity_id"] == "contract:ROOT-1"
    assert first.outcome["items"][1]["stage"] == "contract"
    assert first.outcome["items"][1]["notice"]["published_at"] == datetime(
        2023,
        2,
        1,
        tzinfo=timezone.utc,
    )
    assert first.outcome["items"][1]["latest_activity_date"] == date(2025, 5, 1)
    assert second.outcome["items"][0]["notice_linkage"] == "unlinked"
    assert first.outcome["analysis_basis"]["period_basis"] == "stage_event_date"
    assert first.outcome["analysis_basis"]["notice_stage_period_basis"] == (
        "notice_published_at"
    )
    assert first.outcome["analysis_basis"]["award_stage_period_basis"] == (
        "final_award_date_or_opening_at"
    )
    assert first.outcome["analysis_basis"]["contract_stage_period_basis"] == (
        "first_contract_date"
    )
    assert first.outcome["analysis_basis"]["bid_begin_at_used_for_stage"] is False


@pytest.mark.asyncio
async def test_procurement_activity_separates_source_confirmed_failure_and_cancellation() -> (
    None
):
    class Reader:
        async def find(self, catalog, **kwargs):
            del catalog, kwargs
            common = {
                "published_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "bid_begin_at": None,
                "bid_deadline_at": date(2026, 1, 2),
                "bid_status": "closed",
                "notice_status": "active",
                "notice_kind_name": "등록공고",
                "organization_code": "ORG-1",
                "organization_name": "기관",
                "work_type": "service",
                "field_code": None,
                "field_name": None,
                "large_category": None,
                "middle_category": None,
            }
            return (
                [
                    {
                        **common,
                        "bid_notice_id": "FAILED:000",
                        "notice_name": "유찰 사업",
                        "current_status": "failed",
                        "current_status_label": "유찰",
                        "failure_reason": "단독입찰",
                        "failure_at": datetime(
                            2026,
                            1,
                            2,
                            tzinfo=timezone.utc,
                        ),
                        "status_source": "pps_bid_result_api.list_failing_opening_results",
                    },
                    {
                        **common,
                        "bid_notice_id": "CANCELLED:001",
                        "notice_name": "취소 사업",
                        "notice_status": "cancelled",
                        "current_status": "cancelled",
                        "current_status_label": "취소",
                        "cancellation_reason": "사업계획 변경",
                        "cancellation_at": datetime(2026, 1, 3, tzinfo=timezone.utc),
                        "status_source": "pps_bid_notice_api.notice_kind_name",
                    },
                ],
                [],
                [],
                set(),
            )

    result = await execute_procurement_activity_search(
        RegistryLoader(REGISTRIES).load(),
        "search_procurement_activity",
        {
            "organization_code": "ORG-1",
            "period_from_year": 2026,
            "period_to_year": 2026,
            "stage": "all",
            "view_mode": "notice_grouped",
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )

    assert result.outcome["stage_counts"]["failed"] == 1
    assert result.outcome["stage_counts"]["cancelled"] == 1
    assert result.outcome["stage_counts"]["all"] == 2
    by_stage = {item["latest_stage"]: item for item in result.outcome["items"]}
    assert by_stage["failed"]["notice"]["failure_reason"] == "단독입찰"
    assert by_stage["cancelled"]["notice"]["cancellation_reason"] == "사업계획 변경"


@pytest.mark.asyncio
async def test_procurement_activity_returns_one_contract_record_per_contract_event() -> (
    None
):
    class Reader:
        async def find(self, catalog, **kwargs):
            classification = {
                "work_type": "service",
                "field_code": "81111599",
                "field_name": "정보시스템개발서비스",
                "large_category": "ICT 서비스",
                "middle_category": "SW 및 시스템 개발",
            }
            contracts = []
            for event_id, unified_number, first_date, latest_date, amount in (
                ("EVENT-1", "C1-V2", date(2024, 2, 1), date(2024, 11, 1), 130),
                ("EVENT-2", "C2", date(2024, 7, 1), date(2024, 7, 1), 80),
            ):
                contracts.append(
                    {
                        "contract_event_id": event_id,
                        "unified_contract_number": unified_number,
                        "bid_notice_id": "OLD:000",
                        "notice_name": "기간 이전 게시 공고의 계약",
                        "organization_name": "기관",
                        "first_contract_date": first_date,
                        "contract_date": latest_date,
                        "contract_amount": Decimal(amount),
                        "contract_version_count": 2 if event_id == "EVENT-1" else 1,
                        "is_joint_contract": False,
                        "supplier_sequence": 1,
                        "business_registration_number": "1111111111",
                        "supplier_name": "계약사",
                        "supplier_role_name": "주계약업체",
                        "participation_share_rate": Decimal("100"),
                        **classification,
                    }
                )
            return [], [], contracts, set()

    result = await execute_procurement_activity_search(
        RegistryLoader(REGISTRIES).load(),
        "search_procurement_activity",
        {
            "organization_code": "ORG-1",
            "period_from_year": 2024,
            "period_to_year": 2024,
            "stage": "contract",
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )

    assert result.outcome["pagination"]["total_items"] == 2
    assert result.outcome["stage_counts"]["contract"] == 2
    assert {item["activity_id"] for item in result.outcome["items"]} == {
        "contract:EVENT-1",
        "contract:EVENT-2",
    }
    by_id = {item["activity_id"]: item for item in result.outcome["items"]}
    assert by_id["contract:EVENT-1"]["latest_activity_date"] == date(2024, 2, 1)
    assert by_id["contract:EVENT-1"]["contract"]["contract_date"] == date(2024, 11, 1)
    assert by_id["contract:EVENT-1"]["contract"]["contract_version_count"] == 2
    assert by_id["contract:EVENT-1"]["notice_linkage"] == "linked"
    assert result.outcome["analysis_basis"]["deduplication"]["contract"] == (
        "merged_by_contract_event"
    )


@pytest.mark.asyncio
async def test_procurement_activity_notice_grouped_groups_before_pagination() -> None:
    class Reader:
        async def find(self, catalog, **kwargs):
            classification = {
                "work_type": "service",
                "field_code": "81111599",
                "field_name": "정보시스템개발서비스",
                "large_category": "ICT 서비스",
                "middle_category": "SW 및 시스템 개발",
            }
            common_notice = {
                "published_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "bid_begin_at": None,
                "bid_deadline_at": date(2024, 1, 31),
                "bid_status": "closed",
                "notice_status": "active",
                "notice_kind_name": "일반공고",
                "organization_code": "ORG-1",
                "organization_name": "기관",
                "allocated_budget": None,
                "estimated_price": Decimal("600"),
                "base_amount": Decimal("500"),
                **classification,
            }
            notices = [
                {
                    **common_notice,
                    "bid_notice_id": "N1:000",
                    "notice_name": "같은 이름의 사업",
                },
                {
                    **common_notice,
                    "bid_notice_id": "N2:000",
                    "notice_name": "같은 이름의 사업",
                },
            ]
            awards = [
                {
                    "award_id": "A1",
                    "bid_notice_id": "N1:000",
                    "bid_classification_number": "0",
                    "rebid_number": "0",
                    "award_date": date(2024, 2, 1),
                    "winner_name": "낙찰사",
                    "winner_business_registration_number": "1111111111",
                    "winning_amount": Decimal("90"),
                    "winning_rate": None,
                }
            ]
            contracts = [
                {
                    "contract_event_id": "EVENT-1",
                    "unified_contract_number": "C1-V2",
                    "confirmed_contract_number": "SOURCE-1",
                    "contract_reference_number": "SOURCE-1",
                    "contract_name": "같은 이름의 사업(1차)",
                    "long_term_continuation_type": "장기",
                    "total_amount": Decimal("1000"),
                    "total_amount_currency": "KRW",
                    "current_contract_amount_currency": "KRW",
                    "bid_notice_id": "N1:000",
                    "notice_name": "같은 이름의 사업",
                    "organization_name": "기관",
                    "first_contract_date": date(2024, 3, 1),
                    "contract_date": date(2024, 10, 1),
                    "contract_amount": Decimal("0"),
                    "contract_version_count": 2,
                    "is_joint_contract": False,
                    "supplier_sequence": 1,
                    "business_registration_number": "1111111111",
                    "supplier_name": "첫째계약사",
                    "supplier_role_name": "주계약업체",
                    "participation_share_rate": Decimal("100"),
                    **classification,
                },
                {
                    "contract_event_id": "EVENT-2",
                    "unified_contract_number": "C2",
                    "confirmed_contract_number": "SOURCE-2",
                    "contract_reference_number": "SOURCE-2",
                    "contract_name": "같은 이름의 사업(2차)",
                    "long_term_continuation_type": "장기",
                    "total_amount": Decimal("1000"),
                    "total_amount_currency": "KRW",
                    "current_contract_amount_currency": "KRW",
                    "bid_notice_id": "N1:000",
                    "notice_name": "같은 이름의 사업",
                    "organization_name": "기관",
                    "first_contract_date": date(2024, 8, 1),
                    "contract_date": date(2024, 8, 1),
                    "contract_amount": None,
                    "contract_version_count": 1,
                    "is_joint_contract": False,
                    "supplier_sequence": 1,
                    "business_registration_number": "2222222222",
                    "supplier_name": "둘째계약사",
                    "supplier_role_name": "주계약업체",
                    "participation_share_rate": Decimal("100"),
                    **classification,
                },
                {
                    "contract_event_id": "EVENT-3",
                    "unified_contract_number": "C3",
                    "confirmed_contract_number": "SOURCE-3",
                    "contract_reference_number": "SOURCE-3",
                    "contract_name": "미연결 계약",
                    "long_term_continuation_type": "신규",
                    "total_amount": Decimal("70"),
                    "total_amount_currency": "KRW",
                    "current_contract_amount_currency": "KRW",
                    "bid_notice_id": None,
                    "notice_name": "미연결 계약",
                    "organization_name": "기관",
                    "first_contract_date": date(2024, 7, 1),
                    "contract_date": date(2024, 7, 1),
                    "contract_amount": Decimal("70"),
                    "contract_version_count": 1,
                    "is_joint_contract": False,
                    "supplier_sequence": 1,
                    "business_registration_number": "3333333333",
                    "supplier_name": "독립계약사",
                    "supplier_role_name": "주계약업체",
                    "participation_share_rate": Decimal("100"),
                    **classification,
                },
            ]
            return notices, awards, contracts, set()

    catalog = RegistryLoader(REGISTRIES).load()
    common_inputs = {
        "organization_code": "ORG-1",
        "period_from_year": 2024,
        "period_to_year": 2024,
        "stage": "all",
        "view_mode": "notice_grouped",
        "page_size": 1,
    }
    first = await execute_procurement_activity_search(
        catalog,
        "search_procurement_activity",
        {**common_inputs, "page": 1},
        reader=Reader(),
    )
    second = await execute_procurement_activity_search(
        catalog,
        "search_procurement_activity",
        {**common_inputs, "page": 2},
        reader=Reader(),
    )
    all_groups = await execute_procurement_activity_search(
        catalog,
        "search_procurement_activity",
        {
            **common_inputs,
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )

    assert first.outcome["pagination"] == {
        "page": 1,
        "page_size": 1,
        "total_items": 3,
        "total_pages": 3,
    }
    assert first.outcome["stage_counts"] == {
        "scheduled": 0,
        "open": 0,
        "closed": 1,
        "award": 0,
        "contract": 2,
        "failed": 0,
        "cancelled": 0,
        "all": 3,
    }
    assert (
        sum(
            first.outcome["stage_counts"][stage]
            for stage in (
                "scheduled",
                "open",
                "closed",
                "award",
                "contract",
                "failed",
                "cancelled",
            )
        )
        == first.outcome["stage_counts"]["all"]
    )
    assert first.outcome["items"][0]["activity_group_id"] == "notice:N1:000"
    assert second.outcome["items"][0]["activity_group_id"] == "contract:EVENT-3"
    assert (
        first.outcome["items"][0]["activity_group_id"]
        != second.outcome["items"][0]["activity_group_id"]
    )
    assert {item["activity_group_id"] for item in all_groups.outcome["items"]} == {
        "notice:N1:000",
        "notice:N2:000",
        "contract:EVENT-3",
    }
    independent = next(
        item
        for item in all_groups.outcome["items"]
        if item["activity_group_id"] == "contract:EVENT-3"
    )["contracts"][0]
    assert independent["contract_family_id"] == "contract-family:EVENT-3"
    assert independent["contract_structure"] == "single"
    assert independent["contract_record_type"] == "independent"
    assert independent["relationship_status"] == "confirmed"
    assert independent["relationship_basis"]["contract_event_identity"] == {
        "field": "confirmed_contract_number",
        "value": "SOURCE-3",
    }
    group = first.outcome["items"][0]
    assert group["latest_stage"] == "contract"
    assert group["notice"] == {
        "notice_name": "같은 이름의 사업",
        "published_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "bid_begin_at": None,
        "deadline_at": date(2024, 1, 31),
        "status": "closed",
        "notice_status": "active",
        "work_type": "service",
        "current_status": None,
        "current_status_label": None,
        "cancellation_reason": None,
        "cancellation_at": None,
        "failure_reason": None,
        "failure_at": None,
        "status_source": None,
        "status_confirmed_at": None,
        "original_notice_id": None,
        "current_notice_id": None,
        "revision_number": None,
        "is_latest_revision": None,
        "project_amount": 600,
        "project_amount_basis": "estimated_price",
        "project_amount_basis_name": "추정가격",
    }
    assert group["result_summary"] == {
        "award_count": 1,
        "contract_event_count": 2,
        "contract_version_count": 3,
        "effective_contract_amount": 1000,
        "effective_contract_event_id": "EVENT-2",
        "included_contract_event_ids": ["EVENT-2"],
        "latest_confirmed_contract_amount": None,
        "latest_confirmed_contract_event_id": None,
        "contract_family_count": 1,
        "included_contract_family_count": 1,
        "amount_aggregation_status": "partially_confirmed",
        "amount_aggregation_reason": "inferred_contract_family_relationship",
    }
    by_contract = {item["contract_event_id"]: item for item in group["contracts"]}
    assert by_contract["EVENT-1"]["first_contract_date"] == date(2024, 3, 1)
    assert by_contract["EVENT-1"]["latest_contract_version_date"] == date(
        2024,
        10,
        1,
    )
    assert by_contract["EVENT-1"]["current_contract_amount"] == 0
    assert by_contract["EVENT-1"]["contract_version_count"] == 2
    assert by_contract["EVENT-2"]["current_contract_amount"] is None
    assert by_contract["EVENT-1"]["contract_structure"] == "long_term_continuing"
    assert by_contract["EVENT-1"]["contract_record_type"] == "original"
    assert by_contract["EVENT-1"]["phase_number"] == 1
    assert by_contract["EVENT-1"]["parent_contract_event_id"] is None
    assert by_contract["EVENT-1"]["original_contract_event_id"] == "EVENT-1"
    assert by_contract["EVENT-1"]["total_contract_amount"] == 1000
    assert by_contract["EVENT-1"]["phase_contract_amount"] == 0
    assert by_contract["EVENT-1"]["amount_tax_basis"] == "unknown"
    assert by_contract["EVENT-1"]["relationship_status"] == "inferred"
    assert (
        by_contract["EVENT-2"]["contract_family_id"]
        == (by_contract["EVENT-1"]["contract_family_id"])
    )
    assert by_contract["EVENT-2"]["contract_record_type"] == "phase"
    assert by_contract["EVENT-2"]["phase_number"] == 2
    assert by_contract["EVENT-2"]["parent_contract_event_id"] == "EVENT-1"
    assert by_contract["EVENT-2"]["original_contract_event_id"] == "EVENT-1"
    assert by_contract["EVENT-2"]["relationship_status"] == "inferred"
    assert by_contract["EVENT-2"]["relationship_basis"]["family_inference"] == {
        "bid_notice_id": "N1:000",
        "long_term_continuation_type": "장기",
        "normalized_contract_name": "같은 이름의 사업",
        "phase_marker": 2,
        "parent_link_basis": "same_inferred_family_with_phase_marker",
    }
    assert first.outcome["grouping_basis"]["linked_group_key"] == "bid_notice_id"
    assert first.outcome["analysis_basis"]["view_mode"] == "notice_grouped"

    flat = await execute_procurement_activity_search(
        catalog,
        "search_procurement_activity",
        {
            "organization_code": "ORG-1",
            "period_from_year": 2024,
            "period_to_year": 2024,
            "stage": "all",
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )
    assert flat.outcome["pagination"]["total_items"] == 4
    assert "grouping_basis" not in flat.outcome
    assert flat.outcome["analysis_basis"]["view_mode"] == "flat"
    assert all(
        "_lineage_source" not in contract
        for item in flat.outcome["items"]
        for contract in item["contracts"]
    )


@pytest.mark.asyncio
async def test_procurement_activity_contract_filter_uses_profile_field_identity() -> (
    None
):
    class Reader:
        async def find(self, catalog, **kwargs):
            notices = [
                {
                    "bid_notice_id": "N1:000",
                    "notice_name": "연결 공고",
                    "published_at": date(2024, 1, 1),
                    "bid_begin_at": None,
                    "bid_deadline_at": date(2024, 1, 31),
                    "bid_status": "closed",
                    "notice_status": "active",
                    "organization_name": "기관",
                    "work_type": "service",
                    "field_code": "NOTICE-FIELD",
                    "field_name": "일반용역",
                    "large_category": "일반용역",
                    "middle_category": None,
                }
            ]
            contracts = [
                {
                    "contract_event_id": "EVENT-1",
                    "unified_contract_number": "C1",
                    "bid_notice_id": "N1:000",
                    "notice_name": "연결 공고",
                    "organization_name": "기관",
                    "first_contract_date": date(2024, 2, 1),
                    "contract_date": date(2024, 2, 1),
                    "contract_amount": Decimal("100"),
                    "contract_version_count": 1,
                    "is_joint_contract": False,
                    "supplier_sequence": 1,
                    "business_registration_number": "1111111111",
                    "supplier_name": "계약사",
                    "supplier_role_name": "주계약업체",
                    "participation_share_rate": Decimal("100"),
                    "work_type": "service",
                    "procurement_classification_number": "TECH-1",
                    "procurement_classification_name": "엔지니어링서비스",
                    "procurement_large_classification_name": "기술용역",
                    "procurement_middle_classification_name": "설계용역",
                    "purchase_items": [],
                }
            ]
            return notices, [], contracts, set()

    result = await execute_procurement_activity_search(
        RegistryLoader(REGISTRIES).load(),
        "search_procurement_activity",
        {
            "organization_code": "ORG-1",
            "period_from_year": 2024,
            "period_to_year": 2024,
            "stage": "contract",
            "work_type": "service",
            "large_category": "기술용역",
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )

    assert result.outcome["pagination"]["total_items"] == 1
    assert result.outcome["items"][0]["field_code"] == "TECH-1"
    assert result.outcome["items"][0]["large_category"] == "기술용역"


@pytest.mark.asyncio
async def test_procurement_activity_selects_display_project_amount_by_source_priority() -> (
    None
):
    class Reader:
        async def find(self, catalog, **kwargs):
            common = {
                "published_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                "bid_begin_at": None,
                "bid_deadline_at": date(2025, 1, 31),
                "bid_status": "closed",
                "notice_status": "active",
                "notice_kind_name": "일반공고",
                "organization_code": "ORG-1",
                "organization_name": "기관",
                "work_type": "service",
                "field_code": None,
                "field_name": None,
                "large_category": None,
                "middle_category": None,
            }
            notices = [
                {
                    **common,
                    "bid_notice_id": "BUDGET:000",
                    "notice_name": "예산 공고",
                    "allocated_budget": Decimal("120"),
                    "estimated_price": Decimal("110"),
                    "base_amount": Decimal("100"),
                },
                {
                    **common,
                    "bid_notice_id": "ESTIMATED:000",
                    "notice_name": "추정가격 공고",
                    "allocated_budget": None,
                    "estimated_price": Decimal("210"),
                    "base_amount": Decimal("200"),
                },
                {
                    **common,
                    "bid_notice_id": "BASE:000",
                    "notice_name": "기초금액 공고",
                    "allocated_budget": None,
                    "estimated_price": None,
                    "base_amount": Decimal("300"),
                },
                {
                    **common,
                    "bid_notice_id": "EMPTY:000",
                    "notice_name": "금액 없는 공고",
                    "allocated_budget": None,
                    "estimated_price": None,
                    "base_amount": None,
                },
            ]
            contracts = [
                {
                    "contract_event_id": "ROOT-1",
                    "unified_contract_number": "C1",
                    "bid_notice_id": None,
                    "notice_name": "독립 계약",
                    "organization_name": "기관",
                    "contract_date": date(2025, 2, 1),
                    "contract_amount": Decimal("400"),
                    "is_joint_contract": False,
                    "supplier_sequence": 1,
                    "business_registration_number": "1111111111",
                    "supplier_name": "계약사",
                    "supplier_role_name": "주계약업체",
                    "participation_share_rate": Decimal("100"),
                    "work_type": "service",
                    "field_code": None,
                    "field_name": None,
                    "large_category": None,
                    "middle_category": None,
                }
            ]
            return notices, [], contracts, set()

    result = await execute_procurement_activity_search(
        RegistryLoader(REGISTRIES).load(),
        "search_procurement_activity",
        {
            "organization_code": "ORG-1",
            "period_from_year": 2025,
            "period_to_year": 2025,
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )

    by_id = {item["activity_id"]: item for item in result.outcome["items"]}
    assert (
        by_id["BUDGET:000"]["project_amount"],
        by_id["BUDGET:000"]["project_amount_basis"],
        by_id["BUDGET:000"]["project_amount_basis_name"],
    ) == (120, "allocated_budget", "배정예산")
    assert by_id["BUDGET:000"]["notice"]["estimated_price"] == 110
    assert by_id["ESTIMATED:000"]["project_amount"] == 210
    assert by_id["ESTIMATED:000"]["project_amount_basis"] == "estimated_price"
    assert by_id["BASE:000"]["project_amount"] == 300
    assert by_id["BASE:000"]["project_amount_basis"] == "base_amount"
    assert by_id["EMPTY:000"]["project_amount"] is None
    assert by_id["EMPTY:000"]["project_amount_basis"] is None
    assert by_id["contract:ROOT-1"]["project_amount"] == 400
    assert by_id["contract:ROOT-1"]["project_amount_basis"] == "contract_amount"
    assert by_id["contract:ROOT-1"]["project_amount_basis_name"] == "계약금액"
