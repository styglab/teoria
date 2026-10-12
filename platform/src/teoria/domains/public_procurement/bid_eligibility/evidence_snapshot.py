from __future__ import annotations

from typing import Any

from teoria.domains.public_procurement.bid_eligibility.models import CompanyEvidenceSnapshot
from teoria.runtime.capability.contracts import CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject, OntologyMaterializer


def _snapshot_from_results(
    calls: dict[str, dict[str, Any]],
    results: list[CapabilityResult | BaseException],
) -> CompanyEvidenceSnapshot:
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


def _merge_snapshots(*snapshots: CompanyEvidenceSnapshot) -> CompanyEvidenceSnapshot:
    merged = CompanyEvidenceSnapshot()
    seen: set[str] = set()
    for snapshot in snapshots:
        merged.unavailable_capabilities.update(snapshot.unavailable_capabilities)
        for item in snapshot.objects:
            if item.object_id not in seen:
                merged.objects.append(item)
                seen.add(item.object_id)
    return merged


def _objects(result: CapabilityResult, object_type: str) -> list[MaterializedObject]:
    return [item for item in result.objects if item.object_type == object_type]


def _company_id(snapshot: CompanyEvidenceSnapshot, business_number: str) -> str:
    company = next((item for item in snapshot.objects if item.object_type == "business_registration"), None)
    if company:
        return company.object_id
    return OntologyMaterializer._id(
        "company",
        "business_registration",
        {"business_registration_number": business_number, "parents": []},
    )
