from copy import deepcopy

import pytest

from teoria_pipelines.domains.public_procurement.specification_intelligence.search_evaluation import (
    QuestionSet, check_question_set, grade_answers, normalized_value, split_documents,
    value_in_quote,
)


def documents():
    return [{"document_id": f"d{i}", "notice_number": f"n{i}", "source_sha256": f"h{i}"} for i in range(20)]


def question_set():
    return {"questions": [{
        "question_id": "q1", "question": "서버 A의 설치 메모리 요구 용량은?", "category": "configuration",
        "expected": {"owner": "server_a", "attribute": "memory_capacity", "value": "256", "unit": "GB",
                     "operator": "ge", "configuration": "installed", "aggregation": "total",
                     "quote": "서버 A: 설치 메모리 256GB 이상, 최대 지원 4TB"},
        "rationale": "최대 지원 용량과 구별한다.",
    }, {"question_id": "q2", "question": "서버 A의 무게는?", "category": "unanswerable",
        "expected": None, "rationale": "무게 명시 없음"}]}


def test_split_is_order_independent_and_preserves_exposed_documents():
    docs = documents()
    exposed = {f"h{i}" for i in range(10)}
    result = split_documents(docs, exposed_sha256=exposed, seed="frozen")
    reverse = split_documents(list(reversed(docs)), exposed_sha256=exposed, seed="frozen")
    assert {d["document_id"] for d in result["validation"]} == {d["document_id"] for d in reverse["validation"]}
    assert len(result["development"]) == 16
    assert len(result["validation"]) == 4
    assert not exposed & {d["source_sha256"] for d in result["validation"]}


def test_connected_notice_and_duplicate_hash_never_leak():
    docs = documents()
    docs[1]["notice_number"] = docs[0]["notice_number"]
    docs[2]["source_sha256"] = docs[1]["source_sha256"]
    result = split_documents(docs, exposed_sha256={"h0"}, seed="frozen")
    dev = {d["document_id"] for d in result["development"]}
    assert {"d0", "d1", "d2"} <= dev
    assert not {d["notice_number"] for d in result["development"]} & {d["notice_number"] for d in result["validation"]}


def test_insufficient_unexposed_data_fails_instead_of_reusing_seen_data():
    with pytest.raises(ValueError, match="insufficient"):
        split_documents(documents(), exposed_sha256={f"h{i}" for i in range(20)}, seed="frozen")


def test_label_validation_rejects_fabricated_and_substring_values():
    raw = question_set()
    source = raw["questions"][0]["expected"]["quote"]
    assert check_question_set(raw, source)
    raw["questions"][0]["expected"]["value"] = "56"
    with pytest.raises(ValueError, match="value absent"):
        check_question_set(raw, source)
    raw["questions"][0]["expected"]["value"] = "256"
    with pytest.raises(ValueError, match="quote absent"):
        check_question_set(raw, "다른 문서")


@pytest.mark.parametrize("field,value,failure", [
    ("configuration", "supported", "configuration"),
    ("aggregation", "per_instance", "aggregation"),
    ("operator", "le", "operator"),
    ("value", "4", "value_or_unit"),
    ("unit", "TB", "value_or_unit"),
    ("quote", "서버 B 설치 메모리 256GB 이상", "evidence_identity"),
])
def test_semantic_boundaries_cannot_pass_on_matching_digits(field, value, failure):
    raw = question_set()
    prediction = deepcopy(raw["questions"][0]["expected"])
    prediction[field] = value
    result = grade_answers(QuestionSet.model_validate(raw), {"answers": [
        {"question_id": "q1", "answer": prediction}, {"question_id": "q2", "answer": None},
    ]}, raw["questions"][0]["expected"]["quote"])
    assert result["passed"] == 1
    assert failure in result["rows"][0]["failures"]


def test_missing_is_not_abstention_and_duplicates_fail():
    questions = QuestionSet.model_validate(question_set())
    assert grade_answers(questions, {}, "") ["passed"] == 0
    assert grade_answers(questions, {"answers": [
        {"question_id": "q2", "answer": None}, {"question_id": "q2", "answer": None},
    ]}, "")["passed"] == 0


def test_unit_conversion_never_assumes_tb_means_1024_gb():
    assert normalized_value("3.2", "GHz") == normalized_value("3200", "MHz")
    assert normalized_value("1", "TiB") == normalized_value("1024", "GiB")
    assert normalized_value("1", "TB") != normalized_value("1024", "GB")


def test_adjacent_model_digits_are_not_joined_to_requirement_values():
    assert value_in_quote("96", "GPU D7 96GB")
    assert value_in_quote("2", "CPU EPYC 7T83 2 EA")
    assert not value_in_quote("56", "RAM 256GB")


def test_complete_expected_passage_may_be_quoted_with_more_source_context():
    raw = question_set()
    expected = raw["questions"][0]["expected"]
    extended = "납품 장비\n" + expected["quote"] + "\n서버 B: 메모리 128GB"
    answer = {**expected, "quote": extended}
    result = grade_answers(QuestionSet.model_validate(raw), {"answers": [
        {"question_id": "q1", "answer": answer}, {"question_id": "q2", "answer": None},
    ]}, extended)
    assert result["passed"] == 2
