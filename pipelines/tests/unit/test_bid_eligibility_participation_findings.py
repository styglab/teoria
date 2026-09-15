from teoria_pipelines.tasks.bid_eligibility import (
    _apply_bid_entry_fast_scope,
    _prune_out_of_scope_participation_findings,
    _repair_requirement_semantics,
)


def _requirement(text: str) -> dict:
    return {
        "id": "r1", "type": "custom", "operator": "exists",
        "value": {"text": text, "number": None, "boolean": True,
                  "items": [], "attributes": []},
        "original_text": text, "proposition_text": text,
        "proposition_start": 0, "proposition_end": len(text),
        "holder_scope": "bidder", "reference_date_type": "none",
        "assessment_stage": "qualification_review",
        "failure_effect": "qualification_rejection", "comparison_mode": "manual",
        "mandatory": True, "review_status": "extracted", "confidence": 1.0,
        "evidence": [{"source_type": "document", "source_id": "doc",
                      "document_id": "doc", "block_id": "b1", "page": 1,
                      "section": "개찰결과", "excerpt": text}],
        "proof_requirements": [], "logic": {"placements": [{
            "scope": "common", "alternative_group": None, "alternative_branch": None,
        }]},
    }


def test_first_ranked_bidder_forms_are_not_company_eligibility() -> None:
    text = "개찰결과 1순위 업체는 지정신청서, 가격제안서 및 서약서를 모두 제출하여야 한다."
    result = {"requirements": [_requirement(text)], "participation_findings": [],
              "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert result["requirements"] == []
    assert result["participation_findings"][0]["category"] == "participation_note"
    assert result["participation_findings"][0]["subject"] == "first_ranked_bidder"


def test_winning_bidder_substantive_license_is_retained_as_eligibility() -> None:
    text = "낙찰자는 계약 체결 전까지 정보통신공사업 면허를 등록하고 서류를 제출하여야 한다."
    result = {"requirements": [_requirement(text)], "participation_findings": [],
              "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert len(result["requirements"]) == 1
    assert result["participation_findings"] == []


def _finding(category: str, text: str) -> dict:
    return {
        "id": "f1", "category": category, "type": "test", "title": text,
        "description": text, "evidence": [{"excerpt": text}],
    }


def test_generic_compliance_and_ordinary_market_rules_are_not_findings() -> None:
    result = {"participation_findings": [
        _finding("participation_note", "청렴계약이행서약서를 제출합니다."),
        _finding("competition_risk_signal", "종합건설업의 상호시장 진출을 제한합니다."),
        _finding("competition_risk_signal", "서울특별시 소재지 제한 요건입니다."),
    ]}

    _prune_out_of_scope_participation_findings(result)

    assert result["participation_findings"] == []


def test_named_manufacturer_support_condition_is_retained() -> None:
    finding = _finding(
        "competition_risk_signal", "지정 제조사의 기술지원확약서를 제출해야 합니다.",
    )
    result = {"participation_findings": [finding]}

    _prune_out_of_scope_participation_findings(result)

    assert result["participation_findings"] == [finding]


def test_fast_scope_keeps_only_bid_entry_requirements_and_no_findings() -> None:
    result = {
        "requirements": [
            {"id": "entry", "assessment_stage": "bid_entry"},
            {"id": "review", "assessment_stage": "qualification_review"},
            {"id": "legacy"},
        ],
        "participation_findings": [{"id": "procedure"}],
    }

    _apply_bid_entry_fast_scope(result)

    assert [item["id"] for item in result["requirements"]] == ["entry", "legacy"]
    assert result["participation_findings"] == []
