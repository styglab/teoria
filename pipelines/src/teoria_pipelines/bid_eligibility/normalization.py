from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher

BID_PRICE_ELIGIBILITY_PATTERN = re.compile(
    r"(?:예정(?:가격|금액)|견적(?:가격|금액)|투찰률|낙찰(?:하한율|가격)|"
    r"(?:제한적\s*)?최저(?:가격|가))"
)

def _assign_evidence(evidence: dict, document: dict, block: dict, excerpt: str) -> None:
    evidence.update({
        "source_id": document["document_id"], "document_id": document["document_id"],
        "block_id": block["block_id"],
        "page": block.get("page"), "section": block.get("section"), "excerpt": excerpt,
    })


def _citation_text(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split())


def _citation_compact(value: str) -> str:
    return "".join(character for character in _citation_text(value) if character.isalnum())


def _ellipsis_fragments_match(excerpt: str, source: str) -> bool:
    if "..." not in excerpt and "…" not in excerpt:
        return False
    fragments = [
        _citation_text(fragment).strip(" .…")
        for fragment in excerpt.replace("…", "...").split("...")
    ]
    fragments = [fragment for fragment in fragments if len(fragment) >= 12]
    if len(fragments) < 2:
        return False
    normalized_source = _citation_text(source)
    offset = 0
    for fragment in fragments:
        position = normalized_source.find(fragment, offset)
        if position < 0:
            return False
        offset = position + len(fragment)
    return True


def _citation_similarity(excerpt: str, source: str) -> float:
    left = _citation_text(excerpt)
    right = _citation_text(source)
    if not left or not right:
        return 0.0
    character_score = SequenceMatcher(None, left, right, autojunk=False).ratio()
    left_tokens = re.findall(r"[0-9A-Za-z가-힣]+", left.casefold())
    right_tokens = set(re.findall(r"[0-9A-Za-z가-힣]+", right.casefold()))
    token_score = (
        sum(1 for token in left_tokens if token in right_tokens) / len(left_tokens)
        if left_tokens else 0.0
    )
    # Some Korean PDFs insert spaces inside every word. Comparing only letters and
    # digits recovers those citations without accepting semantically unrelated text.
    compact_left = "".join(character for character in left.casefold() if character.isalnum())
    compact_right = "".join(character for character in right.casefold() if character.isalnum())
    compact_matcher = SequenceMatcher(None, compact_left, compact_right, autojunk=False)
    compact_score = compact_matcher.ratio()
    compact_coverage = (
        sum(match.size for match in compact_matcher.get_matching_blocks()) / len(compact_left)
        if compact_left else 0.0
    )
    return max(character_score, token_score, compact_score, compact_coverage)


def _consolidate_requirements(result: dict) -> None:
    """Merge duplicate propositions while retaining every distinct source."""
    canonical_by_key: dict[tuple, dict] = {}
    aliases: dict[str, str] = {}
    consolidated: list[dict] = []
    for requirement in result["requirements"]:
        _normalize_joint_participation_prohibition(requirement)
        requirement["evidence"] = _deduplicate_evidence(requirement["evidence"])
        for proof in requirement.get("proof_requirements", []):
            proof["evidence"] = _deduplicate_evidence(proof["evidence"])
        key = _requirement_merge_key(requirement)
        canonical = canonical_by_key.get(key) if key is not None else None
        if canonical is None:
            if key is not None:
                canonical_by_key[key] = requirement
            consolidated.append(requirement)
            continue
        aliases[requirement["id"]] = canonical["id"]
        canonical["evidence"] = _deduplicate_evidence([
            *canonical["evidence"], *requirement["evidence"]
        ])
        canonical["value"] = _merge_requirement_value(canonical["value"], requirement["value"])
        canonical["proof_requirements"] = _merge_proof_requirements(
            canonical.get("proof_requirements", []), requirement.get("proof_requirements", [])
        )
        if "logic" in canonical or "logic" in requirement:
            canonical["logic"] = _merge_requirement_logic(
                canonical.get("logic"), requirement.get("logic")
            )
        if len(requirement["original_text"]) < len(canonical["original_text"]):
            canonical["original_text"] = requirement["original_text"]
        if canonical["reference_date_type"] == "none":
            canonical["reference_date_type"] = requirement["reference_date_type"]
        canonical["mandatory"] = canonical["mandatory"] or requirement["mandatory"]
        canonical["confidence"] = min(canonical["confidence"], requirement["confidence"])
        if requirement["review_status"] == "needs_review":
            canonical["review_status"] = "needs_review"
    result["requirements"] = consolidated
    if aliases and "expression" in result:
        result["expression"] = _rewrite_expression(result["expression"], aliases)


def _merge_proof_requirements(left: list[dict], right: list[dict]) -> list[dict]:
    merged: list[dict] = []
    by_key: dict[tuple, dict] = {}
    for proof in [*left, *right]:
        key = (proof["document_type"], proof["submission_stage"], proof["deadline_text"])
        existing = by_key.get(key)
        if existing is None:
            copied = {**proof, "evidence": _deduplicate_evidence(proof["evidence"])}
            by_key[key] = copied
            merged.append(copied)
        else:
            existing["evidence"] = _deduplicate_evidence([
                *existing["evidence"], *proof["evidence"]
            ])
            existing["mandatory"] = existing["mandatory"] or proof["mandatory"]
            if proof["review_status"] == "needs_review":
                existing["review_status"] = "needs_review"
    for index, proof in enumerate(merged, 1):
        proof["id"] = f"p{index}"
    return merged


def _merge_requirement_logic(left: dict | None, right: dict | None) -> dict:
    placements: list[dict] = []
    for logic in (left, right):
        if not logic:
            continue
        for placement in logic.get("placements", []):
            if placement not in placements:
                placements.append(placement)
    return {"placements": placements}


def _validate_semantic_normalization(result: dict) -> None:
    """Reject semantic duplicates that Codex should have merged before persistence."""
    known: set[tuple] = set()
    custom: set[tuple] = set()
    typed: list[tuple[str, tuple]] = []
    requirement_ids: set[str] = set()
    allowed_effects = {
        "bid_entry": {"cannot_bid", "invalid_bid", "needs_review"},
        "qualification_review": {"qualification_rejection", "needs_review"},
        "contracting": {"cannot_contract", "needs_review"},
    }
    for requirement in result["requirements"]:
        if requirement["id"] in requirement_ids:
            raise ValueError("duplicate_requirement_id")
        requirement_ids.add(requirement["id"])
        stage = requirement.get("assessment_stage", "bid_entry")
        effect = requirement.get("failure_effect", "cannot_bid")
        if effect not in allowed_effects[stage]:
            raise ValueError("assessment_stage_effect_mismatch")
        if effect == "needs_review" and requirement["review_status"] != "needs_review":
            raise ValueError("ambiguous_effect_requires_review")
        proof_ids = [proof["id"] for proof in requirement.get("proof_requirements", [])]
        if len(proof_ids) != len(set(proof_ids)):
            raise ValueError("duplicate_proof_id")
        semantic_key = _semantic_requirement_key(requirement)
        typed.append((requirement["type"], semantic_key))
        if requirement["type"] == "consortium":
            normalized_value = json.dumps(requirement["value"], ensure_ascii=False)
            joint = any(token in normalized_value for token in (
                "공동수급", "공동계약", "공동도급", "컨소시엄"
            ))
            if joint and "하도급" in normalized_value:
                raise ValueError("non_atomic_consortium_requirement")
        proposition = _requirement_proposition(requirement)
        start = requirement.get("proposition_start")
        end = requirement.get("proposition_end")
        if (
            not isinstance(start, int) or not isinstance(end, int)
            or start < 0 or end <= start
            or requirement["original_text"][start:end] != proposition
        ):
            raise ValueError("invalid_proposition_span")
        if "조세포탈" in proposition and requirement["type"] != "sanction":
            raise ValueError("tax_evasion_must_be_sanction")
        if re.search(r"적격심사\s*(?:시|때|과정)", proposition):
            if requirement["assessment_stage"] != "qualification_review":
                raise ValueError("qualification_review_stage_mismatch")
            if requirement["failure_effect"] not in {"qualification_rejection", "needs_review"}:
                raise ValueError("qualification_review_effect_mismatch")
        if (
            stage == "qualification_review"
            and requirement["reference_date_type"] == "bid_deadline"
            and not re.search(
                r"(?:입찰(?:서)?|견적서)\s*(?:제출)?\s*마감|입찰\s*마감",
                requirement["original_text"],
            )
        ):
            raise ValueError("qualification_review_bid_deadline_not_explicit")
        if BID_PRICE_ELIGIBILITY_PATTERN.search(proposition):
            raise ValueError("bid_price_must_not_be_eligibility")
        if (
            stage == "contracting"
            and re.search(r"입찰참가\s*등록|입찰참가자격.{0,8}(?:등록|보유|갖춘)", proposition)
            and not re.search(r"계약(?:체결)?일까지|계약\s*(?:체결|상대자)|유지", proposition)
        ):
            raise ValueError("bid_entry_registration_must_not_be_contracting")
        (custom if requirement["type"] == "custom" else known).add(semantic_key)
    if known & custom:
        raise ValueError("custom_duplicates_known_requirement")
    if len(typed) != len(set(typed)):
        raise ValueError("duplicate_requirement_proposition")
    _validate_source_conflicts(result["requirements"])
    for requirement in result["requirements"]:
        if not any(
            requirement["original_text"] in evidence["excerpt"]
            for evidence in requirement["evidence"]
        ):
            raise ValueError("original_text_must_be_verbatim_evidence")


def _validate_source_conflicts(requirements: list[dict]) -> None:
    positive = {"equals", "contains", "in", "exists", "valid_on"}
    negative = {"not_equals", "not_in", "not_exists"}
    seen: dict[tuple, tuple[str, str]] = {}
    for requirement in requirements:
        value = requirement["value"]
        identity = (
            requirement["type"], requirement["holder_scope"],
            requirement["reference_date_type"],
            requirement.get("assessment_stage", "bid_entry"),
            _citation_text(str(value.get("text") or "")).casefold(),
            value.get("number"), value.get("boolean"),
            tuple(sorted(_citation_text(str(item)).casefold()
                         for item in value.get("items", []))),
        )
        polarity = "positive" if requirement["operator"] in positive else (
            "negative" if requirement["operator"] in negative else "other"
        )
        previous = seen.get(identity)
        if previous and previous[0] != polarity and "other" not in {previous[0], polarity}:
            if requirement["review_status"] != "needs_review" or previous[1] != "needs_review":
                raise ValueError("conflicting_source_requirements_need_review")
        seen[identity] = (polarity, requirement["review_status"])


def _semantic_requirement_key(requirement: dict) -> tuple:
    value = requirement["value"]

    def normalized(item: object) -> str:
        return "".join(
            character for character in _citation_text(str(item)).casefold()
            if character.isalnum()
        )

    return (
        requirement["operator"], requirement["holder_scope"],
        requirement.get("reference_date_type"), requirement.get("assessment_stage"),
        requirement.get("failure_effect"), requirement.get("comparison_mode"),
        normalized(value.get("text") or ""), value.get("number"), value.get("boolean"),
        tuple(sorted(normalized(item) for item in value.get("items", []))),
        tuple(sorted(
            (normalized(item.get("name") or ""), normalized(item.get("value") or ""))
            for item in value.get("attributes", [])
        )),
    )


def _requirement_merge_key(requirement: dict) -> tuple | None:
    value = requirement["value"]
    codes = {
        token.casefold()
        for token in value.get("items", [])
        if re.fullmatch(r"[0-9A-Za-z-]{3,}", str(token))
    }
    for attribute in value.get("attributes", []):
        name = str(attribute.get("name") or "").casefold()
        candidate = str(attribute.get("value") or "").strip()
        if ("code" in name or "번호" in name) and re.fullmatch(r"[0-9A-Za-z-]{3,}", candidate):
            codes.add(candidate.casefold())
    base = (
        requirement["type"], requirement["operator"], requirement["holder_scope"],
        requirement.get("reference_date_type"), requirement.get("assessment_stage"),
        requirement.get("failure_effect"), requirement.get("comparison_mode"),
    )
    if _is_joint_participation_prohibition(requirement):
        return (
            requirement["type"], "joint_participation_not_allowed",
            requirement["holder_scope"], requirement.get("reference_date_type"),
            requirement.get("assessment_stage"), requirement.get("failure_effect"),
        )
    if codes and requirement["type"] in {
        "industry_license", "product_registration", "certificate", "procurement_registration"
    }:
        return (*base, "codes", tuple(sorted(codes)))
    text = "".join(
        character for character in _citation_text(str(value.get("text") or "")).casefold()
        if character.isalnum()
    )
    if requirement["type"] != "custom" and text:
        return (*base, "text", text)
    original = "".join(
        character for character in _citation_text(requirement["original_text"]).casefold()
        if character.isalnum()
    )
    return (*base, "exact", original) if original else None


def _is_joint_participation_prohibition(requirement: dict) -> bool:
    if requirement.get("type") != "consortium":
        return False
    value = requirement.get("value") or {}
    proposition = str(requirement.get("proposition_text") or "").strip()
    text = " ".join([
        proposition or str(requirement.get("original_text") or ""),
        str(value.get("text") or ""),
    ])
    joint_denial = re.search(
        r"(?:공동수급|공동계약|공동도급|컨소시엄).{0,16}(?:불가|불허|금지|허용하지|인정하지)",
        text,
    )
    single_only = re.search(
        r"(?:단독이행이?\s*가능해야|단독(?:이행|\s*참가).{0,8}(?:하여야|해야|한함)|"
        r"단독으로만)", text
    )
    return bool(joint_denial or single_only)


def _normalize_joint_participation_prohibition(requirement: dict) -> None:
    """Canonicalize equivalent single-only/joint-denial wording before merging."""
    if not _is_joint_participation_prohibition(requirement):
        return
    value = requirement.get("value") or {}
    requirement["operator"] = "not_exists"
    requirement["value"] = {
        **value,
        "text": "공동수급 불가",
        "boolean": False,
        "attributes": [
            attribute for attribute in value.get("attributes", [])
            if attribute.get("name") not in {"allowed", "consortium_allowed"}
            and not (
                attribute.get("name") == "arrangement_type"
                and str(attribute.get("value") or "").casefold() == "subcontracting"
            )
        ] + [{"name": "allowed", "value": "false"}],
    }
    requirement["logic"] = {"placements": [{
        "scope": "common", "alternative_group": None, "alternative_branch": None,
    }]}


def _requirement_proposition(requirement: dict) -> str:
    """Return the atomic proposition, excluding incidental text in a shared citation."""
    explicit = str(requirement.get("proposition_text") or "").strip()
    if not explicit:
        value = requirement.get("value") or {}
        normalized = str(value.get("text") or "").strip()
        explicit = normalized if normalized and normalized in requirement["original_text"] else requirement["original_text"]
    if explicit in requirement["original_text"]:
        start = requirement["original_text"].index(explicit)
        requirement.setdefault("proposition_text", explicit)
        requirement.setdefault("proposition_start", start)
        requirement.setdefault("proposition_end", start + len(explicit))
    return explicit


def _deduplicate_evidence(items: list[dict]) -> list[dict]:
    unique: dict[tuple, dict] = {}
    for evidence in items:
        key = (
            evidence["source_type"], evidence["source_id"], evidence["document_id"],
            evidence["block_id"], evidence["excerpt"],
        )
        unique.setdefault(key, evidence)
    return list(unique.values())


def _merge_requirement_value(left: dict, right: dict) -> dict:
    attributes = {
        (item["name"], item["value"]): item
        for item in [*left.get("attributes", []), *right.get("attributes", [])]
    }
    return {
        "text": left.get("text") or right.get("text"),
        "number": left.get("number") if left.get("number") is not None else right.get("number"),
        "boolean": left.get("boolean") if left.get("boolean") is not None else right.get("boolean"),
        "items": list(dict.fromkeys([*left.get("items", []), *right.get("items", [])])),
        "attributes": list(attributes.values()),
    }


def _rewrite_expression(expression: dict, aliases: dict[str, str]) -> dict:
    if expression["operator"] == "leaf":
        return {**expression, "requirement_id": aliases.get(
            expression["requirement_id"], expression["requirement_id"]
        )}
    children = [_rewrite_expression(child, aliases) for child in expression["conditions"]]
    unique: dict[str, dict] = {}
    for child in children:
        unique.setdefault(json.dumps(child, sort_keys=True), child)
    children = list(unique.values())
    if expression["operator"] in {"all", "any"} and len(children) == 1:
        return children[0]
    return {**expression, "conditions": children}


def _expression(operator: str, conditions: list[dict] | None = None,
                requirement_id: str | None = None) -> dict:
    return {"operator": operator, "requirement_id": requirement_id,
            "conditions": conditions or []}
