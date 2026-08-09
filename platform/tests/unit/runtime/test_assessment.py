from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from teoria.registry.loader import RegistryLoader
from teoria.runtime.assessment.expression import aggregate_expression
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
                    operator="equals", value_text='{"text":"active"}', original_text="계속사업자",
                    mandatory=True, evidence_summary="공고문 3쪽 | 계속사업자",
                ),
                _object(
                    "public_procurement", "bid_requirement", "requirement-2",
                    requirement_id="requirement-2", local_id="r2", requirement_type="certificate",
                    operator="valid_on", value_text='{"text":"직접생산확인 8111159801"}',
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
        "unsupported_requirement",
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
