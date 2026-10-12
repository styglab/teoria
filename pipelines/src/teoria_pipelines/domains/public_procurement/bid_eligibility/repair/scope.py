from __future__ import annotations

import re

from teoria_pipelines.domains.public_procurement.bid_eligibility.normalization import (
    _citation_compact,
)


def _prune_out_of_scope_participation_findings(result: dict) -> None:
    """Remove findings that are explicitly outside the product-facing taxonomy."""
    retained = []
    for finding in result.get("participation_findings", []):
        text = " ".join(
            str(value or "") for value in (
                finding.get("type"), finding.get("title"), finding.get("description"),
                *(evidence.get("excerpt") for evidence in finding.get("evidence", [])),
            )
        )
        compact = _citation_compact(text)
        if finding.get("category") == "competition_risk_signal" and (
            re.search(r"상호시장(?:진출)?.{0,6}(?:허용|제한|금지)", compact)
            or re.search(r"(?:지역|소재지|중소기업|소기업|면허|업종|공동수급|공동계약).{0,24}(?:제한|요건|금지)", compact)
        ):
            continue
        if re.search(r"(?:청렴계약|청렴서약|반부패|담합금지|부정당업자)", compact):
            continue
        retained.append(finding)
    result["participation_findings"] = retained


def _apply_bid_entry_fast_scope(facts: dict) -> None:
    """Keep the first-pass payload limited to facts needed to enter the bid."""
    facts["requirements"] = [
        item for item in facts.get("requirements", [])
        if item.get("assessment_stage", "bid_entry") == "bid_entry"
    ]
    facts["participation_findings"] = []


def _prune_unsupported_cross_source_evidence(result: dict) -> None:
    """Do not cite prose for an API industry alternative absent from that prose."""
    for requirement in result["requirements"]:
        if requirement.get("type") != "industry_license":
            continue
        evidence = requirement.get("evidence", [])
        if not any(item.get("source_type") == "structured_api" for item in evidence):
            continue
        attributes = {
            str(item.get("name") or "").casefold(): str(item.get("value") or "")
            for item in (requirement.get("value") or {}).get("attributes", [])
        }
        code = _citation_compact(attributes.get("industry_code", ""))
        name = _citation_compact(attributes.get("industry_name", ""))
        requirement["evidence"] = [
            item for item in evidence
            if item.get("source_type") != "document"
            or (code and code in _citation_compact(item.get("excerpt", "")))
            or (name and name in _citation_compact(item.get("excerpt", "")))
        ]
