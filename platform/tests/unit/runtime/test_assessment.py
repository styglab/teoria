from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from teoria.registry.loader import RegistryLoader
from teoria.runtime.assessment.expression import aggregate_expression
from teoria.runtime.assessment.evaluators import evaluate_requirement
from teoria.runtime.assessment.models import CompanyEvidenceSnapshot
from teoria.runtime.assessment.processor import execute_bid_eligibility_assessment
from teoria.runtime.capability.runner import CapabilityResult
from teoria.runtime.capability.presentation import serialize_capability_result
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.provenance import Provenance


REGISTRIES = Path(__file__).parents[3] / "registries"
NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)


def _object(ontology: str, object_type: str, object_id: str, **properties) -> MaterializedObject:
    provenance = Provenance(
        kind="source",
        source="test_source",
        operation="get_records",
        mapping="test_mapping",
        observed_at=NOW,
        record_keys=[object_id],
    )
    return MaterializedObject(
        ontology=ontology,
        object_type=object_type,
        object_id=object_id,
        properties=properties,
        provenance=[provenance],
        property_provenance={key: [provenance] for key in properties},
    )


class AssessmentFixtureRunner:
    async def run(self, catalog, capability_id, inputs):
        if capability_id == "get_bid_notice":
            expression = {
                "operator": "all",
                "requirement_id": None,
                "conditions": [
                    {"operator": "leaf", "requirement_id": "r1", "conditions": []},
                    {"operator": "leaf", "requirement_id": "r2", "conditions": []},
                    {"operator": "leaf", "requirement_id": "r3", "conditions": []},
                ],
            }
            return CapabilityResult(capability_id=capability_id, objects=[
                _object(
                    "public_procurement",
                    "bid_notice",
                    "notice-object",
                    bid_notice_id="R26TEST:00",
                    notice_number="R26TEST",
                    notice_order="00",
                    bid_deadline_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
                    requirement_expression=json.dumps(expression),
                    extraction_completeness="complete",
                    requires_review=False,
                )
            ])
        if capability_id == "get_bid_requirements":
            requirements = [
                _object(
                    "public_procurement", "bid_requirement", "requirement-1",
                    requirement_id="requirement-1", local_id="r1", requirement_type="business_status",
                    standard_rule_id="is_active_business", standard_rule_version="1.0.0",
                    operator="equals", value_text='{"text":"active"}', original_text="계속사업자",
                    mandatory=True, evidence_summary="공고문 3쪽 | 계속사업자",
                ),
                _object(
                    "public_procurement", "bid_requirement", "requirement-2",
                    requirement_id="requirement-2", local_id="r2", requirement_type="certificate",
                    operator="valid_on", value_text='{"text":"직접생산확인 8111159801"}',
                    standard_rule_id="holds_valid_direct_production_confirmation", standard_rule_version="1.0.0",
                    rule_arguments_text='{"product_code":"8111159801"}',
                    original_text="직접생산확인증명서를 보유하여야 한다.", mandatory=True,
                    evidence_summary="공고문 4쪽 | 직접생산확인증명서",
                ),
                _object(
                    "public_procurement", "bid_requirement", "requirement-3",
                    requirement_id="requirement-3", local_id="r3", requirement_type="past_performance",
                    operator="greater_than_or_equal", value_text='{"number":100000000}',
                    original_text="최근 3년 유사실적 1억원 이상", mandatory=True,
                    evidence_summary="공고문 5쪽 | 유사실적",
                ),
            ]
            return CapabilityResult(capability_id=capability_id, objects=requirements)
        if capability_id == "get_business_registration_status":
            return CapabilityResult(capability_id=capability_id, objects=[
                _object("company", "business_registration", "business-object", business_registration_number="1234567890"),
                _object("company", "taxpayer_status_observation", "tax-status", operating_status="active"),
            ])
        if capability_id == "get_direct_production_confirmations":
            return CapabilityResult(capability_id=capability_id, objects=[
                _object(
                    "public_procurement", "direct_production_confirmation", "direct-production",
                    detailed_product_code="8111159801", valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31),
                )
            ])
        return CapabilityResult(capability_id=capability_id)


@pytest.mark.asyncio
async def test_computes_bid_eligibility_as_ontology_objects_with_evidence() -> None:
    catalog = RegistryLoader(REGISTRIES).load()

    result = await execute_bid_eligibility_assessment(
        AssessmentFixtureRunner(),
        catalog,
        "assess_company_bid_eligibility",
        {"business_registration_number": "1234567890", "bid_notice_id": "R26TEST:00"},
    )

    assessment = next(item for item in result.objects if item.object_type == "bid_eligibility_assessment")
    assert assessment.properties["reference_date"] == date(2026, 8, 20)
    assert assessment.properties["outcome"] == "needs_review"
    assert assessment.properties["satisfied_count"] == 2
    assert assessment.properties["needs_review_count"] == 1
    details = [item for item in result.objects if item.object_type == "requirement_assessment"]
    assert {item.properties["reason_code"] for item in details} == {
        "business_active",
        "direct_production_matched",
        "unsupported_standard_rule",
    }
    assert sum(item.object_type == "evidence" for item in result.objects) >= 5
    assert any(item.link_type == "requirement_assessment_supported_by_evidence" for item in result.links)
    assert any(item.link_type == "evidence_derived_from_direct_production_confirmation" for item in result.links)
    limited = serialize_capability_result(result, max_objects=7)
    assert sum(item["type"] == "requirement_assessment" for item in limited["objects"]) == 3
    assert any(item["type"] == "evidence" for item in limited["objects"])


def test_expression_uses_three_state_logic() -> None:
    expression = {
        "operator": "any",
        "requirement_id": None,
        "conditions": [
            {"operator": "leaf", "requirement_id": "a", "conditions": []},
            {"operator": "leaf", "requirement_id": "b", "conditions": []},
        ],
    }
    assert aggregate_expression(expression, {"a": "unsatisfied", "b": "needs_review"}) == "needs_review"
    assert aggregate_expression(expression, {"a": "unsatisfied", "b": "satisfied"}) == "satisfied"


def test_unbound_requirement_does_not_fall_back_to_requirement_type() -> None:
    requirement = _object(
        "public_procurement", "bid_requirement", "unbound-sanction",
        requirement_type="sanction", operator="not_exists", original_text="제재를 받지 않은 자",
    )

    decision = evaluate_requirement(
        requirement,
        CompanyEvidenceSnapshot(),
        date(2026, 8, 20),
        RegistryLoader(REGISTRIES).load(),
    )

    assert decision.outcome == "needs_review"
    assert decision.reason_code == "unsupported_standard_rule"


@pytest.mark.parametrize(("status_name", "valid_until", "outcome", "reason"), [
    ("정상", date(2026, 12, 31), "satisfied", "industry_code_matched"),
    ("정상", date(2026, 7, 31), "unsatisfied", "industry_registration_inactive"),
    ("말소", date(2026, 12, 31), "unsatisfied", "industry_registration_inactive"),
])
def test_registered_software_business_requires_active_procurement_industry(
    status_name: str, valid_until: date, outcome: str, reason: str,
) -> None:
    requirement = _object(
        "public_procurement", "bid_requirement", "software-business-rule",
        standard_rule_id="has_registered_industry",
        rule_arguments_text='{"expected_value":"1468"}',
    )
    industry = _object(
        "public_procurement", "registered_industry", "software-business-industry",
        industry_code="1468", industry_name="소프트웨어사업자(컴퓨터관련서비스사업)",
        registered_at=datetime(2025, 1, 1), valid_until=valid_until, status_name=status_name,
    )

    decision = evaluate_requirement(
        requirement, CompanyEvidenceSnapshot(objects=[industry]), date(2026, 8, 20),
        RegistryLoader(REGISTRIES).load(),
    )

    assert decision.outcome == outcome
    assert decision.reason_code == reason


def test_generic_company_qualification_rule_uses_rule_argument() -> None:
    requirement = _object(
        "public_procurement", "bid_requirement", "women-rule",
        standard_rule_id="holds_valid_company_qualification",
        rule_arguments_text='{"qualification_type":"women_owned_business"}',
        value_text='{"text":"여성기업"}',
    )
    qualification = _object(
        "company", "qualification", "women-qualification",
        qualification_type="women_owned_business",
        valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31),
    )
    decision = evaluate_requirement(
        requirement, CompanyEvidenceSnapshot(objects=[qualification]), date(2026, 8, 20),
        RegistryLoader(REGISTRIES).load(),
    )
    assert decision.outcome == "satisfied"
    assert decision.reason_code == "qualification_valid"


def test_consortium_rule_compares_requested_participation_mode() -> None:
    requirement = _object(
        "public_procurement", "bid_requirement", "consortium-rule",
        standard_rule_id="is_consortium_allowed", value_text='{"boolean":false}',
    )
    decision = evaluate_requirement(
        requirement,
        CompanyEvidenceSnapshot(assessment_context={"participation_mode": "consortium"}),
        date(2026, 8, 20), RegistryLoader(REGISTRIES).load(),
    )
    assert decision.outcome == "unsatisfied"
    assert decision.reason_code == "consortium_participation_prohibited"


def test_company_scale_always_requires_official_document_review() -> None:
    requirement = _object(
        "public_procurement", "bid_requirement", "scale-rule",
        standard_rule_id="has_company_scale_qualification",
        rule_arguments_text='{"company_scale":"소기업"}', value_text='{"text":"소기업"}',
    )
    misleading_fact = _object(
        "company", "qualification", "untrusted-scale",
        qualification_type="소기업", source_code="small_business",
        valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31),
    )
    decision = evaluate_requirement(
        requirement, CompanyEvidenceSnapshot(objects=[misleading_fact]), date(2026, 8, 20),
        RegistryLoader(REGISTRIES).load(),
    )
    assert decision.outcome == "needs_review"
    assert decision.reason_code == "company_scale_document_required"
    assert decision.evidence == []


@pytest.mark.parametrize(("qualification_type", "certification_kind"), [
    ("innobiz", "innobiz"),
    ("mainbiz", "mainbiz"),
])
def test_innovation_qualification_compares_certification_period(
    qualification_type: str, certification_kind: str,
) -> None:
    requirement = _object(
        "public_procurement", "bid_requirement", f"{qualification_type}-rule",
        standard_rule_id="holds_valid_company_qualification",
        rule_arguments_text=json.dumps({"qualification_type": qualification_type}),
    )
    observation = _object(
        "company", "innovation_certification_observation", f"{qualification_type}-observation",
        certification_kind=certification_kind,
        valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31),
    )
    decision = evaluate_requirement(
        requirement, CompanyEvidenceSnapshot(objects=[observation]), date(2026, 8, 20),
        RegistryLoader(REGISTRIES).load(),
    )
    assert decision.outcome == "satisfied"
    assert decision.reason_code == "qualification_valid"


def test_venture_qualification_uses_disclosure_lookup_without_period_comparison() -> None:
    requirement = _object(
        "public_procurement", "bid_requirement", "venture-rule",
        standard_rule_id="holds_valid_company_qualification",
        rule_arguments_text='{"qualification_type":"venture_business"}',
    )
    disclosure = _object(
        "company", "venture_company_disclosure", "venture-disclosure",
        status="currently_disclosed",
    )
    decision = evaluate_requirement(
        requirement, CompanyEvidenceSnapshot(objects=[disclosure]), date(2026, 8, 20),
        RegistryLoader(REGISTRIES).load(),
    )
    assert decision.outcome == "satisfied"
    assert decision.reason_code == "qualification_valid"


@pytest.mark.asyncio
async def test_incomplete_extraction_never_reports_full_satisfaction() -> None:
    runner = AssessmentFixtureRunner()
    original_run = runner.run

    async def run_with_partial_notice(catalog, capability_id, inputs):
        result = await original_run(catalog, capability_id, inputs)
        if capability_id == "get_bid_notice":
            result.objects[0].properties["extraction_completeness"] = "api_only"
            result.objects[0].properties["requires_review"] = True
        return result

    runner.run = run_with_partial_notice
    result = await execute_bid_eligibility_assessment(
        runner,
        RegistryLoader(REGISTRIES).load(),
        "assess_company_bid_eligibility",
        {"business_registration_number": "1234567890", "bid_notice_id": "R26TEST:00"},
    )

    assessment = next(item for item in result.objects if item.object_type == "bid_eligibility_assessment")
    assert assessment.properties["outcome"] == "needs_review"
    assert assessment.properties["lifecycle_status"] == "review_required"
