from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
import time
from typing import Any

import psycopg

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import CapabilityExecutionError, CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.provenance import Provenance

from ..readers import CompanySimilarProjectExperienceReader
from .similarity import (
    TITLE_TRIGRAM_SIMILARITY_THRESHOLD,
    amount_similarity as _amount_similarity,
    character_trigrams as _character_trigrams,
    jaccard as _jaccard,
    number as _number,
    primary_project_type as _primary_project_type,
    project_types as _project_types,
    title_tokens as _title_tokens,
)


async def execute_company_similar_project_experience(
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
    *,
    reader: CompanySimilarProjectExperienceReader | None = None,
) -> CapabilityResult:
    """Find company experience sharing any current mandatory industry/license."""
    started = time.perf_counter()
    reference_bid_notice_id = str(inputs["reference_bid_notice_id"])
    company_number = "".join(
        character for character in str(inputs["business_registration_number"])
        if character.isdigit()
    )
    return await _execute_company_similar_project_experience_body(
        catalog, capability_id, inputs, started=started,
        reference_bid_notice_id=reference_bid_notice_id,
        company_number=company_number, reader=reader,
    )


async def _execute_company_similar_project_experience_body(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    started: float, reference_bid_notice_id: str, company_number: str,
    reader: CompanySimilarProjectExperienceReader | None,
) -> CapabilityResult:
    period_years = int(inputs.get("period_years", 10))
    page = int(inputs.get("page", 1))
    page_size = int(inputs.get("page_size", 20))
    resolved_reader = reader or CompanySimilarProjectExperienceReader()
    try:
        reference, rows = await asyncio.to_thread(
            resolved_reader.find, catalog,
            reference_bid_notice_id=reference_bid_notice_id,
            business_registration_number=company_number,
            period_years=period_years,
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

    required_codes = sorted(map(str, reference.get("industry_codes") or []))
    if not required_codes:
        raise CapabilityExecutionError(
            "reference_industry_requirements_unavailable",
            "the reference notice has no complete structured industry/license requirements",
            capability_id=capability_id,
        )
    reference_amount = reference.get("estimated_price") or reference.get("allocated_budget")
    experiences = []
    for row in rows:
        candidate_codes = sorted(map(str, row.get("industry_codes") or []))
        matched_codes = sorted(set(required_codes) & set(candidate_codes))
        amount = (row.get("contract_amount") or row.get("winning_amount")
                  or row.get("estimated_price") or row.get("allocated_budget"))
        amount_score, amount_reason = _amount_similarity(reference_amount, amount)
        share = _number(row.get("participation_share_rate"))
        supplier_count = int(row.get("supplier_count") or 0)
        contract_amount = row.get("contract_amount")
        attributed_amount = None
        if contract_amount is not None:
            if share is not None:
                attributed_amount = _number(
                    Decimal(str(contract_amount)) * Decimal(str(share)) / Decimal("100")
                )
            elif supplier_count == 1:
                attributed_amount = _number(contract_amount)
        comparison = _title_project_comparison(
            str(reference.get("notice_name") or ""), str(row.get("notice_name") or ""),
            trigram_score=(float(row["title_trigram_score"])
                           if row.get("title_trigram_score") is not None else None),
        )
        experiences.append({
            "bid_notice_id": row["bid_notice_id"], "notice_name": row.get("notice_name"),
            "notice_published_date": row.get("notice_published_date"),
            "organization_code": row.get("demand_organization_code"),
            "organization_name": row.get("demand_organization_name"),
            "work_type": row.get("work_type"),
            "industry_license_assessment": {
                "required_codes": required_codes, "candidate_codes": candidate_codes,
                "matched_codes": matched_codes, "matched_code_count": len(matched_codes),
                "required_code_count": len(required_codes),
                "coverage_ratio": round(len(matched_codes) / len(required_codes), 6),
                "any_required_code_matched": bool(matched_codes),
                "all_required_codes_included": len(matched_codes) == len(required_codes),
                "status": "matched", "rule": "any_required_industry_code_overlap",
            },
            "award_date": row.get("award_date"), "contract_date": row.get("contract_date"),
            "winning_amount": _number(row.get("winning_amount")),
            "contract_amount": _number(contract_amount),
            "attributed_contract_amount": attributed_amount,
            "attributed_contract_amount_completeness": (
                "complete" if attributed_amount is not None
                else "partial" if contract_amount is not None else "unknown"
            ),
            "company_role": (
                "sole" if supplier_count == 1
                else "consortium_lead" if row.get("supplier_role_name") in {
                    "대표사", "주계약자", "대표업체",
                } else "consortium_member" if supplier_count > 1 else "award_winner"
            ),
            "share_percent": share,
            "project_type": _primary_project_type(str(row.get("notice_name") or "")),
            "is_similar_amount": amount_score >= 0.5 if reference_amount and amount else None,
            "similar_amount_reason": amount_reason, **comparison,
        })
    experiences.sort(
        key=lambda item: item.get("contract_date") or item.get("award_date")
        or item.get("notice_published_date") or date.min, reverse=True,
    )
    total_items = len(experiences)
    eligible = [item for item in experiences if item["comparison_eligible"]]
    quality_counts = {
        quality: sum(item["comparison_quality"] == quality for item in experiences)
        for quality in ("strong", "limited", "reference_only")
    }
    offset = (page - 1) * page_size
    provenance = Provenance(
        kind="execution", source="teoria_runtime",
        operation="market_context.get_company_similar_project_experience",
        mapping="public_procurement_market_context", observed_at=datetime.now(timezone.utc),
        record_keys=[reference_bid_notice_id, company_number],
    )
    properties = {
        "company_similar_project_experience_id": f"{reference_bid_notice_id}:{company_number}",
        "reference_bid_notice_id": reference_bid_notice_id,
        "company_number": company_number, "experience_count": total_items,
    }
    return CapabilityResult(
        capability_id=capability_id,
        objects=[MaterializedObject(
            ontology="public_procurement", object_type="company_similar_project_experience",
            object_id=properties["company_similar_project_experience_id"],
            properties=properties, provenance=[provenance],
            property_provenance={key: [provenance] for key in properties},
        )],
        outcome={
            "reference_bid_notice_id": reference_bid_notice_id,
            "company": {"business_registration_number": company_number},
            "analysis_basis": {
                "period_years": period_years, "work_type": reference.get("work_type"),
                "required_industries": [
                    {"code": code, "name": (reference.get("industry_names") or {}).get(code)}
                    for code in required_codes
                ],
                "matching_rule": "any_required_industry_code_overlap",
                "title_keyword_filter_applied": False,
                "semantic_similarity_applied": False,
                "title_comparison_profile": "normalized_token_and_character_trigram_v1",
                "title_trigram_similarity_threshold": TITLE_TRIGRAM_SIMILARITY_THRESHOLD,
            },
            "summary": {
                "candidate_count": total_items, "event_count": len(eligible),
                "strong_event_count": quality_counts["strong"],
                "limited_event_count": quality_counts["limited"],
                "reference_only_event_count": quality_counts["reference_only"],
                "similar_amount_event_count": sum(
                    item["is_similar_amount"] is True for item in eligible
                ),
            },
            "experiences": experiences[offset:offset + page_size],
            "pagination": {
                "page": page, "page_size": page_size, "total_items": total_items,
                "total_pages": (total_items + page_size - 1) // page_size,
            },
            "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
        },
    )


def _title_project_comparison(
    reference_title: str, candidate_title: str, *, trigram_score: float | None = None,
) -> dict[str, Any]:
    reference_tokens = _title_tokens(reference_title)
    candidate_tokens = _title_tokens(candidate_title)
    token_score = _jaccard(reference_tokens, candidate_tokens)
    reference_trigrams = _character_trigrams(reference_title)
    candidate_trigrams = _character_trigrams(candidate_title)
    if trigram_score is None:
        trigram_score = _jaccard(reference_trigrams, candidate_trigrams)
    matched_tokens = sorted(reference_tokens & candidate_tokens)
    title_related = trigram_score >= TITLE_TRIGRAM_SIMILARITY_THRESHOLD
    reference_projects = _project_types(reference_title)
    candidate_projects = _project_types(candidate_title)
    matched_projects = sorted(reference_projects & candidate_projects)
    project_type_match = bool(matched_projects)
    quality = (
        "strong" if title_related and project_type_match
        else "limited" if title_related or project_type_match
        else "reference_only"
    )
    return {
        "title_assessment": {
            "token_score": round(token_score, 6),
            "trigram_score": round(trigram_score, 6),
            "matched_tokens": matched_tokens,
            "title_related": title_related,
        },
        "project_type_match": project_type_match,
        "matched_project_types": matched_projects,
        "comparison_quality": quality,
        "comparison_eligible": quality in {"strong", "limited"},
    }
