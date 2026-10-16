from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
import time
from typing import Any, TYPE_CHECKING

from teoria.domains.public_procurement.bid_eligibility.evaluators import evaluate_requirement
from teoria.domains.public_procurement.bid_eligibility.models import RequirementEvaluation
from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import CapabilityExecutionError, CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject

from .assessment_cache import (
    _assessment_fingerprint,
    _get_batch_summary_cache,
    _put_batch_summary_cache,
    _runtime_cache,
)
from .assessment_policy import CACHE_TTL_SECONDS, RULESET_VERSION
from .evidence_loader import _load_company_evidence, _load_company_evidence_for_dates, logger
from .evidence_snapshot import _objects
from .result_builder import _materialize_batch_summary, _materialize_result


if TYPE_CHECKING:
    from teoria.runtime.capability.runner import CapabilityRunner


async def execute_bid_eligibility_assessment(
    runner: CapabilityRunner,
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
) -> CapabilityResult:
    cache_inputs = {
        "business_registration_number": inputs.get("business_registration_number"),
        "bid_notice_id": inputs.get("bid_notice_id"),
        "reference_date": inputs.get("reference_date"),
        "participation_mode": inputs.get("participation_mode") or "single",
        "registry_version": catalog.release.version if catalog.release else "draft",
        "ruleset_version": RULESET_VERSION,
    }
    runtime_cache = _runtime_cache(runner)
    cache_key = runtime_cache.key(
        catalog.release.version if catalog.release else "draft", capability_id, cache_inputs,
    )
    cached = await runtime_cache.get(cache_key)
    if cached is not None:
        return cached

    result = await _execute_bid_eligibility_assessment_uncached(
        runner, catalog, capability_id, inputs,
    )
    await runtime_cache.set(cache_key, result, int(CACHE_TTL_SECONDS))
    return result


async def _execute_bid_eligibility_assessment_uncached(
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


async def execute_bid_eligibility_assessments(
    runner: CapabilityRunner,
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
) -> CapabilityResult:
    runtime_cache = _runtime_cache(runner)
    shared_cache_key = runtime_cache.key(
        catalog.release.version if catalog.release else "draft", capability_id, inputs,
    )
    shared_cached = await runtime_cache.get(shared_cache_key)
    if shared_cached is not None:
        return shared_cached
    bid_notice_ids = list(dict.fromkeys(str(item) for item in inputs["bid_notice_ids"]))
    if not 1 <= len(bid_notice_ids) <= 100:
        raise CapabilityExecutionError(
            "invalid_batch_size",
            "bid_notice_ids must contain between 1 and 100 unique values",
            capability_id=capability_id,
        )
    started = time.monotonic()
    notice_result, requirements_result = await asyncio.gather(
        runner.run(catalog, "get_bid_notices_by_ids", {"bid_notice_ids": bid_notice_ids}),
        runner.run(catalog, "get_bid_requirements_by_notice_ids", {"bid_notice_ids": bid_notice_ids}),
    )
    notices_by_id = {
        str(item.properties.get("bid_notice_id")): item
        for item in _objects(notice_result, "bid_notice")
    }
    requirements_by_id: dict[str, list[MaterializedObject]] = {
        bid_notice_id: [] for bid_notice_id in bid_notice_ids
    }
    for requirement in _objects(requirements_result, "bid_requirement"):
        requirement_notice_id = str(requirement.properties.get("bid_notice_id"))
        if requirement_notice_id in requirements_by_id:
            requirements_by_id[requirement_notice_id].append(requirement)

    explicit_reference_date = inputs.get("reference_date")
    reference_dates = {
        bid_notice_id: explicit_reference_date or _notice_reference_date(notice)
        for bid_notice_id, notice in notices_by_id.items()
    }
    business_number = str(inputs["business_registration_number"])
    participation_mode = str(inputs.get("participation_mode") or "single")
    snapshots = await _load_company_evidence_for_dates(
        runner, catalog, business_number, set(reference_dates.values())
    )
    summaries: list[dict[str, Any]] = []
    assessments: list[MaterializedObject] = []
    cache_hits = 0
    for bid_notice_id in bid_notice_ids:
        notice = notices_by_id.get(bid_notice_id)
        requirements = requirements_by_id[bid_notice_id]
        if notice is None:
            summaries.append({"bid_notice_id": bid_notice_id, "status": "error", "error_code": "bid_notice_not_found"})
            continue
        if not requirements:
            summaries.append({"bid_notice_id": bid_notice_id, "status": "error", "error_code": "bid_requirements_not_found"})
            continue
        reference_date = reference_dates[bid_notice_id]
        snapshot = snapshots[reference_date]
        snapshot.assessment_context["participation_mode"] = participation_mode
        fingerprint = _assessment_fingerprint(
            catalog, business_number, notice, requirements, snapshot, reference_date,
        )
        cached = _get_batch_summary_cache(fingerprint)
        if cached is not None:
            summary, assessment = cached
            cache_hits += 1
        else:
            evaluations = [
                RequirementEvaluation(
                    requirement=item,
                    decision=evaluate_requirement(item, snapshot, reference_date, catalog),
                )
                for item in requirements
            ]
            assessment, summary = _materialize_batch_summary(
                catalog, business_number, notice, requirements, snapshot, evaluations,
                reference_date, fingerprint,
            )
            _put_batch_summary_cache(fingerprint, summary, assessment)
        assessments.append(assessment)
        summaries.append(summary)
    logger.info(
        "batch bid eligibility assessment completed notices=%d cache_hits=%d duration_ms=%.1f",
        len(bid_notice_ids), cache_hits, (time.monotonic() - started) * 1000,
    )
    result = CapabilityResult(
        capability_id=capability_id,
        objects=assessments,
        outcome={"items": summaries},
    )
    await runtime_cache.set(shared_cache_key, result, int(CACHE_TTL_SECONDS))
    return result


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
