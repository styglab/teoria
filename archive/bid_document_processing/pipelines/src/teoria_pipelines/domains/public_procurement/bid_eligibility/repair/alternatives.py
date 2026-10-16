from __future__ import annotations

import copy
import re

from teoria_pipelines.domains.public_procurement.bid_eligibility.repair.requirements import (
    _add_unresolved,
)


_COMPANY_SCALE_TERMS = {
    "소기업": "small_enterprise",
    "소상공인": "small_business_owner",
}


def _hydrate_structured_requirement_attributes(result: dict, inputs: dict) -> None:
    """Restore provider identifiers even when the model returns only display text."""
    structured = {item["source_id"]: item for item in inputs["structured_requirements"]}
    for requirement in result["requirements"]:
        records = [
            structured[evidence["source_id"]]
            for evidence in requirement.get("evidence", [])
            if evidence.get("source_type") == "structured_api"
            and evidence.get("source_id") in structured
        ]
        if not records:
            continue
        value = requirement.get("value") or {}
        attributes = {
            str(item.get("name") or "").casefold(): item
            for item in value.get("attributes", [])
        }
        for record in records:
            additions = (
                (("industry_code", record.get("industry_code")),
                 ("industry_name", record.get("industry_name")))
                if requirement["type"] == "industry_license"
                else (("region_code", record.get("code")),
                      ("region_name", record.get("name")))
                if requirement["type"] == "participation_region"
                else ()
            )
            for name, candidate in additions:
                if candidate not in (None, ""):
                    attributes[name] = {"name": name, "value": str(candidate)}
        value["attributes"] = list(attributes.values())
        requirement["value"] = value


def _preserve_company_scale_alternatives(result: dict, inputs: dict) -> None:
    """Recover both sides of an explicit small-enterprise OR from source prose."""
    for document in inputs["documents"]:
        for block in document["content"]["blocks"]:
            text = str(block.get("text") or "")
            for match in re.finditer(
                r"[^\n.]{0,100}소기업\s*확인서[\s\S]{0,120}?또는[\s\S]{0,120}?"
                r"소상공인\s*확인서[^\n.]{0,100}?(?:업체|자)",
                text,
            ):
                clause = match.group(0).strip()
                if not all(term in clause for term in _COMPANY_SCALE_TERMS):
                    continue
                source_id = document["document_id"]
                matching = [
                    item for item in result["requirements"]
                    if item.get("type") == "company_scale"
                    and any(
                        evidence.get("source_type") == "document"
                        and evidence.get("document_id") == source_id
                        and evidence.get("block_id") == block["block_id"]
                        for evidence in item.get("evidence", [])
                    )
                ]
                template = matching[0] if matching else None
                if template is None:
                    continue
                group = f"company_scale_{block['block_id']}"
                for branch_index, (term, scale_type) in enumerate(
                    _COMPANY_SCALE_TERMS.items(), 1
                ):
                    item = next((
                        candidate for candidate in matching
                        if term in str((candidate.get("value") or {}).get("text") or "")
                    ), None)
                    if item is None:
                        item = copy.deepcopy(template)
                        used_ids = {candidate["id"] for candidate in result["requirements"]}
                        next_id = len(used_ids) + 1
                        while f"r{next_id}" in used_ids:
                            next_id += 1
                        item["id"] = f"r{next_id}"
                        result["requirements"].append(item)
                        matching.append(item)
                    value = item.get("value") or {}
                    attributes = [
                        attribute for attribute in value.get("attributes", [])
                        if str(attribute.get("name") or "").casefold()
                        not in {"company_scale", "company_scale_type"}
                    ]
                    attributes.append({"name": "company_scale_type", "value": scale_type})
                    value.update({"text": term, "attributes": attributes})
                    item["value"] = value
                    item["original_text"] = clause
                    start = clause.index(term)
                    item["proposition_text"] = term
                    item["proposition_start"] = start
                    item["proposition_end"] = start + len(term)
                    item["evidence"] = [{
                        "source_type": "document", "source_id": source_id,
                        "document_id": source_id, "block_id": block["block_id"],
                        "page": block.get("page"), "section": block.get("section"),
                        "excerpt": clause,
                    }]
                    item["logic"] = {"placements": [{
                        "scope": "common", "alternative_group": group,
                        "alternative_branch": f"scale_{branch_index}",
                    }]}


def _repair_absorbed_alternative_branches(result: dict) -> None:
    """Conservatively simplify A OR (A AND B), preserving B for review."""
    requirements = result["requirements"]
    while True:
        groups: dict[tuple[str, str], dict[str, set[str]]] = {}
        for requirement in requirements:
            for placement in requirement["logic"]["placements"]:
                group = placement.get("alternative_group")
                branch = placement.get("alternative_branch")
                if group and branch:
                    groups.setdefault((placement["scope"], group), {}).setdefault(
                        branch, set()
                    ).add(requirement["id"])
        removal: tuple[str, str, str] | None = None
        for (scope, group), branches in groups.items():
            entries = list(branches.items())
            for index, (left_name, left) in enumerate(entries):
                for right_name, right in entries[index + 1:]:
                    if left <= right:
                        removal = (scope, group, right_name)
                        break
                    if right <= left:
                        removal = (scope, group, left_name)
                        break
                if removal:
                    break
            if removal:
                break
        if not removal:
            break
        scope, group, branch = removal
        for requirement in requirements:
            requirement["logic"]["placements"] = [
                placement
                for placement in requirement["logic"]["placements"]
                if not (
                    placement["scope"] == scope
                    and placement.get("alternative_group") == group
                    and placement.get("alternative_branch") == branch
                )
            ]

    retained: list[dict] = []
    for requirement in requirements:
        if requirement["logic"]["placements"]:
            retained.append(requirement)
        else:
            _add_unresolved(
                result,
                requirement["original_text"],
                "manual_evidence_interpretation",
                True,
            )
    result["requirements"] = retained


def _repair_explicit_performance_review_alternative(result: dict, inputs: dict) -> None:
    """Restore a source-explicit performance OR prior-review branch."""
    for document in inputs["documents"]:
        for block in document["content"]["blocks"]:
            text = str(block.get("text") or "")
            alternative = re.search(
                r"(?P<performance>[^\n.]{0,120}납품\s*실적[^\n.]{0,80}?업체)\s*"
                r"또는(?:\s*또는)?\s*"
                r"(?P<review>사전에[^\n.]{0,100}?심사[^\n.]{0,100}?입찰\s*자격[^\n.]{0,40}?업체)",
                text,
            )
            if alternative is None:
                continue
            performance = next((
                item for item in result["requirements"]
                if item.get("type") == "past_performance"
                and "납품" in str(item.get("proposition_text") or item.get("original_text") or "")
                and any(evidence.get("document_id") == document["document_id"]
                        and evidence.get("block_id") == block["block_id"]
                        for evidence in item.get("evidence", []))
            ), None)
            prior_review = next((
                item for item in result["requirements"]
                if item.get("type") == "custom"
                and re.search(r"사전.{0,40}심사.{0,40}입찰\s*자격", str(
                    item.get("proposition_text") or item.get("original_text") or ""
                ))
                and any(evidence.get("document_id") == document["document_id"]
                        and evidence.get("block_id") == block["block_id"]
                        for evidence in item.get("evidence", []))
            ), None)
            if performance is None or prior_review is None:
                continue
            group = f"source_{block['block_id']}_performance_review"
            for item, branch in ((performance, "performance"), (prior_review, "prior_review")):
                item["logic"] = {"placements": [{
                    "scope": "common", "alternative_group": group,
                    "alternative_branch": branch,
                }]}
            return
