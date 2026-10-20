import socket

import pytest

from teoria_pipelines.domains.public_procurement.specification_intelligence.attachment_selection import (
    prioritize_attachment,
    SELECTED_REVIEW_PRIORITIES,
)


@pytest.mark.parametrize("filename", [
    "2. 물품규격서_GPU서버.hwp", "물품 내역 및 세부 규격서_최종.hwpx",
    "붙임 3. 물품 규격서.pdf", "물품 규격 사양서.hwp",
    "수질측정기 사양서.pdf", "책상 제작 시방서.hwpx",
])
def test_direct_roles_work_across_goods_without_product_codes(filename):
    result = prioritize_attachment(filename)
    assert result.priority == "first_review"
    assert result.content_state == "not_reviewed"
    assert result.original_filename == filename


@pytest.mark.parametrize("filename", ["규격서 작성양식.hwp", "규격서 평가표.pdf", "제안요청서 작성안내.hwp"])
def test_auxiliary_document_cannot_be_promoted_even_by_reference(filename):
    result = prioritize_attachment(filename, source_reference="제안요청서 참조")
    assert result.priority == "manual_review"
    assert result.auxiliary_terms


@pytest.mark.parametrize("filename", ["현품설명서.xlsx", "제안요청서.pdf", "과업지시서.hwp", "물품내역서.xlsx"])
def test_related_document_gets_additional_review_not_confirmed_contents(filename):
    result = prioritize_attachment(filename)
    assert result.priority == "additional_review"
    assert result.content_state == "not_reviewed"


def test_reference_selects_the_named_role_not_a_different_file():
    result = prioritize_attachment("1. 입찰공고문.hwp", source_reference="공고문 참조", rule_version="attachment_review_v2")
    assert result.priority == "first_review"
    assert result.reference_matches == ("공고문",)
    assert result.content_state == "not_reviewed"
    assert prioritize_attachment("공고문.hwp", source_reference="사양서 참조").priority == "manual_review"
    assert prioritize_attachment("공고문.hwp", source_reference="공고문 참조하지 않음").priority == "manual_review"


@pytest.mark.parametrize("filename", [None, " \u200b ", 17, "붙임1.hwp", "구매 특수조건.hwp", "서버 목록.xlsx"])
def test_insufficient_metadata_stays_manual(filename):
    assert prioritize_attachment(filename).priority == "manual_review"


def test_mixed_document_does_not_disappear_or_silently_become_first():
    result = prioritize_attachment("공고문 및 규격서.hwp")
    assert result.priority == "manual_review"
    assert result.mixed_roles
    assert result.matched_roles


def test_normalization_determinism_and_no_network(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Network must not be used")
    monkeypatch.setattr(socket, "socket", unexpected)
    result = prioritize_attachment("【물품_규격_사양서】.HWP")
    assert result == prioritize_attachment("【물품_규격_사양서】.HWP")
    assert result.normalized_filename == "물품규격사양서.hwp"
    assert result.priority == "first_review"


@pytest.mark.parametrize("filename", ["규격비교조사표.hwp", "산출내역서.xlsx", "기자재용도설명서.hwp", "인프라 구성도.pdf"])
def test_v2_adds_review_roles_without_rewriting_v1(filename):
    original = prioritize_attachment(filename, rule_version="attachment_review_v1")
    revised = prioritize_attachment(filename, rule_version="attachment_review_v2")
    assert original.priority == "manual_review"
    assert original.rule_version == "attachment_review_v1"
    assert revised.priority == "additional_review"
    assert revised.rule_version == "attachment_review_v2"
    assert revised.content_state == "not_reviewed"
    assert prioritize_attachment(filename.replace('.', ' 작성양식.'), rule_version="attachment_review_v2").priority == "manual_review"


def test_unknown_version_is_rejected():
    with pytest.raises(ValueError, match="unsupported"):
        prioritize_attachment("규격서.hwp", rule_version="future")


@pytest.mark.parametrize("filename,reference,priority", [
    ("제안요청서.hwp", "제안요청서 참조", "additional_review"),
    ("공고문.hwp", "공고문 참조", "manual_review"),
    ("공고문 및 규격서.hwp", "공고문 참조", "manual_review"),
    ("현품설명서.xlsx", "현품설명서 참조", "additional_review"),
])
def test_v3_reference_is_preserved_but_cannot_select_ambiguous_document(filename, reference, priority):
    previous = prioritize_attachment(filename, source_reference=reference, rule_version="attachment_review_v2")
    current = prioritize_attachment(filename, source_reference=reference)
    assert previous.priority == "first_review"
    assert current.rule_version == "attachment_review_v3"
    assert current.priority == priority
    assert current.reference_matches
    assert current.priority not in SELECTED_REVIEW_PRIORITIES
    assert current.content_state == "not_reviewed"


def test_selected_direct_specification_is_still_not_a_training_label():
    result = prioritize_attachment("물품규격서.hwp")
    assert result.priority in SELECTED_REVIEW_PRIORITIES
    assert result.content_state == "not_reviewed"
