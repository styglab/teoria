from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

from teoria.domains.public_procurement.market_analysis.profiles.reader import (
    ProcurementProfileReader,
)
from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import (
    CapabilityExecutionError,
    CapabilityResult,
)
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.provenance import Provenance

from ..periods import _fiscal_period_start
from ..profiles.profile_aggregation import _profile_aggregate
from ..related_projects.similarity import number as _number


async def execute_bid_notice_relationship_context(
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
    *,
    reader: ProcurementProfileReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    bid_notice_id = str(inputs["bid_notice_id"])
    history_years = int(inputs.get("relationship_history_years", 5))
    resolved_reader = reader or ProcurementProfileReader()
    try:
        notice, participant_rows = await resolved_reader.bid_context(
            catalog, bid_notice_id=bid_notice_id
        )
        cutoff = notice["notice_published_date"]
        period_from = _fiscal_period_start(cutoff, history_years)
        company_numbers = sorted(
            {
                str(row["company_number"])
                for row in participant_rows
                if row.get("company_number")
            }
        )
        prior_rows = await resolved_reader.activities(
            catalog,
            organization_code=str(notice["organization_code"]),
            company_numbers=company_numbers,
            period_from=period_from,
            period_to=cutoff,
        )
    except LookupError as exc:
        raise CapabilityExecutionError(
            "bid_notice_not_found",
            str(exc),
            capability_id=capability_id,
        ) from exc
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error",
            str(exc),
            capability_id=capability_id,
            source_id="teoria_public_procurement",
            retryable=isinstance(exc, psycopg.Error),
        ) from exc
    _, prior_relationships, _, _, _, _ = _profile_aggregate(
        prior_rows,
        relationship_dimension="company",
    )
    prior_by_company = {item["company_number"]: item for item in prior_relationships}
    participants = []
    for row in participant_rows:
        company_number = str(row["company_number"])
        current_contract = None
        if row.get("contract_date"):
            current_contract = {
                "contracted": True,
                "contract_date": row["contract_date"],
                "contract_amount": _number(row.get("contract_amount")),
                "attributed_contract_amount": _number(
                    row.get("attributed_contract_amount")
                ),
                "company_role": row.get("company_role"),
                "share_percent": _number(row.get("share_percent")),
                "amount_completeness": row.get("amount_completeness"),
            }
        current_award = {
            "awarded": bool(row.get("award_date")),
            "award_date": row.get("award_date"),
            "winning_amount": _number(row.get("winning_amount")),
            "winning_rate": _number(row.get("winning_rate")),
        }
        prior = prior_by_company.get(company_number)
        participants.append(
            {
                "business_registration_number": company_number,
                "company_name": row.get("company_name"),
                "opening_rank": row.get("opening_rank"),
                "bid_amount": _number(row.get("bid_amount")),
                "bid_rate": _number(row.get("bid_rate")),
                "result": (
                    "contracted"
                    if current_contract
                    else "awarded"
                    if current_award["awarded"]
                    else "participated"
                ),
                "current_award": current_award,
                "current_contract": current_contract,
                "prior_organization_relationship": (
                    {
                        key: value
                        for key, value in prior.items()
                        if key
                        not in {
                            "company_number",
                            "company_name",
                            "representative_notices",
                        }
                    }
                    if prior
                    else {
                        "participation_count": 0,
                        "award_event_count": 0,
                        "contract_event_count": 0,
                        "total_attributed_contract_amount": 0,
                        "amount_completeness": "unknown",
                        "first_activity_date": None,
                        "latest_activity_date": None,
                        "active_years": [],
                        "active_year_count": 0,
                        "yearly_activity": [],
                    }
                ),
            }
        )
    lifecycle = {
        "status": (
            "contracted"
            if any(item["current_contract"] for item in participants)
            else "awarded"
            if any(item["current_award"]["awarded"] for item in participants)
            else "opened"
            if participants
            else "open"
        ),
        "participation_count": len(participants),
        "award_count": sum(item["current_award"]["awarded"] for item in participants),
        "contract_count": sum(
            item["current_contract"] is not None for item in participants
        ),
    }
    missing_reasons = []
    if any(
        item["current_contract"]
        and item["current_contract"]["amount_completeness"] != "complete"
        for item in participants
    ):
        missing_reasons.append("some_contract_amounts_not_attributable")
    observed_at = datetime.now(timezone.utc)
    provenance = Provenance(
        kind="execution",
        source="teoria_runtime",
        operation="market_context.get_bid_notice_relationship_context",
        mapping="public_procurement_market_context",
        observed_at=observed_at,
        record_keys=[bid_notice_id],
    )
    properties = {
        "bid_notice_relationship_context_id": bid_notice_id,
        "bid_notice_id": bid_notice_id,
        "participant_count": len(participants),
    }
    return CapabilityResult(
        capability_id=capability_id,
        objects=[
            MaterializedObject(
                ontology="public_procurement",
                object_type="bid_notice_relationship_context",
                object_id=bid_notice_id,
                properties=properties,
                provenance=[provenance],
                property_provenance={key: [provenance] for key in properties},
            )
        ],
        outcome={
            "bid_notice": {
                "bid_notice_id": bid_notice_id,
                "notice_name": notice["notice_name"],
                "organization_code": notice["organization_code"],
                "organization_name": notice["organization_name"],
            },
            "lifecycle": lifecycle,
            "participants": participants,
            "contracts": [
                item["current_contract"]
                for item in participants
                if item["current_contract"]
            ],
            "analysis_basis": {
                "period_from": period_from,
                "period_to": cutoff - timedelta(days=1),
                "period_years": history_years,
                "period_type": "calendar_fiscal_years",
                "prior_relationship_cutoff": cutoff,
                "amount_basis": "attributed_contract_amount",
                "event_deduplication": "award_contract_linked_and_contract_versions_merged",
            },
            "data_completeness": {
                "status": "partial" if missing_reasons else "complete",
                "missing_reasons": missing_reasons,
            },
            "registry_version": catalog.release.version
            if catalog.release
            else "unpublished",
            "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
        },
    )
