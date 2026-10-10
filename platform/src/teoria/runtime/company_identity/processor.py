from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.runner import CapabilityResult


_DETAIL_CACHE_TTL_SECONDS = 21_600


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


async def execute_company_identifier_resolution(
    runner: Any,
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
) -> CapabilityResult:
    business_number = _digits(inputs.get("business_registration_number"))
    company_name = str(inputs.get("company_name") or "").strip()

    search_result = await runner._run(
        catalog,
        "search_companies_by_name",
        {"company_name": company_name},
        include_raw_responses=False,
    )
    registrations = {
        item.object_id: item
        for item in search_result.objects
        if item.object_type == "business_registration"
        and _digits(item.properties.get("business_registration_number")) == business_number
    }
    matched_links = [
        link for link in search_result.links
        if link.link_type == "legal_entity_has_business_registration"
        and link.target_object_id in registrations
    ]
    legal_entity_ids = {link.source_object_id for link in matched_links}
    legal_entities = [
        item for item in search_result.objects
        if item.object_type == "legal_entity" and item.object_id in legal_entity_ids
    ]
    if len(legal_entities) != 1:
        reason = (
            "multiple_exact_business_number_matches"
            if len(legal_entities) > 1
            else "exact_business_number_match_not_found"
        )
        return _unresolved(capability_id, business_number, reason, company_name=company_name)

    legal_entity = legal_entities[0]
    confirmed_links = [
        link for link in matched_links if link.source_object_id == legal_entity.object_id
    ]
    confirmed_registrations = [
        item for identity, item in registrations.items()
        if any(link.target_object_id == identity for link in confirmed_links)
    ]
    corporate_number = _digits(
        legal_entity.properties.get("corporate_registration_number")
    )
    identifiers = {
        "business_registration_number": business_number,
        "corporate_registration_number": corporate_number or None,
        "financial_supervisory_unique_number": legal_entity.properties.get(
            "financial_supervisory_unique_number"
        ),
    }
    return CapabilityResult(
        capability_id=capability_id,
        objects=[legal_entity, *confirmed_registrations],
        links=confirmed_links,
        outcome={
            "resolution_status": "confirmed",
            "resolution_method": "fsc_business_number_exact_match",
            "company_name": company_name,
            "identifiers": identifiers,
            "evidence": [
                {
                    "source": "fsc_company_basic",
                    "fact": "exact_business_registration_number_match",
                    "value": business_number,
                },
            ],
            "warnings": (
                []
                if str(legal_entity.properties.get("legal_name") or "").strip() == company_name
                else ["company_name_used_for_candidate_search_only"]
            ),
        },
    )


def _unresolved(
    capability_id: str,
    business_number: str,
    reason: str,
    *,
    company_name: str | None = None,
) -> CapabilityResult:
    return CapabilityResult(
        capability_id=capability_id,
        outcome={
            "resolution_status": "unresolved",
            "resolution_method": None,
            "company_name": company_name,
            "identifiers": {
                "business_registration_number": business_number,
                "corporate_registration_number": None,
                "financial_supervisory_unique_number": None,
            },
            "evidence": [],
            "warnings": [reason],
        },
    )


async def execute_company_detail_context(
    runner: Any,
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
) -> CapabilityResult:
    business_number = _digits(inputs.get("business_registration_number"))
    company_name = str(inputs.get("company_name") or "").strip()
    year_limit = int(inputs.get("financial_year_limit", 3))
    lookback_years = int(inputs.get("financial_lookback_years", 7))
    include_relationships = bool(inputs.get("include_relationships", True))
    cache_inputs = {
        "business_registration_number": business_number,
        "company_name": re.sub(r"\s+", "", company_name).casefold(),
        "financial_year_limit": year_limit,
        "financial_lookback_years": lookback_years,
        "include_relationships": include_relationships,
    }
    cache_key = runner.cache.key(
        catalog.release.version if catalog.release else "draft",
        capability_id,
        cache_inputs,
    )
    cached = await runner.cache.get(cache_key)
    if cached is not None:
        result = cached
        if result.outcome is not None:
            result.outcome["cache"] = {"status": "hit", "ttl_seconds": _DETAIL_CACHE_TTL_SECONDS}
        return result
    lock_token = await runner.cache.acquire_lock(cache_key, 30)
    if lock_token is None:
        for _ in range(20):
            await asyncio.sleep(0.1)
            cached = await runner.cache.get(cache_key)
            if cached is not None:
                if cached.outcome is not None:
                    cached.outcome["cache"] = {
                        "status": "hit_after_wait",
                        "ttl_seconds": _DETAIL_CACHE_TTL_SECONDS,
                    }
                return cached

    started_at = datetime.now(timezone.utc)
    resolution_value, status_value = await asyncio.gather(
        _safe_run(
            runner, catalog, "resolve_company_identifiers",
            {"business_registration_number": business_number, "company_name": company_name},
        ),
        _safe_run(
            runner, catalog, "get_business_registration_status",
            {"business_registration_numbers": [business_number]},
        ),
    )
    errors: list[dict[str, Any]] = []
    sections: dict[str, dict[str, Any]] = {}
    all_results: list[CapabilityResult] = []

    resolution_result, resolution_error = resolution_value
    status_result, status_error = status_value
    if status_result is not None:
        all_results.append(status_result)
        sections["business_status"] = {
            "status": "available" if _has_type(status_result, "taxpayer_status_observation") else "no_data"
        }
    else:
        sections["business_status"] = {"status": "error"}
        errors.append(_error("business_status", status_error))

    resolution = (
        dict(resolution_result.outcome or {})
        if resolution_result is not None
        else {
            "resolution_status": "error",
            "identifiers": {
                "business_registration_number": business_number,
                "corporate_registration_number": None,
            },
        }
    )
    if resolution_result is not None:
        all_results.append(resolution_result)
    else:
        errors.append(_error("resolution", resolution_error))
    corporate_number = (
        resolution.get("identifiers", {}).get("corporate_registration_number")
        if resolution.get("resolution_status") == "confirmed"
        else None
    )

    searched_years: list[int] = []
    available_years: list[int] = []
    no_data_years: list[int] = []
    error_years: list[int] = []
    financial_entries: list[dict[str, Any]] = []
    profile_payload: list[dict[str, Any]] = []
    relationship_payload: list[dict[str, Any]] = []

    if corporate_number:
        latest_finalized_year = datetime.now(timezone.utc).year - 1
        searched_years = list(range(latest_finalized_year, latest_finalized_year - lookback_years, -1))
        profile_task = _safe_run(
            runner, catalog, "get_company_profile",
            {"corporate_registration_number": corporate_number},
        )
        relationship_task = (
            _safe_run(
                runner, catalog, "get_company_relationships",
                {"corporate_registration_number": corporate_number},
            )
            if include_relationships else None
        )
        finance_tasks = [
            _safe_run(
                runner, catalog, "get_company_financials",
                {"corporate_registration_number": corporate_number, "fiscal_year": year},
            )
            for year in searched_years
        ]
        gathered = await asyncio.gather(
            profile_task,
            *(finance_tasks),
            *([relationship_task] if relationship_task is not None else []),
        )
        profile_result, profile_error = gathered[0]
        finance_values = gathered[1:1 + len(finance_tasks)]
        relationship_value = gathered[-1] if relationship_task is not None else None

        if profile_result is not None:
            all_results.append(profile_result)
            profile_payload = _objects(profile_result, {"legal_entity", "postal_address", "business_registration"})
            sections["company_profile"] = {"status": "available" if profile_payload else "no_data"}
        else:
            sections["company_profile"] = {"status": "error"}
            errors.append(_error("company_profile", profile_error))

        for year, (finance_result, finance_error) in zip(searched_years, finance_values, strict=True):
            if finance_result is None:
                error_years.append(year)
                errors.append(_error("financials", finance_error, fiscal_year=year))
                continue
            statements = _objects(finance_result, {"financial_statement", "financial_fact"})
            if statements:
                available_years.append(year)
                if len(financial_entries) < year_limit:
                    financial_entries.append({
                        "fiscal_year": year,
                        "status": "available",
                        "objects": statements,
                    })
                    all_results.append(finance_result)
            else:
                no_data_years.append(year)
        financial_status = "available" if available_years else ("error" if error_years else "no_data")
        sections["financials"] = {
            "status": financial_status,
            "completeness": "complete" if len(available_years) >= year_limit else "partial",
            "reason": None if len(available_years) >= year_limit else "fewer_than_requested_available_years",
        }

        if relationship_value is None:
            sections["relationships"] = {"status": "not_requested"}
        else:
            relationship_result, relationship_error = relationship_value
            if relationship_result is not None:
                all_results.append(relationship_result)
                relationship_payload = _objects(
                    relationship_result, {"organization_relationship", "legal_entity"}
                )
                sections["relationships"] = {
                    "status": "available" if _has_type(
                        relationship_result, "organization_relationship"
                    ) else "no_data"
                }
            else:
                sections["relationships"] = {"status": "error"}
                errors.append(_error("relationships", relationship_error))
    else:
        sections["company_profile"] = {"status": "unavailable", "reason": "identifier_unresolved"}
        sections["financials"] = {"status": "unavailable", "reason": "identifier_unresolved"}
        sections["relationships"] = {
            "status": "not_requested" if not include_relationships else "unavailable",
            "reason": None if not include_relationships else "identifier_unresolved",
        }

    objects, links = _merge_results(all_results)
    sources = sorted({
        provenance.source
        for result in all_results
        for item in [*result.objects, *result.links]
        for provenance in item.provenance
        if provenance.kind == "source"
    })
    outcome = {
        "resolution": {
            "status": resolution.get("resolution_status"),
            "business_registration_number": business_number,
            "corporate_registration_number": corporate_number,
            "resolution_method": resolution.get("resolution_method"),
            "warnings": resolution.get("warnings", []),
        },
        "business_status": _objects(status_result, {"taxpayer_status_observation"}) if status_result else [],
        "company_profile": profile_payload,
        "financials": financial_entries,
        "financial_availability": {
            "requested_limit": year_limit,
            "lookback_years": lookback_years,
            "searched_years": searched_years,
            "available_years": available_years,
            "no_data_years": no_data_years,
            "error_years": error_years,
            "latest_available_year": available_years[0] if available_years else None,
        },
        "relationships": relationship_payload,
        "sections": sections,
        "data_availability": {
            key: value["status"] == "available" for key, value in sections.items()
        },
        "sources": sources,
        "observed_at": started_at.isoformat(),
        "partial_failure": bool(errors),
        "errors": errors,
        "cache": {"status": "miss", "ttl_seconds": _DETAIL_CACHE_TTL_SECONDS},
    }
    result = CapabilityResult(
        capability_id=capability_id,
        objects=objects,
        links=links,
        outcome=outcome,
    )
    if _is_cacheable_detail_result(resolution, errors):
        await runner.cache.set(cache_key, result, _DETAIL_CACHE_TTL_SECONDS)
    if lock_token is not None:
        await runner.cache.release_lock(cache_key, lock_token)
    return result


def _is_cacheable_detail_result(
    resolution: dict[str, Any], errors: list[dict[str, Any]],
) -> bool:
    return not errors and resolution.get("resolution_status") == "confirmed"


async def _safe_run(
    runner: Any,
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
) -> tuple[CapabilityResult | None, Exception | None]:
    try:
        return await runner._run(
            catalog, capability_id, inputs, include_raw_responses=False,
        ), None
    except Exception as exc:  # section isolation is the contract of this aggregate capability
        return None, exc


def _objects(result: CapabilityResult, types: set[str]) -> list[dict[str, Any]]:
    return [
        {
            "ontology": item.ontology,
            "type": item.object_type,
            "id": item.object_id,
            "properties": item.model_dump(mode="json")["properties"],
        }
        for item in result.objects if item.object_type in types
    ]


def _has_type(result: CapabilityResult, object_type: str) -> bool:
    return any(item.object_type == object_type for item in result.objects)


def _error(section: str, error: Exception | None, **context: Any) -> dict[str, Any]:
    return {
        "section": section,
        "code": getattr(error, "code", "section_query_failed"),
        "message": str(error or "unknown error"),
        **context,
    }


def _merge_results(results: list[CapabilityResult]) -> tuple[list[Any], list[Any]]:
    objects: dict[tuple[str, str, str], Any] = {}
    links: dict[tuple[str, str, str, str], Any] = {}
    for result in results:
        for item in result.objects:
            objects[(item.ontology, item.object_type, item.object_id)] = item
        for item in result.links:
            links[(item.ontology, item.link_type, item.source_object_id, item.target_object_id)] = item
    return list(objects.values()), list(links.values())
