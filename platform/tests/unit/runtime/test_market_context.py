from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from teoria.registry.loader import RegistryLoader
from teoria.runtime.capability.runner import CapabilityExecutionError, CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.market_context.processor import (
    _organization_field_event_analysis,
    _industry_license_eligibility,
    execute_bid_project_lineage,
    execute_bid_notice_relationship_context,
    execute_company_procurement_profile,
    execute_organization_procurement_profile,
    execute_organization_company_field_relationship,
    execute_organization_company_relationship,
    execute_company_similar_project_experience,
    enrich_contract_search_objects,
    execute_procurement_outcome_search,
    execute_procurement_activity_search,
    execute_organization_field_companies,
    execute_bid_relevant_companies,
    execute_similar_bid_notices,
)
from teoria.runtime.provenance import Provenance


REGISTRIES = Path(__file__).parents[3] / "registries"


class RelevantCompanyReader:
    def find_relevant(self, catalog, bid_notice_id, similar_bid_notice_ids, *, limit):
        assert similar_bid_notice_ids == ["R25SIMILAR:000"]
        return ({
            "bid_notice_id": bid_notice_id,
            "notice_number": "R26TEST",
            "notice_order": "000",
            "work_type": "service",
            "demand_organization_code": "ORG-1",
            "demand_organization_name": "테스트기관",
            "requirement_expression": None,
            "extraction_completeness": "complete",
            "bid_deadline_at": datetime(2026, 9, 30, tzinfo=timezone.utc),
            "as_of": datetime(2026, 9, 22, tzinfo=timezone.utc),
        }, [{
            "company_number": "1234567890",
            "company_name": "스마트이앤씨",
            "similar_participation_count": 1,
            "similar_award_count": 1,
            "similar_contract_count": 0,
            "similar_unified_contract_count": 0,
            "similar_award_amount": Decimal("980000000"),
            "similar_contract_amount": None,
            "similar_contract_amount_complete": True,
            "participation_notice_ids": ["R25SIMILAR:000"],
            "award_notice_ids": ["R25SIMILAR:000"],
            "contract_notice_ids": [],
            "similar_first_activity_date": date(2025, 6, 1),
            "similar_latest_activity_date": date(2025, 6, 2),
            "organization_participation_count": 7,
            "organization_award_count": 2,
            "organization_contract_count": 2,
            "organization_unified_contract_count": 3,
            "organization_contract_amount": Decimal("640000000"),
            "contract_amount_complete": True,
            "organization_first_activity_date": date(2022, 4, 11),
            "organization_latest_activity_date": date(2026, 6, 18),
            "organization_activities": [{
                "bid_notice_id": "R24ORGANIZATION:000",
                "notice_name": "기관 정보시스템 운영 사업",
                "notice_published_date": date(2024, 2, 20),
                "bid_classification_number": "0",
                "rebid_number": "0",
                "opening_rank": 3,
                "bid_amount": Decimal("32418000"),
                "result": "not_awarded",
                "activity_date": date(2024, 3, 15),
            }],
            "similar_activities": [{
                "bid_notice_id": "R25SIMILAR:000",
                "bid_classification_number": "0",
                "rebid_number": "0",
                "opening_rank": 1,
                "bid_amount": Decimal("980000000"),
                "winning_amount": Decimal("980000000"),
                "result": "awarded",
                "activity_date": date(2025, 6, 2),
                "unified_contract_number": None,
            }],
        }], [{"region_code": "11", "region_name": "서울특별시", "business_type_name": None}], [{
            "requirement_id": "req-industry-1",
            "bid_notice_id": bid_notice_id,
            "local_id": "industry-1",
            "requirement_type": "industry_license",
            "value_text": '{"text":"소프트웨어사업자","attributes":[{"name":"industry_code","value":"1468"},{"name":"industry_name","value":"소프트웨어사업자"}]}',
            "original_text": "소프트웨어사업자(1468) 등록 업체",
            "mandatory": True,
            "review_status": "resolved",
            "assessment_stage": "bid_entry",
            "standard_rule_id": "has_registered_industry",
            "standard_rule_version": "1.0.0",
            "rule_arguments_text": '{"expected_value":"1468"}',
        }])


class SupplierRunner:
    async def run(self, catalog, capability_id, inputs):
        provenance = Provenance(
            kind="source", source="pps_user", operation="list_procurement_companies",
            mapping="pps_user", observed_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
            record_keys=[inputs["business_registration_number"]],
        )
        if capability_id == "get_procurement_supplier":
            object_type = "procurement_supplier"
            properties = {
                "business_registration_number": inputs["business_registration_number"],
                "company_name": "스마트이앤씨",
                "region_code": "11",
                "region_name": "서울특별시",
                "base_address": "서울특별시 중구",
                "head_office_type_name": "본사",
            }
        else:
            assert capability_id == "get_procurement_supplier_industries"
            object_type = "registered_industry"
            properties = {
                "business_registration_number": inputs["business_registration_number"],
                "industry_code": "1468",
                "industry_name": "소프트웨어사업자(컴퓨터관련서비스사업)",
                "status_name": "등록",
                "registered_at": date(2020, 1, 1),
            }
        return CapabilityResult(capability_id=capability_id, objects=[MaterializedObject(
            ontology="public_procurement", object_type=object_type,
            object_id=f"{object_type}:1", properties=properties, provenance=[provenance],
            property_provenance={key: [provenance] for key in properties},
        )])


class SimilarNoticeReader:
    def find(self, catalog, bid_notice_id, *, period_years, result_statuses):
        assert period_years == 5
        assert result_statuses == ["awarded", "contracted"]
        notice = {
            "bid_notice_id": bid_notice_id,
            "notice_name": "정보시스템 구축 및 유지관리 사업",
            "notice_published_date": date(2026, 9, 1),
            "work_type": "service", "contract_method_name": "일반경쟁",
            "estimated_price": Decimal("200000000"), "allocated_budget": None,
            "demand_organization_code": "ORG-1", "demand_organization_name": "기관",
            "industry_codes": ["1468", "0036"],
            "industries": [
                {"industry_code": "1468", "industry_name": "소프트웨어사업자"},
                {"industry_code": "0036", "industry_name": "정보통신공사업"},
            ],
            "as_of": datetime(2026, 9, 23, tzinfo=timezone.utc),
        }
        rows = [{
            "bid_notice_id": "R25SIMILAR:000", "notice_number": "R25SIMILAR",
            "notice_order": "000", "notice_name": "정보시스템 구축 및 유지관리",
            "notice_published_date": date(2025, 7, 15),
            "work_type": "service", "contract_method_name": "일반경쟁",
            "estimated_price": Decimal("190000000"), "allocated_budget": None,
            "demand_organization_code": "ORG-2", "demand_organization_name": "과거기관",
            "industry_codes": ["1468", "0036"],
            "title_trigram_score": Decimal("0.9"),
            "winner_business_registration_number": "1234567890",
            "winner_name": "스마트이앤씨", "winning_amount": Decimal("170000000"),
            "winning_rate": Decimal("89.5"), "award_date": date(2025, 8, 1),
        }, {
            "bid_notice_id": "R24ORGFIELD:000", "notice_number": "R24ORGFIELD",
            "notice_order": "000", "notice_name": "소득기반 정보시스템 개선 사업",
            "notice_published_date": date(2024, 5, 10),
            "work_type": "service", "contract_method_name": "제한경쟁",
            "estimated_price": Decimal("700000000"), "allocated_budget": None,
            "demand_organization_code": "ORG-1", "demand_organization_name": "기관",
            "industry_codes": ["1468"], "title_trigram_score": Decimal("0.1"),
            "winner_business_registration_number": "9876543210",
            "winner_name": "과거업체", "winning_amount": Decimal("650000000"),
            "winning_rate": Decimal("92.0"), "award_date": date(2024, 6, 1),
        }]
        return notice, rows


class OrganizationFieldCompanyReader:
    def find_relevant(self, catalog, bid_notice_id, similar_bid_notice_ids, *, limit):
        assert "R24ORGFIELD:000" in similar_bid_notice_ids
        return ({
            "bid_notice_id": bid_notice_id,
            "demand_organization_code": "ORG-1",
            "demand_organization_name": "기관",
        }, [{
            "company_number": "1234567890", "company_name": "기관분야업체",
            "organization_award_count": 5, "organization_contract_count": 4,
            "organization_contract_amount": Decimal("4200000000"),
            "contract_amount_complete": True,
            "organization_latest_activity_date": date(2026, 8, 12),
            "similar_latest_activity_date": date(2024, 6, 1),
            "similar_activities": [],
            "organization_activities": [{
                "bid_notice_id": "20240541416:000",
                "notice_name": "정보시스템 응용프로그램(보험부문) 유지관리 위탁사업",
                "bid_classification_number": None, "rebid_number": None,
                "bid_amount": Decimal("4344079100"), "result": "contracted",
                "activity_date": date(2025, 3, 11),
                "unified_contract_number": "R25TE01912869",
            }],
        }], [], [])


class OrganizationFieldEventReader:
    def find(self, catalog, *, organization_code, work_type, as_of):
        return [{
            "source_kind": "award", "notice_number": "R25EVENT",
            "notice_order": "000", "bid_classification_number": "0",
            "rebid_number": "0", "bid_notice_id": "R25EVENT:000",
            "notice_name": "정보시스템 구축", "event_date": date(2025, 3, 1),
            "notice_published_date": date(2025, 2, 20),
            "event_amount": Decimal("200000000"),
            "company_number": "1234567890", "company_name": "기관분야업체",
        }]

    def context(self, catalog, *, organization_code, business_registration_number,
                reference_bid_notice_id):
        return {
            "organization": {
                "organization_code": organization_code, "organization_name": "기관",
            },
            "company": {
                "business_registration_number": business_registration_number,
                "company_name": "기관분야업체",
            },
            "reference_notice": {
                "bid_notice_id": reference_bid_notice_id,
                "notice_name": "정보시스템 구축 및 유지관리 사업",
                "work_type": "service", "estimated_price": Decimal("200000000"),
                "allocated_budget": None, "industry_codes": ["1468", "0036"],
                "as_of": datetime(2026, 9, 23, tzinfo=timezone.utc),
            } if reference_bid_notice_id else None,
        }


@pytest.mark.asyncio
async def test_procurement_outcome_search_merges_awards_contracts_and_paginates() -> None:
    class Reader:
        def find(self, catalog, *, organization_code, period_from, period_to):
            assert organization_code == "ORG-1"
            assert period_from == date(2025, 1, 1)
            assert period_to == date(2026, 1, 1)
            classification = {
                "work_type": "service", "field_code": "81111599",
                "field_name": "정보시스템개발서비스", "large_category": "ICT 서비스",
                "middle_category": "SW 및 시스템 개발",
            }
            awards = [{
                "award_id": "N1:000:0:0", "bid_notice_id": "N1:000",
                "bid_classification_number": "0", "rebid_number": "0",
                "notice_name": "정보시스템 구축", "organization_name": "기관",
                "award_date": date(2025, 3, 1), "winner_name": "낙찰사",
                "winner_business_registration_number": "1111111111",
                "winning_amount": Decimal("90"), "winning_rate": Decimal("87.4"),
                **classification,
            }, {
                "award_id": "N2:000:0:0", "bid_notice_id": "N2:000",
                "bid_classification_number": "0", "rebid_number": "0",
                "notice_name": "정보시스템 운영", "organization_name": "기관",
                "award_date": date(2025, 5, 1), "winner_name": "낙찰전용",
                "winner_business_registration_number": "2222222222",
                "winning_amount": Decimal("80"), "winning_rate": None,
                **classification,
            }]
            contracts = []
            for unified_number, contract_date, amount in (
                ("C1-OLD", date(2024, 4, 1), Decimal("95")),
                ("C1-NEW", date(2025, 4, 1), Decimal("100")),
            ):
                for sequence, number, name, role, share in (
                    (1, "1111111111", "대표사", "주계약업체", Decimal("60")),
                    (2, "3333333333", "구성사", "도급업체", Decimal("40")),
                ):
                    contracts.append({
                        "contract_event_id": "ROOT-C1",
                        "unified_contract_number": unified_number,
                        "bid_notice_id": "N1:000", "notice_name": "정보시스템 구축",
                        "organization_name": "기관", "contract_date": contract_date,
                        "contract_amount": amount, "is_joint_contract": True,
                        "supplier_sequence": sequence,
                        "business_registration_number": number, "supplier_name": name,
                        "supplier_role_name": role, "participation_share_rate": share,
                        **classification,
                    })
            return awards, contracts

    result = await execute_procurement_outcome_search(
        RegistryLoader(REGISTRIES).load(), "search_procurement_outcomes", {
            "organization_code": "ORG-1", "period_from_year": 2025,
            "period_to_year": 2025, "work_type": "service",
            "large_category": "ICT 서비스", "query": "정보시스템",
            "page": 1, "page_size": 20,
        }, reader=Reader(),
    )

    assert result.outcome["pagination"]["total_items"] == 2
    by_id = {item["outcome_id"]: item for item in result.outcome["items"]}
    assert by_id["N1:000"]["stage"] == "contract"
    assert by_id["N1:000"]["latest_activity_date"] == date(2025, 4, 1)
    assert by_id["N1:000"]["contract"]["contract_version_count"] == 2
    assert by_id["N1:000"]["contract"]["contract_amount"] == 100
    assert by_id["N1:000"]["contract"]["lead_contractor"]["company_name"] == "대표사"
    assert by_id["N1:000"]["contract"]["contractor_count"] == 2
    assert len(by_id["N1:000"]["contracts"]) == 1
    assert len(by_id["N1:000"]["awards"]) == 1
    assert by_id["N2:000"]["stage"] == "award"
    assert len(result.objects) == 2


@pytest.mark.asyncio
async def test_procurement_activity_uses_publication_period_and_latest_activity_sort() -> None:
    class Reader:
        def find(self, catalog, **kwargs):
            classification = {
                "work_type": "service", "field_code": "81111599",
                "field_name": "정보시스템개발서비스", "large_category": "ICT 서비스",
                "middle_category": "SW 및 시스템 개발",
            }
            notices = [{
                "bid_notice_id": "N1:000", "notice_name": "2023년 게시 사업",
                "published_at": datetime(2023, 2, 1, tzinfo=timezone.utc), "bid_begin_at": None,
                "bid_deadline_at": date(2023, 3, 1), "bid_status": "closed",
                "notice_status": "active", "notice_kind_name": "일반공고",
                "organization_code": "ORG-1", "organization_name": "기관",
                **classification,
            }, {
                "bid_notice_id": "N2:000", "notice_name": "예정 사업",
                "published_at": datetime.now(timezone.utc) - timedelta(days=1),
                "bid_begin_at": datetime.now(timezone.utc) + timedelta(days=1),
                "bid_deadline_at": datetime.now(timezone.utc) + timedelta(days=2),
                "bid_status": "scheduled",
                "notice_status": "active", "notice_kind_name": "일반공고",
                "organization_code": "ORG-1", "organization_name": "기관",
                **classification,
            }]
            awards = [{
                "award_id": "N1:000:0:0", "bid_notice_id": "N1:000",
                "bid_classification_number": "0", "rebid_number": "0",
                "award_date": date(2024, 1, 1), "winner_name": "수주사",
                "winner_business_registration_number": "1111111111",
                "winning_amount": Decimal("90"), "winning_rate": None,
            }]
            contracts = [{
                "contract_event_id": "ROOT-1", "unified_contract_number": "C1",
                "bid_notice_id": "N1:000", "notice_name": "2023년 게시 사업",
                "organization_name": "기관", "contract_date": date(2025, 5, 1),
                "contract_amount": Decimal("100"), "is_joint_contract": False,
                "supplier_sequence": 1, "business_registration_number": "1111111111",
                "supplier_name": "수주사", "supplier_role_name": "주계약업체",
                "participation_share_rate": Decimal("100"), **classification,
            }, {
                "contract_event_id": "ROOT-2", "unified_contract_number": "C2",
                "bid_notice_id": None, "notice_name": "독립 계약",
                "organization_name": "기관", "contract_date": date(2024, 6, 1),
                "contract_amount": Decimal("50"), "is_joint_contract": False,
                "supplier_sequence": 1, "business_registration_number": "2222222222",
                "supplier_name": "계약사", "supplier_role_name": "주계약업체",
                "participation_share_rate": Decimal("100"), **classification,
            }]
            return notices, awards, contracts, set()

    catalog = RegistryLoader(REGISTRIES).load()
    first = await execute_procurement_activity_search(
        catalog, "search_procurement_activity", {
            "organization_code": "ORG-1", "period_from_year": 2023,
            "period_to_year": 2026, "stage": "all", "page": 1, "page_size": 2,
        }, reader=Reader(),
    )
    second = await execute_procurement_activity_search(
        catalog, "search_procurement_activity", {
            "organization_code": "ORG-1", "period_from_year": 2023,
            "period_to_year": 2026, "stage": "all", "page": 2, "page_size": 2,
        }, reader=Reader(),
    )

    assert first.outcome["pagination"] == {
        "page": 1, "page_size": 2, "total_items": 3, "total_pages": 2,
    }
    assert second.outcome["pagination"]["total_items"] == 3
    assert first.outcome["stage_counts"] == second.outcome["stage_counts"]
    assert first.outcome["stage_counts"]["all"] == 3
    assert first.outcome["linkage_counts"] == {"linked": 2, "unlinked": 1}
    assert sum(first.outcome["stage_counts"][key] for key in (
        "scheduled", "open", "closed", "award", "contract", "failed_or_cancelled",
    )) == 3
    assert first.outcome["items"][0]["activity_id"] == "N2:000"
    assert first.outcome["items"][0]["stage"] == "open"
    assert first.outcome["items"][1]["activity_id"] == "N1:000"
    assert first.outcome["items"][1]["stage"] == "contract"
    assert first.outcome["items"][1]["notice"]["published_at"] == datetime(
        2023, 2, 1, tzinfo=timezone.utc,
    )
    assert first.outcome["items"][1]["latest_activity_date"] == date(2025, 5, 1)
    assert second.outcome["items"][0]["notice_linkage"] == "unlinked"
    assert first.outcome["analysis_basis"]["period_basis"] == "notice_published_at"
    assert first.outcome["analysis_basis"]["bid_begin_at_used_for_stage"] is False


@pytest.mark.asyncio
async def test_procurement_activity_selects_display_project_amount_by_source_priority() -> None:
    class Reader:
        def find(self, catalog, **kwargs):
            common = {
                "published_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                "bid_begin_at": None, "bid_deadline_at": date(2025, 1, 31),
                "bid_status": "closed", "notice_status": "active",
                "notice_kind_name": "일반공고", "organization_code": "ORG-1",
                "organization_name": "기관", "work_type": "service",
                "field_code": None, "field_name": None, "large_category": None,
                "middle_category": None,
            }
            notices = [{
                **common, "bid_notice_id": "BUDGET:000", "notice_name": "예산 공고",
                "allocated_budget": Decimal("120"),
                "estimated_price": Decimal("110"), "base_amount": Decimal("100"),
            }, {
                **common, "bid_notice_id": "ESTIMATED:000", "notice_name": "추정가격 공고",
                "allocated_budget": None, "estimated_price": Decimal("210"),
                "base_amount": Decimal("200"),
            }, {
                **common, "bid_notice_id": "BASE:000", "notice_name": "기초금액 공고",
                "allocated_budget": None, "estimated_price": None,
                "base_amount": Decimal("300"),
            }, {
                **common, "bid_notice_id": "EMPTY:000", "notice_name": "금액 없는 공고",
                "allocated_budget": None, "estimated_price": None, "base_amount": None,
            }]
            contracts = [{
                "contract_event_id": "ROOT-1", "unified_contract_number": "C1",
                "bid_notice_id": None, "notice_name": "독립 계약",
                "organization_name": "기관", "contract_date": date(2025, 2, 1),
                "contract_amount": Decimal("400"), "is_joint_contract": False,
                "supplier_sequence": 1, "business_registration_number": "1111111111",
                "supplier_name": "계약사", "supplier_role_name": "주계약업체",
                "participation_share_rate": Decimal("100"), "work_type": "service",
                "field_code": None, "field_name": None, "large_category": None,
                "middle_category": None,
            }]
            return notices, [], contracts, set()

    result = await execute_procurement_activity_search(
        RegistryLoader(REGISTRIES).load(), "search_procurement_activity", {
            "organization_code": "ORG-1", "period_from_year": 2025,
            "period_to_year": 2025, "page": 1, "page_size": 20,
        }, reader=Reader(),
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


@pytest.mark.asyncio
async def test_contract_search_enrichment_returns_lead_members_and_share_completeness() -> None:
    class Reader:
        def find(self, catalog, *, unified_contract_numbers):
            assert unified_contract_numbers == ["C-1"]
            return [
                {
                    "unified_contract_number": "C-1", "is_joint_contract": True,
                    "supplier_sequence": 2, "business_registration_number": "1078700904",
                    "supplier_name": "한국이디에스", "supplier_role_name": "주계약업체",
                    "joint_contract_method_name": "공동",
                    "participation_share_rate": Decimal("60"),
                },
                {
                    "unified_contract_number": "C-1", "is_joint_contract": True,
                    "supplier_sequence": 1, "business_registration_number": "1234567890",
                    "supplier_name": "구성업체", "supplier_role_name": "도급업체",
                    "joint_contract_method_name": "공동", "participation_share_rate": None,
                },
            ]

    contract = MaterializedObject(
        ontology="public_procurement", object_type="contract", object_id="contract-id",
        properties={"unified_contract_number": "C-1", "is_joint_contract": True},
        provenance=[], property_provenance={},
    )
    await enrich_contract_search_objects(
        RegistryLoader(REGISTRIES).load(), [contract],
        observed_at=datetime(2026, 10, 1, tzinfo=timezone.utc), reader=Reader(),
    )

    assert contract.properties["contractor_count"] == 2
    assert contract.properties["lead_contractor"]["company_name"] == "한국이디에스"
    assert contract.properties["contractors"][0]["company_role"] == "consortium_lead"
    assert contract.properties["contractors"][0]["share_percent"] == 60
    assert contract.properties["contractors"][0]["share_completeness"] == "complete"
    assert contract.properties["contractors"][1]["company_role"] == "consortium_member"
    assert contract.properties["contractors"][1]["share_percent"] is None
    assert contract.properties["contractors"][1]["share_completeness"] == "unknown"
    assert contract.property_provenance["contractors"][0].operation == "contract_suppliers"


@pytest.mark.asyncio
async def test_relevant_companies_use_provided_notices_and_region_evidence() -> None:
    result = await execute_bid_relevant_companies(
        SupplierRunner(), RegistryLoader(REGISTRIES).load(),
        "find_bid_relevant_companies",
        {"bid_notice_id": "R26TEST:000", "similar_bid_notice_ids": ["R25SIMILAR:000"]},
        reader=RelevantCompanyReader(),
    )

    item = result.outcome["items"][0]
    assert item["similar_history"]["matched_participation_bid_notice_ids"] == ["R25SIMILAR:000"]
    assert item["similar_history"]["activities"][0]["opening_rank"] == 1
    assert item["similar_history"]["activities"][0]["result"] == "awarded"
    assert item["organization_relationship"]["activities"][0]["bid_notice_id"] == "R24ORGANIZATION:000"
    assert item["organization_relationship"]["activities"][0]["opening_rank"] == 3
    assert item["organization_relationship"]["activities"][0]["result"] == "not_awarded"
    assert item["organization_relationship"]["contract_count"] == 2
    assert item["organization_relationship"]["unified_contract_count"] == 3
    assert item["organization_relationship"]["contract_amount_basis"] == "current_contract_amount_supplier_attributed"
    assert item["similar_history"]["contract_amount_basis"] == "current_contract_amount_supplier_attributed"
    assert item["selection_evidence"] == {
        "similar_bid_notice_ids": ["R25SIMILAR:000"],
        "has_demand_organization_relationship": True,
    }
    assert item["region_eligibility"]["status"] == "satisfied"
    assert item["region_eligibility"]["company_locations"][0]["location_type"] == "본사"
    assert item["industry_license_eligibility"]["status"] == "satisfied"
    assert item["industry_license_eligibility"]["required_industries"][0]["industry_code"] == "1468"
    assert item["industry_license_eligibility"]["matched_industries"][0]["industry_code"] == "1468"
    assert item["industry_license_eligibility"]["reference_date"] == date(2026, 9, 30)
    assert "similar_bid_award_history" in item["reason_codes"]
    assert result.objects[0].object_type == "bid_relevant_company"


def test_relevant_company_capability_requires_similar_notice_ids() -> None:
    capability = RegistryLoader(REGISTRIES).load().capabilities["find_bid_relevant_companies"]
    assert capability.inputs["similar_bid_notice_ids"].required is True
    assert capability.inputs["similar_bid_notice_ids"].collection == "list"
    assert capability.inputs["limit"].maximum == 50


def test_industry_license_status_distinguishes_absence_incomplete_and_source_failure() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    notice = {
        "bid_notice_id": "R26TEST:000",
        "requirement_expression": None,
        "extraction_completeness": "complete",
    }
    assert _industry_license_eligibility(
        notice, [], {"industries": [], "industries_available": True}, date(2026, 9, 22), catalog,
    )["status"] == "not_applicable"
    assert _industry_license_eligibility(
        {**notice, "extraction_completeness": "partial"}, [],
        {"industries": [], "industries_available": True}, date(2026, 9, 22), catalog,
    )["status"] == "needs_review"
    requirement = {
        "requirement_id": "req-1", "bid_notice_id": "R26TEST:000", "local_id": "r1",
        "requirement_type": "industry_license", "value_text": '{"text":"소프트웨어사업자"}',
        "original_text": "소프트웨어사업자 등록", "mandatory": True,
        "assessment_stage": "bid_entry", "standard_rule_id": "has_registered_industry",
        "standard_rule_version": "1.0.0", "rule_arguments_text": '{"expected_value":"1468"}',
    }
    result = _industry_license_eligibility(
        notice, [requirement], {"industries": [], "industries_available": False},
        date(2026, 9, 22), catalog,
    )
    assert result["status"] == "unknown"
    assert result["reason_codes"] == ["source_unavailable"]


@pytest.mark.asyncio
async def test_similar_bid_notices_returns_scored_explainable_results() -> None:
    result = await execute_similar_bid_notices(
        RegistryLoader(REGISTRIES).load(), "find_similar_bid_notices",
        {"bid_notice_id": "R26TEST:000", "period_years": 5}, reader=SimilarNoticeReader(),
    )
    item = result.outcome["items"][0]
    assert item["bid_notice_id"] == "R25SIMILAR:000"
    assert item["notice_published_date"] == date(2025, 7, 15)
    assert item["award_date"] == date(2025, 8, 1)
    assert item["similarity_level"] == "high"
    assert item["matched_features"]["title_score"] >= 0.75
    assert item["similarity_reasons"] == ["notice_title_similar"]
    assert item["relationship_type"] == "comparable"
    assert item["comparison_eligible"] is True
    assert item["price_reference_eligible"] is True
    assert result.outcome["comparable_notices"] == [item]
    organization_item = result.outcome["organization_field_notices"][0]
    assert organization_item["bid_notice_id"] == "R24ORGFIELD:000"
    assert organization_item["comparison_eligible"] is False
    assert organization_item["price_reference_eligible"] is False
    assert "same_organization" in organization_item["matched_factors"]
    assert result.outcome["title_search_results"] == []
    assert result.objects[0].object_type == "similar_bid_notice"
    assert result.outcome["policy"]["similarity_profile"] == "bid_comparison_v1"


@pytest.mark.asyncio
async def test_organization_field_companies_use_only_award_or_contract_evidence() -> None:
    class SimilarExperienceReader:
        def count_many(self, catalog, **kwargs):
            return {"1234567890": {
                "candidate_count": 9,
                "event_count": 7,
                "strong_event_count": 2,
                "limited_event_count": 5,
                "reference_only_event_count": 2,
                "similar_amount_event_count": 3,
            }}

    result = await execute_organization_field_companies(
        RegistryLoader(REGISTRIES).load(), "analyze_bid_organization_field_companies",
        {"bid_notice_id": "R26TEST:000"}, similar_reader=SimilarNoticeReader(),
        company_reader=OrganizationFieldCompanyReader(),
        event_reader=OrganizationFieldEventReader(),
        similar_experience_reader=SimilarExperienceReader(),
    )
    item = result.outcome["organization_field_companies"][0]
    assert item["company_name"] == "기관분야업체"
    assert item["same_organization_award_count"] == 5
    assert item["same_field_award_count"] == 0
    assert item["same_field_contract_count"] == 1
    assert item["relationship_group"] == "organization_field"
    assert result.outcome["policy"]["participation_is_relationship_evidence"] is False
    basis = result.outcome["analysis_basis"]
    assert basis["period_years"] == 5
    assert basis["organization_code"] == "ORG-1"
    assert basis["work_type"] == "service"
    assert basis["field"] == {"code": "information_system", "label": "정보시스템"}
    assert basis["project_type"] == {"code": "build", "label": "정보시스템 구축"}
    assert basis["project_types"] == [
        "information_system_build", "information_system_maintenance",
    ]
    assert basis["similar_amount_range"]["amount_basis"] == "estimated_price"
    assert basis["similar_amount_range"]["reference_amount"] == 200000000
    assert basis["similar_amount_range"]["minimum_amount"] == 100000000
    assert basis["similar_amount_range"]["maximum_amount"] == 400000000
    assert basis["similar_amount_range"]["rule"] == "0.5x_to_2.0x"
    assert result.outcome["market_structure"]["award_event_count"] == 1
    assert item["organization_relationship"]["award_event_count"] == 1
    assert item["organization_relationship"]["yearly_activity"][0]["year"] == 2025
    assert item["organization_relationship"]["total_attributed_contract_amount"] == 0
    assert item["organization_relationship"]["amount_completeness"] == "unknown"
    assert item["similar_project_experience"] == {
        "candidate_count": 9,
        "event_count": 7,
        "strong_event_count": 2,
        "limited_event_count": 5,
        "reference_only_event_count": 2,
        "similar_amount_event_count": 3,
    }
    assert item["annual_activity"] == [{
        "year": 2025,
        "award_event_count": 1,
        "attributed_contract_amount": 0,
        "amount_completeness": "unknown",
        "sole_count": 1,
        "consortium_lead_count": 0,
        "consortium_member_count": 0,
    }]
    assert result.outcome["market_entry"]["classification"] == "first_observed"
    assert result.outcome["timings"]["cache_hit"] is False
    assert "total_ms" in result.outcome["timings"]
    assert result.objects[0].object_type == "bid_organization_field_company"
    cached = await execute_organization_field_companies(
        RegistryLoader(REGISTRIES).load(), "analyze_bid_organization_field_companies",
        {"bid_notice_id": "R26TEST:000"}, similar_reader=SimilarNoticeReader(),
        company_reader=OrganizationFieldCompanyReader(),
        event_reader=OrganizationFieldEventReader(),
    )
    assert cached.outcome["timings"]["cache_hit"] is True


@pytest.mark.asyncio
async def test_organization_company_field_relationship_returns_event_distributions() -> None:
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
    assert sum(item["event_count"] for item in result.outcome["project_type_distribution"]) == 1
    assert sum(item["event_count"] for item in result.outcome["amount_distribution"]) == 1
    assert sum(item["event_count"] for item in result.outcome["yearly_activity"]) == 1
    assert result.outcome["events"][0]["is_similar_amount"] is True
    assert result.outcome["events"][0]["notice_published_date"] == date(2025, 2, 20)
    assert result.outcome["events"][0]["award_date"] == date(2025, 3, 1)
    assert result.outcome["events"][0]["contract_date"] is None
    assert result.outcome["events"][0]["attributed_contract_amount_completeness"] == "unknown"
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
async def test_organization_company_relationship_applies_procurement_hierarchy_filters() -> None:
    class Reader(OrganizationFieldEventReader):
        received = None

        def find(self, catalog, **kwargs):
            self.received = kwargs
            return super().find(
                catalog,
                organization_code=kwargs["organization_code"],
                work_type=kwargs["work_type"],
                as_of=kwargs["as_of"],
            )

    reader = Reader()
    result = await execute_organization_company_relationship(
        RegistryLoader(REGISTRIES).load(), "get_organization_company_relationship",
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
async def test_organization_company_relationship_limits_metrics_and_separates_versions() -> None:
    class Reader(OrganizationFieldEventReader):
        def find(self, catalog, *, organization_code, work_type, as_of):
            rows = []
            for contract_number, event_date, amount in (
                ("C-OLD", date(2021, 5, 1), Decimal("80")),
                ("C-V1", date(2023, 5, 1), Decimal("90")),
                ("C-V2", date(2025, 5, 1), Decimal("100")),
            ):
                rows.append({
                    "source_kind": "contract", "notice_number": "N1",
                    "unified_contract_number": contract_number,
                    "original_contract_number": contract_number,
                    "bid_notice_id": "N1:000", "notice_name": "정보시스템 유지관리",
                    "event_date": event_date, "event_amount": amount,
                    "notice_published_date": date(2023, 2, 1),
                    "attribution_date": date(2023, 2, 1),
                    "attribution_date_basis": "notice_published_at",
                    "first_contract_date": date(2021, 5, 1),
                    "latest_contract_version_date": date(2025, 5, 1),
                    "contract_amount": amount, "contract_currency": "KRW",
                    "company_number": "1234567890", "company_name": "기관분야업체",
                    "participation_share_rate": Decimal("100"),
                    "supplier_role_name": "단독",
                })
            return rows

    result = await execute_organization_company_relationship(
        RegistryLoader(REGISTRIES).load(), "get_organization_company_relationship",
        {
            "organization_code": "ORG-1", "business_registration_number": "1234567890",
            "period_years": 5, "page": 1, "page_size": 20,
        }, reader=Reader(),
    )

    summary = result.outcome["summary"]
    assert summary["unique_project_count"] == 1
    assert summary["contract_event_count"] == 1
    assert summary["contract_version_count"] == 3
    assert summary["total_attributed_contract_amount"] == 100
    assert summary["active_years"] == [2023]
    assert result.outcome["yearly_activity"] == [{
        "year": 2023, "award_event_count": 1,
        "attributed_contract_amount": 100, "amount_completeness": "complete",
        "sole_count": 1, "consortium_lead_count": 0, "consortium_member_count": 0,
    }]
    assert result.outcome["events"][0]["first_contract_date"] == date(2021, 5, 1)
    assert result.outcome["events"][0]["latest_contract_version_date"] == date(2025, 5, 1)


@pytest.mark.asyncio
async def test_organization_company_relationship_validates_explicit_year_range() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    base = {
        "organization_code": "ORG-1",
        "business_registration_number": "1234567890",
    }
    with pytest.raises(CapabilityExecutionError, match="must be provided together"):
        await execute_organization_company_relationship(
            catalog, "get_organization_company_relationship",
            {**base, "period_from_year": 2023},
        )
    with pytest.raises(CapabilityExecutionError, match="less than or equal"):
        await execute_organization_company_relationship(
            catalog, "get_organization_company_relationship",
            {**base, "period_from_year": 2025, "period_to_year": 2023},
        )
    with pytest.raises(CapabilityExecutionError, match="cannot be later"):
        await execute_organization_company_relationship(
            catalog, "get_organization_company_relationship",
            {**base, "period_from_year": 2026, "period_to_year": 2027},
        )


@pytest.mark.asyncio
async def test_company_similar_project_experience_uses_any_industry_overlap() -> None:
    class Reader:
        def find(self, catalog, **kwargs):
            return ({
                "notice_name": "정보시스템 구축 및 운영 사업",
                "work_type": "service",
                "estimated_price": Decimal("200000000"),
                "allocated_budget": None,
                "industry_codes": ["0036", "1468"],
                "industry_names": {"0036": "정보통신공사업", "1468": "소프트웨어사업자"},
            }, [{
                "bid_notice_id": "R25ONE:000",
                "notice_name": "전산장비 운영 용역",
                "notice_published_date": date(2025, 1, 1),
                "demand_organization_code": "ORG-2",
                "demand_organization_name": "다른기관",
                "work_type": "service",
                "estimated_price": Decimal("180000000"),
                "allocated_budget": None,
                "industry_codes": ["1468"],
                "award_date": date(2025, 2, 1),
                "winning_amount": Decimal("170000000"),
                "contract_date": None,
                "contract_amount": None,
                "participation_share_rate": None,
                "supplier_role_name": None,
                "supplier_count": 0,
            }])

    result = await execute_company_similar_project_experience(
        RegistryLoader(REGISTRIES).load(),
        "get_company_similar_project_experience",
        {
            "reference_bid_notice_id": "R26TEST:000",
            "business_registration_number": "1234567890",
            "period_years": 10,
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )

    assessment = result.outcome["experiences"][0]["industry_license_assessment"]
    assert assessment["matched_codes"] == ["1468"]
    assert assessment["coverage_ratio"] == 0.5
    assert assessment["all_required_codes_included"] is False
    assert result.outcome["analysis_basis"]["title_keyword_filter_applied"] is False
    assert result.outcome["summary"]["candidate_count"] == 1
    assert result.outcome["summary"]["event_count"] == 1
    assert result.outcome["summary"]["limited_event_count"] == 1
    assert result.objects[0].object_type == "company_similar_project_experience"


def test_award_event_analysis_merges_contract_and_preserves_joint_members() -> None:
    rows = [{
        "source_kind": "award", "notice_number": "R25A", "notice_order": "000",
        "bid_classification_number": "0", "rebid_number": "0",
        "bid_notice_id": "R25A:000", "notice_name": "정보시스템 구축",
        "event_date": date(2025, 3, 1), "event_amount": Decimal("200000000"),
        "company_number": "1111111111", "company_name": "대표사",
    }, {
        "source_kind": "contract", "notice_number": "R25A",
        "unified_contract_number": "C1-1", "original_contract_number": "C1",
        "bid_notice_id": "R25A:000", "notice_name": "정보시스템 구축",
        "event_date": date(2025, 3, 10), "event_amount": Decimal("200000000"),
        "contract_amount": Decimal("200000000"), "contract_currency": "KRW",
        "company_number": "1111111111", "company_name": "대표사",
        "participation_share_rate": Decimal("60"), "supplier_role_name": "대표사",
    }, {
        "source_kind": "contract", "notice_number": "R25A",
        "unified_contract_number": "C1-1", "original_contract_number": "C1",
        "bid_notice_id": "R25A:000", "notice_name": "정보시스템 구축",
        "event_date": date(2025, 3, 10), "event_amount": Decimal("200000000"),
        "contract_amount": Decimal("200000000"), "contract_currency": "KRW",
        "company_number": "2222222222", "company_name": "구성사",
        "participation_share_rate": Decimal("40"), "supplier_role_name": "구성사",
    }]
    notice = {
        "notice_name": "차세대 정보시스템 구축", "estimated_price": Decimal("200000000"),
        "allocated_budget": None, "as_of": datetime(2026, 9, 1, tzinfo=timezone.utc),
    }

    result = _organization_field_event_analysis(rows, notice, 5)

    assert result["event_deduplication"]["merged_award_contract_count"] == 1
    assert result["market_structure"]["award_event_count"] == 1
    assert result["market_structure"]["company_count"] == 2
    assert result["market_structure"]["top_1_share"] == 0.6
    assert result["company_metrics"]["1111111111"]["same_field_event_count"] == 1
    assert result["company_metrics"]["2222222222"]["same_field_contract_amount"] == 80000000
    assert result["company_metrics"]["1111111111"]["annual_activity"] == [{
        "year": 2025,
        "award_event_count": 1,
        "attributed_contract_amount": 120000000,
        "amount_completeness": "complete",
        "sole_count": 0,
        "consortium_lead_count": 1,
        "consortium_member_count": 0,
    }]
    assert result["company_metrics"]["2222222222"]["annual_activity"][0][
        "consortium_member_count"
    ] == 1
    event = result["events"][0]
    assert event["award_date"] == date(2025, 3, 1)
    assert event["contract_date"] == date(2025, 3, 10)


@pytest.mark.asyncio
async def test_project_lineage_keeps_structured_only_matches_as_candidates() -> None:
    result = await execute_bid_project_lineage(
        RegistryLoader(REGISTRIES).load(), "find_bid_project_lineage",
        {"bid_notice_id": "R26TEST:000", "period_years": 5},
        reader=SimilarNoticeReader(),
    )

    assert result.outcome["items"]
    assert all(item["relationship_type"] == "related_candidate" for item in result.outcome["items"])
    assert all(item["confirmation_status"] == "requires_source_evidence" for item in result.outcome["items"])
    assert result.outcome["policy"]["title_similarity_alone_confirms_lineage"] is False


@pytest.mark.asyncio
async def test_procurement_profiles_keep_event_types_and_attributed_amounts_separate() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            return [
                {
                    "activity_type": "participation", "event_key": "N1:C1",
                    "bid_notice_id": "N1:000", "notice_name": "정보시스템 구축",
                    "organization_code": "ORG-1", "organization_name": "기관",
                    "company_number": "1111111111", "company_name": "업체",
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "work_type": "service",
                    "activity_date": date(2025, 1, 1), "event_amount": Decimal("90"),
                    "attributed_contract_amount": None, "amount_completeness": "unknown",
                },
                {
                    "activity_type": "award", "event_key": "N1:000:0:0",
                    "bid_notice_id": "N1:000", "notice_name": "정보시스템 구축",
                    "organization_code": "ORG-1", "organization_name": "기관",
                    "company_number": "1111111111", "company_name": "업체",
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "work_type": "service",
                    "activity_date": date(2025, 2, 1), "event_amount": Decimal("90"),
                    "attributed_contract_amount": None, "amount_completeness": "unknown",
                },
                {
                    "activity_type": "contract", "event_key": "C1",
                    "bid_notice_id": "N1:000", "notice_name": "정보시스템 구축",
                    "organization_code": "ORG-1", "organization_name": "기관",
                    "company_number": "1111111111", "company_name": "업체",
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "work_type": "service",
                    "activity_date": date(2025, 3, 1), "event_amount": Decimal("100"),
                    "attributed_contract_amount": Decimal("60"),
                    "amount_completeness": "complete",
                },
            ]

    catalog = RegistryLoader(REGISTRIES).load()
    organization = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "period_years": 5}, reader=Reader(),
    )
    company = await execute_company_procurement_profile(
        catalog, "analyze_company_procurement_profile",
        {"business_registration_number": "1111111111", "period_years": 5}, reader=Reader(),
    )

    assert organization.outcome["summary"]["participation_count"] == 1
    assert organization.outcome["summary"]["award_event_count"] == 1
    assert organization.outcome["summary"]["contract_event_count"] == 1
    assert organization.outcome["summary"]["total_attributed_contract_amount"] == 60
    assert organization.outcome["analysis_basis"]["period_type"] == "calendar_fiscal_years"
    assert organization.outcome["analysis_basis"]["period_from"] == date(
        date.today().year - 4, 1, 1,
    )
    assert organization.outcome["company_relationships"][0]["major_fields"][0][
        "event_count"
    ] == 1
    assert organization.outcome["field_distribution_level"] == "large"
    assert organization.outcome["field_distribution"][0]["large_category"] == "ICT 서비스"
    assert organization.outcome["project_type_distribution"][0]["project_type"] == "build"
    assert organization.outcome["work_type_distribution"] == [{
        "work_type": "service", "work_type_name": "용역", "event_count": 3,
        "participation_count": 1, "award_event_count": 1, "contract_event_count": 1,
        "attributed_contract_amount": 60,
    }]
    assert organization.outcome["field_distribution"][0]["work_types"] == ["service"]
    assert company.outcome["organization_relationships"][0]["active_years"] == [2025]

    filtered = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1", "period_years": 5,
            "large_category": " ICT   서비스 ",
            "middle_category": "SW 및 시스템 개발",
            "field_code": "81111599", "work_type": "service",
        },
        reader=Reader(),
    )
    assert filtered.outcome["summary"]["contract_event_count"] == 1
    assert filtered.outcome["company_relationships"][0]["company_number"] == "1111111111"
    assert filtered.outcome["field_distribution_level"] == "detail"
    assert filtered.outcome["field_distribution"][0]["field_code"] == "81111599"
    assert filtered.outcome["analysis_basis"]["field_filter"]["field_name"] == (
        "정보시스템개발서비스"
    )

    empty = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "field_code": "00000000"}, reader=Reader(),
    )
    assert empty.outcome["summary"]["notice_count"] == 0
    assert empty.outcome["company_relationships"] == []


@pytest.mark.asyncio
async def test_procurement_profile_merges_contract_versions_by_project() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            return [{
                "activity_type": "contract", "event_key": event_key,
                "bid_notice_id": "N1:000", "notice_name": "정보시스템 유지관리",
                "organization_code": "ORG-1", "organization_name": "기관",
                "company_number": "1111111111", "company_name": "업체",
                "procurement_classification_number": "81111899",
                "procurement_classification_name": "정보시스템유지관리서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "정보시스템 운영",
                "work_type": "service", "activity_date": date(2023, 1, 1),
                "attribution_date_basis": "notice_published_at",
                "first_contract_date": date(2023, 2, 1),
                "latest_contract_version_date": activity_date,
                "event_amount": amount, "attributed_contract_amount": amount,
                "amount_completeness": "complete",
            } for event_key, activity_date, amount in (
                ("C1", date(2023, 1, 1), Decimal("80")),
                ("C2", date(2025, 1, 1), Decimal("100")),
            )]

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(), "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "period_years": 5}, reader=Reader(),
    )

    relationship = result.outcome["company_relationships"][0]
    assert relationship["contract_event_count"] == 1
    assert relationship["contract_version_count"] == 2
    assert relationship["unique_project_count"] == 1
    assert relationship["total_attributed_contract_amount"] == 100
    assert relationship["active_years"] == [2023]
    assert relationship["latest_contract_date"] == date(2025, 1, 1)
    assert relationship["yearly_activity"] == [{
        "year": 2023, "participation_count": 0, "award_event_count": 0,
        "contract_event_count": 1, "attributed_contract_amount": 100,
        "amount_completeness": "complete",
    }]
    representative = relationship["representative_notices"][0]
    assert representative["attribution_date"] == date(2023, 1, 1)
    assert representative["first_contract_date"] == date(2023, 2, 1)
    assert representative["latest_contract_version_date"] == date(2025, 1, 1)
    assert result.outcome["summary"]["contract_event_count"] == 1
    assert result.outcome["summary"]["contract_version_count"] == 2
    assert result.outcome["summary"]["unique_project_count"] == 1


@pytest.mark.asyncio
async def test_procurement_profile_applies_explicit_year_range_everywhere() -> None:
    class Reader:
        observed_period = None

        def activities(self, catalog, **kwargs):
            self.observed_period = (kwargs["period_from"], kwargs["period_to"])
            return [
                {
                    "activity_type": "contract", "event_key": f"C-{year}",
                    "bid_notice_id": f"N-{year}:000", "notice_name": f"사업 {year}",
                    "organization_code": "ORG-1", "organization_name": "기관",
                    "company_number": f"{year:010d}", "company_name": f"업체 {year}",
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "work_type": "service", "activity_date": date(year, 6, 1),
                    "event_amount": Decimal(str(year)),
                    "attributed_contract_amount": Decimal(str(year)),
                    "amount_completeness": "complete",
                }
                for year in (2022, 2023, 2024, 2025, 2026)
                if kwargs["period_from"] <= date(year, 6, 1) < kwargs["period_to"]
            ]

        def organization_award_history(self, catalog, **kwargs):
            assert kwargs["history_from"] == date(2020, 1, 1)
            assert kwargs["history_to"] == date(2026, 1, 1)
            assert kwargs["work_type"] is None
            assert kwargs["large_category"] is None
            assert kwargs["middle_category"] is None
            assert kwargs["field_code"] is None
            return {}, kwargs["history_from"]

    reader = Reader()
    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(), "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1", "period_years": 5,
            "period_from_year": 2023, "period_to_year": 2025,
        }, reader=reader,
    )

    assert reader.observed_period == (date(2020, 1, 1), date(2026, 1, 1))
    assert result.outcome["summary"]["contract_event_count"] == 3
    assert result.outcome["pagination"]["total_items"] == 3
    assert [item["year"] for item in result.outcome["yearly_activity"]] == [2025, 2024, 2023]
    assert result.outcome["field_distribution"][0]["contract_event_count"] == 3
    assert result.outcome["work_type_distribution"][0]["contract_event_count"] == 3
    assert {
        key: result.outcome["analysis_basis"][key]
        for key in (
            "period_from", "period_to", "period_from_year", "period_to_year",
            "period_years", "period_type",
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
            catalog, "analyze_company_procurement_profile",
            {"business_registration_number": "1111111111", "period_from_year": 2023},
        )
    with pytest.raises(CapabilityExecutionError, match="less than or equal"):
        await execute_company_procurement_profile(
            catalog, "analyze_company_procurement_profile",
            {
                "business_registration_number": "1111111111",
                "period_from_year": 2025, "period_to_year": 2023,
            },
        )


@pytest.mark.asyncio
async def test_organization_profile_lists_only_contracted_companies() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            base = {
                "notice_name": "조달 사업", "organization_code": "ORG-1",
                "organization_name": "기관", "work_type": "service",
                "procurement_classification_number": None,
                "procurement_classification_name": None,
                "procurement_large_classification_name": None,
                "procurement_middle_classification_name": None,
                "event_amount": Decimal("100"), "amount_completeness": "unknown",
            }
            return [
                {
                    **base, "activity_type": "participation", "event_key": "P-ONLY",
                    "bid_notice_id": "P:000", "company_number": "1111111111",
                    "company_name": "참여만", "activity_date": date(2025, 1, 1),
                    "attributed_contract_amount": None,
                },
                {
                    **base, "activity_type": "award", "event_key": "A-ONLY",
                    "bid_notice_id": "A:000", "company_number": "2222222222",
                    "company_name": "낙찰만", "activity_date": date(2025, 2, 1),
                    "attributed_contract_amount": None,
                },
                {
                    **base, "activity_type": "participation", "event_key": "P-C",
                    "bid_notice_id": "C:000", "company_number": "3333333333",
                    "company_name": "계약업체", "activity_date": date(2025, 3, 1),
                    "attributed_contract_amount": None,
                },
                {
                    **base, "activity_type": "contract", "event_key": "C-0",
                    "bid_notice_id": "C:000", "company_number": "3333333333",
                    "company_name": "계약업체", "activity_date": date(2020, 4, 1),
                    "attributed_contract_amount": Decimal("80"),
                    "amount_completeness": "complete",
                },
                {
                    **base, "activity_type": "contract", "event_key": "C-1",
                    "bid_notice_id": "C:000", "company_number": "3333333333",
                    "company_name": "계약업체", "activity_date": date(2025, 4, 1),
                    "attributed_contract_amount": Decimal("100"),
                    "amount_completeness": "complete",
                },
            ]

        def organization_award_history(self, catalog, **kwargs):
            return {}, kwargs["history_from"]

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(), "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "period_from_year": 2025, "period_to_year": 2025},
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
    assert sum(rolling[key] for key in (
        "first_observed_company_count", "reentering_company_count",
        "incumbent_company_count",
    )) == rolling["total_company_count"]


@pytest.mark.asyncio
async def test_organization_profile_company_search_sort_and_pagination_are_list_only() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            rows = []
            definitions = [
                ("1111111111", "알파 시스템", [("A-1", date(2025, 2, 1), "40"),
                                                ("A-2", date(2025, 5, 1), "60")]),
                ("2222222222", "베타정보", [("B-1", date(2025, 3, 1), "300")]),
                ("3333333333", "감마테크", [("C-1", date(2025, 8, 1), "200")]),
            ]
            for company_number, company_name, contracts in definitions:
                for event_key, activity_date, amount in contracts:
                    rows.append({
                        "activity_type": "contract", "event_key": event_key,
                        "bid_notice_id": f"{event_key}:000", "notice_name": event_key,
                        "organization_code": "ORG-1", "organization_name": "기관",
                        "company_number": company_number, "company_name": company_name,
                        "procurement_classification_number": None,
                        "procurement_classification_name": None,
                        "procurement_large_classification_name": None,
                        "procurement_middle_classification_name": None,
                        "work_type": "service", "activity_date": activity_date,
                        "event_amount": Decimal(amount),
                        "attributed_contract_amount": Decimal(amount),
                        "amount_completeness": "complete",
                    })
            return rows

    catalog = RegistryLoader(REGISTRIES).load()
    base_inputs = {
        "organization_code": "ORG-1", "period_from_year": 2025,
        "period_to_year": 2025, "page": 1, "page_size": 20,
    }
    baseline = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile", base_inputs, reader=Reader(),
    )
    searched = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile", {
            **base_inputs, "company_query": "  알파   ", "sort": "contract_count_desc",
        }, reader=Reader(),
    )

    assert searched.outcome["pagination"]["total_items"] == 1
    assert searched.outcome["pagination"]["total_pages"] == 1
    assert searched.outcome["pagination"]["sort"] == "contract_count_desc"
    assert searched.outcome["company_relationships"][0]["company_name"] == "알파 시스템"
    assert searched.outcome["company_relationships"][0]["latest_contract_date"] == date(
        2025, 5, 1,
    )
    assert searched.outcome["summary"] == baseline.outcome["summary"]
    assert searched.outcome["yearly_activity"] == baseline.outcome["yearly_activity"]
    assert searched.outcome["field_distribution"] == baseline.outcome["field_distribution"]
    assert searched.outcome["work_type_distribution"] == baseline.outcome[
        "work_type_distribution"
    ]
    assert searched.objects[0].properties["relationship_count"] == 3

    expected_orders = {
        "contract_amount_desc": ["베타정보", "감마테크", "알파 시스템"],
        "contract_count_desc": ["알파 시스템", "베타정보", "감마테크"],
        "latest_contract_desc": ["감마테크", "알파 시스템", "베타정보"],
    }
    for sort, expected in expected_orders.items():
        result = await execute_organization_procurement_profile(
            catalog, "analyze_organization_procurement_profile", {
                **base_inputs, "sort": sort,
            }, reader=Reader(),
        )
        assert [
            item["company_name"] for item in result.outcome["company_relationships"]
        ] == expected


@pytest.mark.asyncio
async def test_rolling_supplier_entry_ignores_start_year_and_filters_history() -> None:
    class Reader:
        history_calls = []

        def activities(self, catalog, **kwargs):
            return [{
                "activity_type": "contract", "event_key": "C-1",
                "bid_notice_id": "C:000", "notice_name": "정보시스템 계약",
                "organization_code": "ORG-1", "organization_name": "기관",
                "company_number": "3333333333", "company_name": "계약업체",
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "work_type": "service", "activity_date": date(2025, 4, 1),
                "event_amount": Decimal("100"),
                "attributed_contract_amount": Decimal("100"),
                "amount_completeness": "complete",
            }]

        def organization_award_history(self, catalog, **kwargs):
            self.history_calls.append(kwargs)
            return {"3333333333": date(2025, 4, 1)}, kwargs["history_from"]

    reader = Reader()
    catalog = RegistryLoader(REGISTRIES).load()
    outcomes = []
    for from_year in (2021, 2024):
        result = await execute_organization_procurement_profile(
            catalog, "analyze_organization_procurement_profile", {
                "organization_code": "ORG-1", "period_from_year": from_year,
                "period_to_year": 2025, "work_type": "service",
                "large_category": "ICT 서비스",
                "middle_category": "SW 및 시스템 개발", "field_code": "81111599",
            }, reader=reader,
        )
        outcomes.append(result.outcome["summary"]["rolling_12m_supplier_entry"])

    assert outcomes[0] == outcomes[1]
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
async def test_organization_profile_reports_rolling_supplier_entry_without_participation() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            base = {
                "notice_name": "정보시스템 용역",
                "organization_code": "ORG-1", "organization_name": "기관",
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "work_type": "service", "event_amount": Decimal("100"),
                "attributed_contract_amount": None, "amount_completeness": "unknown",
            }
            return [
                {**base, "activity_type": "participation", "event_key": "P1",
                 "bid_notice_id": "P1:000", "company_number": "9999999999",
                 "company_name": "참여업체", "activity_date": date(2025, 1, 1)},
                {**base, "activity_type": "award", "event_key": "A1",
                 "bid_notice_id": "A1:000", "company_number": "1111111111",
                 "company_name": "기존업체", "activity_date": date(2025, 2, 1)},
                {**base, "activity_type": "contract", "event_key": "C1",
                 "bid_notice_id": "A1:000", "company_number": "3333333333",
                 "company_name": "공동수급구성원", "activity_date": date(2026, 2, 10),
                 "attributed_contract_amount": Decimal("30"),
                 "amount_completeness": "complete"},
                {**base, "activity_type": "award", "event_key": "A2",
                 "bid_notice_id": "A2:000", "company_number": "2222222222",
                 "company_name": "신규업체", "activity_date": date(2025, 3, 1)},
                {**base, "activity_type": "award", "event_key": "A3",
                 "bid_notice_id": "A3:000", "company_number": None,
                 "company_name": None, "activity_date": date(2025, 4, 1)},
            ]

        def organization_award_history(self, catalog, **kwargs):
            return {
                "1111111111": date(2022, 1, 1),
                "2222222222": date(2025, 3, 1),
                "3333333333": date(2026, 2, 10),
            }, date(2022, 1, 1)

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(), "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "period_years": 5}, reader=Reader(),
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
        "history_to": date.today().replace(year=date.today().year - 1) - timedelta(days=1),
        "history_years": 5,
        "history_basis": "five_fiscal_years_before_target_period",
        "minimum_sample_size": 10,
        "sample_sufficient": False,
    }


@pytest.mark.asyncio
async def test_bid_relationship_context_batches_only_history_before_notice() -> None:
    class Reader:
        observed_period_to = None

        def bid_context(self, catalog, **kwargs):
            return ({
                "notice_name": "현재 공고", "organization_code": "ORG-1",
                "organization_name": "기관", "notice_published_date": date(2026, 4, 1),
            }, [{
                "company_number": "1111111111", "company_name": "업체",
                "opening_rank": 1, "bid_amount": Decimal("90"), "bid_rate": Decimal("90"),
                "award_date": date(2026, 5, 1), "winning_amount": Decimal("90"),
                "winning_rate": Decimal("90"), "contract_date": None,
                "contract_amount": None, "attributed_contract_amount": None,
                "share_percent": None, "company_role": None,
                "amount_completeness": None,
            }])

        def activities(self, catalog, **kwargs):
            self.observed_period_to = kwargs["period_to"]
            return []

    reader = Reader()
    result = await execute_bid_notice_relationship_context(
        RegistryLoader(REGISTRIES).load(), "get_bid_notice_relationship_context",
        {"bid_notice_id": "N2:000", "relationship_history_years": 5}, reader=reader,
    )

    assert reader.observed_period_to == date(2026, 4, 1)
    assert result.outcome["analysis_basis"]["period_from"] == date(2022, 1, 1)
    assert result.outcome["analysis_basis"]["period_type"] == "calendar_fiscal_years"
    assert result.outcome["participants"][0]["result"] == "awarded"
    assert result.outcome["participants"][0]["prior_organization_relationship"][
        "award_event_count"
    ] == 0


@pytest.mark.asyncio
async def test_construction_profile_uses_official_field_as_flat_category() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            return [{
                "activity_type": "contract", "event_key": "C1",
                "bid_notice_id": "N1:000", "notice_name": "청사 내부 공사",
                "organization_code": "ORG-1", "organization_name": "기관",
                "company_number": "1111111111", "company_name": "업체",
                "procurement_classification_number": "72153699",
                "procurement_classification_name": "실내건축공사",
                "procurement_large_classification_name": None,
                "procurement_middle_classification_name": None,
                "purchase_items": None, "work_type": "construction",
                "activity_date": date(2025, 3, 1), "event_amount": Decimal("100"),
                "attributed_contract_amount": Decimal("100"),
                "amount_completeness": "complete",
            }]

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(), "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1", "work_type": "construction",
            "large_category": "실내건축공사",
        },
        reader=Reader(),
    )

    assert result.outcome["field_distribution_level"] == "construction_field"
    assert result.outcome["field_hierarchy_depth"] == 1
    assert result.outcome["field_distribution"] == [{
        "field_code": "72153699", "field_name": "실내건축공사",
        "large_category": "실내건축공사", "middle_category": None,
        "detailed_items": [], "classification_source": "construction_work_category",
        "work_types": ["construction"], "participation_count": 0,
        "award_event_count": 0, "contract_event_count": 1, "event_count": 1,
        "attributed_contract_amount": 100, "amount_share": 1.0,
    }]


@pytest.mark.asyncio
async def test_profile_includes_and_filters_unclassified_field_bucket() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            base = {
                "activity_type": "contract", "organization_code": "ORG-1",
                "organization_name": "기관", "company_number": "1111111111",
                "company_name": "업체", "work_type": "goods",
                "activity_date": date(2025, 1, 1), "amount_completeness": "complete",
            }
            return [
                {**base, "event_key": "C1", "bid_notice_id": "N1:000",
                 "notice_name": "분류 물품", "event_amount": Decimal("20"),
                 "attributed_contract_amount": Decimal("20"),
                 "procurement_classification_number": "82141502",
                 "procurement_classification_name": "그래픽디자인서비스",
                 "procurement_large_classification_name": "매체제작·디자인",
                 "procurement_middle_classification_name": "디자인"},
                {**base, "event_key": "C2", "bid_notice_id": "N2:000",
                 "notice_name": "원천 분류 없는 물품", "event_amount": Decimal("80"),
                 "attributed_contract_amount": Decimal("80"),
                 "procurement_classification_number": None,
                 "procurement_classification_name": None,
                 "procurement_large_classification_name": None,
                 "procurement_middle_classification_name": None},
            ]

        def organization_award_history(self, catalog, **kwargs):
            return {}, None

    catalog = RegistryLoader(REGISTRIES).load()
    result = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "work_type": "goods"}, reader=Reader(),
    )
    distribution = {item["large_category"]: item for item in result.outcome[
        "field_distribution"
    ]}
    assert result.outcome["summary"]["total_attributed_contract_amount"] == 100
    assert sum(item["attributed_contract_amount"] for item in distribution.values()) == 100
    assert distribution["미분류"] == {
        "large_category": "미분류", "field_code": None, "field_name": None,
        "middle_category": None, "classification_source": "unclassified",
        "event_count": 1, "participation_count": 0, "award_event_count": 0,
        "contract_event_count": 1, "attributed_contract_amount": 80,
        "work_types": ["goods"], "amount_share": 0.8,
    }

    filtered = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "work_type": "goods",
         "large_category": "미분류"}, reader=Reader(),
    )
    assert filtered.outcome["summary"]["total_attributed_contract_amount"] == 80
    assert filtered.outcome["field_distribution_level"] == "unclassified"
    assert filtered.outcome["field_distribution"][0]["classification_source"] == "unclassified"


@pytest.mark.asyncio
async def test_profile_splits_unclassified_buckets_by_work_type() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            return [{
                "activity_type": "contract", "event_key": f"C{index}",
                "bid_notice_id": f"N{index}:000", "notice_name": "미분류 계약",
                "organization_code": "ORG-1", "organization_name": "기관",
                "company_number": f"111111111{index}", "company_name": f"업체{index}",
                "work_type": work_type, "activity_date": date(2025, 1, index),
                "event_amount": Decimal(str(amount)),
                "attributed_contract_amount": Decimal(str(amount)),
                "amount_completeness": "complete",
                "procurement_classification_number": None,
                "procurement_classification_name": None,
                "procurement_large_classification_name": None,
                "procurement_middle_classification_name": None,
            } for index, (work_type, amount) in enumerate(
                (("goods", 30), ("service", 70)), start=1,
            )]

        def organization_award_history(self, catalog, **kwargs):
            return {}, None

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(), "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1"}, reader=Reader(),
    )
    buckets = sorted(
        (item for item in result.outcome["field_distribution"]
         if item["large_category"] == "미분류"),
        key=lambda item: item["work_types"],
    )
    assert [(item["work_types"], item["attributed_contract_amount"]) for item in buckets] == [
        (["goods"], 30), (["service"], 70),
    ]

    filtered = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(), "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "large_category": "미분류"}, reader=Reader(),
    )
    assert len(filtered.outcome["field_distribution"]) == 2
