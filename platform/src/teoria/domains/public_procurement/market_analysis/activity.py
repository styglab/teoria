from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
import json
import time
from typing import Any

import psycopg

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import CapabilityExecutionError, CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.provenance import Provenance

from .contracts.contract_lineage import _contract_family_summary, _decorate_contract_lineage
from .field_identity import _normalized_category, _procurement_field_identity
from .outcomes import _outcome_contractor
from .periods import _resolve_profile_period
from .readers import ProcurementActivityReader
from .related_projects.similarity import number as _number


def _notice_group_id(record: dict[str, Any]) -> str:
    bid_notice_id = str(record.get("bid_notice_id") or "").strip()
    if bid_notice_id:
        return f"notice:{bid_notice_id}"
    contract = record.get("contract") or {}
    contract_key = str(
        contract.get("contract_event_id")
        or contract.get("unified_contract_number")
        or ""
    ).strip()
    if contract_key:
        return f"contract:{contract_key}"
    award = record.get("award") or {}
    award_key = str(award.get("award_id") or "").strip()
    if award_key:
        return f"award:{award_key}"
    return f"activity:{record['activity_id']}"


def _group_procurement_activity_records(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for record in records:
        group_id = _notice_group_id(record)
        group = groups.setdefault(group_id, {
            "activity_group_id": group_id,
            "bid_notice_id": record.get("bid_notice_id"),
            "notice_linkage": record.get("notice_linkage"),
            "notice": None,
            "_records": [],
            "_awards": {},
            "_contracts": {},
        })
        group["_records"].append(record)

        source_notice = record.get("notice")
        if group["notice"] is None and (
            source_notice is not None or record.get("bid_notice_id")
        ):
            source_notice = source_notice or {}
            amount_candidates = (
                ("allocated_budget", "배정예산"),
                ("estimated_price", "추정가격"),
                ("base_amount", "기초금액"),
            )
            project_amount, amount_basis, amount_basis_name = next((
                (source_notice.get(basis), basis, basis_name)
                for basis, basis_name in amount_candidates
                if source_notice.get(basis) is not None
            ), (None, None, None))
            group["notice"] = {
                "notice_name": record.get("notice_name"),
                "published_at": source_notice.get("published_at"),
                "bid_begin_at": source_notice.get("bid_begin_at"),
                "deadline_at": source_notice.get("deadline_at"),
                "status": source_notice.get("status"),
                "notice_status": source_notice.get("notice_status"),
                "current_status": source_notice.get("current_status"),
                "current_status_label": source_notice.get("current_status_label"),
                "cancellation_reason": source_notice.get("cancellation_reason"),
                "cancellation_at": source_notice.get("cancellation_at"),
                "failure_reason": source_notice.get("failure_reason"),
                "failure_at": source_notice.get("failure_at"),
                "status_source": source_notice.get("status_source"),
                "status_confirmed_at": source_notice.get("status_confirmed_at"),
                "original_notice_id": source_notice.get("original_notice_id"),
                "current_notice_id": source_notice.get("current_notice_id"),
                "revision_number": source_notice.get("revision_number"),
                "is_latest_revision": source_notice.get("is_latest_revision"),
                "work_type": record.get("work_type"),
                "project_amount": project_amount,
                "project_amount_basis": amount_basis,
                "project_amount_basis_name": amount_basis_name,
            }

        for award in record.get("awards") or []:
            award_key = str(award.get("award_id") or "").strip() or json.dumps(
                award, sort_keys=True, default=str,
            )
            group["_awards"][award_key] = dict(award)

        for contract in record.get("contracts") or []:
            contract_key = str(
                contract.get("contract_event_id")
                or contract.get("unified_contract_number")
                or ""
            ).strip()
            if not contract_key:
                continue
            grouped_contract = dict(contract)
            grouped_contract["latest_contract_version_date"] = grouped_contract.pop(
                "contract_date", None,
            )
            grouped_contract["current_contract_amount"] = grouped_contract.pop(
                "contract_amount", None,
            )
            group["_contracts"][contract_key] = grouped_contract

    grouped_records = []
    for group in groups.values():
        records_in_group = group.pop("_records")
        representative = max(
            records_in_group,
            key=lambda item: (
                _PROCUREMENT_ACTIVITY_STAGE_PRIORITY.get(str(item.get("stage")), -1),
                item.get("latest_activity_date") or date.min,
                str(item.get("activity_id") or ""),
            ),
        )
        latest_stage = str(representative["stage"])
        same_stage_dates = [
            item.get("latest_activity_date")
            for item in records_in_group
            if item.get("stage") == latest_stage and item.get("latest_activity_date")
        ]
        awards = list(group.pop("_awards").values())
        awards.sort(
            key=lambda value: (
                value.get("award_date") or date.min,
                str(value.get("award_id") or ""),
            ),
            reverse=True,
        )
        contracts = list(group.pop("_contracts").values())
        _decorate_contract_lineage(
            contracts, bid_notice_id=group.get("bid_notice_id"),
        )
        contracts.sort(
            key=lambda value: (
                value.get("first_contract_date") or date.min,
                str(value.get("contract_event_id") or ""),
            ),
            reverse=True,
        )
        contract_family_summary = _contract_family_summary(contracts)
        group.update({
            "latest_stage": latest_stage,
            "latest_stage_name": representative.get("stage_name"),
            "latest_activity_date": max(same_stage_dates) if same_stage_dates else None,
            "notice_name": representative.get("notice_name"),
            "organization_code": representative.get("organization_code"),
            "organization_name": representative.get("organization_name"),
            "work_type": representative.get("work_type"),
            "field_code": representative.get("field_code"),
            "field_name": representative.get("field_name"),
            "large_category": representative.get("large_category"),
            "middle_category": representative.get("middle_category"),
            "awards": awards,
            "contracts": contracts,
            "result_summary": {
                "award_count": len(awards),
                "contract_event_count": len(contracts),
                "contract_version_count": sum(
                    int(contract.get("contract_version_count") or 0)
                    for contract in contracts
                ),
                **contract_family_summary,
            },
        })
        grouped_records.append(group)
    return grouped_records


async def execute_procurement_activity_search(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: ProcurementActivityReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    period_from, period_to, _, period_type, from_year, to_year = _resolve_profile_period(
        inputs, capability_id=capability_id,
    )
    organization_code = str(inputs["organization_code"])
    company_number = "".join(
        character for character in str(inputs.get("company_number") or "")
        if character.isdigit()
    ) or None
    page = int(inputs.get("page", 1))
    page_size = int(inputs.get("page_size", 20))
    requested_stage = str(inputs.get("stage", "all"))
    view_mode = str(inputs.get("view_mode", "flat"))
    sort = str(inputs.get("sort", "latest_activity_desc"))
    query = " ".join(str(inputs.get("query") or "").split()).casefold()
    work_type = str(inputs.get("work_type") or "").strip() or None
    large_category = _normalized_category(inputs.get("large_category"))
    middle_category = _normalized_category(inputs.get("middle_category"))
    field_code = str(inputs.get("field_code") or "").strip() or None
    stage_as_of = datetime.now(timezone.utc)
    try:
        notices, award_rows, contract_rows, participated_notice_ids = await asyncio.to_thread(
            (reader or ProcurementActivityReader()).find, catalog,
            organization_code=organization_code, period_from=period_from,
            period_to=period_to, company_number=company_number,
        )
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc

    activities: dict[str, dict[str, Any]] = {}
    notice_to_activity: dict[str, str] = {}
    organization_name = None
    for row in notices:
        activity_id = str(row.get("notice_lineage_id") or row["bid_notice_id"])
        organization_name = organization_name or row.get("organization_name")
        activities[activity_id] = {
            "activity_id": activity_id, "bid_notice_id": str(row["bid_notice_id"]),
            "notice_lineage_id": activity_id,
            "root_bid_notice_id": row.get("root_bid_notice_id"),
            "lineage_count": row.get("lineage_count", 1),
            "notice_name": row.get("notice_name"), "notice_linkage": "linked",
            "organization_code": organization_code,
            "organization_name": row.get("organization_name"),
            "notice": {
                "published_at": row.get("published_at"),
                "bid_begin_at": row.get("bid_begin_at"),
                "deadline_at": row.get("bid_deadline_at"),
                "status": row.get("bid_status"),
                "notice_status": row.get("notice_status"),
                "current_status": row.get("current_status"),
                "current_status_label": row.get("current_status_label"),
                "cancellation_reason": row.get("cancellation_reason"),
                "cancellation_at": row.get("cancellation_at"),
                "failure_reason": row.get("failure_reason"),
                "failure_at": row.get("failure_at"),
                "status_source": row.get("status_source"),
                "status_confirmed_at": row.get("status_confirmed_at"),
                "original_notice_id": row.get("original_notice_id"),
                "current_notice_id": row.get("current_notice_id"),
                "revision_number": row.get("revision_number"),
                "is_latest_revision": row.get("is_latest_revision"),
                "allocated_budget": _number(row.get("allocated_budget")),
                "estimated_price": _number(row.get("estimated_price")),
                "base_amount": _number(row.get("base_amount")),
            },
            "awards": [], "contracts": [],
            "work_type": row.get("work_type"), "field_code": row.get("field_code"),
            "field_name": row.get("field_name"),
            "large_category": row.get("large_category"),
            "middle_category": row.get("middle_category"),
            "_notice_status": row.get("notice_status"),
            "_current_status": row.get("current_status"),
            "_bid_status": row.get("bid_status"),
        }
        notice_to_activity[str(row["bid_notice_id"])] = activity_id
        try:
            lineage_members = json.loads(str(row.get("lineage_notices") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            lineage_members = []
        for member in lineage_members:
            if isinstance(member, dict) and member.get("bid_notice_id"):
                notice_to_activity[str(member["bid_notice_id"])] = activity_id

    participated_activity_ids = {
        notice_to_activity.get(notice_id, notice_id)
        for notice_id in participated_notice_ids
    }

    for row in award_rows:
        linked_id = str(row.get("bid_notice_id") or "") or None
        activity = activities.get(notice_to_activity.get(linked_id, linked_id))
        if activity is None:
            activity_id = f"award:{row['award_id']}"
            organization_name = organization_name or row.get("organization_name")
            activity = activities.setdefault(activity_id, {
                "activity_id": activity_id, "bid_notice_id": linked_id,
                "notice_name": row.get("notice_name"),
                "notice_linkage": "linked" if linked_id else "unlinked",
                "organization_code": organization_code,
                "organization_name": row.get("organization_name"),
                "notice": None, "awards": [], "contracts": [],
                "work_type": row.get("work_type"), "field_code": row.get("field_code"),
                "field_name": row.get("field_name"),
                "large_category": row.get("large_category"),
                "middle_category": row.get("middle_category"),
                "_notice_status": None, "_bid_status": None,
            })
        activity["awards"].append({
            "award_id": row.get("award_id"),
            "bid_classification_number": row.get("bid_classification_number"),
            "rebid_number": row.get("rebid_number"),
            "award_date": row.get("award_date"), "winner_name": row.get("winner_name"),
            "winner_business_registration_number": row.get(
                "winner_business_registration_number"
            ),
            "winning_amount": _number(row.get("winning_amount")),
            "winning_rate": _number(row.get("winning_rate")),
        })

    contract_versions: dict[str, list[dict[str, Any]]] = {}
    contract_classifications: dict[str, dict[str, Any]] = {}
    for row in contract_rows:
        contract_versions.setdefault(str(row["contract_event_id"]), []).append(row)
    for contract_event_id, versions in contract_versions.items():
        dated_versions = [row for row in versions if row.get("contract_date")]
        if not dated_versions:
            continue
        first_contract_date = next((
            row["first_contract_date"] for row in versions
            if row.get("first_contract_date")
        ), min(row["contract_date"] for row in dated_versions))
        if not period_from <= first_contract_date < period_to:
            continue
        latest_contract_date = max(row["contract_date"] for row in dated_versions)
        latest_versions = [
            row for row in dated_versions if row["contract_date"] == latest_contract_date
        ]
        representative = latest_versions[0]
        identity = _procurement_field_identity(representative)
        contract_classification = {
            "work_type": representative.get("work_type"),
            "field_code": identity.get("code") if identity else None,
            "field_name": identity.get("name") if identity else None,
            "large_category": identity.get("large_category") if identity else None,
            "middle_category": identity.get("middle_category") if identity else None,
        }
        contract_classifications[contract_event_id] = contract_classification
        linked_id = str(representative.get("bid_notice_id") or "") or None
        activity = activities.get(notice_to_activity.get(linked_id, linked_id)) if linked_id else None
        if activity is None:
            activity_id = f"contract:{contract_event_id}"
            organization_name = organization_name or representative.get("organization_name")
            activity = activities.setdefault(activity_id, {
                "activity_id": activity_id, "bid_notice_id": linked_id,
                "notice_name": representative.get("notice_name"),
                "notice_linkage": "linked" if linked_id else "unlinked",
                "organization_code": organization_code,
                "organization_name": representative.get("organization_name"),
                "notice": None, "awards": [], "contracts": [],
                **contract_classification,
                "_notice_status": None, "_bid_status": None,
            })
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
            (value for value in contractors if value["company_role"] == "consortium_lead"),
            contractors[0] if len(contractors) == 1 else None,
        )
        activity["contracts"].append({
            "contract_event_id": contract_event_id,
            "unified_contract_number": representative.get("unified_contract_number"),
            "first_contract_date": first_contract_date,
            "contract_date": latest_contract_date,
            "contract_amount": _number(representative.get("contract_amount")),
            "contract_version_count": int(
                representative.get("contract_version_count")
                or len({row.get("unified_contract_number") for row in versions})
            ),
            "lead_contractor": lead, "contractor_count": len(contractors),
            "contractors": contractors,
            "_lineage_source": {
                "unified_contract_number": representative.get(
                    "unified_contract_number"
                ),
                "confirmed_contract_number": representative.get(
                    "confirmed_contract_number"
                ),
                "contract_reference_number": representative.get(
                    "contract_reference_number"
                ),
                "contract_name": representative.get("contract_name"),
                "long_term_continuation_type": representative.get(
                    "long_term_continuation_type"
                ),
                "request_number": representative.get("request_number"),
                "contract_detail_url": representative.get("contract_detail_url"),
                "total_amount": representative.get("total_amount"),
                "total_amount_currency": representative.get("total_amount_currency"),
                "current_contract_amount_currency": representative.get(
                    "current_contract_amount_currency"
                ),
            },
        })

    filtered_before_stage = []
    for activity in activities.values():
        activity["awards"].sort(
            key=lambda value: value.get("award_date") or date.min, reverse=True,
        )
        activity["contracts"].sort(
            key=lambda value: value.get("contract_date") or date.min, reverse=True,
        )
        activity["award"] = activity["awards"][0] if activity["awards"] else None
        activity["contract"] = activity["contracts"][0] if activity["contracts"] else None
        if activity["notice_linkage"] == "linked" and activity["notice"] is not None:
            notice_amounts = activity["notice"]
            amount_candidates = (
                ("allocated_budget", "배정예산"),
                ("estimated_price", "추정가격"),
                ("base_amount", "기초금액"),
            )
            selected_amount = next((
                (notice_amounts[basis], basis, basis_name)
                for basis, basis_name in amount_candidates
                if notice_amounts.get(basis) is not None
            ), (None, None, None))
        elif activity["contract"] is not None:
            selected_amount = (
                activity["contract"].get("contract_amount"),
                "contract_amount",
                "계약금액",
            )
        elif activity["award"] is not None:
            selected_amount = (
                activity["award"].get("winning_amount"),
                "winning_amount",
                "낙찰금액",
            )
        else:
            selected_amount = (None, None, None)
        (
            activity["project_amount"], activity["project_amount_basis"],
            activity["project_amount_basis_name"],
        ) = selected_amount
        if activity["contract"]:
            stage = "contract"
            latest_activity_date = activity["contract"]["contract_date"]
        elif activity["award"]:
            stage = "award"
            latest_activity_date = activity["award"]["award_date"]
        elif activity.get("_current_status") in {"cancelled", "failed"}:
            stage = str(activity["_current_status"])
            latest_activity_date = (
                activity["notice"].get("cancellation_at")
                if stage == "cancelled"
                else activity["notice"].get("failure_at")
            ) or activity["notice"]["published_at"]
        else:
            activity.pop("_bid_status", None)
            published_at = activity["notice"]["published_at"]
            deadline_at = activity["notice"]["deadline_at"]
            published_moment = (
                published_at if isinstance(published_at, datetime)
                else datetime.combine(published_at, datetime.min.time(), timezone.utc)
            )
            if published_moment.tzinfo is None:
                published_moment = published_moment.replace(tzinfo=timezone.utc)
            deadline_moment = None
            if deadline_at is not None:
                deadline_moment = (
                    deadline_at if isinstance(deadline_at, datetime)
                    else datetime.combine(deadline_at, datetime.min.time(), timezone.utc)
                )
                if deadline_moment.tzinfo is None:
                    deadline_moment = deadline_moment.replace(tzinfo=timezone.utc)
            stage = (
                "scheduled" if published_moment > stage_as_of else
                "open" if deadline_moment is not None and stage_as_of < deadline_moment else
                "closed"
            )
            latest_activity_date = published_at
        activity.pop("_notice_status", None)
        activity.pop("_current_status", None)
        activity.pop("_bid_status", None)
        activity["stage"] = stage
        activity["stage_name"] = {
            "scheduled": "예정", "open": "진행", "closed": "마감",
            "award": "낙찰", "contract": "계약",
            "failed": "유찰", "cancelled": "취소",
        }[stage]
        activity["latest_activity_date"] = (
            latest_activity_date.date()
            if isinstance(latest_activity_date, datetime) else latest_activity_date
        )
        filtered_before_stage.append(activity)

    expanded_records = []
    for activity in filtered_before_stage:
        if activity["contracts"]:
            for contract in activity["contracts"]:
                record = {
                    **activity,
                    **contract_classifications.get(contract["contract_event_id"], {}),
                    "activity_id": f"contract:{contract['contract_event_id']}",
                    "stage": "contract", "stage_name": "계약",
                    "contracts": [contract], "contract": contract,
                    "latest_activity_date": contract["first_contract_date"],
                    "project_amount": contract.get("contract_amount"),
                    "project_amount_basis": "contract_amount",
                    "project_amount_basis_name": "계약금액",
                }
                expanded_records.append(record)
        elif activity["awards"]:
            for award in activity["awards"]:
                record = {
                    **activity,
                    "activity_id": f"award:{award['award_id']}",
                    "stage": "award", "stage_name": "낙찰",
                    "awards": [award], "award": award,
                    "latest_activity_date": award["award_date"],
                    "project_amount": award.get("winning_amount"),
                    "project_amount_basis": "winning_amount",
                    "project_amount_basis_name": "낙찰금액",
                }
                expanded_records.append(record)
        else:
            expanded_records.append(activity)

    filtered_records = []
    for record in expanded_records:
        if work_type and record.get("work_type") != work_type:
            continue
        if large_category and _normalized_category(
            record.get("large_category")
        ) != large_category:
            continue
        if middle_category and _normalized_category(
            record.get("middle_category")
        ) != middle_category:
            continue
        if field_code and str(record.get("field_code") or "") != field_code:
            continue
        if company_number:
            if record["stage"] == "contract":
                matched_company = any(
                    contractor.get("business_registration_number") == company_number
                    for contractor in record["contract"]["contractors"]
                )
            elif record["stage"] == "award":
                matched_company = (
                    record["award"].get("winner_business_registration_number")
                    == company_number
                )
            else:
                matched_company = (
                    notice_to_activity.get(str(record.get("bid_notice_id") or ""))
                    in participated_activity_ids
                )
            if not matched_company:
                continue
        if query:
            searchable = " ".join(str(value or "") for value in (
                record.get("notice_name"), record.get("bid_notice_id"),
                record.get("activity_id"),
                *(award.get("winner_name") for award in record["awards"]),
                *(contractor.get("company_name") for contract in record["contracts"]
                  for contractor in contract["contractors"]),
            )).casefold()
            if query not in searchable:
                continue
        filtered_records.append(record)

    if view_mode == "notice_grouped":
        response_records = _group_procurement_activity_records(filtered_records)
    else:
        for record in filtered_records:
            for contract in record.get("contracts") or []:
                contract.pop("_lineage_source", None)
        response_records = filtered_records
    stage_property = "latest_stage" if view_mode == "notice_grouped" else "stage"
    id_property = "activity_group_id" if view_mode == "notice_grouped" else "activity_id"
    stage_counts = {
        value: sum(item[stage_property] == value for item in response_records)
        for value in (
            "scheduled", "open", "closed", "award", "contract", "failed", "cancelled",
        )
    }
    stage_counts["all"] = len(response_records)
    linkage_counts = {
        "linked": sum(
            item["notice_linkage"] == "linked" for item in response_records
        ),
        "unlinked": sum(
            item["notice_linkage"] == "unlinked" for item in response_records
        ),
    }
    filtered = (
        response_records if requested_stage == "all"
        else [item for item in response_records if item[stage_property] == requested_stage]
    )
    filtered.sort(
        key=lambda item: (
            item.get("latest_activity_date") or date.min,
            str(item[id_property]),
        ),
        reverse=True,
    )
    total_items = len(filtered)
    offset = (page - 1) * page_size
    page_items = filtered[offset:offset + page_size]
    pagination = {
        "page": page, "page_size": page_size, "total_items": total_items,
        "total_pages": (total_items + page_size - 1) // page_size,
    }
    observed_at = datetime.now(timezone.utc)
    objects = []
    for item in page_items:
        properties = {
            id_property: item.get(id_property),
            "bid_notice_id": item.get("bid_notice_id"),
            "notice_name": item.get("notice_name"),
            stage_property: item.get(stage_property),
            "latest_activity_date": item.get("latest_activity_date"),
        }
        if view_mode == "notice_grouped":
            properties["activity_id"] = item.get("activity_group_id")
        if view_mode == "flat":
            properties.update({key: item.get(key) for key in (
                "project_amount", "project_amount_basis", "project_amount_basis_name",
            )})
        provenance = Provenance(
            kind="execution", source="teoria_runtime",
            operation=f"market_context.{capability_id}",
            mapping="public_procurement_market_context", observed_at=observed_at,
            record_keys=[str(item[id_property])],
        )
        objects.append(MaterializedObject(
            ontology="public_procurement", object_type="procurement_activity",
            object_id=str(item[id_property]), properties=properties,
            provenance=[provenance],
            property_provenance={key: [provenance] for key in properties},
        ))
    return CapabilityResult(
        capability_id=capability_id, objects=objects, pagination=pagination,
        outcome={
            "organization": {"code": organization_code, "name": organization_name},
            "items": page_items, "stage_counts": stage_counts,
            "linkage_counts": linkage_counts, "pagination": pagination,
            **({
                "grouping_basis": {
                    "linked_group_key": "bid_notice_id",
                    "unlinked_group_key": (
                        "contract_event_id_or_unified_contract_number"
                    ),
                    "contract_version_deduplication": "merged_by_contract_event",
                    "stage_count_basis": "activity_group",
                    "contract_amount_basis": (
                        "latest_version_at_or_before_period_end"
                    ),
                    "contract_family_basis": (
                        "official_contract_number_and_change_order_then_evidence_labelled_inference"
                    ),
                    "family_amount_aggregation": (
                        "one_effective_current_record_per_contract_family"
                    ),
                },
            } if view_mode == "notice_grouped" else {}),
            "analysis_basis": {
                "period_from": period_from, "period_to": period_to - timedelta(days=1),
                "period_from_year": from_year, "period_to_year": to_year,
                "period_type": period_type,
                "period_basis": "stage_event_date",
                "notice_stage_period_basis": "notice_published_at",
                "award_stage_period_basis": "final_award_date_or_opening_at",
                "contract_stage_period_basis": "first_contract_date",
                "sort_basis": "latest_activity_date", "sort": sort,
                "stage_as_of": stage_as_of,
                "stage_policy": "publication_to_deadline",
                "bid_begin_at_used_for_stage": False,
                "company_number": company_number,
                "company_filter_basis": (
                    ["opening_top10_participation", "award_winner", "contract_supplier"]
                    if company_number else []
                ),
                "participation_completeness": "partial" if company_number else None,
                "work_type": work_type,
                "field_filter": {
                    "large_category": large_category, "middle_category": middle_category,
                    "field_code": field_code,
                },
                "query": query or None, "stage": requested_stage,
                "view_mode": view_mode,
                "stage_record_model": (
                    "notice_group_latest_lifecycle_stage"
                    if view_mode == "notice_grouped"
                    else "latest_lifecycle_stage_event"
                ),
                "deduplication": {
                    "notice": "latest_notice_lineage",
                    "award": "award_event_id",
                    "contract": "merged_by_contract_event",
                },
            },
            "registry_version": catalog.release.version if catalog.release else "unpublished",
            "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
        },
    )


_PROCUREMENT_ACTIVITY_STAGE_PRIORITY = {
    "scheduled": 0,
    "open": 1,
    "closed": 2,
    "failed": 3,
    "cancelled": 4,
    "award": 5,
    "contract": 6,
}
