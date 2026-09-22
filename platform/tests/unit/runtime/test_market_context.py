from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from teoria.registry.loader import RegistryLoader
from teoria.runtime.capability.runner import CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.market_context.processor import (
    _industry_license_eligibility,
    execute_bid_relevant_companies,
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
            "similar_award_amount": Decimal("980000000"),
            "similar_contract_amount": None,
            "participation_notice_ids": ["R25SIMILAR:000"],
            "award_notice_ids": ["R25SIMILAR:000"],
            "contract_notice_ids": [],
            "similar_first_activity_date": date(2025, 6, 1),
            "similar_latest_activity_date": date(2025, 6, 2),
            "organization_participation_count": 7,
            "organization_award_count": 2,
            "organization_contract_count": 2,
            "organization_contract_amount": Decimal("640000000"),
            "contract_amount_complete": True,
            "organization_first_activity_date": date(2022, 4, 11),
            "organization_latest_activity_date": date(2026, 6, 18),
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
