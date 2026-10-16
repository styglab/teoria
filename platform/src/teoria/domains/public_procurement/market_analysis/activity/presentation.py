from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.provenance import Provenance

from .models import ActivityPage
from .query import ActivityQuery


def build_activity_result(
    catalog: RegistryCatalog,
    capability_id: str,
    request: ActivityQuery,
    organization_name: str | None,
    page: ActivityPage,
    started: float,
) -> CapabilityResult:
    observed_at = datetime.now(timezone.utc)
    objects = []
    for item in page.items:
        properties = {
            page.id_property: item.get(page.id_property),
            "bid_notice_id": item.get("bid_notice_id"),
            "notice_name": item.get("notice_name"),
            page.stage_property: item.get(page.stage_property),
            "latest_activity_date": item.get("latest_activity_date"),
        }
        if request.view_mode == "notice_grouped":
            properties["activity_id"] = item.get("activity_group_id")
        if request.view_mode == "flat":
            properties.update(
                {
                    key: item.get(key)
                    for key in (
                        "project_amount",
                        "project_amount_basis",
                        "project_amount_basis_name",
                    )
                }
            )
        provenance = Provenance(
            kind="execution",
            source="teoria_runtime",
            operation=f"market_context.{capability_id}",
            mapping="public_procurement_market_context",
            observed_at=observed_at,
            record_keys=[str(item[page.id_property])],
        )
        objects.append(
            MaterializedObject(
                ontology="public_procurement",
                object_type="procurement_activity",
                object_id=str(item[page.id_property]),
                properties=properties,
                provenance=[provenance],
                property_provenance={key: [provenance] for key in properties},
            )
        )
    return CapabilityResult(
        capability_id=capability_id,
        objects=objects,
        pagination=page.pagination,
        outcome={
            "organization": {
                "code": request.organization_code,
                "name": organization_name,
            },
            "items": page.items,
            "stage_counts": page.stage_counts,
            "linkage_counts": page.linkage_counts,
            "pagination": page.pagination,
            **(
                {
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
                }
                if request.view_mode == "notice_grouped"
                else {}
            ),
            "analysis_basis": {
                "period_from": request.period_from,
                "period_to": request.period_to - timedelta(days=1),
                "period_from_year": request.from_year,
                "period_to_year": request.to_year,
                "period_type": request.period_type,
                "period_basis": "stage_event_date",
                "notice_stage_period_basis": "notice_published_at",
                "award_stage_period_basis": "final_award_date_or_opening_at",
                "contract_stage_period_basis": "first_contract_date",
                "sort_basis": "latest_activity_date",
                "sort": request.sort,
                "stage_as_of": request.stage_as_of,
                "stage_policy": "publication_to_deadline",
                "bid_begin_at_used_for_stage": False,
                "company_number": request.company_number,
                "company_filter_basis": (
                    ["opening_top10_participation", "award_winner", "contract_supplier"]
                    if request.company_number
                    else []
                ),
                "participation_completeness": "partial"
                if request.company_number
                else None,
                "work_type": request.work_type,
                "field_filter": {
                    "large_category": request.large_category,
                    "middle_category": request.middle_category,
                    "field_code": request.field_code,
                },
                "query": request.query or None,
                "stage": request.requested_stage,
                "view_mode": request.view_mode,
                "stage_record_model": (
                    "notice_group_latest_lifecycle_stage"
                    if request.view_mode == "notice_grouped"
                    else "latest_lifecycle_stage_event"
                ),
                "deduplication": {
                    "notice": "latest_notice_lineage",
                    "award": "award_event_id",
                    "contract": "merged_by_contract_event",
                },
            },
            "registry_version": catalog.release.version
            if catalog.release
            else "unpublished",
            "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
        },
    )
