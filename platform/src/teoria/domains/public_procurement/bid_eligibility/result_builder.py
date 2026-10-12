from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from teoria.domains.public_procurement.bid_eligibility.models import (
    CompanyEvidenceSnapshot,
    RequirementEvaluation,
)
from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedLink, MaterializedObject
from teoria.runtime.provenance import Provenance

from .assessment_cache import _assessment_fingerprint, _hash
from .assessment_policy import BATCH_PROCESSOR_ID, PROCESSOR_ID, RULESET_VERSION
from .evidence_snapshot import _company_id
from .outcomes import _aggregate_assessment, _key_outcomes, _participation_evaluations


def _materialize_batch_summary(
    catalog: RegistryCatalog,
    business_number: str,
    notice: MaterializedObject,
    requirements: list[MaterializedObject],
    snapshot: CompanyEvidenceSnapshot,
    evaluations: list[RequirementEvaluation],
    reference_date: date,
    assessment_fingerprint: str,
) -> tuple[MaterializedObject, dict[str, Any]]:
    overall, counts = _aggregate_assessment(notice, evaluations)
    now = datetime.now(timezone.utc)
    provenance = Provenance(
        kind="execution", source="teoria", operation=BATCH_PROCESSOR_ID,
        mapping="assessment_runtime", observed_at=now, record_keys=[],
    )
    assessment = _object("bid_eligibility_assessment", assessment_fingerprint, {
        "assessment_id": assessment_fingerprint,
        "assessment_fingerprint": assessment_fingerprint,
        "business_registration_number": business_number,
        "bid_notice_id": notice.properties.get("bid_notice_id"),
        "reference_date": reference_date,
        "participation_mode": snapshot.assessment_context.get("participation_mode"),
        "outcome": overall,
        "lifecycle_status": "review_required" if overall == "needs_review" else "completed",
        "requirement_set_hash": _hash([
            {"id": item.properties.get("requirement_id"), "value": item.properties}
            for item in requirements
        ]),
        "evidence_fingerprint": _hash([
            {"id": item.object_id, "properties": item.properties}
            for item in snapshot.objects
        ]),
        "ruleset_version": RULESET_VERSION,
        "registry_version": catalog.release.version if catalog.release else "draft",
        "satisfied_count": counts["satisfied"],
        "unsatisfied_count": counts["unsatisfied"],
        "needs_review_count": counts["needs_review"],
        "started_at": now,
        "completed_at": now,
    }, provenance)
    participation_evaluations = _participation_evaluations(evaluations)
    problems = sorted(
        (item for item in participation_evaluations if item.decision.outcome in {"unsatisfied", "needs_review"}),
        key=lambda item: 0 if item.decision.outcome == "unsatisfied" else 1,
    )[:2]
    summary = {
        "bid_notice_id": str(notice.properties.get("bid_notice_id")),
        "status": "completed",
        "outcome": overall,
        "satisfied_count": counts["satisfied"],
        "unsatisfied_count": counts["unsatisfied"],
        "needs_review_count": counts["needs_review"],
        "key_outcomes": _key_outcomes(notice, evaluations),
        "issues": [{
            "requirement_id": item.requirement.properties.get("requirement_id"),
            "outcome": item.decision.outcome,
            "summary": _reasoning(item.requirement, item.decision),
        } for item in problems],
    }
    return assessment, summary


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
    assessment_fingerprint = _assessment_fingerprint(
        catalog, business_number, notice, requirements, snapshot, reference_date,
    )
    overall, counts = _aggregate_assessment(notice, evaluations)
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
                "assessment_stage": requirement.properties.get("assessment_stage") or "bid_entry",
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


def _reasoning(requirement: MaterializedObject, decision: Any) -> str:
    requirement_type = requirement.properties.get("requirement_type") or "custom"
    if decision.outcome == "needs_review":
        return f"{requirement_type} 요건은 현재 근거와 규칙으로 자동 확정할 수 없습니다."
    return f"{requirement_type} 요건을 정규화된 요구값과 회사 근거로 비교했습니다."
