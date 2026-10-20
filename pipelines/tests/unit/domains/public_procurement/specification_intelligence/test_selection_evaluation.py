import pytest

from teoria_pipelines.domains.public_procurement.specification_intelligence.selection_evaluation import (
    ReviewedAttachment, evaluate_selection,
)


def case(slot, priority, label, target=True, notice="n"):
    return ReviewedAttachment(notice, str(slot), priority, label, "reviewed source passage", target, 100)


def test_reports_real_misses_false_positives_and_unknowns_separately():
    cases = [case(1, "first_review", "includes_requirements"),
             case(2, "additional_review", "no_requirements"),
             case(3, "manual_review", "includes_requirements"),
             case(4, "first_review", "unconfirmed"),
             case(5, "manual_review", "unconfirmed")]
    result = evaluate_selection(cases, notice_ids={"n", "missing"},
                                selected_priorities=frozenset({"first_review", "additional_review"}))
    assert result["true_positive"] == result["false_positive"] == result["false_negative"] == 1
    assert result["selected_unknown"] == result["unselected_unknown"] == 1
    assert result["precision_on_confirmed"] == result["recall_on_confirmed"] == .5
    assert result["precision_bounds_with_unknowns"] == [1/3, 2/3]
    assert result["recall_bounds_with_unknowns"] == [1/3, 2/3]
    assert result["fully_reviewed_notices"] == 0
    assert result["target_notice_recall_on_complete"] is None
    assert result["selected_bytes"] == 300


def test_non_target_technical_document_is_not_a_server_recovery():
    result = evaluate_selection([case(1, "first_review", "includes_requirements", target=False)], notice_ids={"n"})
    assert result["precision_on_confirmed"] == 1
    assert result["target_positive_notices"] == 0
    assert result["target_notice_recall_on_complete"] is None


def test_complete_notice_must_include_a_selected_real_target_specification():
    cases = [case(1, "first_review", "no_requirements"),
             case(2, "manual_review", "includes_requirements")]
    result = evaluate_selection(cases, notice_ids={"n"})
    assert result["target_positive_notices"] == 1
    assert result["target_recovered_notices"] == 0
    assert result["target_notice_recall_on_complete"] == 0
    assert result["population_target_status"] == "not_established_by_this_sample"


def test_narrow_policy_does_not_silently_include_additional_review():
    result = evaluate_selection([case(1, "additional_review", "includes_requirements")], notice_ids={"n"},
                                selected_priorities=frozenset({"first_review"}))
    assert result["selected_files"] == 0
    assert result["false_negative"] == 1


def test_default_policy_holds_related_documents_out_of_selection():
    result = evaluate_selection([case(1, "additional_review", "includes_requirements")], notice_ids={"n"})
    assert result["selected_priorities"] == ["first_review"]
    assert result["selected_files"] == 0
    assert result["false_negative"] == 1


def test_invalid_or_unsupported_labels_and_duplicate_rows_are_rejected():
    row = case(1, "first_review", "includes_requirements")
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_selection([row, row], notice_ids={"n"})
    with pytest.raises(ValueError, match="evidence"):
        evaluate_selection([ReviewedAttachment("n", "1", "first_review", "includes_requirements")], notice_ids={"n"})
    with pytest.raises(ValueError, match="state"):
        evaluate_selection([case(1, "first_review", "filename_says_specification")], notice_ids={"n"})


def test_known_miss_is_not_hidden_by_unknown_unselected_images():
    rows = [case(1, "manual_review", "includes_requirements"),
            case(2, "manual_review", "unconfirmed")]
    result = evaluate_selection(rows, notice_ids={"n"})
    assert result["fully_reviewed_notices"] == 0
    assert result["known_target_positive_notices"] == 1
    assert result["definite_missed_target_notices"] == 1
    assert result["known_target_notice_recall_bounds"] == [0, 0]


def test_selected_unknown_document_does_not_become_a_definite_miss():
    rows = [case(1, "manual_review", "includes_requirements"),
            case(2, "first_review", "unconfirmed")]
    result = evaluate_selection(rows, notice_ids={"n"})
    assert result["definite_missed_target_notices"] == 0
    assert result["known_target_notice_recall_bounds"] == [0, 1]
    assert result["known_target_recovery_unknown_ids"] == ["n"]
