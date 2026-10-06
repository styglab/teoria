from teoria.intelligence.binding_candidates import rank_binding_candidates


def test_contract_amount_column_prefers_contract_amount_property() -> None:
    candidates = rank_binding_candidates(
        {"name": "contract_amount", "description": "계약금액", "dataType": "NUMERIC", "tags": []},
        [
            {"concept_id": "1", "concept_kind": "property", "stable_key": "procurement.Contract.amount", "name": "계약금액", "description": "확정 계약금액", "value_type": "decimal"},
            {"concept_id": "2", "concept_kind": "property", "stable_key": "procurement.Contract.contractDate", "name": "계약일", "description": "계약 체결일", "value_type": "date"},
        ],
    )

    assert candidates[0].stable_key == "procurement.Contract.amount"
    assert candidates[0].score > candidates[1].score
    assert {item["type"] for item in candidates[0].evidence} >= {
        "normalized_name_similarity", "datatype_compatibility"
    }


def test_source_column_matches_canonical_property_code_across_languages() -> None:
    candidates = rank_binding_candidates(
        {"name": "current_contract_amount", "description": None, "dataType": "NUMERIC", "tags": []},
        [
            {"concept_id": "1", "concept_kind": "property", "stable_key": "procurement.Contract.currentAmount", "code": "currentAmount", "name": "계약금액", "description": "최신 계약 버전 금액", "value_type": "decimal"},
            {"concept_id": "2", "concept_kind": "property", "stable_key": "procurement.Award.winningAmount", "code": "winningAmount", "name": "낙찰금액", "description": "낙찰 결과 금액", "value_type": "decimal"},
        ],
    )

    assert candidates[0].stable_key == "procurement.Contract.currentAmount"
    assert candidates[0].evidence[0]["property_code"] == "currentAmount"
