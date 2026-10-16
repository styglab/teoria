from __future__ import annotations

import asyncio
from datetime import date
import logging
from typing import TYPE_CHECKING

from teoria.domains.public_procurement.bid_eligibility.models import CompanyEvidenceSnapshot
from teoria.registry.loader import RegistryCatalog

from .assessment_cache import _get_company_evidence_cache, _hash, _put_company_evidence_cache
from .evidence_snapshot import _merge_snapshots, _snapshot_from_results


if TYPE_CHECKING:
    from teoria.runtime.capability.runner import CapabilityRunner


async def _load_company_evidence_for_dates(
    runner: CapabilityRunner,
    catalog: RegistryCatalog,
    business_number: str,
    reference_dates: set[date],
) -> dict[date, CompanyEvidenceSnapshot]:
    static_calls = {
        "get_business_registration_status": {"business_registration_numbers": [business_number]},
        "get_procurement_supplier": {"business_registration_number": business_number},
        "get_procurement_supplier_industries": {"business_registration_number": business_number},
        "get_procurement_supplier_products": {"business_registration_number": business_number},
        "get_procurement_supplier_sanctions": {"business_registration_number": business_number},
        "verify_venture_company": {"business_registration_number": business_number},
        "verify_innobiz_company": {"business_registration_number": business_number},
        "verify_mainbiz_company": {"business_registration_number": business_number},
    }
    registry_version = catalog.release.version if catalog.release else "draft"
    static_key = _hash({
        "kind": "company_static", "business_registration_number": business_number,
        "registry_version": registry_version,
    })
    static_snapshot = _get_company_evidence_cache(static_key)
    if static_snapshot is None:
        static_results = await asyncio.gather(*(
            runner.run(catalog, capability_id, arguments)
            for capability_id, arguments in static_calls.items()
        ), return_exceptions=True)
        static_snapshot = _snapshot_from_results(static_calls, static_results)
        _put_company_evidence_cache(static_key, static_snapshot)

    async def load_dated(reference_date: date) -> tuple[date, CompanyEvidenceSnapshot]:
        dated_key = _hash({
            "kind": "company_dated", "business_registration_number": business_number,
            "reference_date": reference_date, "registry_version": registry_version,
        })
        cached_dated = _get_company_evidence_cache(dated_key)
        if cached_dated is not None:
            return reference_date, _merge_snapshots(static_snapshot, cached_dated)
        dated_calls = {
            "get_company_qualifications": {
                "business_registration_number": business_number,
                "reference_date": reference_date,
            },
            "get_direct_production_confirmations": {
                "business_registration_number": business_number,
                "reference_date": reference_date,
            },
        }
        dated_results = await asyncio.gather(*(
            runner.run(catalog, capability_id, arguments)
            for capability_id, arguments in dated_calls.items()
        ), return_exceptions=True)
        dated_snapshot = _snapshot_from_results(dated_calls, dated_results)
        _put_company_evidence_cache(dated_key, dated_snapshot)
        return reference_date, _merge_snapshots(static_snapshot, dated_snapshot)

    return dict(await asyncio.gather(*(load_dated(value) for value in reference_dates)))


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
    return _snapshot_from_results(calls, results)


logger = logging.getLogger(__name__)
