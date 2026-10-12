from __future__ import annotations

import re

from teoria_pipelines.domains.public_procurement.bid_eligibility.normalization import (
    BID_PRICE_ELIGIBILITY_PATTERN,
    _citation_compact,
    _requirement_proposition,
)


_TYPE_PROPOSITION_MARKERS = {
    "sanction": re.compile(
        r"부정당|입찰참가.{0,12}제한|참가자격.{0,12}제한|조세포탈|유죄|제재|처분"
    ),
    "consortium": re.compile(r"공동수급|공동계약|공동도급|컨소시엄|단독이행|단독\s*참가"),
}


def _atomic_clause_candidates(text: str) -> list[tuple[int, int, str]]:
    """Return verbatim line/sentence-sized clauses with offsets in source text."""
    candidates: dict[tuple[int, int], str] = {}
    boundaries = re.compile(
        r"[^\n]+?(?:[.!?](?=\s|$)|(?=\s+(?:\d+|[가-힣])[.)]\s)|$)"
    )
    for match in boundaries.finditer(text):
        start, end = match.span()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            candidates[(start, end)] = text[start:end]
    return [(start, end, clause) for (start, end), clause in candidates.items()]


def _infer_atomic_proposition(requirement: dict) -> tuple[int, int, str] | None:
    """Find one unambiguous exact clause for a model-expanded proposition."""
    original = requirement["original_text"]
    marker = _TYPE_PROPOSITION_MARKERS.get(requirement["type"])
    if marker is None:
        return None
    value = requirement.get("value") or {}
    value_tokens = {
        token.casefold() for token in re.findall(
            r"[0-9A-Za-z가-힣]+", " ".join([
                str(value.get("text") or ""),
                *(str(item) for item in value.get("items", [])),
                *(str(item.get("value") or "") for item in value.get("attributes", [])),
            ])
        ) if len(token) >= 2
    }
    ranked: list[tuple[float, int, int, str]] = []
    for start, end, clause in _atomic_clause_candidates(original):
        if not marker.search(clause):
            continue
        clause_tokens = {
            token.casefold() for token in re.findall(r"[0-9A-Za-z가-힣]+", clause)
        }
        overlap = len(value_tokens & clause_tokens) / max(len(value_tokens), 1)
        ranked.append((overlap, start, end, clause))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], len(item[3])))
    best = ranked[0]
    # With no normalized-value overlap, multiple matching clauses cannot safely be
    # assigned to distinct requirements. Preserve them for review instead.
    if best[0] == 0 and len(ranked) > 1:
        return None
    if len(ranked) > 1 and best[0] == ranked[1][0] and best[3] != ranked[1][3]:
        return None
    return best[1], best[2], best[3]


def _repair_non_atomic_propositions(result: dict) -> None:
    """Shrink expanded citations or demote requirements that cannot be anchored."""
    retained: list[dict] = []
    for requirement in result["requirements"]:
        original = requirement["original_text"]
        proposition = str(requirement.get("proposition_text") or "").strip()
        expanded = (
            (not proposition or proposition == original.strip() or proposition not in original)
            and (len(original) >= 240 or original.count("\n") >= 3)
        )
        if not expanded:
            retained.append(requirement)
            continue
        inferred = _infer_atomic_proposition(requirement)
        if inferred is None:
            _add_unresolved(result, original, "manual_evidence_interpretation", True)
            continue
        start, end, proposition = inferred
        requirement["proposition_text"] = proposition
        requirement["proposition_start"] = start
        requirement["proposition_end"] = end
        retained.append(requirement)
    result["requirements"] = retained


def _repair_requirement_fields(result: dict) -> None:
    """Repair local stage/date contradictions without regenerating the whole notice."""
    stage_by_effect = {
        "cannot_bid": "bid_entry",
        "invalid_bid": "bid_entry",
        "qualification_rejection": "qualification_review",
        "cannot_contract": "contracting",
    }
    deadline = re.compile(
        r"(?:입찰(?:서)?|견적서)\s*(?:제출)?\s*마감|입찰\s*마감"
    )
    for requirement in result["requirements"]:
        proposition = str(
            requirement.get("proposition_text") or requirement.get("original_text") or ""
        )
        evidence_text = " ".join(
            str(evidence.get("excerpt") or "")
            for evidence in requirement.get("evidence", [])
        )
        registration_text = f"{proposition} {evidence_text}"
        expected_stage = stage_by_effect.get(requirement["failure_effect"])
        if expected_stage and requirement["assessment_stage"] != expected_stage:
            requirement["assessment_stage"] = expected_stage
            requirement["review_status"] = "needs_review"
            requirement["confidence"] = min(requirement["confidence"], 0.7)
        if (
            requirement["assessment_stage"] == "qualification_review"
            and requirement["reference_date_type"] == "bid_deadline"
            and not deadline.search(requirement["original_text"])
        ):
            requirement["reference_date_type"] = "none"
        if requirement["type"] == "sanction" and requirement["operator"] == "not_equals":
            requirement["operator"] = "not_exists"
        if (
            requirement["type"] == "product_registration"
            and requirement["operator"] in {"contains", "equals"}
            and re.search(r"(?:제조|공급)?물품.{0,30}등록|등록.{0,30}(?:제조|공급)?물품", proposition)
        ):
            requirement["operator"] = "exists"
        if (
            requirement["type"] in {"industry_license", "procurement_registration"}
            and requirement["operator"] in {"contains", "equals"}
            and re.search(r"등록(?:한|된|을\s*필|하여야|해야|완료|보유)", registration_text)
            and not re.search(r"미등록|등록하지\s*않|등록되지\s*않", registration_text)
        ):
            requirement["operator"] = "exists"
        if (
            requirement["type"] == "industry_license"
            and any(evidence.get("source_type") == "structured_api"
                    for evidence in requirement.get("evidence", []))
        ):
            requirement["reference_date_type"] = "qualification_registration_deadline"
        if requirement["type"] == "consortium" and requirement["operator"] == "not_exists":
            value = requirement.get("value") or {}
            attributes = [
                item for item in value.get("attributes", [])
                if str(item.get("name") or "").casefold() != "participation_mode"
            ]
            consortium_text = " ".join((
                proposition, str(value.get("text") or ""),
                str(requirement.get("original_text") or ""),
            ))
            participation_itself_is_prohibited = (
                not re.search(r"공동수급체.{0,20}(?:중복|복수).{0,12}(?:결성|구성)", consortium_text)
                and not re.search(r"하도급", consortium_text)
                and bool(re.search(
                    r"(?:공동(?:수급|도급|계약)(?:은|는|이|가|을|를)?\s*"
                    r"(?:불가|불허|금지|허용하지\s*않|허용되지)|공동수급불허|"
                    r"단독(?:으로만|만)\s*(?:참가|계약|제출))",
                    consortium_text,
                ))
            )
            if participation_itself_is_prohibited:
                attributes.append({"name": "participation_mode", "value": "single_only"})
            value["attributes"] = attributes
            requirement["value"] = value
            if not deadline.search(requirement["original_text"]):
                requirement["reference_date_type"] = "none"
        if (
            requirement["type"] == "consortium"
            and requirement["operator"] in {"equals", "not_equals"}
            and re.search(
                r"하도급.{0,16}(?:불가|불허|금지|할\s*수\s*없|허용하지\s*않)",
                proposition,
            )
        ):
            requirement["operator"] = "not_exists"
            if not deadline.search(requirement["original_text"]):
                requirement["reference_date_type"] = "none"
        if (
            requirement["type"] == "legal_qualification"
            and requirement["reference_date_type"] == "qualification_registration_deadline"
            and not re.search(r"등록|마감|전일|까지", proposition)
        ):
            requirement["reference_date_type"] = "bid_deadline"


def _add_unresolved(result: dict, text: str, reason: str, blocks: bool) -> None:
    candidate = {"text": text, "review_reason": reason, "blocks_qualification": blocks}
    if candidate not in result["unresolved_candidates"]:
        result["unresolved_candidates"].append(candidate)


def _repair_requirement_semantics(result: dict) -> None:
    """Demote unsafe model inferences and prevent compound facts from auto-comparison."""
    retained: list[dict] = []
    missing_reference_texts = [
        _citation_compact(candidate["text"])
        for candidate in result["unresolved_candidates"]
        if candidate.get("review_reason") == "referenced_document_missing"
    ]
    for requirement in result["requirements"]:
        original = requirement["original_text"]
        value = requirement.get("value") or {}
        value_text = str(value.get("text") or "")
        compact_original = _citation_compact(original)
        if (
            re.search(r"(?:개찰결과\s*)?(?:1순위|낙찰자|우선\s*협상대상자)", original)
            and re.search(r"(?:제출|제출하여야|제출해야|구비)", original)
            and re.search(
                r"지정\s*신청서|가격\s*제안서|서약서|계약\s*서류|인지세|"
                r"입찰\s*내역서|산출\s*내역서|청렴\s*계약",
                original,
            )
            and not re.search(
                r"면허|허가|등록|자격증|업종|직접\s*생산|실적|제조사|공급사|"
                r"파트너|기술\s*지원\s*확약|신용\s*등급",
                original,
            )
        ):
            finding_ids = {item["id"] for item in result.get("participation_findings", [])}
            sequence = len(finding_ids) + 1
            while f"f{sequence}" in finding_ids:
                sequence += 1
            subject = (
                "first_ranked_bidder" if re.search(r"(?:개찰결과\s*)?1순위", original)
                else "preferred_negotiator" if re.search(r"우선\s*협상대상자", original)
                else "successful_bidder"
            )
            result.setdefault("participation_findings", []).append({
                "id": f"f{sequence}",
                "category": "participation_note",
                "type": "post_selection_document_submission",
                "title": "선정 후 제출서류",
                "subject": subject,
                "stage": "after_opening" if subject == "first_ranked_bidder" else "contracting",
                "description": value_text or original,
                "deadline_text": None,
                "failure_effect": "needs_review",
                "importance": "high",
                "competitive_effect": None,
                "legitimate_justification": None,
                "review_status": "extracted",
                "confidence": min(float(requirement.get("confidence", 1.0)), 0.95),
                "evidence": requirement.get("evidence", []),
            })
            continue
        if BID_PRICE_ELIGIBILITY_PATTERN.search(_requirement_proposition(requirement)):
            continue
        if not any(
            evidence.get("source_type") == "structured_api"
            for evidence in requirement.get("evidence", [])
        ) and any(
            compact_original in candidate or candidate in compact_original
            for candidate in missing_reference_texts
        ):
            continue
        reference_only_law = (
            requirement.get("review_status") == "needs_review"
            and re.search(r"(?:법률|시행령|시행규칙).{0,80}제\s*조", original)
            and re.search(r"(?:따른\s*자격요건|각\s*호에\s*해당)", original)
            and not re.search(r"(?:별표|다음\s*각\s*호)\s*[:：]?\s*\n?\s*[①-⑳1-9가-하]", original)
        )
        if reference_only_law:
            _add_unresolved(result, original, "referenced_document_missing", True)
            continue
        if requirement["type"] == "sanction" and re.search(r"법정관리\s*중", original):
            requirement["type"] = "legal_qualification"
            requirement["comparison_mode"] = "manual"
            attributes = [
                item for item in value.get("attributes", [])
                if str(item.get("name") or "").casefold() != "sanction_type"
            ]
            attributes.append({"name": "excluded_status", "value": "legal_administration"})
            value["attributes"] = attributes
            requirement["value"] = value
        if (
            requirement["type"] == "custom"
            and re.search(r"(?:국가를\s*당사자로\s*하는\s*계약에\s*관한\s*법률|국가계약법)", original)
            and re.search(r"(?:시행령.{0,20}제\s*12\s*조|제12조)", original)
            and re.search(r"(?:소정의\s*자격|경쟁입찰\s*참가자격)", original)
        ):
            requirement["type"] = "legal_qualification"
        if (
            requirement["type"] == "custom"
            and re.search(
                r"(?:제조사|제작사|제조원).{0,24}(?:판권계약.{0,16})?(?:대리점|공급사|지사)"
                r"|(?:대리점|공급사|지사).{0,24}(?:제조사|제작사|제조원)",
                original,
            )
        ):
            requirement["type"] = "manufacturer_status"
        if (
            requirement["type"] == "custom"
            and re.search(r"(?:기관|진흥원|공단|연구원).{0,12}퇴직자", original)
            and re.search(r"(?:설립|임원|재취업).{0,30}(?:무효|제외|제한)|(?:무효|제외|제한).{0,30}(?:설립|임원|재취업)", original)
        ):
            requirement["type"] = "legal_qualification"
        if re.search(r"부정[.\s]*당업체로\s*제재\s*중", original):
            requirement["type"] = "sanction"
            requirement["comparison_mode"] = "manual"
            requirement["review_status"] = "needs_review"
            requirement["confidence"] = min(requirement["confidence"], 0.8)
            attributes = [
                item for item in value.get("attributes", [])
                if str(item.get("name") or "").casefold() != "excluded_status"
            ]
            attributes.append({"name": "sanction_basis", "value": "institutional_debarment"})
            value["attributes"] = attributes
            requirement["value"] = value
        if (
            re.search(r"(?:업체|대상자)\s*선정\s*완료\s*후", original)
            and re.search(r"실제\s*납품\s*요청|납품\s*시", original)
            and re.search(r"주문.{0,30}(?:가능|불가능)|납품\s*대상\s*업체.{0,20}변경", original)
        ):
            continue
        qualification_match = next((
            qualification_type
            for pattern, qualification_type in (
                (r"벤처기업", "venture_business"),
                (r"(?:이노비즈|기술혁신형\s*중소기업)", "innobiz"),
                (r"(?:메인비즈|경영혁신형\s*중소기업)", "mainbiz"),
            )
            if re.search(pattern, original)
        ), None)
        if qualification_match and requirement["type"] in {
            "business_status", "certificate", "legal_qualification", "custom"
        }:
            requirement["type"] = "certificate"
            attributes = [
                item for item in value.get("attributes", [])
                if str(item.get("name") or "").casefold() != "qualification_type"
            ]
            attributes.append({"name": "qualification_type", "value": qualification_match})
            value["attributes"] = attributes
            requirement["value"] = value
        software_business_match = re.search(
            r"소프트웨어\s*사업자(?:\s*\([^)]*\))?", original
        )
        if software_business_match and requirement["type"] in {
            "industry_license", "business_status", "certificate", "legal_qualification", "custom"
        }:
            requirement["type"] = "industry_license"
            attributes = [
                item for item in value.get("attributes", [])
                if str(item.get("name") or "").casefold()
                != "industry_code"
            ]
            industry_code = re.search(
                r"업종\s*코드\s*[:：]?\s*\[?\s*(\d{4})\s*\]?", original
            )
            if industry_code:
                attributes.append({"name": "industry_code", "value": industry_code.group(1)})
            value["text"] = software_business_match.group(0)
            value["attributes"] = attributes
            requirement["value"] = value
        if (
            requirement["holder_scope"] == "representative"
            and re.search(r"입찰\s*대리인(?:의|인)?\s*경우", original)
        ):
            _add_unresolved(result, original, "manual_evidence_interpretation", True)
            continue
        attributes = {
            str(item.get("name") or ""): str(item.get("value") or "")
            for item in value.get("attributes", [])
        }
        compact_auth_text = re.sub(r"\s+", "", f"{original} {value_text}")
        if (
            requirement["type"] == "procurement_registration"
            and (
                attributes.get("authentication_method") == "personal_certificate_exception"
                or (
                    "지문인식신원확인" in compact_auth_text
                    and "곤란" in compact_auth_text
                    and "개인인증서" in compact_auth_text
                    and ("예외" in compact_auth_text or "제출할수" in compact_auth_text)
                )
            )
        ):
            continue
        if (
            requirement["type"] == "legal_qualification"
            and re.search(r"입찰기간\s*중.{0,40}지위\s*승계", original)
            and re.search(r"(?:서류|증빙).{0,30}참가자격.{0,12}유지", original)
        ):
            _add_unresolved(result, original, "manual_evidence_interpretation", True)
            continue
        if (
            requirement["type"] == "technical_personnel"
            and requirement["holder_scope"] == "bidder"
            and re.search(r"업무정지.{0,20}기술자|기술자.{0,20}업무정지", original)
            and re.search(r"기술자.{0,20}평가대상.{0,8}제외", original)
        ):
            _add_unresolved(result, original, "informational_exclusion", False)
            continue
        if (
            requirement["type"] == "credit_rating"
            and requirement["operator"] == "exists"
            and re.search(r"신용평가등급.{0,20}(?:기준|평가)", original)
            and re.search(r"(?:자료|등급).{0,20}제출|미준수.{0,12}(?:탈락|평가\s*불가)", original)
            and not re.search(r"(?:등급|평점).{0,8}(?:이상|이하|[A-D][+-]?)", original)
        ):
            _add_unresolved(result, original, "manual_evidence_interpretation", True)
            continue
        if (
            requirement["type"] == "credit_rating"
            and re.search(r"(?:전송하지|요구[·ㆍ\s]*약속|이전의\s*유리한).{0,60}(?:평가자료|신용평가)", original)
            and re.search(r"(?:입찰을\s*무효|낙찰자에서\s*배제)", original)
        ):
            _add_unresolved(result, original, "conditional_applicability_unknown", True)
            continue
        if (
            requirement["type"] == "sanction"
            and re.search(r"입찰참가자격.{0,20}유지", original)
            and not re.search(r"부정당|조세포탈|유죄|제재|처분|업무정지|참가자격\s*제한", original)
        ):
            requirement["type"] = "legal_qualification"
            requirement["operator"] = "valid_on"
            requirement["value"] = {
                **value,
                "text": value_text.replace(" 상실", " 유지") or "입찰참가자격 유지",
                "boolean": True,
            }
        if requirement["type"] == "sanction" and re.search(r"업체와.{0,40}기술자", original):
            bidder_clause = re.search(
                r"(?:본\s+용역사업.{0,80})?(?:부정당업자|부실업자).{0,100}?업체",
                original,
            )
            if bidder_clause:
                proposition = bidder_clause.group(0)
                requirement["proposition_text"] = proposition
                requirement["proposition_start"] = bidder_clause.start()
                requirement["proposition_end"] = bidder_clause.end()
        if (
            requirement["type"] == "procurement_registration"
            and len(value.get("items") or []) > 1
        ):
            requirement["comparison_mode"] = "manual"
            requirement["review_status"] = "needs_review"
            requirement["confidence"] = min(requirement["confidence"], 0.7)
            _add_unresolved(result, original, "manual_evidence_interpretation", True)
        if (
            requirement["type"] == "past_performance"
            and re.search(r"경험(?:과|\s*및)?\s*능력|실적", original)
            and value.get("number") is None
            and not re.search(r"\d+\s*(?:건|회|년|개월|원|천원|만원|억원|%)", original)
        ):
            requirement["comparison_mode"] = "manual"
            requirement["review_status"] = "needs_review"
            requirement["confidence"] = min(requirement["confidence"], 0.7)
            _add_unresolved(result, original, "manual_evidence_interpretation", True)
        if requirement["type"] == "business_status" and len(value.get("items") or []) > 1:
            requirement["comparison_mode"] = "manual"
            requirement["review_status"] = "needs_review"
            requirement["confidence"] = min(requirement["confidence"], 0.7)
            _add_unresolved(result, original, "manual_evidence_interpretation", True)
        if (
            requirement["type"] == "custom"
            and re.search(r"(?:제작|납품|이행).{0,40}(?:능력|할\s*수)|품질보장|무상\s*(?:A/S|AS)", original, re.I)
        ):
            requirement["comparison_mode"] = "manual"
            requirement["review_status"] = "needs_review"
            requirement["confidence"] = min(requirement["confidence"], 0.7)
            _add_unresolved(result, original, "manual_evidence_interpretation", True)
        if (
            requirement["type"] == "sanction"
            and re.search(r"(?:응찰|입찰).{0,30}(?:방해|담합)|입찰가격.{0,12}담합", original)
            and not re.search(r"제재|제한기간|처분|유죄|확정", original)
        ):
            requirement["type"] = "custom"
            requirement["operator"] = "custom"
            requirement["comparison_mode"] = "manual"
            requirement["review_status"] = "needs_review"
            requirement["confidence"] = min(requirement["confidence"], 0.7)
            _add_unresolved(result, original, "manual_evidence_interpretation", True)
        retained.append(requirement)
    result["requirements"] = retained


def _repair_unresolved_candidates(result: dict) -> None:
    """Keep ordinary submission checklists from blocking company qualification."""
    for candidate in result["unresolved_candidates"]:
        text = candidate["text"]
        if (
            re.search(r"사업자등록증|법인등기부|인감증명서|사용인감계", text)
            and not re.search(r"누락|미제출|자격.{0,8}(?:상실|없)|무효|제외", text)
        ):
            candidate["review_reason"] = "informational_exclusion"
            candidate["blocks_qualification"] = False
        if (
            re.search(r"(?:업체|대상자)\s*선정\s*완료\s*후", text)
            and re.search(r"실제\s*납품\s*요청|납품\s*시", text)
            and re.search(r"주문.{0,30}(?:가능|불가능)|납품\s*대상\s*업체.{0,20}변경", text)
        ):
            candidate["review_reason"] = "informational_exclusion"
            candidate["blocks_qualification"] = False
        if re.search(r"(?:법률|법|규정)\s*등에\s*위배", text) and re.search(r"무효", text):
            candidate["review_reason"] = "referenced_document_missing"
            candidate["blocks_qualification"] = True
    shared_representative_invalid = any(
        requirement.get("failure_effect") == "invalid_bid"
        and re.search(
            r"대표자\s*중\s*1인이\s*다른\s*업체의\s*대표자를\s*겸임|"
            r"동일.{0,12}대표자.{0,30}(?:복수|여러)\s*업체",
            str(requirement.get("original_text") or ""),
        )
        for requirement in result.get("requirements", [])
    )
    if shared_representative_invalid:
        result["unresolved_candidates"] = [
            candidate for candidate in result["unresolved_candidates"]
            if not re.search(
                r"대표자\s*중\s*1인이\s*다른\s*업체의\s*대표자를\s*겸임",
                candidate["text"],
            )
        ]


def _prune_redundant_aggregate_unresolved(result: dict) -> None:
    """Remove a whole eligibility section when every bullet has an atomic result."""
    represented = [
        _citation_compact(text)
        for requirement in result["requirements"]
        for text in [
            requirement.get("proposition_text", ""),
            requirement.get("original_text", ""),
            (requirement.get("value") or {}).get("text", ""),
            *[
                attribute.get("value", "")
                for attribute in (requirement.get("value") or {}).get("attributes", [])
            ],
            *[
                evidence.get("excerpt", "")
                for evidence in requirement.get("evidence", [])
                if evidence.get("source_type") == "document"
            ],
        ]
        if len(_citation_compact(text)) >= 4
    ]
    retained: list[dict] = []
    for candidate in result["unresolved_candidates"]:
        text = candidate["text"]
        bullets = re.split(r"\n\s*[◦○●■□]\s*", text)
        clauses = [part.strip() for part in bullets[1:] if part.strip()]
        if len(text) < 240 or len(clauses) < 2:
            retained.append(candidate)
            continue
        unmatched = [
            clause for clause in clauses
            if not any(snippet in _citation_compact(clause) for snippet in represented)
        ]
        if not unmatched:
            continue
        if len(unmatched) < len(clauses):
            retained.extend({
                "text": clause,
                "review_reason": candidate["review_reason"],
                "blocks_qualification": candidate["blocks_qualification"],
            } for clause in unmatched)
            continue
        retained.append(candidate)
    result["unresolved_candidates"] = retained


def _prune_resolved_unresolved_candidates(result: dict) -> None:
    """Drop manual candidates already represented by an identical atomic rule."""
    represented = {
        _citation_compact(text)
        for requirement in result["requirements"]
        for text in (
            requirement.get("original_text", ""),
            requirement.get("proposition_text", ""),
        )
        if len(_citation_compact(text)) >= 12
    }
    result["unresolved_candidates"] = [
        candidate for candidate in result["unresolved_candidates"]
        if candidate.get("review_reason") == "referenced_document_missing"
        or _citation_compact(candidate["text"]) not in represented
    ]
