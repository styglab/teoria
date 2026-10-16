from __future__ import annotations

import json
import re

from teoria_pipelines.domains.public_procurement.bid_eligibility.normalization import _expression
from teoria_pipelines.domains.public_procurement.bid_notices.normalization import (
    parse_industry_main_field_groups,
    parse_industry_reference,
    parse_permitted_industries,
)


def _structured_license_candidates(item: dict) -> list[dict]:
    """Give every API license alternative its own exact source identity and excerpt."""
    alternatives: list[dict] = []
    primary = parse_industry_reference(item.get("name"))
    if primary:
        alternatives.append(primary)
    permitted = item.get("permitted_industries")
    if isinstance(permitted, str):
        parsed_permitted = parse_permitted_industries(permitted)
    else:
        parsed_permitted = [
            parsed for value in permitted or []
            if (parsed := parse_industry_reference(value)) is not None
        ]
    known = {(value["name"], value["code"]) for value in alternatives}
    for value in parsed_permitted:
        identity = (value["name"], value["code"])
        if identity not in known:
            alternatives.append(value)
            known.add(identity)
    main_field_groups = parse_industry_main_field_groups(item.get("main_fields"))
    base_id = f"license:{item['group']}:{item['sequence']}"
    return [
        {
            "source_id": f"{base_id}:{'primary' if index == 0 else f'alternative:{index}'}",
            "kind": "industry_license",
            **item,
            "name": value["text"],
            "industry_name": value["name"],
            "industry_code": value["code"],
            "permitted_industries": [],
            "main_field_groups": main_field_groups,
            "alternative_index": index,
        }
        for index, value in enumerate(alternatives)
    ]


def _structured_api_result(notice: dict) -> dict:
    requirements: list[dict] = []
    license_groups: dict[str, list[dict]] = {}
    region_leaves: list[dict] = []
    consortium_leaves: list[dict] = []

    def requirement(kind: str, source_id: str, text: str, attributes: list[dict]) -> dict:
        local_id = f"r{len(requirements) + 1}"
        item = {
            "id": local_id, "type": kind, "operator": "in" if kind == "participation_region" else "exists",
            "value": {"text": text, "number": None, "boolean": None, "items": [],
                      "attributes": attributes},
            "original_text": text, "holder_scope": "bidder",
            "proposition_text": text, "proposition_start": 0,
            "proposition_end": len(text),
            "reference_date_type": "qualification_registration_deadline",
            "assessment_stage": "bid_entry", "failure_effect": "cannot_bid",
            "comparison_mode": "structured", "proof_requirements": [],
            "mandatory": True, "review_status": "extracted", "confidence": 1.0,
            "evidence": [{"source_type": "structured_api", "source_id": source_id,
                          "document_id": None, "block_id": None, "page": None,
                          "section": None, "excerpt": text}],
        }
        requirements.append(item)
        return _expression("leaf", requirement_id=local_id)

    for item in notice["licenses"]:
        candidates = _structured_license_candidates(item)
        for candidate in candidates:
            attributes = [
                {"name": key, "value": str(value)} for key, value in (
                    ("restriction_group", item["group"]),
                    ("business_type", item["business_type"]),
                    ("industry_name", candidate["industry_name"]),
                    ("industry_code", candidate["industry_code"]),
                ) if value not in (None, "", [])
            ]
            if candidate["main_field_groups"]:
                attributes.append({
                    "name": "main_field_expression",
                    "value": json.dumps({
                        "operator": "any",
                        "conditions": candidate["main_field_groups"],
                    }, ensure_ascii=False, sort_keys=True),
                })
            leaf = requirement(
                "industry_license", candidate["source_id"], candidate["name"], attributes
            )
            if candidate["main_field_groups"]:
                requirements[-1]["review_status"] = "needs_review"
            license_groups.setdefault(str(item["group"]), []).append(leaf)

    for item in notice["regions"]:
        source_id = f"region:{item['sequence']}"
        attributes = [
            {"name": key, "value": str(value)} for key, value in (
                ("region_code", item.get("code")),
                ("region_name", item.get("name")),
                ("business_type", item.get("business_type")),
            ) if value not in (None, "")
        ]
        region_leaves.append(requirement(
            "participation_region", source_id, item["name"], attributes
        ))

    for item in notice.get("consortiums", []):
        source_id = f"consortium:{item['sequence']}"
        method = item["name"]
        attributes = [{"name": "method", "value": method}]
        leaf = requirement("consortium", source_id, method, attributes)
        stored = requirements[-1]
        stored["operator"] = "equals"
        stored["value"]["boolean"] = not bool(re.search(r"불허|금지", method))
        consortium_leaves.append(leaf)

    root_conditions = [
        leaves[0] if len(leaves) == 1 else _expression("any", leaves)
        for leaves in license_groups.values()
    ]
    if region_leaves:
        root_conditions.append(
            region_leaves[0] if len(region_leaves) == 1 else _expression("any", region_leaves)
        )
    root_conditions.extend(consortium_leaves)
    expression = (
        root_conditions[0] if len(root_conditions) == 1
        else _expression("all", root_conditions)
    )
    return {"schema_version": "1.3.0", "requirements": requirements,
            "expression": expression, "participation_findings": [],
            "unresolved_candidates": []}
