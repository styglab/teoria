from __future__ import annotations

import json
import re

from teoria_pipelines.domains.public_procurement.bid_eligibility.normalization import (
    _citation_compact,
)
from teoria_pipelines.domains.public_procurement.bid_eligibility.repair.requirements import (
    _add_unresolved,
)


def _preserve_omitted_manual_eligibility(result: dict, inputs: dict) -> None:
    """Recover explicit, time-bound ability gates omitted by the model."""
    represented = "\n".join(
        [item["original_text"] for item in result["requirements"]]
        + [item["text"] for item in result["unresolved_candidates"]]
    )
    structured_consortium_denial = any(
        item.get("kind") == "consortium"
        and re.search(r"공동수급\s*불허", str(item.get("name") or ""))
        for item in inputs.get("structured_requirements", [])
    )
    for document in inputs["documents"]:
        blocks = document["content"]["blocks"]
        for index, block in enumerate(blocks):
            text = str(block.get("text") or "")
            section = str(block.get("section") or "")
            next_block = blocks[index + 1] if index + 1 < len(blocks) else None
            same_refined_parent = bool(
                next_block
                and block.get("parent_block_id")
                and block.get("parent_block_id") == next_block.get("parent_block_id")
            )
            joined_text = text
            if same_refined_parent:
                joined_text = f"{text.rstrip()} {str(next_block.get('text') or '').lstrip()}"
            consortium_document_conflict = re.search(
                r"○?\s*공동계약\s*및\s*구성방식\s*:\s*전자문서\s*/\s*공동수급",
                text,
            )
            if structured_consortium_denial and consortium_document_conflict:
                for requirement in result["requirements"]:
                    if (
                        requirement.get("type") == "consortium"
                        and requirement.get("operator") == "not_exists"
                        and any(
                            evidence.get("source_type") == "structured_api"
                            and evidence.get("source_id") == "consortium:method"
                            for evidence in requirement.get("evidence", [])
                        )
                    ):
                        requirement["review_status"] = "needs_review"
                        requirement["failure_effect"] = "needs_review"
                        requirement["confidence"] = min(requirement.get("confidence", 1.0), 0.5)
                _add_unresolved(
                    result, consortium_document_conflict.group(0).strip(),
                    "source_conflict", True,
                )
            representative_consistency = re.search(
                r"입찰참가자격등록증\s*상의\s*상호\s*및\s*대표자"
                r"[\s\S]{0,180}?대표자\s*전원[\s\S]{0,220}?"
                r"입찰참가자격등록증을\s*변경등록하고\s*입찰에\s*참여하여야\s*하며"
                r"[\s\S]{0,100}?변경등록하지\s*않고\s*참여한\s*입찰은\s*무효입찰",
                text,
            )
            if representative_consistency and not any(
                item.get("type") == "procurement_registration"
                and item.get("holder_scope") == "representative"
                and any(
                    attribute.get("name") == "registration_scope"
                    and attribute.get("value") == "all_representatives_and_identity"
                    for attribute in (item.get("value") or {}).get("attributes", [])
                )
                for item in result["requirements"]
            ):
                original = representative_consistency.group(0).strip()
                used_ids = {item["id"] for item in result["requirements"]}
                next_id = len(used_ids) + 1
                while f"r{next_id}" in used_ids:
                    next_id += 1
                result["requirements"].append({
                    "id": f"r{next_id}", "type": "procurement_registration",
                    "operator": "exists",
                    "value": {
                        "text": "상호 및 복수 대표자 전원의 입찰참가자격 변경등록",
                        "number": None, "boolean": True, "items": [],
                        "attributes": [{
                            "name": "registration_scope",
                            "value": "all_representatives_and_identity",
                        }],
                    },
                    "original_text": original, "proposition_text": original,
                    "proposition_start": 0, "proposition_end": len(original),
                    "holder_scope": "representative",
                    "reference_date_type": "qualification_registration_deadline",
                    "assessment_stage": "bid_entry", "failure_effect": "invalid_bid",
                    "comparison_mode": "structured", "mandatory": True,
                    "review_status": "extracted", "confidence": 1.0,
                    "evidence": [{
                        "source_type": "document", "source_id": str(document["document_id"]),
                        "document_id": str(document["document_id"]),
                        "block_id": block.get("block_id"), "page": block.get("page"),
                        "section": block.get("section"), "excerpt": original,
                    }],
                    "proof_requirements": [], "logic": {"placements": [{
                        "scope": "common", "alternative_group": None,
                        "alternative_branch": None,
                    }]},
                })
            paired_certificates = re.search(
                r"(?P<manufacturer>제작사의\s*제작사증명서)\s*및\s*"
                r"(?P<supplier>공급사의\s*공급사증명서를\s*보유한\s*자)",
                text,
            )
            if paired_certificates:
                invalid_when_missing = bool(re.search(
                    r"증명서를\s*기한\s*내\s*제출하지\s*아니한[\s\S]{0,80}?무효",
                    text,
                ))
                original = paired_certificates.group(0).strip()
                certificate_specs = (
                    ("manufacturer_certificate", "제안 장비 제작사의 제작사증명서 보유", "manufacturer"),
                    ("supplier_certificate", "제안 장비 공급사의 공급사증명서 보유", "supplier"),
                )
                for certificate_type, normalized_text, group_name in certificate_specs:
                    existing_certificate = next((
                        item for item in result["requirements"]
                        if item.get("type") == "certificate"
                        and any(
                            attribute.get("name") == "certificate_type"
                            and attribute.get("value") == certificate_type
                            for attribute in (item.get("value") or {}).get("attributes", [])
                        )
                    ), None)
                    if existing_certificate:
                        if invalid_when_missing:
                            existing_certificate["failure_effect"] = "invalid_bid"
                        continue
                    proposition = paired_certificates.group(group_name)
                    proposition_start = original.index(proposition)
                    used_ids = {item["id"] for item in result["requirements"]}
                    next_id = len(used_ids) + 1
                    while f"r{next_id}" in used_ids:
                        next_id += 1
                    result["requirements"].append({
                        "id": f"r{next_id}", "type": "certificate",
                        "operator": "exists",
                        "value": {
                            "text": normalized_text, "number": None,
                            "boolean": True, "items": [], "attributes": [{
                                "name": "certificate_type", "value": certificate_type,
                            }],
                        },
                        "original_text": original, "proposition_text": proposition,
                        "proposition_start": proposition_start,
                        "proposition_end": proposition_start + len(proposition),
                        "holder_scope": "bidder",
                        "reference_date_type": "qualification_registration_deadline",
                        "assessment_stage": "bid_entry",
                        "failure_effect": "invalid_bid" if invalid_when_missing else "cannot_bid",
                        "comparison_mode": "document_evidence", "mandatory": True,
                        "review_status": "extracted", "confidence": 1.0,
                        "evidence": [{
                            "source_type": "document", "source_id": str(document["document_id"]),
                            "document_id": str(document["document_id"]),
                            "block_id": block.get("block_id"), "page": block.get("page"),
                            "section": block.get("section"), "excerpt": original,
                        }],
                        "proof_requirements": [], "logic": {"placements": [{
                            "scope": "common", "alternative_group": None,
                            "alternative_branch": None,
                        }]},
                    })
            personal_authentication = re.search(
                r"신원확인\s*입찰이\s*적용[\s\S]{0,220}?개인인증수단을\s*이용"
                r"[\s\S]{0,100}?신원을\s*확인받은\s*후\s*입찰에\s*참여하여야\s*합니다",
                joined_text,
            )
            already_has_personal_authentication = any(
                item.get("type") == "procurement_registration"
                and (
                    "개인인증수단" in str(item.get("original_text") or "")
                    or any(
                        attribute.get("name") == "authentication_method"
                        and attribute.get("value") == "personal_authentication"
                        for attribute in item.get("value", {}).get("attributes", [])
                    )
                )
                for item in result["requirements"]
            )
            if personal_authentication and not already_has_personal_authentication:
                original = personal_authentication.group(0).strip()
                used_ids = {item["id"] for item in result["requirements"]}
                next_id = len(used_ids) + 1
                while f"r{next_id}" in used_ids:
                    next_id += 1
                evidence_blocks = [block]
                if same_refined_parent and personal_authentication.end() > len(text):
                    evidence_blocks.append(next_block)
                result["requirements"].append({
                    "id": f"r{next_id}", "type": "procurement_registration",
                    "operator": "exists",
                    "value": {
                        "text": "나라장터 개인인증수단을 통한 신원확인",
                        "number": None, "boolean": True, "items": [],
                        "attributes": [{
                            "name": "authentication_method",
                            "value": "personal_authentication",
                        }],
                    },
                    "original_text": original, "proposition_text": original,
                    "proposition_start": 0, "proposition_end": len(original),
                    "holder_scope": "representative",
                    "reference_date_type": "bid_deadline",
                    "assessment_stage": "bid_entry", "failure_effect": "cannot_bid",
                    "comparison_mode": "manual", "mandatory": True,
                    "review_status": "extracted", "confidence": 1.0,
                    "evidence": [{
                        "source_type": "document", "source_id": str(document["document_id"]),
                        "document_id": str(document["document_id"]),
                        "block_id": evidence_block.get("block_id"),
                        "page": evidence_block.get("page"),
                        "section": evidence_block.get("section"),
                        "excerpt": str(evidence_block.get("text") or "").strip(),
                    } for evidence_block in evidence_blocks],
                    "proof_requirements": [],
                    "logic": {"placements": [{
                        "scope": "common", "alternative_group": None,
                        "alternative_branch": None,
                    }]},
                })
                represented += "\n" + original
            qualification_heading = re.search(
                r"(?:입찰|견적(?:서)?\s*제출?)\s*참가\s*자격|입찰참가자격", text,
            )
            equipment = re.search(
                r"(?:「([^」]{2,60})」|([가-힣A-Za-z0-9ㆍ·‧()\s]{2,60}?))\s*"
                r"(\d+)\s*대\s*이상(?:을)?\s*보유",
                text,
            )
            if (qualification_heading and equipment
                    and equipment.start() >= qualification_heading.start()
                    and equipment.start() - qualification_heading.end() <= 1500
                    and not any(item.get("type") == "equipment_ownership"
                                and _citation_compact(equipment.group(0))
                                in _citation_compact(item.get("original_text", ""))
                                for item in result["requirements"])):
                original = equipment.group(0).strip()
                equipment_name = (equipment.group(1) or equipment.group(2) or "").strip()
                count = int(equipment.group(3))
                used_ids = {item["id"] for item in result["requirements"]}
                next_id = len(used_ids) + 1
                while f"r{next_id}" in used_ids:
                    next_id += 1
                result["requirements"].append({
                    "id": f"r{next_id}", "type": "equipment_ownership",
                    "operator": "greater_than_or_equal",
                    "value": {
                        "text": f"{equipment_name} {count}대 이상 보유",
                        "number": count, "boolean": None, "items": [],
                        "attributes": [{"name": "equipment_name",
                                        "value": equipment_name}],
                    },
                    "original_text": original, "proposition_text": original,
                    "proposition_start": 0, "proposition_end": len(original),
                    "holder_scope": "bidder", "reference_date_type": "bid_deadline",
                    "assessment_stage": "bid_entry", "failure_effect": "cannot_bid",
                    "comparison_mode": "structured", "mandatory": True,
                    "review_status": "extracted", "confidence": 1.0,
                    "evidence": [{
                        "source_type": "document", "source_id": str(document["document_id"]),
                        "document_id": str(document["document_id"]),
                        "block_id": block.get("block_id"), "page": block.get("page"),
                        "section": block.get("section"), "excerpt": original,
                    }],
                    "proof_requirements": [],
                    "logic": {"placements": [{
                        "scope": "common", "alternative_group": None,
                        "alternative_branch": None,
                    }]},
                })
                represented += "\n" + original
            registration = re.search(
                r"(?:조달청|나라장터|국가종합전자조달시스템).{0,20}"
                r"입찰참가(?:자격)?\s*(?:미\s*)?등록"
                r"(?:[\s\S]{0,220}?등록하여야\s*합니다\.?|[^\n.]{0,80}?(?:업체|자)(?=[,.\s]|$))",
                text,
            )
            if (registration and "procurement_registration_type" not in represented
                    and not any(item.get("type") == "procurement_registration"
                                and any(attribute.get("name") == "procurement_registration_type"
                                        and attribute.get("value") == "supplier_registration"
                                        for attribute in item.get("value", {}).get("attributes", []))
                                for item in result["requirements"])):
                original = registration.group(0).strip()
                registration_context = text[max(0, registration.start() - 80):registration.end()]
                used_ids = {item["id"] for item in result["requirements"]}
                next_id = len(used_ids) + 1
                while f"r{next_id}" in used_ids:
                    next_id += 1
                result["requirements"].append({
                    "id": f"r{next_id}",
                    "type": "procurement_registration", "operator": "exists",
                    "value": {
                        "text": "조달청 입찰참가자격 등록", "number": None,
                        "boolean": True, "items": [], "attributes": [{
                            "name": "procurement_registration_type",
                            "value": "supplier_registration",
                        }],
                    },
                    "original_text": original, "proposition_text": original,
                    "proposition_start": 0, "proposition_end": len(original),
                    "holder_scope": "bidder",
                    "reference_date_type": (
                        "qualification_registration_deadline"
                        if re.search(r"마감일\s*전일까지", registration_context)
                        else "bid_deadline"
                    ),
                    "assessment_stage": "bid_entry", "failure_effect": "cannot_bid",
                    "comparison_mode": "structured", "mandatory": True,
                    "review_status": "extracted", "confidence": 1.0,
                    "evidence": [{
                        "source_type": "document", "source_id": str(document["document_id"]),
                        "document_id": str(document["document_id"]),
                        "block_id": block.get("block_id"), "page": block.get("page"),
                        "section": block.get("section"), "excerpt": original,
                    }],
                    "proof_requirements": [],
                    "logic": {"placements": [{
                        "scope": "common", "alternative_group": None,
                        "alternative_branch": None,
                    }]},
                })
                represented += "\nprocurement_registration_type\n" + original
            local_bid_registration = re.search(
                r"(?:제시한\s*조건[\s\S]{0,40}?수락하고\s*)?"
                r"소정의\s*입찰등록을?\s*마친\s*자",
                text,
            )
            if local_bid_registration:
                matching_local_requirement = next((
                    item for item in result["requirements"]
                    if item.get("type") == "custom"
                    and (
                        "입찰참가 승락" in str(item.get("value", {}).get("text") or "")
                        or "소정의 입찰등록" in str(item.get("value", {}).get("text") or "")
                        or "입찰참가 승락" in str(item.get("original_text") or "")
                    )
                ), None)
                if matching_local_requirement is None:
                    original = text.strip()
                    proposition = local_bid_registration.group(0).strip()
                    proposition_start = original.index(proposition)
                    used_ids = {item["id"] for item in result["requirements"]}
                    next_id = len(used_ids) + 1
                    while f"r{next_id}" in used_ids:
                        next_id += 1
                    matching_local_requirement = {
                        "id": f"r{next_id}", "type": "custom",
                        "operator": "equals",
                        "value": {
                            "text": "발주기관의 소정 입찰등록 완료",
                            "number": None, "boolean": True, "items": [],
                            "attributes": [],
                        },
                        "original_text": original,
                        "proposition_text": proposition,
                        "proposition_start": proposition_start,
                        "proposition_end": proposition_start + len(proposition),
                        "holder_scope": "bidder",
                        "reference_date_type": "qualification_registration_deadline",
                        "assessment_stage": "bid_entry",
                        "failure_effect": "cannot_bid",
                        "comparison_mode": "manual",
                        "mandatory": True,
                        "review_status": "needs_review",
                        "confidence": 0.9,
                        "evidence": [],
                        "proof_requirements": [],
                        "logic": {"placements": [{
                            "scope": "common", "alternative_group": None,
                            "alternative_branch": None,
                        }]},
                    }
                    result["requirements"].append(matching_local_requirement)
                if matching_local_requirement is not None:
                    evidence = {
                        "source_type": "document",
                        "source_id": str(document["document_id"]),
                        "document_id": str(document["document_id"]),
                        "block_id": block.get("block_id"),
                        "page": block.get("page"),
                        "section": block.get("section"),
                        "excerpt": text.strip(),
                    }
                    evidence_key = (
                        evidence["document_id"], evidence["block_id"],
                        _citation_compact(evidence["excerpt"]),
                    )
                    existing_keys = {
                        (
                            str(item.get("document_id") or ""),
                            item.get("block_id"),
                            _citation_compact(str(item.get("excerpt") or "")),
                        )
                        for item in matching_local_requirement.get("evidence", [])
                    }
                    if evidence_key not in existing_keys:
                        matching_local_requirement.setdefault("evidence", []).append(evidence)
            product_window = blocks[index:index + 3]
            product_window_text = " ".join(
                str(candidate.get("text") or "").strip() for candidate in product_window
            )
            product_registration = re.search(
                r"전자입찰서\s*제출\s*마감일\s*전일까지[\s\S]{0,160}?"
                r"나라장터(?:\(G2B\))?에\s*"
                r"(?P<name>[가-힣A-Za-z0-9ㆍ·‧()\s]{2,80}?)"
                r"\s*\(세부품명번호\s*(?:10자리)?\s*:\s*(?P<code>\d{10})\)를\s*"
                r"제조\s*또는\s*공급\s*물품으로[\s\S]{0,80}?입찰참가\s*등록한\s*업체",
                product_window_text,
            )
            existing_product_registration = next((
                item for item in result["requirements"]
                if item.get("type") == "product_registration"
                and product_registration
                and product_registration.group("code") in json.dumps(
                    item.get("value") or {}, ensure_ascii=False
                )
            ), None)
            if product_registration:
                product_name = product_registration.group("name").strip()
                product_code = product_registration.group("code")
                source_block = next(
                    candidate for candidate in product_window
                    if product_code in str(candidate.get("text") or "")
                )
                original = str(source_block.get("text") or "").strip()
                used_ids = {item["id"] for item in result["requirements"]}
                next_id = len(used_ids) + 1
                while f"r{next_id}" in used_ids:
                    next_id += 1
                recovered_requirement = {
                    "id": (
                        existing_product_registration["id"]
                        if existing_product_registration is not None
                        else f"r{next_id}"
                    ),
                    "type": "product_registration",
                    "operator": "exists",
                    "value": {
                        "text": f"{product_name} 제조 또는 공급물품 등록",
                        "number": None, "boolean": True, "items": [product_code],
                        "attributes": [
                            {"name": "product_code", "value": product_code},
                            {"name": "product_name", "value": product_name},
                            {"name": "registration_category",
                             "value": "제조물품 또는 공급물품"},
                        ],
                    },
                    "original_text": original, "proposition_text": original,
                    "proposition_start": 0, "proposition_end": len(original),
                    "holder_scope": "bidder", "reference_date_type": "bid_deadline",
                    "assessment_stage": "bid_entry", "failure_effect": "cannot_bid",
                    "comparison_mode": "structured", "mandatory": True,
                    "review_status": "extracted", "confidence": 1.0,
                    "evidence": [{
                        "source_type": "document", "source_id": str(document["document_id"]),
                        "document_id": str(document["document_id"]),
                        "block_id": candidate.get("block_id"), "page": candidate.get("page"),
                        "section": candidate.get("section"),
                        "excerpt": str(candidate.get("text") or "").strip(),
                    } for candidate in product_window],
                    "proof_requirements": [], "logic": {"placements": [{
                        "scope": "common", "alternative_group": None,
                        "alternative_branch": None,
                    }]},
                }
                if existing_product_registration is None:
                    result["requirements"].append(recovered_requirement)
                else:
                    existing_product_registration.clear()
                    existing_product_registration.update(recovered_requirement)
            representative_registration = re.search(
                r"대표자가\s*수인\(2인\s*이상\)\s*업체의\s*경우[\s\S]{0,220}?"
                r"입찰참가자격\s*등록\s*시\s*대표자\s*전원을\s*등록하여야\s*하고"
                r"[\s\S]{0,220}?변경등록을\s*하지\s*아니하고\s*입찰에\s*참가한\s*자는"
                r"[\s\S]{0,120}?입찰무효\s*사유에\s*해당합니다",
                text,
            )
            existing_representative_registration = next((
                item for item in result["requirements"]
                if item.get("type") == "procurement_registration"
                and item.get("holder_scope") == "representative"
                and "대표자 전원" in str((item.get("value") or {}).get("text") or "")
            ), None)
            if representative_registration:
                original = representative_registration.group(0).strip()
                proposition_match = re.search(
                    r"입찰참가자격\s*등록\s*시\s*대표자\s*전원을\s*등록하여야\s*하고",
                    original,
                )
                assert proposition_match is not None
                proposition = proposition_match.group(0)
                used_ids = {item["id"] for item in result["requirements"]}
                next_id = len(used_ids) + 1
                while f"r{next_id}" in used_ids:
                    next_id += 1
                recovered_requirement = {
                    "id": (
                        existing_representative_registration["id"]
                        if existing_representative_registration is not None
                        else f"r{next_id}"
                    ),
                    "type": "procurement_registration",
                    "operator": "exists",
                    "value": {
                        "text": "복수 대표자 전원의 입찰참가자격 등록",
                        "number": None, "boolean": True, "items": [],
                        "attributes": [{
                            "name": "registration_scope", "value": "all_representatives",
                        }],
                    },
                    "original_text": original, "proposition_text": proposition,
                    "proposition_start": proposition_match.start(),
                    "proposition_end": proposition_match.end(),
                    "holder_scope": "representative",
                    "reference_date_type": "qualification_registration_deadline",
                    "assessment_stage": "bid_entry", "failure_effect": "invalid_bid",
                    "comparison_mode": "structured", "mandatory": True,
                    "review_status": "extracted", "confidence": 1.0,
                    "evidence": [{
                        "source_type": "document", "source_id": str(document["document_id"]),
                        "document_id": str(document["document_id"]),
                        "block_id": block.get("block_id"), "page": block.get("page"),
                        "section": block.get("section"), "excerpt": original,
                    }],
                    "proof_requirements": [], "logic": {"placements": [{
                        "scope": "common", "alternative_group": None,
                        "alternative_branch": None,
                    }]},
                }
                if existing_representative_registration is None:
                    result["requirements"].append(recovered_requirement)
                else:
                    existing_representative_registration.clear()
                    existing_representative_registration.update(recovered_requirement)
                recovered = _citation_compact(original)
                result["unresolved_candidates"] = [
                    candidate for candidate in result["unresolved_candidates"]
                    if recovered not in _citation_compact(candidate["text"])
                    and _citation_compact(candidate["text"]) not in recovered
                ]
            subcontracting_prohibition = re.search(
                r"공동수급\s*및\s*하도급(?:은|을)?\s*허용하지\s*않습니다",
                text,
            )
            existing_subcontracting_prohibition = next((
                item for item in result["requirements"]
                if item.get("type") == "consortium"
                and item.get("holder_scope") == "subcontractor"
            ), None)
            if subcontracting_prohibition:
                original = subcontracting_prohibition.group(0).strip()
                proposition_start = original.index("하도급")
                proposition = original[proposition_start:]
                used_ids = {item["id"] for item in result["requirements"]}
                next_id = len(used_ids) + 1
                while f"r{next_id}" in used_ids:
                    next_id += 1
                recovered_requirement = {
                    "id": (
                        existing_subcontracting_prohibition["id"]
                        if existing_subcontracting_prohibition is not None
                        else f"r{next_id}"
                    ),
                    "type": "consortium",
                    "operator": "not_exists",
                    "value": {
                        "text": "하도급 불가", "number": None,
                        "boolean": False, "items": [], "attributes": [{
                            "name": "subcontracting_allowed", "value": "false",
                        }],
                    },
                    "original_text": original, "proposition_text": proposition,
                    "proposition_start": proposition_start,
                    "proposition_end": proposition_start + len(proposition),
                    "holder_scope": "subcontractor", "reference_date_type": "none",
                    "assessment_stage": "bid_entry", "failure_effect": "cannot_bid",
                    "comparison_mode": "manual", "mandatory": True,
                    "review_status": "extracted", "confidence": 1.0,
                    "evidence": [{
                        "source_type": "document", "source_id": str(document["document_id"]),
                        "document_id": str(document["document_id"]),
                        "block_id": block.get("block_id"), "page": block.get("page"),
                        "section": block.get("section"), "excerpt": original,
                    }],
                    "proof_requirements": [], "logic": {"placements": [{
                        "scope": "common", "alternative_group": None,
                        "alternative_branch": None,
                    }]},
                }
                if existing_subcontracting_prohibition is None:
                    result["requirements"].append(recovered_requirement)
                else:
                    existing_subcontracting_prohibition.clear()
                    existing_subcontracting_prohibition.update(recovered_requirement)
            tax_evasion = re.search(
                r"조세포탈\s*등을\s*한\s*자로서[\s\S]{0,100}?"
                r"유죄판결이\s*확정된\s*날부터\s*2년이\s*지나지\s*"
                r"아니한\s*자는[\s\S]{0,40}?(?:입찰|견적제출)에\s*"
                r"(?:참여|참가)할\s*수\s*(?:없음|없습니다)",
                text,
            )
            if (tax_evasion and not any(
                item.get("type") == "sanction"
                and "조세포탈" in str(item.get("original_text") or "")
                for item in result["requirements"]
            )):
                original = tax_evasion.group(0).strip()
                used_ids = {item["id"] for item in result["requirements"]}
                next_id = len(used_ids) + 1
                while f"r{next_id}" in used_ids:
                    next_id += 1
                result["requirements"].append({
                    "id": f"r{next_id}", "type": "sanction", "operator": "not_exists",
                    "value": {
                        "text": "조세포탈 등 유죄판결 확정일부터 2년 미경과 상태",
                        "number": 2, "boolean": False, "items": [], "attributes": [{
                            "name": "lookback_unit", "value": "years",
                        }],
                    },
                    "original_text": original, "proposition_text": original,
                    "proposition_start": 0, "proposition_end": len(original),
                    "holder_scope": "bidder", "reference_date_type": "bid_deadline",
                    "assessment_stage": "bid_entry", "failure_effect": "cannot_bid",
                    "comparison_mode": "manual", "mandatory": True,
                    "review_status": "extracted", "confidence": 1.0,
                    "evidence": [{
                        "source_type": "document", "source_id": str(document["document_id"]),
                        "document_id": str(document["document_id"]),
                        "block_id": block.get("block_id"), "page": block.get("page"),
                        "section": block.get("section"), "excerpt": original,
                    }],
                    "proof_requirements": [],
                    "logic": {"placements": [{
                        "scope": "common", "alternative_group": None,
                        "alternative_branch": None,
                    }]},
                })
                represented += "\n" + original
            score_threshold = re.search(
                r"[^\n.]{0,100}(?P<proposition>"
                r"(?:종합평점|기술능력평가(?:\s*분야)?(?:\s*점수)?)[^\n.]{0,80}?"
                r"(?:100점\s*만점에\s*)?(\d{2,3})\s*(%|점)\s*이상[^\n.]{0,100}?"
                r"(?:적격업체|협상적격자|협상\s*실시|낙찰자로\s*결정))",
                text,
            )
            if score_threshold and not any(
                item.get("assessment_stage") == "qualification_review"
                and item.get("value", {}).get("number") == int(score_threshold.group(2))
                and re.search(r"적격|협상|낙찰", str(item.get("original_text") or ""))
                for item in result["requirements"]
            ):
                original = score_threshold.group(0).strip()
                proposition = score_threshold.group("proposition").strip()
                proposition_start = original.index(proposition)
                used_ids = {item["id"] for item in result["requirements"]}
                next_id = len(used_ids) + 1
                while f"r{next_id}" in used_ids:
                    next_id += 1
                result["requirements"].append({
                    "id": f"r{next_id}", "type": "custom",
                    "operator": "greater_than_or_equal",
                    "value": {
                        "text": proposition, "number": int(score_threshold.group(2)),
                        "boolean": None, "items": [], "attributes": [{
                            "name": "score_unit",
                            "value": "percent" if score_threshold.group(3) == "%" else "points",
                        }],
                    },
                    "original_text": original, "proposition_text": proposition,
                    "proposition_start": proposition_start,
                    "proposition_end": proposition_start + len(proposition),
                    "holder_scope": "bidder", "reference_date_type": "none",
                    "assessment_stage": "qualification_review",
                    "failure_effect": "qualification_rejection",
                    "comparison_mode": "manual", "mandatory": True,
                    "review_status": "extracted", "confidence": 1.0,
                    "evidence": [{
                        "source_type": "document", "source_id": str(document["document_id"]),
                        "document_id": str(document["document_id"]),
                        "block_id": block.get("block_id"), "page": block.get("page"),
                        "section": block.get("section"), "excerpt": original,
                    }],
                    "proof_requirements": [],
                    "logic": {"placements": [{
                        "scope": "common", "alternative_group": None,
                        "alternative_branch": None,
                    }]},
                })
                represented += "\n" + original
            bankruptcy_patterns = (
                (
                    re.search(
                        r"부도\s*또는\s*파산\s*상태에\s*있는\s*업체는.{0,30}?"
                        r"(?:입찰|견적제출)에\s*참가할\s*수\s*없(?:으며|습니다|음)",
                        text,
                    ),
                    "bid_entry", "cannot_bid", "none",
                ),
                (
                    re.search(
                        r"낙찰\s*후\s*계약\s*체결\s*전에.{0,50}?부도\s*또는\s*"
                        r"파산\s*상태에\s*있는\s*업체.{0,30}?계약\s*체결\s*대상에서\s*제외(?:함|됩니다)",
                        text,
                    ),
                    "contracting", "cannot_contract", "contract_date",
                ),
            )
            for bankruptcy, stage, effect, reference_date in bankruptcy_patterns:
                if not bankruptcy or any(
                    item.get("type") == "business_status"
                    and item.get("assessment_stage") == stage
                    and re.search(r"부도|파산", str(item.get("original_text") or ""))
                    for item in result["requirements"]
                ):
                    continue
                original = bankruptcy.group(0).strip()
                used_ids = {item["id"] for item in result["requirements"]}
                next_id = len(used_ids) + 1
                while f"r{next_id}" in used_ids:
                    next_id += 1
                result["requirements"].append({
                    "id": f"r{next_id}", "type": "business_status",
                    "operator": "not_exists",
                    "value": {
                        "text": "부도 또는 파산 상태", "number": None,
                        "boolean": False, "items": ["부도", "파산"],
                        "attributes": [],
                    },
                    "original_text": original, "proposition_text": original,
                    "proposition_start": 0, "proposition_end": len(original),
                    "holder_scope": "bidder", "reference_date_type": reference_date,
                    "assessment_stage": stage, "failure_effect": effect,
                    "comparison_mode": "manual", "mandatory": True,
                    "review_status": "extracted", "confidence": 1.0,
                    "evidence": [{
                        "source_type": "document", "source_id": str(document["document_id"]),
                        "document_id": str(document["document_id"]),
                        "block_id": block.get("block_id"), "page": block.get("page"),
                        "section": block.get("section"), "excerpt": original,
                    }],
                    "proof_requirements": [],
                    "logic": {"placements": [{
                        "scope": "common", "alternative_group": None,
                        "alternative_branch": None,
                    }]},
                })
                represented += "\n" + original
            if "참가자격" not in section.replace(" ", "") and "입찰 참가자격" not in text:
                continue
            for match in re.finditer(
                r"[^\n.]{0,120}(?:연동|개발|제작|납품|이행)[^\n.]{0,120}"
                r"(?:까지|내|內)[^\n.]{0,40}가능한\s*업체(?:\([^\n)]*\))?",
                text,
            ):
                candidate = re.sub(
                    r"^\s*(?:[-•·]|[가-하][.)])\s*", "", match.group(0)
                ).strip()
                if len(candidate) >= 12 and _citation_compact(candidate) not in _citation_compact(represented):
                    _add_unresolved(result, candidate, "manual_evidence_interpretation", True)
                    represented += "\n" + candidate


def _preserve_certificate_borrowing_invalid_bid(result: dict, inputs: dict) -> None:
    """Preserve the explicit invalid-bid effect of borrowed electronic certificates."""
    represented = _citation_compact("\n".join(
        [item["original_text"] for item in result["requirements"]]
        + [item["text"] for item in result["unresolved_candidates"]]
    ))
    for document in inputs["documents"]:
        for block in document["content"]["blocks"]:
            text = str(block.get("text") or "")
            match = re.search(
                r"1인이\s*수인의\s*공인인증서를\s*차용하여\s*입찰서를\s*제출할\s*경우"
                r"[\s\S]{0,220}?무효인\s*입찰에\s*해당되며?",
                text,
            )
            if not match or _citation_compact(match.group(0)) in represented:
                continue
            original = match.group(0)
            used_ids = {item["id"] for item in result["requirements"]}
            next_id = len(used_ids) + 1
            while f"r{next_id}" in used_ids:
                next_id += 1
            local_id = f"r{next_id}"
            result["requirements"].append({
                "id": local_id,
                "type": "procurement_registration",
                "operator": "custom",
                "value": {
                    "text": "타인의 공인인증서를 차용하여 입찰서를 제출하지 않아야 함",
                    "number": None,
                    "boolean": None,
                    "items": [],
                    "attributes": [],
                },
                "original_text": original,
                "proposition_text": original,
                "proposition_start": 0,
                "proposition_end": len(original),
                "holder_scope": "bidder",
                "reference_date_type": "none",
                "assessment_stage": "bid_entry",
                "failure_effect": "invalid_bid",
                "comparison_mode": "manual",
                "mandatory": True,
                "review_status": "extracted",
                "confidence": 1.0,
                "evidence": [{
                    "source_type": "document",
                    "source_id": document["document_id"],
                    "document_id": document["document_id"],
                    "block_id": block["block_id"],
                    "page": block.get("page"),
                    "section": block.get("section"),
                    "excerpt": original,
                }],
                "proof_requirements": [],
                "logic": {"placements": [{
                    "scope": "common",
                    "alternative_group": None,
                    "alternative_branch": None,
                }]},
            })
            represented += _citation_compact(original)


def _preserve_shared_representative_invalid_bid(result: dict, inputs: dict) -> None:
    """Recover the explicit invalidity of simultaneous bids sharing a representative."""
    represented = _citation_compact("\n".join(
        [item["original_text"] for item in result["requirements"]]
    ))
    for document in inputs["documents"]:
        for block in document["content"]["blocks"]:
            text = str(block.get("text") or "")
            match = re.search(
                r"(?:한\s*업체의\s*소속\s*)?대표자\s*중\s*1인이\s*다른\s*업체의\s*대표자를\s*겸임"
                r"[\s\S]{0,180}?(?:동시\s*참여|동시에\s*참여)[\s\S]{0,160}?"
                r"(?:모두\s*무효|입찰\s*무효)",
                text,
            )
            if not match or _citation_compact(match.group(0)) in represented:
                continue
            original = match.group(0).strip()
            used_ids = {item["id"] for item in result["requirements"]}
            next_id = len(used_ids) + 1
            while f"r{next_id}" in used_ids:
                next_id += 1
            result["requirements"].append({
                "id": f"r{next_id}", "type": "custom", "operator": "not_exists",
                "value": {
                    "text": "동일 대표자가 겸임하는 여러 업체의 동시 입찰 참여",
                    "number": None, "boolean": False, "items": [],
                    "attributes": [{
                        "name": "conflict_type",
                        "value": "shared_representative_simultaneous_bidding",
                    }],
                },
                "original_text": original, "proposition_text": original,
                "proposition_start": 0, "proposition_end": len(original),
                "holder_scope": "bidder", "reference_date_type": "bid_deadline",
                "assessment_stage": "bid_entry", "failure_effect": "invalid_bid",
                "comparison_mode": "manual", "mandatory": True,
                "review_status": "extracted", "confidence": 1.0,
                "evidence": [{
                    "source_type": "document", "source_id": document["document_id"],
                    "document_id": document["document_id"], "block_id": block["block_id"],
                    "page": block.get("page"), "section": block.get("section"),
                    "excerpt": original,
                }],
                "proof_requirements": [],
                "logic": {"placements": [{
                    "scope": "common", "alternative_group": None,
                    "alternative_branch": None,
                }]},
            })
            recovered = _citation_compact(original)
            result["unresolved_candidates"] = [
                candidate for candidate in result["unresolved_candidates"]
                if recovered not in _citation_compact(candidate["text"])
                and _citation_compact(candidate["text"]) not in recovered
            ]
            represented += recovered


def _preserve_legal_administration_disqualification(result: dict, inputs: dict) -> None:
    """Split legal-administration status from a compound debarment sentence."""
    represented = _citation_compact("\n".join(
        [item.get("proposition_text") or item["original_text"]
         for item in result["requirements"]]
    ))
    if "법정관리중" in represented:
        return
    for document in inputs["documents"]:
        for block in document["content"]["blocks"]:
            text = str(block.get("text") or "")
            match = re.search(
                r"[^\n.]{0,20}법정관리\s*(?:중이거나|등이나)[\s\S]{0,140}?"
                r"부정[.\s]*당업체로\s*제재\s*중인\s*업체는\s*참여할\s*수\s*없(?:다|음)",
                text,
            )
            if not match:
                continue
            original = match.group(0).strip()
            proposition_match = re.search(r"법정관리(?:\s*중)?", original)
            if proposition_match is None:
                continue
            used_ids = {item["id"] for item in result["requirements"]}
            next_id = len(used_ids) + 1
            while f"r{next_id}" in used_ids:
                next_id += 1
            proposition = proposition_match.group(0)
            result["requirements"].append({
                "id": f"r{next_id}", "type": "legal_qualification",
                "operator": "not_equals",
                "value": {
                    "text": "법정관리 중이 아님", "number": None,
                    "boolean": False, "items": [], "attributes": [{
                        "name": "excluded_status", "value": "legal_administration",
                    }],
                },
                "original_text": original, "proposition_text": proposition,
                "proposition_start": proposition_match.start(),
                "proposition_end": proposition_match.end(),
                "holder_scope": "bidder", "reference_date_type": "bid_deadline",
                "assessment_stage": "bid_entry", "failure_effect": "cannot_bid",
                "comparison_mode": "manual", "mandatory": True,
                "review_status": "extracted", "confidence": 1.0,
                "evidence": [{
                    "source_type": "document", "source_id": document["document_id"],
                    "document_id": document["document_id"], "block_id": block["block_id"],
                    "page": block.get("page"), "section": block.get("section"),
                    "excerpt": original,
                }],
                "proof_requirements": [], "logic": {"placements": [{
                    "scope": "common", "alternative_group": None,
                    "alternative_branch": None,
                }]},
            })
            return


def _preserve_compound_debarment_disqualification(result: dict, inputs: dict) -> None:
    """Keep active debarment distinct from an adjacent FTC-history condition."""
    if any(
        item.get("type") == "sanction"
        and re.search(
            r"부정[.\s]*당(?:업자|업체).{0,30}(?:참가\s*자격제한|제재\s*중)",
            str(item.get("proposition_text") or item.get("original_text") or ""),
        )
        for item in result["requirements"]
    ):
        return
    for document in inputs["documents"]:
        for block in document["content"]["blocks"]:
            text = str(block.get("text") or "")
            match = re.search(
                r"부정[.\s]*당업자의?\s*입찰\s*참가\s*자격제한[”\"']?에\s*"
                r"해당되지\s*않는\s*업체",
                text,
            )
            if match is None:
                continue
            proposition = match.group(0).strip()
            used_ids = {item["id"] for item in result["requirements"]}
            next_id = len(used_ids) + 1
            while f"r{next_id}" in used_ids:
                next_id += 1
            result["requirements"].append({
                "id": f"r{next_id}", "type": "sanction", "operator": "not_exists",
                "value": {
                    "text": "부정당업자 입찰참가자격 제한 상태",
                    "number": None, "boolean": False, "items": [],
                    "attributes": [{
                        "name": "sanction_type",
                        "value": "procurement_participation_restriction",
                    }],
                },
                "original_text": proposition, "proposition_text": proposition,
                "proposition_start": 0, "proposition_end": len(proposition),
                "holder_scope": "bidder", "reference_date_type": "bid_deadline",
                "assessment_stage": "bid_entry", "failure_effect": "cannot_bid",
                "comparison_mode": "structured", "mandatory": True,
                "review_status": "extracted", "confidence": 1.0,
                "evidence": [{
                    "source_type": "document", "source_id": document["document_id"],
                    "document_id": document["document_id"], "block_id": block["block_id"],
                    "page": block.get("page"), "section": block.get("section"),
                    "excerpt": proposition,
                }],
                "proof_requirements": [], "logic": {"placements": [{
                    "scope": "common", "alternative_group": None,
                    "alternative_branch": None,
                }]},
            })
            return
