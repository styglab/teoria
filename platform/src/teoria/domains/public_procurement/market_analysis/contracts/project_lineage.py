from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import re
from typing import Any

import psycopg

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import CapabilityExecutionError, CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.provenance import Provenance

from ..readers import SimilarBidNoticeReader
from ..related_projects.similarity import (
    business_fields as _business_fields,
    compact as _compact,
    jaccard as _jaccard,
    number as _number,
    project_types as _project_types,
    title_tokens as _title_tokens,
)


async def execute_bid_project_lineage(
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
    *,
    reader: SimilarBidNoticeReader | None = None,
) -> CapabilityResult:
    bid_notice_id = str(inputs["bid_notice_id"])
    period_years = int(inputs.get("period_years", 10))
    try:
        resolved_reader = reader or SimilarBidNoticeReader()
        kwargs: dict[str, Any] = {
            "period_years": period_years,
            "result_statuses": ["awarded", "contracted"],
        }
        if reader is None:
            kwargs.update(candidate_limit=200, similarity_threshold=0.10)
        notice, rows = await asyncio.to_thread(
            resolved_reader.find, catalog, bid_notice_id, **kwargs,
        )
    except LookupError as exc:
        raise CapabilityExecutionError(
            "bid_notice_not_found", str(exc), capability_id=capability_id,
        ) from exc
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc

    current_title = str(notice.get("notice_name") or "")
    current_published = notice.get("notice_published_date")
    current_projects = _project_types(current_title)
    current_fields = _business_fields(current_title)
    if "1468" in set(map(str, notice.get("industry_codes") or [])) and "시스템" in current_title:
        current_fields.add("information_system")
    items = []
    for row in rows:
        if current_published and row.get("notice_published_date") \
                and row["notice_published_date"] >= current_published:
            continue
        previous_title = str(row.get("notice_name") or "")
        previous_projects = _project_types(previous_title)
        previous_fields = _business_fields(previous_title)
        if "1468" in set(map(str, row.get("industry_codes") or [])) and "시스템" in previous_title:
            previous_fields.add("information_system")
        same_organization = bool(
            notice.get("demand_organization_code")
            and notice.get("demand_organization_code") == row.get("demand_organization_code")
        )
        field_overlap = sorted(current_fields & previous_fields)
        candidate_type = None
        if "build" in previous_projects and "improvement" in current_projects:
            candidate_type = "build_to_improvement"
        elif "build" in previous_projects and "maintenance" in current_projects:
            candidate_type = "build_to_maintenance"
        elif "차세대" in _compact(current_title) and field_overlap:
            candidate_type = "existing_to_next_generation"
        elif re.search(r"\b[1-9]\s*단계|\([1-9]차\)", current_title) and field_overlap:
            candidate_type = "phased_successor"
        elif same_organization and field_overlap:
            candidate_type = "same_asset_or_field_candidate"
        if candidate_type is None:
            continue
        reasons = []
        if same_organization:
            reasons.append("same_demand_organization")
        reasons.extend(f"same_field_{value}" for value in field_overlap)
        if previous_projects:
            reasons.append("predecessor_project_type_" + "_".join(sorted(previous_projects)))
        if current_projects:
            reasons.append("successor_project_type_" + "_".join(sorted(current_projects)))
        title_score = _jaccard(_title_tokens(current_title), _title_tokens(previous_title))
        confidence = min(0.65, round(
            0.20 + 0.20 * float(same_organization)
            + 0.15 * float(bool(field_overlap)) + 0.10 * title_score,
            4,
        ))
        items.append({
            "relationship_type": "related_candidate",
            "candidate_relationship_type": candidate_type,
            "predecessor_bid_notice_id": row.get("bid_notice_id"),
            "successor_bid_notice_id": bid_notice_id,
            "project_stage": {
                "predecessor": sorted(previous_projects),
                "successor": sorted(current_projects),
            },
            "performing_company_number": row.get("winner_business_registration_number"),
            "performing_company_name": row.get("winner_name"),
            "contract_amount": _number(row.get("winning_amount")),
            "performance_period": None,
            "confidence": confidence,
            "reason_codes": reasons,
            "evidence_labels": [],
            "evidence": [{
                "source_type": "structured_notice_metadata",
                "bid_notice_id": row.get("bid_notice_id"),
                "original_text": previous_title,
            }],
            "confirmation_status": "requires_source_evidence",
        })
    items.sort(key=lambda item: item["confidence"], reverse=True)
    limit = int(inputs.get("limit", 20))
    items = items[:limit]
    observed_at = datetime.now(timezone.utc)
    provenance = Provenance(
        kind="execution", source="teoria_runtime",
        operation="market_context.find_bid_project_lineage",
        mapping="public_procurement_market_context", observed_at=observed_at,
        record_keys=[bid_notice_id],
    )
    objects = []
    for item in items:
        object_id = (
            f"{item['predecessor_bid_notice_id']}:{item['successor_bid_notice_id']}"
        )
        properties = {"project_lineage_id": object_id, **item}
        objects.append(MaterializedObject(
            ontology="public_procurement", object_type="bid_project_lineage",
            object_id=object_id, properties=properties, provenance=[provenance],
            property_provenance={key: [provenance] for key in properties},
        ))
    confirmed_items = [
        item for item in items if item["relationship_type"] in {"confirmed", "probable"}
    ]
    related_candidates = [
        item for item in items if item["relationship_type"] == "related_candidate"
    ]
    return CapabilityResult(
        capability_id=capability_id, objects=objects,
        outcome={
            "bid_notice_id": bid_notice_id,
            "items": items,
            "confirmed_items": confirmed_items,
            "related_candidates": related_candidates,
            "confirmed_count": len(confirmed_items),
            "candidate_count": len(related_candidates),
            "policy": {
                "profile": "bid_project_lineage_v1",
                "weak_evidence_relationship": "related_candidate",
                "title_similarity_alone_confirms_lineage": False,
            },
        },
    )
