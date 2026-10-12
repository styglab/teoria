from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import time
from typing import Any

import psycopg

from teoria.domains.public_procurement.classification import decorate_field_distribution
from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import CapabilityExecutionError, CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.provenance import Provenance

from ..field_identity import _normalized_category, _procurement_field_identity
from .market_structure import (
    _organization_entry,
    _organization_market_structure,
    _previous_period_comparison,
    _rolling_12m_supplier_entry,
    _supplier_entry,
)
from ..periods import _resolve_profile_period, _shift_years
from .participation_analysis import participation_analysis
from .profile_aggregation import (
    _collapse_profile_contract_versions,
    _drilldown_field_distribution,
    _filter_profile_rows,
    _profile_aggregate,
)
from ..readers import ProcurementProfileReader
from ..related_projects.similarity import number as _number


async def _execute_procurement_profile(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    profile_type: str, reader: ProcurementProfileReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    (
        period_from, period_to, period_years, period_type,
        period_from_year, period_to_year,
    ) = _resolve_profile_period(inputs, capability_id=capability_id)
    organization_entry_target_year = (period_to - timedelta(days=1)).year
    organization_entry_status = None
    if profile_type == "company":
        organization_entry_target_year = int(
            inputs.get("target_year", organization_entry_target_year)
        )
        organization_entry_status = inputs.get("organization_entry_status")
        if organization_entry_status not in {
            None, "first_observed", "reentering", "incumbent",
        }:
            raise CapabilityExecutionError(
                "invalid_organization_entry_status",
                f"unsupported organization_entry_status '{organization_entry_status}'",
                capability_id=capability_id,
            )
        if not (
            period_from.year
            <= organization_entry_target_year
            <= (period_to - timedelta(days=1)).year
        ):
            raise CapabilityExecutionError(
                "invalid_target_year",
                "target_year must be within the selected profile period",
                capability_id=capability_id,
            )
    page = int(inputs.get("page", 1))
    page_size = int(inputs.get("page_size", 20))
    requested_sort = inputs.get("sort")
    sort_by = str(requested_sort or inputs.get("sort_by", "contract_amount"))
    sort_aliases = {
        "contract_amount_desc": "contract_amount",
        "contract_count_desc": "contract_count",
        "latest_contract_desc": "latest_contract",
    }
    sort_by = sort_aliases.get(sort_by, sort_by)
    if sort_by not in {
        "contract_amount", "contract_count", "award_count", "latest_activity",
        "latest_contract",
    }:
        raise CapabilityExecutionError(
            "invalid_sort_by", f"unsupported sort_by '{sort_by}'",
            capability_id=capability_id,
        )
    large_category = _normalized_category(inputs.get("large_category"))
    middle_category = _normalized_category(inputs.get("middle_category"))
    field_code = str(inputs.get("field_code") or "").strip() or None
    work_type = str(inputs.get("work_type") or "").strip() or None
    company_query = (
        " ".join(str(inputs.get("company_query") or "").split()).casefold()
        if profile_type == "organization" else ""
    )
    organization_query = (
        " ".join(str(inputs.get("organization_query") or "").split()).casefold()
        if profile_type == "company" else ""
    )
    allowed_work_types = {"goods", "service", "construction", "foreign", "other", "unknown"}
    if work_type and work_type not in allowed_work_types:
        raise CapabilityExecutionError(
            "invalid_work_type", f"unsupported work_type '{work_type}'",
            capability_id=capability_id,
        )
    entry_period_to = (
        period_to if period_to < date.today() + timedelta(days=1) else date.today()
    )
    entry_period_from = _shift_years(entry_period_to, -1)
    entry_history_from = date(entry_period_from.year - 5, 1, 1)
    organization_entry_history_from = (
        date(2000, 1, 1) if profile_type == "company" else entry_history_from
    )
    # The rolling supplier metric must use the same contract-version population
    # regardless of the profile's requested start year.  Fetch its full fixed
    # history window before collapsing amended/installment contracts.
    source_period_from = min(
        period_from, entry_history_from, organization_entry_history_from,
    )
    organization_code = (
        str(inputs["organization_code"]) if profile_type == "organization" else None
    )
    organization_company_number = (
        "".join(
            character for character in str(inputs.get("business_registration_number") or "")
            if character.isdigit()
        ) or None
        if profile_type == "organization" else None
    )
    company_number = (
        "".join(character for character in str(inputs["business_registration_number"])
                if character.isdigit()) if profile_type == "company" else None
    )
    resolved_reader = reader or ProcurementProfileReader()
    history_result: tuple[dict[str, date], date | None] | None = None
    notice_rows: list[dict[str, Any]] = []
    try:
        activities_task = asyncio.to_thread(
            resolved_reader.activities, catalog, organization_code=organization_code,
            company_numbers=(
                [company_number] if company_number else
                [organization_company_number] if organization_company_number else []
            ),
            period_from=source_period_from, period_to=period_to,
        )
        history_method = (
            getattr(resolved_reader, "organization_award_history", None)
            if profile_type == "organization" else None
        )
        notice_method = (
            getattr(resolved_reader, "notice_publications", None)
            if profile_type == "organization" else None
        )
        pending = [activities_task]
        if history_method is not None:
            pending.append(asyncio.to_thread(
                    history_method, catalog, organization_code=str(organization_code),
                    history_from=entry_history_from, history_to=period_to,
                    work_type=work_type, large_category=large_category,
                    middle_category=middle_category, field_code=field_code,
                ))
        if notice_method is not None:
            pending.append(asyncio.to_thread(
                notice_method, catalog, organization_code=str(organization_code),
                period_from=period_from, period_to=period_to,
            ))
        gathered = await asyncio.gather(*pending)
        rows = gathered[0]
        offset_result = 1
        if history_method is not None:
            history_result = gathered[offset_result]
            offset_result += 1
        if notice_method is not None:
            notice_rows = gathered[offset_result]
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc
    rows = _filter_profile_rows(
        rows, large_category=large_category, middle_category=middle_category,
        field_code=field_code, work_type=work_type,
    )
    notice_rows = _filter_profile_rows(
        notice_rows, large_category=large_category, middle_category=middle_category,
        field_code=field_code, work_type=work_type,
    )
    rows = _collapse_profile_contract_versions(rows)
    missing_first_contract_date_count = len({
        str(row.get("event_key") or row.get("bid_notice_id") or "")
        for row in rows
        if row.get("activity_type") == "contract"
        and row.get("first_contract_date") is None
    } - {""})
    profile_rows = [
        row for row in rows if row.get("activity_date") and row["activity_date"] >= period_from
    ]
    incumbent_share = None
    supplier_entry = None
    supplier_entry_companies: list[dict[str, Any]] = []
    if profile_type == "organization":
        try:
            if history_result is None:
                relationship_rows = [
                    row for row in rows
                    if row.get("activity_type") in {"award", "contract"}
                    and row.get("company_number") and row.get("activity_date")
                ]
                first_dates: dict[str, date] = {}
                for row in relationship_rows:
                    company = str(row["company_number"])
                    observed = row["activity_date"]
                    first_dates[company] = min(first_dates.get(company, observed), observed)
                history_from = entry_history_from
            else:
                first_dates, history_from = history_result
            incumbent_share = _rolling_12m_supplier_entry(
                rows, first_dates, history_from, period_to=entry_period_to,
            )
            target_year = (period_to - timedelta(days=1)).year
            supplier_history_rows = [
                row for row in rows
                if row.get("activity_date") and row["activity_date"] >= entry_history_from
            ]
            supplier_entry, supplier_entry_companies = _supplier_entry(
                supplier_history_rows, target_year=target_year, period_to=period_to,
                history_available_from=history_from,
            )
        except (ValueError, psycopg.Error, RuntimeError) as exc:
            raise CapabilityExecutionError(
                "database_source_error", str(exc), capability_id=capability_id,
                source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
            ) from exc
    dimension = "company" if profile_type == "organization" else "organization"
    summary, relationships, yearly_activity, fields, project_types, work_types = (
        _profile_aggregate(
            profile_rows, relationship_dimension=dimension,
            require_contract_relationship=profile_type == "organization",
            notice_rows=notice_rows if profile_type == "organization" else None,
            period_from=period_from, period_to=period_to,
        )
    )
    if profile_type == "organization":
        summary["company_count_basis"] = "contracted_companies"
    summary["missing_first_contract_date_count"] = missing_first_contract_date_count
    if incumbent_share is not None:
        summary["rolling_12m_supplier_entry"] = incumbent_share
    if supplier_entry is not None:
        summary["supplier_entry"] = supplier_entry
    notice_quarter_distribution = None
    contract_method_distribution = None
    company_structure = None
    previous_period_comparison = None
    if profile_type == "organization":
        contract_count = int(summary.get("contract_event_count") or 0)
        total_amount = summary.get("total_attributed_contract_amount")
        summary["average_contract_amount"] = (
            _number(Decimal(str(total_amount)) / contract_count)
            if total_amount is not None and contract_count else None
        )
        selected_end_year = (period_to - timedelta(days=1)).year
        previous_period_comparison = _previous_period_comparison(
            rows, comparison_year=selected_end_year - 1,
            current_year=selected_end_year, period_to=period_to,
        )
        summary["previous_period_comparison"] = previous_period_comparison
        (
            notice_quarter_distribution,
            contract_method_distribution,
            company_structure,
        ) = _organization_market_structure(
            profile_rows, relationships,
            notice_rows=notice_rows or profile_rows, period_to=period_to,
            rolling_12m=incumbent_share,
        )
        summary["notice_quarter_basis_notice_count"] = sum(
            item["notice_count"] for item in notice_quarter_distribution
        )
    field_distribution_level, field_distribution = _drilldown_field_distribution(
        fields, large_category=large_category, middle_category=middle_category,
        field_code=field_code, work_type=work_type,
    )
    field_distribution = decorate_field_distribution(
        field_distribution, level=field_distribution_level, work_type=work_type,
        large_category=large_category, middle_category=middle_category,
    )
    organization_entry = None
    if profile_type == "company":
        organization_entry, organization_entries = _organization_entry(
            rows,
            target_year=organization_entry_target_year,
            period_to=period_to,
            history_available_from=organization_entry_history_from,
        )
        entries_by_organization = {
            item["organization_code"]: item for item in organization_entries
        }
        for relationship in relationships:
            entry = entries_by_organization.get(
                str(relationship.get("organization_code") or "")
            )
            relationship["organization_entry_status"] = (
                entry["organization_entry_status"] if entry else None
            )
            relationship["organization_entry"] = entry
            # Compatibility for consumers that already use the relationship-level
            # supplier_entry object in the reverse company-to-organization view.
            relationship["supplier_entry"] = ({
                "target_year": organization_entry_target_year,
                "entry_status": entry["organization_entry_status"],
                "entry_status_name": entry["organization_entry_status_name"],
                "previous_contract_date": entry["previous_contract_date"],
                "history_complete_for_lookback": organization_entry[
                    "history_complete_for_lookback"
                ],
            } if entry else None)
        summary["organization_entry"] = organization_entry
        if organization_entry_status:
            relationships = [
                item for item in relationships
                if item.get("organization_entry_status") == organization_entry_status
            ]
    sort_fields = {
        "contract_amount": "total_attributed_contract_amount",
        "contract_count": "contract_event_count",
        "award_count": "award_event_count",
        "latest_activity": "latest_activity_date",
        "latest_contract": "latest_contract_date",
    }
    if company_query:
        relationships = [
            item for item in relationships
            if company_query in " ".join(str(item.get("company_name") or "").split()).casefold()
        ]
    if organization_query:
        relationships = [
            item for item in relationships
            if organization_query in " ".join(
                str(item.get("organization_name") or "").split()
            ).casefold()
        ]
    relationship_key = "company_number" if profile_type == "organization" else "organization_code"
    relationships.sort(key=lambda item: str(item.get(relationship_key) or ""))
    relationships.sort(
        key=lambda item: item.get(sort_fields[sort_by]) or (
            date.min if sort_by in {"latest_activity", "latest_contract"} else 0
        ),
        reverse=True,
    )
    total_items = len(relationships)
    offset = (page - 1) * page_size
    paged = relationships[offset:offset + page_size]
    missing_reasons = []
    if summary["amount_completeness"] != "complete":
        missing_reasons.append("some_contract_amounts_not_attributable")
    if missing_first_contract_date_count:
        missing_reasons.append("some_contract_events_missing_first_contract_date")
    identity = (
        {"code": organization_code, "name": next((row.get("organization_name") for row in profile_rows if row.get("organization_name")), None)}
        if profile_type == "organization" else
        {"business_registration_number": company_number,
         "name": next((row.get("company_name") for row in profile_rows if row.get("company_name")), None)}
    )
    object_type = f"{profile_type}_procurement_profile"
    object_id = organization_code or company_number
    observed_at = datetime.now(timezone.utc)
    provenance = Provenance(
        kind="execution", source="teoria_runtime", operation=f"market_context.{capability_id}",
        mapping="public_procurement_market_context", observed_at=observed_at,
        record_keys=[str(object_id)],
    )
    properties = {
        f"{object_type}_id": str(object_id),
        "relationship_count": (
            summary["company_count"] if profile_type == "organization" else total_items
        ),
    }
    outcome = {
        profile_type: identity,
        "summary": summary,
        f"{dimension}_relationships": paged,
        "yearly_activity": yearly_activity,
        "participation_analysis": participation_analysis(profile_rows, period_from=period_from, period_to=period_to),
        "field_distribution": field_distribution,
        "field_distribution_level": field_distribution_level,
        "field_hierarchy_depth": 1 if work_type == "construction" else 3,
        "project_type_distribution": sorted(
            project_types, key=lambda item: item["event_count"], reverse=True,
        ),
        "work_type_distribution": sorted(
            work_types, key=lambda item: item["event_count"], reverse=True,
        ),
        "pagination": {
            "page": page, "page_size": page_size, "total_items": total_items,
            "total_pages": (total_items + page_size - 1) // page_size,
            "sort": {
                "contract_amount": "contract_amount_desc",
                "contract_count": "contract_count_desc",
                "latest_contract": "latest_contract_desc",
            }.get(sort_by, sort_by),
            "sort_by": sort_by,
        },
        "analysis_basis": {
            "period_from": period_from, "period_to": period_to - timedelta(days=1),
            "period_years": period_years,
            "period_from_year": period_from_year or period_from.year,
            "period_to_year": period_to_year or (period_to - timedelta(days=1)).year,
            "period_type": period_type,
            "amount_basis": "attributed_contract_amount",
            "event_deduplication": "award_contract_linked_and_contract_versions_merged",
            "event_attribution": "contract_first_contract_date",
            "contract_amount_version": "latest_at_or_before_period_end",
            "contract_event_date_basis": "first_contract_date",
            "contract_amount_basis": "latest_version_at_or_before_period_end",
            "contract_amount_year_attribution": "first_contract_year",
            "contract_version_deduplication": "merged_by_contract_event",
            "notice_year_basis": "notice_published_at",
            "award_year_basis": "opening_at_or_final_award_date",
            "participation_year_basis": "opening_at_or_final_award_date_or_bid_at",
            "participation_event_identity": "company_notice_order_classification_rebid",
            "contract_year_basis": "first_contract_date",
            "field_filter": {
                "large_category": large_category,
                "middle_category": middle_category,
                "field_code": field_code,
                "field_name": next((
                    identity.get("name") for row in profile_rows
                    if (identity := _procurement_field_identity(row))
                    and field_code and str(identity.get("code") or "") == field_code
                    and identity.get("name")
                ), None),
            },
            "work_type": work_type,
            "company_query": company_query or None,
            "organization_query": organization_query or None,
            "organization_entry_target_year": (
                organization_entry_target_year if profile_type == "company" else None
            ),
            "organization_entry_status": organization_entry_status,
            "organization_entry_definition": (
                "target_year_contract_and_prior_observable_contract_history"
                if profile_type == "company" else None
            ),
            "company_relationship_sort": {
                "contract_amount": "contract_amount_desc",
                "contract_count": "contract_count_desc",
                "latest_contract": "latest_contract_desc",
            }.get(sort_by, sort_by),
        },
        "data_completeness": {
            "status": "partial",
            "missing_reasons": missing_reasons + ["participation_limited_to_top_10_and_available_winner"],
        },
        "registry_version": catalog.release.version if catalog.release else "unpublished",
        "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
    }
    if profile_type == "organization":
        outcome.update({
            "notice_quarter_distribution": notice_quarter_distribution,
            "notice_quarter_basis": "notice_published_at",
            "contract_method_distribution": contract_method_distribution,
            "contract_method_basis": {
                "competitive": ["일반경쟁", "제한경쟁", "지명경쟁"],
                "direct": ["수의계약"],
                "other": [],
                "unknown": ["원천값 없음", "판정 불가"],
            },
            "company_structure": company_structure,
            "supplier_entry": supplier_entry,
            "deprecated_fields": [{
                "field": "rolling_12m_supplier_entry",
                "replacement": "supplier_entry",
            }],
        })
        if inputs.get("_include_supplier_entry_companies"):
            outcome["_supplier_entry_companies"] = supplier_entry_companies
    if profile_type == "company":
        outcome["organization_entry"] = organization_entry
        outcome["recent_activity"] = sorted(
            [{
                "bid_notice_id": row["bid_notice_id"], "notice_name": row.get("notice_name"),
                "activity_type": row["activity_type"], "activity_date": row["activity_date"],
                "organization_code": row.get("organization_code"),
                "organization_name": row.get("organization_name"),
                "work_type": row.get("work_type"),
            } for row in profile_rows], key=lambda item: item["activity_date"], reverse=True,
        )[:20]
    elif organization_company_number:
        outcome["_relationship_contract_events"] = sorted(
            [{
                "award_event_id": str(row["event_key"]),
                "bid_notice_id": row.get("bid_notice_id"),
                "notice_linkage": (
                    "linked" if row.get("attribution_date_basis") == "notice_published_at"
                    else "unlinked"
                ),
                "notice_name": row.get("notice_name"),
                "attribution_date": row.get("activity_date"),
                "attribution_date_basis": row.get("attribution_date_basis"),
                "first_contract_date": row.get("first_contract_date"),
                "latest_contract_version_date": row.get("latest_contract_version_date"),
                "contract_date": row.get("latest_contract_version_date"),
                "contract_amount": _number(row.get("event_amount")),
                "attributed_contract_amount": _number(row.get("attributed_contract_amount")),
                "attributed_contract_amount_completeness": row.get("amount_completeness"),
                "work_type": row.get("work_type"),
                "field_code": row.get("procurement_classification_number"),
                "field_name": row.get("procurement_classification_name"),
                "organization_match": True,
            } for row in profile_rows if row.get("activity_type") == "contract"],
            key=lambda item: (
                item.get("attribution_date") or date.min,
                item.get("latest_contract_version_date") or date.min,
                item["award_event_id"],
            ), reverse=True,
        )
    return CapabilityResult(
        capability_id=capability_id,
        objects=[MaterializedObject(
            ontology="public_procurement", object_type=object_type,
            object_id=str(object_id), properties=properties, provenance=[provenance],
            property_provenance={key: [provenance] for key in properties},
        )], outcome=outcome,
    )


async def execute_organization_procurement_profile(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: ProcurementProfileReader | None = None,
) -> CapabilityResult:
    return await _execute_procurement_profile(
        catalog, capability_id, inputs, profile_type="organization", reader=reader,
    )


async def execute_company_procurement_profile(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: ProcurementProfileReader | None = None,
) -> CapabilityResult:
    return await _execute_procurement_profile(
        catalog, capability_id, inputs, profile_type="company", reader=reader,
    )


async def execute_organization_supplier_entry_search(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: ProcurementProfileReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    target_year = int(inputs["target_year"])
    status = str(inputs.get("entry_status", "all"))
    if status not in {"all", "first_observed", "reentering", "incumbent"}:
        raise CapabilityExecutionError(
            "invalid_entry_status", f"unsupported entry_status '{status}'",
            capability_id=capability_id,
        )
    sort = str(inputs.get("sort", "contract_amount_desc"))
    if sort not in {
        "contract_amount_desc", "contract_count_desc", "first_contract_desc",
        "latest_contract_desc", "company_name_asc",
    }:
        raise CapabilityExecutionError(
            "invalid_sort", f"unsupported sort '{sort}'", capability_id=capability_id,
        )
    profile_inputs = {
        "organization_code": inputs["organization_code"],
        "period_from_year": target_year, "period_to_year": target_year,
        "period_years": 1, "page": 1, "page_size": 1,
        "_include_supplier_entry_companies": True,
    }
    for key in ("work_type", "large_category", "middle_category", "field_code"):
        if inputs.get(key) is not None:
            profile_inputs[key] = inputs[key]
    profile = await _execute_procurement_profile(
        catalog, capability_id, profile_inputs, profile_type="organization", reader=reader,
    )
    outcome = profile.outcome or {}
    supplier_entry = dict(outcome.get("supplier_entry") or {})
    items = list(outcome.pop("_supplier_entry_companies", []))
    if status != "all":
        items = [item for item in items if item["entry_status"] == status]
    company_query = " ".join(
        str(inputs.get("company_query") or "").split()
    ).casefold()
    if company_query:
        company_number_query = "".join(
            character for character in company_query if character.isdigit()
        )
        items = [
            item for item in items
            if company_query in " ".join(
                str(item.get("company_name") or "").split()
            ).casefold()
            or company_query in str(item.get("company_number") or "").casefold()
            or (
                company_number_query
                and company_number_query in "".join(
                    character for character in str(item.get("company_number") or "")
                    if character.isdigit()
                )
            )
        ]
    if sort == "company_name_asc":
        items.sort(key=lambda item: (
            " ".join(str(item.get("company_name") or "").split()).casefold(),
            item["company_number"],
        ))
    elif sort in {"first_contract_desc", "latest_contract_desc"}:
        key = (
            "target_year_first_contract_date"
            if sort == "first_contract_desc"
            else "target_year_latest_contract_date"
        )
        items.sort(key=lambda item: (
            item.get(key) is None,
            -(item[key].toordinal() if item.get(key) else 0),
            item["company_number"],
        ))
    else:
        key = {
            "contract_amount_desc": "target_year_attributed_contract_amount",
            "contract_count_desc": "target_year_contract_count",
        }[sort]
        items.sort(key=lambda item: (
            item.get(key) is None,
            -(item.get(key) or 0),
            item["company_number"],
        ))
    page, page_size = int(inputs.get("page", 1)), int(inputs.get("page_size", 20))
    total_items = len(items); offset = (page - 1) * page_size
    analysis_basis = {key: supplier_entry.get(key) for key in (
        "target_year", "period_from", "period_to", "lookback_from", "lookback_to",
        "lookback_years", "basis", "history_available_from", "history_complete_for_lookback",
    )}
    analysis_basis.update({key: inputs.get(key) for key in (
        "entry_status", "work_type", "large_category", "middle_category", "field_code",
    )})
    analysis_basis.update({
        "company_query": company_query or None,
        "sort": sort,
        "search_applied_before_pagination": True,
        "supplier_entry_summary_query_independent": True,
    })
    return CapabilityResult(capability_id=capability_id, objects=profile.objects, outcome={
        "organization": outcome.get("organization"), "supplier_entry": supplier_entry,
        "items": items[offset:offset + page_size],
        "pagination": {"page": page, "page_size": page_size, "total_items": total_items,
                       "total_pages": (total_items + page_size - 1) // page_size, "sort": sort},
        "analysis_basis": analysis_basis,
        "registry_version": catalog.release.version if catalog.release else "unpublished",
        "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
    })
