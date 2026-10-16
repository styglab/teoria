from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import psycopg

from teoria.domains.public_procurement.market_analysis.field_identity import (
    _normalized_category,
)
from teoria.domains.public_procurement.market_analysis.outcomes.reader import (
    ProcurementOutcomeReader,
)
from teoria.domains.public_procurement.market_analysis.periods import (
    _resolve_profile_period,
)
from teoria.domains.public_procurement.market_analysis.related_projects.similarity import (
    number as _number,
)
from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import (
    CapabilityExecutionError,
    CapabilityResult,
)
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.provenance import Provenance


def _outcome_contractor(row: dict[str, Any]) -> dict[str, Any]:
    source_role = str(row.get("supplier_role_name") or "").strip()
    joint = bool(row.get("is_joint_contract"))
    role = (
        "sole"
        if not joint
        else "consortium_lead"
        if source_role in {"주계약업체", "대표사", "주계약자", "대표업체"}
        else "consortium_member"
    )
    return {
        "business_registration_number": row.get("business_registration_number"),
        "company_name": row.get("supplier_name"),
        "company_role": role,
        "company_role_label": {
            "sole": "단독",
            "consortium_lead": "대표사",
            "consortium_member": "구성원",
        }[role],
        "share_percent": _number(row.get("participation_share_rate")),
    }


async def execute_procurement_outcome_search(
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
    *,
    reader: ProcurementOutcomeReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    period_from, period_to, _, period_type, from_year, to_year = (
        _resolve_profile_period(
            inputs,
            capability_id=capability_id,
        )
    )
    organization_code = str(inputs["organization_code"])
    page = int(inputs.get("page", 1))
    page_size = int(inputs.get("page_size", 20))
    sort = str(inputs.get("sort", "latest_activity_desc"))
    if sort != "latest_activity_desc":
        raise CapabilityExecutionError(
            "invalid_sort",
            f"unsupported sort '{sort}'",
            capability_id=capability_id,
        )
    work_type = str(inputs.get("work_type") or "").strip() or None
    large_category = _normalized_category(inputs.get("large_category"))
    middle_category = _normalized_category(inputs.get("middle_category"))
    field_code = str(inputs.get("field_code") or "").strip() or None
    query = " ".join(str(inputs.get("query") or "").split()).casefold()
    try:
        award_rows, contract_rows = await (reader or ProcurementOutcomeReader()).find(
            catalog,
            organization_code=organization_code,
            period_from=period_from,
            period_to=period_to,
        )
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error",
            str(exc),
            capability_id=capability_id,
            source_id="teoria_public_procurement",
            retryable=isinstance(exc, psycopg.Error),
        ) from exc

    outcomes: dict[str, dict[str, Any]] = {}
    notice_to_outcome: dict[str, str] = {}
    organization_name = None
    for row in award_rows:
        source_bid_notice_id = str(row["bid_notice_id"])
        outcome_key = str(row.get("notice_lineage_id") or source_bid_notice_id)
        bid_notice_id = str(
            row.get("representative_bid_notice_id") or source_bid_notice_id
        )
        notice_to_outcome[source_bid_notice_id] = outcome_key
        organization_name = organization_name or row.get("organization_name")
        item = outcomes.setdefault(
            outcome_key,
            {
                "outcome_id": outcome_key,
                "bid_notice_id": bid_notice_id,
                "notice_lineage_id": outcome_key,
                "root_bid_notice_id": row.get("root_bid_notice_id"),
                "lineage_count": row.get("lineage_count", 1),
                "notice_name": row.get("notice_name"),
                "organization_code": organization_code,
                "organization_name": row.get("organization_name"),
                "awards": [],
                "contracts": [],
                "_classification": None,
            },
        )
        award = {
            "award_id": row.get("award_id"),
            "bid_classification_number": row.get("bid_classification_number"),
            "rebid_number": row.get("rebid_number"),
            "award_date": row.get("award_date"),
            "winner_name": row.get("winner_name"),
            "winner_business_registration_number": row.get(
                "winner_business_registration_number"
            ),
            "winning_amount": _number(row.get("winning_amount")),
            "winning_rate": _number(row.get("winning_rate")),
        }
        item["awards"].append(award)
        if item["_classification"] is None:
            item["_classification"] = {
                "work_type": row.get("work_type"),
                "field_code": row.get("field_code"),
                "field_name": row.get("field_name"),
                "large_category": row.get("large_category"),
                "middle_category": row.get("middle_category"),
            }

    contract_versions: dict[str, list[dict[str, Any]]] = {}
    for row in contract_rows:
        contract_versions.setdefault(str(row["contract_event_id"]), []).append(row)
    for contract_event_id, versions in contract_versions.items():
        latest_date = max(
            (row.get("contract_date") for row in versions if row.get("contract_date")),
            default=None,
        )
        latest_versions = [
            row for row in versions if row.get("contract_date") == latest_date
        ]
        representative = latest_versions[0] if latest_versions else versions[0]
        bid_notice_id = representative.get("bid_notice_id")
        outcome_id = str(
            notice_to_outcome.get(str(bid_notice_id), str(bid_notice_id))
            if bid_notice_id
            else f"contract:{contract_event_id}"
        )
        organization_name = organization_name or representative.get("organization_name")
        item = outcomes.setdefault(
            outcome_id,
            {
                "outcome_id": outcome_id,
                "bid_notice_id": bid_notice_id,
                "notice_name": representative.get("notice_name"),
                "organization_code": organization_code,
                "organization_name": representative.get("organization_name"),
                "awards": [],
                "contracts": [],
                "_classification": None,
            },
        )
        contractors_by_key: dict[str, dict[str, Any]] = {}
        for row in latest_versions:
            contractor = _outcome_contractor(row)
            key = str(
                contractor.get("business_registration_number")
                or f"sequence:{row.get('supplier_sequence')}"
            )
            contractors_by_key[key] = contractor
        contractors = list(contractors_by_key.values())
        lead = next(
            (
                value
                for value in contractors
                if value["company_role"] == "consortium_lead"
            ),
            contractors[0] if len(contractors) == 1 else None,
        )
        contract = {
            "contract_event_id": contract_event_id,
            "unified_contract_number": representative.get("unified_contract_number"),
            "first_contract_date": min(
                row["contract_date"] for row in versions if row.get("contract_date")
            )
            if any(row.get("contract_date") for row in versions)
            else None,
            "contract_date": latest_date,
            "contract_amount": _number(representative.get("contract_amount")),
            "contract_version_count": len(
                {row.get("unified_contract_number") for row in versions}
            ),
            "lead_contractor": lead,
            "contractor_count": len(contractors),
            "contractors": contractors,
        }
        item["contracts"].append(contract)
        if not item.get("notice_name"):
            item["notice_name"] = representative.get("notice_name")
        if not item.get("organization_name"):
            item["organization_name"] = representative.get("organization_name")
        if item["_classification"] is None:
            item["_classification"] = {
                "work_type": representative.get("work_type"),
                "field_code": representative.get("field_code"),
                "field_name": representative.get("field_name"),
                "large_category": representative.get("large_category"),
                "middle_category": representative.get("middle_category"),
            }

    filtered = []
    for item in outcomes.values():
        item["awards"].sort(
            key=lambda value: value.get("award_date") or date.min, reverse=True
        )
        item["contracts"].sort(
            key=lambda value: value.get("contract_date") or date.min,
            reverse=True,
        )
        item["award"] = item["awards"][0] if item["awards"] else None
        item["contract"] = item["contracts"][0] if item["contracts"] else None
        item["stage"] = "contract" if item["contract"] else "award"
        item["stage_name"] = "계약" if item["contract"] else "낙찰"
        item["latest_activity_date"] = (
            item["contract"]["contract_date"]
            if item["contract"]
            else item["award"]["award_date"]
        )
        classification = item.pop("_classification") or {}
        item.update(classification)
        activity_date = item["latest_activity_date"]
        if not activity_date or not period_from <= activity_date < period_to:
            continue
        if work_type and item.get("work_type") != work_type:
            continue
        if (
            large_category
            and _normalized_category(item.get("large_category")) != large_category
        ):
            continue
        if (
            middle_category
            and _normalized_category(item.get("middle_category")) != middle_category
        ):
            continue
        if field_code and str(item.get("field_code") or "") != field_code:
            continue
        if query:
            searchable = " ".join(
                str(value or "")
                for value in (
                    item.get("notice_name"),
                    item.get("bid_notice_id"),
                    item.get("outcome_id"),
                    *(award.get("winner_name") for award in item["awards"]),
                    *(
                        contractor.get("company_name")
                        for contract in item["contracts"]
                        for contractor in contract["contractors"]
                    ),
                )
            ).casefold()
            if query not in searchable:
                continue
        filtered.append(item)
    filtered.sort(
        key=lambda item: (item["latest_activity_date"], item["outcome_id"]),
        reverse=True,
    )
    total_items = len(filtered)
    offset = (page - 1) * page_size
    page_items = filtered[offset : offset + page_size]
    observed_at = datetime.now(timezone.utc)
    objects = []
    for item in page_items:
        properties = {
            key: item.get(key)
            for key in (
                "outcome_id",
                "bid_notice_id",
                "notice_name",
                "stage",
                "latest_activity_date",
            )
        }
        provenance = Provenance(
            kind="execution",
            source="teoria_runtime",
            operation=f"market_context.{capability_id}",
            mapping="public_procurement_market_context",
            observed_at=observed_at,
            record_keys=[str(item["outcome_id"])],
        )
        objects.append(
            MaterializedObject(
                ontology="public_procurement",
                object_type="procurement_outcome",
                object_id=str(item["outcome_id"]),
                properties=properties,
                provenance=[provenance],
                property_provenance={key: [provenance] for key in properties},
            )
        )
    pagination = {
        "page": page,
        "page_size": page_size,
        "total_items": total_items,
        "total_pages": (total_items + page_size - 1) // page_size,
    }
    return CapabilityResult(
        capability_id=capability_id,
        objects=objects,
        pagination=pagination,
        outcome={
            "organization": {"code": organization_code, "name": organization_name},
            "items": page_items,
            "pagination": pagination,
            "analysis_basis": {
                "organization_code": organization_code,
                "period_from": period_from,
                "period_to": period_to - timedelta(days=1),
                "period_from_year": from_year,
                "period_to_year": to_year,
                "period_type": period_type,
                "work_type": work_type,
                "field_filter": {
                    "large_category": large_category,
                    "middle_category": middle_category,
                    "field_code": field_code,
                },
                "query": query or None,
                "deduplication": "notice_outcome_with_original_contract_merge",
                "sort": sort,
            },
            "registry_version": catalog.release.version
            if catalog.release
            else "unpublished",
            "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
        },
    )
