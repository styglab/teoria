from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.assessment.evaluators import evaluate_requirement
from teoria.runtime.assessment.expression import aggregate_expression
from teoria.runtime.assessment.models import CompanyEvidenceSnapshot, RequirementEvaluation
from teoria.runtime.capability.runner import CapabilityExecutionError, CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedLink, MaterializedObject, OntologyMaterializer
from teoria.runtime.provenance import Provenance

if TYPE_CHECKING:
    from teoria.runtime.capability.runner import CapabilityRunner


PROCESSOR_ID = "assessment.evaluate_bid_eligibility"
RULESET_VERSION = "1.0.0"


async def execute_bid_eligibility_assessment(
    runner: CapabilityRunner,
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
) -> CapabilityResult:
    bid_notice_id = str(inputs["bid_notice_id"])
    notice_number, notice_order = _split_bid_notice_id(bid_notice_id, capability_id)
    notice_result, requirements_result = await asyncio.gather(
        runner.run(catalog, "get_bid_notice", {"notice_number": notice_number, "notice_order": notice_order}),
        runner.run(catalog, "get_bid_requirements", {"notice_number": notice_number, "notice_order": notice_order}),
    )
    notices = _objects(notice_result, "bid_notice")
    requirements = _objects(requirements_result, "bid_requirement")
    if not notices:
        raise CapabilityExecutionError(
            "bid_notice_not_found",
            f"bid notice '{bid_notice_id}' was not found",
            capability_id=capability_id,
        )
    if not requirements:
        raise CapabilityExecutionError(
            "bid_requirements_not_found",
            f"no completed eligibility extraction exists for bid notice '{bid_notice_id}'",
            capability_id=capability_id,
        )

    notice = notices[0]
    reference_date = inputs.get("reference_date") or _notice_reference_date(notice)
    business_number = str(inputs["business_registration_number"])
    snapshot = await _load_company_evidence(runner, catalog, business_number, reference_date)
    snapshot.assessment_context["participation_mode"] = str(inputs.get("participation_mode") or "single")
    evaluations = [
        RequirementEvaluation(requirement=item, decision=evaluate_requirement(item, snapshot, reference_date, catalog))
        for item in requirements
    ]
    return _materialize_result(
        catalog,
        capability_id,
        business_number,
        notice,
        requirements,
        snapshot,
        evaluations,
        reference_date,
    )


async def _load_company_evidence(
    runner: CapabilityRunner,
    catalog: RegistryCatalog,
    business_number: str,
    reference_date: date,
) -> CompanyEvidenceSnapshot:
    calls = {
        "get_business_registration_status": {"business_registration_numbers": [business_number]},
        "get_procurement_supplier": {"business_registration_number": business_number},
        "get_procurement_supplier_industries": {"business_registration_number": business_number},
        "get_procurement_supplier_products": {"business_registration_number": business_number},
        "get_procurement_supplier_sanctions": {"business_registration_number": business_number},
        "get_company_qualifications": {
            "business_registration_number": business_number,
            "reference_date": reference_date,
        },
        "verify_venture_company": {"business_registration_number": business_number},
        "verify_innobiz_company": {"business_registration_number": business_number},
        "verify_mainbiz_company": {"business_registration_number": business_number},
        "get_direct_production_confirmations": {
            "business_registration_number": business_number,
            "reference_date": reference_date,
        },
    }
    results = await asyncio.gather(
        *(runner.run(catalog, capability_id, arguments) for capability_id, arguments in calls.items()),
        return_exceptions=True,
    )
    snapshot = CompanyEvidenceSnapshot()
    seen: set[str] = set()
    for (called_capability, _), result in zip(calls.items(), results, strict=True):
        if isinstance(result, BaseException):
            snapshot.unavailable_capabilities.add(called_capability)
            continue
        for item in result.objects:
            if item.object_id not in seen:
                snapshot.objects.append(item)
                seen.add(item.object_id)
    return snapshot


def _materialize_result(
    catalog: RegistryCatalog,
    capability_id: str,
    business_number: str,
    notice: MaterializedObject,
    requirements: list[MaterializedObject],
    snapshot: CompanyEvidenceSnapshot,
    evaluations: list[RequirementEvaluation],
    reference_date: date,
) -> CapabilityResult:
    now = datetime.now(timezone.utc)
    provenance = Provenance(
        kind="execution",
        source="teoria",
        operation=PROCESSOR_ID,
        mapping="assessment_runtime",
        observed_at=now,
        record_keys=[],
    )
    requirement_set_hash = _hash([
        {"id": item.properties.get("requirement_id"), "value": item.properties}
        for item in requirements
    ])
    evidence_fingerprint = _hash([
        {"id": item.object_id, "properties": item.properties}
        for item in snapshot.objects
    ])
    registry_version = catalog.release.version if catalog.release else "draft"
    assessment_fingerprint = _hash({
        "business_registration_number": business_number,
        "bid_notice_id": notice.properties.get("bid_notice_id"),
        "reference_date": reference_date,
        "participation_mode": snapshot.assessment_context.get("participation_mode"),
        "requirement_set_hash": requirement_set_hash,
        "evidence_fingerprint": evidence_fingerprint,
        "ruleset_version": RULESET_VERSION,
        "registry_version": registry_version,
    })
    outcomes = {
        str(item.requirement.properties.get("local_id")): item.decision.outcome
        for item in evaluations
    }
    expression = _parse_expression(notice.properties.get("requirement_expression"))
    if expression is None:
        mandatory_outcomes = {
            key: value
            for key, value in outcomes.items()
            if next(
                item.requirement.properties.get("mandatory", True)
                for item in evaluations
                if str(item.requirement.properties.get("local_id")) == key
            )
        }
        overall = aggregate_expression(None, mandatory_outcomes)
    else:
        overall = aggregate_expression(expression, outcomes)
    incomplete_coverage = (
        notice.properties.get("extraction_completeness") in {"partial", "api_only"}
        or notice.properties.get("requires_review") is True
    )
    if incomplete_coverage and overall == "satisfied":
        overall = "needs_review"
    counts = {value: sum(item.decision.outcome == value for item in evaluations) for value in ("satisfied", "unsatisfied", "needs_review")}
    lifecycle = "review_required" if overall == "needs_review" else "completed"
    assessment = _object(
        "bid_eligibility_assessment",
        assessment_fingerprint,
        {
            "assessment_id": assessment_fingerprint,
            "assessment_fingerprint": assessment_fingerprint,
            "business_registration_number": business_number,
            "bid_notice_id": notice.properties.get("bid_notice_id"),
            "reference_date": reference_date,
            "participation_mode": snapshot.assessment_context.get("participation_mode"),
            "outcome": overall,
            "lifecycle_status": lifecycle,
            "requirement_set_hash": requirement_set_hash,
            "evidence_fingerprint": evidence_fingerprint,
            "ruleset_version": RULESET_VERSION,
            "registry_version": registry_version,
            "satisfied_count": counts["satisfied"],
            "unsatisfied_count": counts["unsatisfied"],
            "needs_review_count": counts["needs_review"],
            "started_at": now,
            "completed_at": now,
        },
        provenance,
    )

    objects: list[MaterializedObject] = [assessment]
    detail_objects: list[MaterializedObject] = []
    evidence_objects: list[MaterializedObject] = []
    links: list[MaterializedLink] = []
    company_id = _company_id(snapshot, business_number)
    links.extend([
        _link("business_registration_has_bid_eligibility_assessment", company_id, assessment.object_id, provenance),
        _link("bid_eligibility_assessment_evaluates_bid_notice", assessment.object_id, notice.object_id, provenance),
    ])
    seen_evidence: set[str] = set()
    for evaluation in evaluations:
        requirement = evaluation.requirement
        requirement_id = _hash({"assessment": assessment.object_id, "requirement": requirement.object_id})
        decision = evaluation.decision
        requirement_assessment = _object(
            "requirement_assessment",
            requirement_id,
            {
                "requirement_assessment_id": requirement_id,
                "assessment_id": assessment.object_id,
                "requirement_id": requirement.properties.get("requirement_id"),
                "business_registration_number": business_number,
                "outcome": decision.outcome,
                "reason_code": decision.reason_code,
                "required_value_text": requirement.properties.get("value_text") or "",
                "evaluated_value_text": decision.evaluated_value_text,
                "reasoning_summary": _reasoning(requirement, decision),
                "evaluator_id": str(requirement.properties.get("standard_rule_id") or requirement.properties.get("requirement_type") or "fallback"),
                "evaluator_version": str(requirement.properties.get("standard_rule_version") or RULESET_VERSION),
                "evaluated_at": now,
            },
            provenance,
        )
        detail_objects.append(requirement_assessment)
        links.extend([
            _link("requirement_assessment_belongs_to_bid_eligibility_assessment", requirement_assessment.object_id, assessment.object_id, provenance),
            _link("requirement_assessment_evaluates_bid_requirement", requirement_assessment.object_id, requirement.object_id, provenance),
            _link("requirement_assessment_evaluated_for_business_registration", requirement_assessment.object_id, company_id, provenance),
        ])
        notice_evidence = _notice_evidence(requirement, now, provenance)
        for evidence, derived in [(notice_evidence, None), *[(_source_evidence(requirement, item, now, provenance), item) for item in decision.evidence]]:
            if evidence.object_id not in seen_evidence:
                evidence_objects.append(evidence)
                seen_evidence.add(evidence.object_id)
            links.append(_link("requirement_assessment_supported_by_evidence", requirement_assessment.object_id, evidence.object_id, provenance))
            if derived and derived.object_type == "qualification":
                links.append(_link("evidence_derived_from_qualification", evidence.object_id, derived.object_id, provenance))
            if derived and derived.object_type == "direct_production_confirmation":
                links.append(_link("evidence_derived_from_direct_production_confirmation", evidence.object_id, derived.object_id, provenance))

    objects.extend([*detail_objects, *evidence_objects, notice, *requirements, *snapshot.objects])
    objects = list({item.object_id: item for item in objects}.values())
    links = list({(item.link_type, item.source_object_id, item.target_object_id): item for item in links}.values())
    return CapabilityResult(capability_id=capability_id, objects=objects, links=links)


def _notice_evidence(requirement: MaterializedObject, now: datetime, provenance: Provenance) -> MaterializedObject:
    excerpt = str(requirement.properties.get("evidence_summary") or requirement.properties.get("original_text") or "")
    evidence_id = _hash({"requirement": requirement.object_id, "kind": "notice_document", "excerpt": excerpt})
    return _object("evidence", evidence_id, {
        "evidence_id": evidence_id,
        "evidence_kind": "notice_document",
        "source_id": "teoria_public_procurement",
        "source_operation_id": "bid_requirements",
        "source_record_id": str(requirement.properties.get("requirement_id") or ""),
        "excerpt": excerpt,
        "observed_at": now,
        "content_hash": _hash(excerpt),
    }, provenance)


def _source_evidence(requirement: MaterializedObject, source: MaterializedObject, now: datetime, provenance: Provenance) -> MaterializedObject:
    evidence_id = _hash({"requirement": requirement.object_id, "source": source.object_id})
    observed = next((value for value in source.properties.values() if value is not None and value != ""), "")
    source_provenance = source.provenance[0] if source.provenance else provenance
    return _object("evidence", evidence_id, {
        "evidence_id": evidence_id,
        "evidence_kind": "structured_api" if source_provenance.kind == "source" else "database_record",
        "source_id": source_provenance.source,
        "source_operation_id": source_provenance.operation,
        "source_record_id": source.object_id,
        "property_path": f"{source.ontology}.{source.object_type}",
        "observed_value_text": str(observed),
        "observed_at": source_provenance.observed_at,
        "valid_from": source.properties.get("valid_from"),
        "valid_until": source.properties.get("valid_until"),
        "content_hash": _hash(source.properties),
    }, provenance)


def _object(object_type: str, object_id: str, properties: dict[str, Any], provenance: Provenance) -> MaterializedObject:
    return MaterializedObject(
        ontology="assessment",
        object_type=object_type,
        object_id=object_id,
        properties={key: value for key, value in properties.items() if value is not None},
        provenance=[provenance],
        property_provenance={key: [provenance] for key, value in properties.items() if value is not None},
    )


def _link(link_type: str, source: str, target: str, provenance: Provenance) -> MaterializedLink:
    return MaterializedLink(
        ontology="assessment",
        link_type=link_type,
        source_object_id=source,
        target_object_id=target,
        provenance=[provenance],
    )


def _company_id(snapshot: CompanyEvidenceSnapshot, business_number: str) -> str:
    company = next((item for item in snapshot.objects if item.object_type == "business_registration"), None)
    if company:
        return company.object_id
    return OntologyMaterializer._id(
        "company",
        "business_registration",
        {"business_registration_number": business_number, "parents": []},
    )


def _notice_reference_date(notice: MaterializedObject) -> date:
    value = notice.properties.get("bid_deadline_at")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date()


def _split_bid_notice_id(value: str, capability_id: str) -> tuple[str, str]:
    if ":" not in value:
        raise CapabilityExecutionError(
            "invalid_bid_notice_id",
            "bid_notice_id must use '<notice_number>:<notice_order>'",
            capability_id=capability_id,
        )
    return tuple(value.rsplit(":", 1))  # type: ignore[return-value]


def _objects(result: CapabilityResult, object_type: str) -> list[MaterializedObject]:
    return [item for item in result.objects if item.object_type == object_type]


def _parse_expression(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except ValueError:
            return None
    return None


def _reasoning(requirement: MaterializedObject, decision: Any) -> str:
    requirement_type = requirement.properties.get("requirement_type") or "custom"
    if decision.outcome == "needs_review":
        return f"{requirement_type} 요건은 현재 근거와 규칙으로 자동 확정할 수 없습니다."
    return f"{requirement_type} 요건을 정규화된 요구값과 회사 근거로 비교했습니다."


def _hash(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
