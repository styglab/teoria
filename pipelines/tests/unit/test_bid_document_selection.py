import pytest

from teoria_pipelines.bid_document_selection import (
    deduplicate_semantic_documents,
    select_eligibility_blocks,
)


def _document(name: str, texts: list[str]) -> dict:
    return {
        "file_name": name,
        "content": {
            "blocks": [
                {"block_id": f"b{index}", "page": None, "text": text}
                for index, text in enumerate(texts)
            ]
        },
    }


def test_keeps_bid_notice_whole_even_when_large() -> None:
    document = _document("입찰공고문.pdf", [f"내용 {index}" for index in range(200)])

    selected = select_eligibility_blocks(document)

    assert len(selected["content"]["blocks"]) == 200
    assert selected["selection"]["strategy"] == "full_document"


def test_large_bid_notice_is_bounded_by_character_budget() -> None:
    texts = [(f"일반 공고 내용 {index} " * 80) for index in range(200)]
    texts[190] = "입찰참가자격은 정보통신공사업 등록 업체로 제한합니다."

    selected = select_eligibility_blocks(_document("입찰공고문.pdf", texts), max_chars=12_000)

    assert selected["selection"]["selected_char_count"] <= 12_000
    assert selected["selection"]["original_char_count"] > 12_000
    assert any(block["block_id"].startswith("b190") for block in selected["content"]["blocks"])
    assert selected["selection"]["strategy"] == "focused_with_omission_guard"


def test_keeps_short_supplement_whole() -> None:
    document = _document("제안요청서.hwpx", [f"내용 {index}" for index in range(100)])

    selected = select_eligibility_blocks(document)

    assert len(selected["content"]["blocks"]) == 100


def test_large_rfp_uses_terms_and_independent_omission_guard() -> None:
    texts = [f"일반 내용 {index}" for index in range(220)]
    texts[100] = "입찰참가자격은 중소기업 확인서를 보유한 자"
    texts[190] = "전문인력 3인 이상을 재직 상태로 보유하여야 한다"
    document = _document("제안요청서.hwpx", texts)

    selected = select_eligibility_blocks(document)
    chosen = selected["content"]["blocks"]

    assert 50 < len(chosen) < 220
    assert any(block["block_id"] == "b100" for block in chosen)
    assert any(block["block_id"] == "b190" for block in chosen)
    assert selected["selection"]["passes"] == [
        "leading_blocks", "requirement_terms", "omission_guard"
    ]
    assert selected["selection"]["omitted_block_count"] == 220 - len(chosen)


def test_unknown_document_type_defaults_to_full_for_safety() -> None:
    document = _document("기타첨부.dat", [f"내용 {index}" for index in range(200)])

    selected = select_eligibility_blocks(document)

    assert len(selected["content"]["blocks"]) == 200


def test_large_cost_breakdown_uses_focused_selection() -> None:
    texts = [f"공사 내역 셀 {index}" for index in range(3000)]
    texts[2800] = "법인등기부상 본점 소재지가 해당 지역인 업체만 참가할 수 있습니다."

    selected = select_eligibility_blocks(_document("공사내역서.xlsx", texts))

    assert len(selected["content"]["blocks"]) < 3000
    assert any(block["block_id"] == "b2800" for block in selected["content"]["blocks"])
    assert selected["selection"]["strategy"] == "focused_with_omission_guard"


def test_large_supplement_unions_semantic_retrieval_with_exact_terms() -> None:
    texts = [f"일반적인 계약 설명 {index}" for index in range(220)]
    texts[180] = "선정 전 갖춰야 할 특별한 조직 상태를 설명합니다."

    selected = select_eligibility_blocks(
        _document("과업지시서.hwpx", texts), semantic_block_ids={"b180"},
    )

    assert any(block["block_id"] == "b180" for block in selected["content"]["blocks"])
    assert "semantic_retrieval" in selected["selection"]["passes"]


def test_large_source_block_is_split_with_stable_parent_offsets() -> None:
    text = "\n".join(f"{index}. 참가자격 세부 조건을 확인하여야 합니다." for index in range(80))

    selected = select_eligibility_blocks(_document("입찰공고문.hwp", [text]))
    blocks = selected["content"]["blocks"]

    assert len(blocks) > 1
    assert all(block["parent_block_id"] == "b0" for block in blocks)
    assert all(len(block["text"]) <= 900 for block in blocks)
    assert blocks[0]["char_start"] == 0


def test_semantic_duplicate_prefers_pdf_and_keeps_alias() -> None:
    common = "입찰참가자격은 중소기업 확인서를 보유한 업체로 제한합니다. " * 20
    documents = [
        {**_document("공고문.hwp", [common]), "document_id": "hwp"},
        {**_document("공고문.pdf", [common.replace(" ", "  ")]), "document_id": "pdf"},
    ]

    deduplicated = deduplicate_semantic_documents(documents)

    assert len(deduplicated) == 1
    assert deduplicated[0]["document_id"] == "pdf"
    assert deduplicated[0]["semantic_duplicate_documents"] == [
        {"document_id": "hwp", "file_name": "공고문.hwp"}
    ]


def test_large_rfp_keeps_company_category_condition_in_late_blocks() -> None:
    texts = [f"일반 내용 {index}" for index in range(220)]
    texts[205] = "여성기업지원에 관한 법률에 따른 여성기업만 참여할 수 있습니다."

    selected = select_eligibility_blocks(_document("제안요청서.hwp", texts))

    assert any(block["block_id"] == "b205" for block in selected["content"]["blocks"])


def test_large_supplement_keeps_borrowed_certificate_invalid_bid_clause() -> None:
    texts = [f"일반 내용 {index}" for index in range(220)]
    texts[205] = (
        "1인이 수인의 공인인증서를 차용하여 입찰서를 제출할 경우 "
        "당해 입찰은 무효인 입찰에 해당됩니다."
    )

    selected = select_eligibility_blocks(_document("제안요청서.hwp", texts))

    assert any(block["block_id"] == "b205" for block in selected["content"]["blocks"])


def test_semantic_deduplication_preserves_document_with_unique_requirement() -> None:
    common = "입찰 일반 안내입니다. " * 200
    documents = [
        {**_document("공고문.pdf", [common]), "document_id": "pdf"},
        {**_document("공고문.hwp", [common, "장애인기업만 참가할 수 있습니다."]),
         "document_id": "hwp"},
    ]

    assert len(deduplicate_semantic_documents(documents)) == 2


@pytest.mark.parametrize("clause", [
    "세부품명번호 4511161601이 공급물품으로 등록된 자만 참여할 수 있습니다.",
    "법인등기부상 본점 소재지가 서울특별시인 자만 참여할 수 있습니다.",
    "파산 또는 회생절차가 진행 중인 업체는 참여할 수 없습니다.",
])
def test_large_supplement_keeps_late_realistic_eligibility_clauses(clause: str) -> None:
    texts = [f"일반 내용 {index}" for index in range(180)]
    texts[160] = clause

    selected = select_eligibility_blocks(_document("구매규격서.hwp", texts))

    assert any(block["block_id"] == "b160" for block in selected["content"]["blocks"])
