from __future__ import annotations

from collections import OrderedDict
from datetime import date
import hashlib
import json
import time
from typing import Any

from teoria.domains.public_procurement.bid_eligibility.models import CompanyEvidenceSnapshot
from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject

from .assessment_policy import CACHE_MAX_ENTRIES, CACHE_TTL_SECONDS, RULESET_VERSION
from .evidence_snapshot import _merge_snapshots


def _runtime_cache(runner: Any) -> Any:
    cache = getattr(runner, "cache", None)
    if cache is None:
        from teoria.runtime.cache import MemoryRuntimeCache

        cache = MemoryRuntimeCache()
        runner.cache = cache
    return cache


def clear_assessment_cache() -> None:
    _assessment_cache.clear()
    _batch_summary_cache.clear()
    _company_evidence_cache.clear()


def _get_company_evidence_cache(key: str) -> CompanyEvidenceSnapshot | None:
    cached = _company_evidence_cache.get(key)
    if cached is None:
        return None
    if time.monotonic() - cached[0] >= CACHE_TTL_SECONDS:
        del _company_evidence_cache[key]
        return None
    _company_evidence_cache.move_to_end(key)
    return _merge_snapshots(cached[1])


def _put_company_evidence_cache(key: str, snapshot: CompanyEvidenceSnapshot) -> None:
    _company_evidence_cache[key] = (time.monotonic(), _merge_snapshots(snapshot))
    _company_evidence_cache.move_to_end(key)
    while len(_company_evidence_cache) > CACHE_MAX_ENTRIES:
        _company_evidence_cache.popitem(last=False)


def _assessment_fingerprint(
    catalog: RegistryCatalog,
    business_number: str,
    notice: MaterializedObject,
    requirements: list[MaterializedObject],
    snapshot: CompanyEvidenceSnapshot,
    reference_date: date,
) -> str:
    return _hash({
        "business_registration_number": business_number,
        "bid_notice_id": notice.properties.get("bid_notice_id"),
        "reference_date": reference_date,
        "participation_mode": snapshot.assessment_context.get("participation_mode"),
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
    })


def _get_batch_summary_cache(
    fingerprint: str,
) -> tuple[dict[str, Any], MaterializedObject] | None:
    cached = _batch_summary_cache.get(fingerprint)
    if cached is None:
        return None
    if time.monotonic() - cached[0] >= CACHE_TTL_SECONDS:
        del _batch_summary_cache[fingerprint]
        return None
    _batch_summary_cache.move_to_end(fingerprint)
    return dict(cached[1]), cached[2].model_copy(deep=True)


def _put_batch_summary_cache(
    fingerprint: str,
    summary: dict[str, Any],
    assessment: MaterializedObject,
) -> None:
    _batch_summary_cache[fingerprint] = (
        time.monotonic(), dict(summary), assessment.model_copy(deep=True),
    )
    _batch_summary_cache.move_to_end(fingerprint)
    while len(_batch_summary_cache) > CACHE_MAX_ENTRIES:
        _batch_summary_cache.popitem(last=False)


def _hash(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


_assessment_cache: OrderedDict[str, tuple[float, CapabilityResult]] = OrderedDict()


_batch_summary_cache: OrderedDict[str, tuple[float, dict[str, Any], MaterializedObject]] = OrderedDict()


_company_evidence_cache: OrderedDict[str, tuple[float, CompanyEvidenceSnapshot]] = OrderedDict()
