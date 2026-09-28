from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from teoria.registry.loader import RegistryLoader
from teoria.runtime.capability.runner import CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.market_context.processor import (
    _organization_field_event_analysis,
    _industry_license_eligibility,
    execute_bid_project_lineage,
    execute_organization_company_field_relationship,
    execute_organization_company_relationship,
    execute_company_similar_project_experience,
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
