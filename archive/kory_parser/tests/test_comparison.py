from kory_parser.compare import compare_results


def test_character_bag_agreement_does_not_hide_reading_order():
    result = compare_results(
        {"success": True, "blocks": [{"text": "ABCD"}]}, {"success": True, "blocks": [{"text": "DCBA"}]}
    )
    assert result["character_multiset_f1"] == 1
    assert result["reading_order_similarity"] < 1
    assert not result["observed_agreement"]


def test_matching_failures_are_not_successful_agreement():
    result = compare_results({"success": False}, {"success": False})
    assert not result["observed_agreement"]


def test_cell_relationship_changes_are_visible_with_same_text():
    def result(rs):
        return {
            "success": True,
            "blocks": [
                {
                    "type": "table",
                    "table": {
                        "rows": 2,
                        "cols": 1,
                        "cells": [[{"text": "CPU", "rowSpan": rs, "colSpan": 1}], [{"text": ""}]],
                    },
                }
            ],
        }

    metrics = compare_results(result(2), result(1))
    assert metrics["text_equal_normalized"]
    assert not metrics["all_table_grids_equal"]
    assert not metrics["observed_agreement"]
