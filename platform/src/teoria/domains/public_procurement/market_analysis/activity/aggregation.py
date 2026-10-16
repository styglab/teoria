from __future__ import annotations

import json
from datetime import date
from typing import Any

from teoria.domains.public_procurement.market_analysis.outcomes.service import (
    _outcome_contractor,
)

from ..field_identity import _procurement_field_identity
from ..related_projects.similarity import number as _number
from .models import ActivityEvents


def build_activity_events(
    notices,
    award_rows,
    contract_rows,
    participated_notice_ids,
    *,
    organization_code: str,
    period_from: date,
    period_to: date,
) -> ActivityEvents:
    activities: dict[str, dict[str, Any]] = {}
    notice_to_activity: dict[str, str] = {}
    organization_name = None
    for row in notices:
        activity_id = str(row.get("notice_lineage_id") or row["bid_notice_id"])
        organization_name = organization_name or row.get("organization_name")
        activities[activity_id] = {
            "activity_id": activity_id,
            "bid_notice_id": str(row["bid_notice_id"]),
            "notice_lineage_id": activity_id,
            "root_bid_notice_id": row.get("root_bid_notice_id"),
            "lineage_count": row.get("lineage_count", 1),
            "notice_name": row.get("notice_name"),
            "notice_linkage": "linked",
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
            "awards": [],
            "contracts": [],
            "work_type": row.get("work_type"),
            "field_code": row.get("field_code"),
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
            activity = activities.setdefault(
                activity_id,
                {
                    "activity_id": activity_id,
                    "bid_notice_id": linked_id,
                    "notice_name": row.get("notice_name"),
                    "notice_linkage": "linked" if linked_id else "unlinked",
                    "organization_code": organization_code,
                    "organization_name": row.get("organization_name"),
                    "notice": None,
                    "awards": [],
                    "contracts": [],
                    "work_type": row.get("work_type"),
                    "field_code": row.get("field_code"),
                    "field_name": row.get("field_name"),
                    "large_category": row.get("large_category"),
                    "middle_category": row.get("middle_category"),
                    "_notice_status": None,
                    "_bid_status": None,
                },
            )
        activity["awards"].append(
            {
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
        )

    contract_versions: dict[str, list[dict[str, Any]]] = {}
    contract_classifications: dict[str, dict[str, Any]] = {}
    for row in contract_rows:
        contract_versions.setdefault(str(row["contract_event_id"]), []).append(row)
    for contract_event_id, versions in contract_versions.items():
        dated_versions = [row for row in versions if row.get("contract_date")]
        if not dated_versions:
            continue
        first_contract_date = next(
            (
                row["first_contract_date"]
                for row in versions
                if row.get("first_contract_date")
            ),
            min(row["contract_date"] for row in dated_versions),
        )
        if not period_from <= first_contract_date < period_to:
            continue
        latest_contract_date = max(row["contract_date"] for row in dated_versions)
        latest_versions = [
            row
            for row in dated_versions
            if row["contract_date"] == latest_contract_date
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
        activity = (
            activities.get(notice_to_activity.get(linked_id, linked_id))
            if linked_id
            else None
        )
        if activity is None:
            activity_id = f"contract:{contract_event_id}"
            organization_name = organization_name or representative.get(
                "organization_name"
            )
            activity = activities.setdefault(
                activity_id,
                {
                    "activity_id": activity_id,
                    "bid_notice_id": linked_id,
                    "notice_name": representative.get("notice_name"),
                    "notice_linkage": "linked" if linked_id else "unlinked",
                    "organization_code": organization_code,
                    "organization_name": representative.get("organization_name"),
                    "notice": None,
                    "awards": [],
                    "contracts": [],
                    **contract_classification,
                    "_notice_status": None,
                    "_bid_status": None,
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
        activity["contracts"].append(
            {
                "contract_event_id": contract_event_id,
                "unified_contract_number": representative.get(
                    "unified_contract_number"
                ),
                "first_contract_date": first_contract_date,
                "contract_date": latest_contract_date,
                "contract_amount": _number(representative.get("contract_amount")),
                "contract_version_count": int(
                    representative.get("contract_version_count")
                    or len({row.get("unified_contract_number") for row in versions})
                ),
                "lead_contractor": lead,
                "contractor_count": len(contractors),
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
                    "total_amount_currency": representative.get(
                        "total_amount_currency"
                    ),
                    "current_contract_amount_currency": representative.get(
                        "current_contract_amount_currency"
                    ),
                },
            }
        )

    return ActivityEvents(
        activities,
        notice_to_activity,
        participated_activity_ids,
        contract_classifications,
        organization_name,
    )
