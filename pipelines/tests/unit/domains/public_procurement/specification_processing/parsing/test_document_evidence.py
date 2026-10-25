import hashlib
import json

import pytest

from teoria_pipelines.domains.public_procurement.specification_processing.parsing.document_evidence import (
    EvidenceQuote, build_document_evidence, validate_evidence,
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


def test_duplicate_document_identities_are_rejected():
    d = document([{"type": "paragraph", "text": "RAM 16GB이상"}])
    with pytest.raises(ValueError, match="duplicate document"):
        validate_evidence([quote("RAM")], [d, d])
