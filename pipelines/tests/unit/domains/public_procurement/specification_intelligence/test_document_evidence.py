import hashlib
import json

import pytest

from teoria_pipelines.domains.public_procurement.specification_intelligence.document_evidence import (
    EvidenceQuote, build_document_evidence, validate_evidence,
)
from teoria_pipelines.domains.public_procurement.specification_intelligence.document_qualification import (
    QualificationProposal, validate_qualification,
)


def document(blocks, **extra):
    native = {"success": True, "blocks": blocks, **extra}
    return build_document_evidence(
        native, document_id="spec", parse_run_id="parse_1",
        native_sha256=hashlib.sha256(json.dumps(native).encode()).hexdigest(),
    )


def quote(text, node_id="n00000"):
    return EvidenceQuote(document_id="spec", node_id=node_id, quote=text)


@pytest.mark.parametrize("altered", ["메모리 16MB이상", "메모리 160GB이상", "메모리 1.6GB이상", "메모리 16GB이하"])
def test_changed_value_unit_and_operator_are_not_source_evidence(altered):
    d = document([{"type": "paragraph", "text": "메모리 16GB이상"}])
    assert validate_evidence([quote(altered)], [d]) == ["quote_not_in_source"]


def test_spacing_and_full_width_characters_are_allowed_but_blank_is_not():
    d = document([{"type": "paragraph", "text": "RAM １６ＧＢ 이상"}])
    assert validate_evidence([quote("RAM 16GB이상")], [d]) == []
    assert validate_evidence([quote("   ")], [d]) == ["quote_not_in_source"]
    assert validate_evidence([quote("RAM", "unknown")], [d]) == ["unknown_evidence_node"]


def test_nested_table_preserves_parent_span_and_native_pointer_without_double_counting():
    d = document([{"type": "table", "table": {"sourceId": "t1", "cells": [[{
        "text": "RAM 16GB", "rowSpan": 2, "colSpan": 1,
        "blocks": [{"type": "paragraph", "text": "RAM 16GB"}],
    }]]}}])
    table, cell, text = d.nodes
    assert cell.text == ""
    assert cell.parent_id == table.node_id and text.parent_id == cell.node_id
    assert cell.row_span == 2 and cell.source_table_id == "t1"
    assert text.native_ref == "/blocks/0/table/cells/0/0/blocks/0"
    assert sum(n.text.count("16GB") for n in d.nodes) == 1


def proposal(decision="REQUIREMENTS_FOUND", evidence=None):
    return QualificationProposal.model_validate({
        "document_role": "procurement_specification", "summary": "Codex proposal",
        "regions": [{"region_id": "r1", "decision": decision,
                     "evidence": [quote("RAM 16GB이상").model_dump()] if evidence is None else evidence,
                     "reason": "발주 조건"}],
    })


def test_valid_quote_does_not_approve_semantic_correctness():
    d = document([{"type": "paragraph", "text": "RAM 16GB이상"}])
    result = validate_qualification(proposal(), d)
    assert result["decision"] == "REQUIREMENTS_FOUND"
    assert result["review_status"] == "pending"
    assert result["scope"] == "supplied_parse_only"


def test_missing_evidence_blocks_positive_proposal():
    d = document([{"type": "paragraph", "text": "RAM 16GB이상"}])
    result = validate_qualification(proposal(evidence=[]), d)
    assert result["decision"] == "AMBIGUOUS"
    assert not result["regions"][0]["eligible_for_analysis"]


def test_image_regions_prevent_negative_document_conclusion():
    d = document([{"type": "paragraph", "text": "RAM 16GB이상"}, {"type": "image"}])
    result = validate_qualification(proposal("NO_REQUIREMENTS_FOUND"), d)
    assert result["decision"] == "AMBIGUOUS"
    assert result["unassessed_native_refs"] == ["/blocks/1"]


def test_empty_document_is_unassessable():
    d = document([], warnings=[{"code": "NEEDS_OCR"}])
    p = QualificationProposal(document_role="unknown", regions=[], summary="no text")
    assert validate_qualification(p, d)["decision"] == "UNASSESSABLE"


def test_image_filename_is_not_readable_document_content():
    d = document([{"type": "image", "text": "image_001.bmp"}])
    p = QualificationProposal(document_role="unknown", regions=[], summary="image only")
    assert validate_qualification(p, d)["decision"] == "UNASSESSABLE"
    assert "/document:no_extractable_text" in d.unreadable_refs


def test_duplicate_document_and_region_identities_are_rejected():
    d = document([{"type": "paragraph", "text": "RAM 16GB이상"}])
    with pytest.raises(ValueError, match="duplicate document"):
        validate_evidence([quote("RAM")], [d, d])
    p = proposal()
    p.regions.append(p.regions[0])
    with pytest.raises(ValueError, match="duplicate qualification region"):
        validate_qualification(p, d)
