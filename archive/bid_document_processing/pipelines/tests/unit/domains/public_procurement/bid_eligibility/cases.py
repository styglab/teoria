"""Shared source-evidence builders for eligibility regression tests."""


def _simple_document_inputs(text: str) -> dict:
    return {
        "documents": [
            {
                "document_id": "doc-1",
                "content": {
                    "blocks": [
                        {
                            "block_id": "p1",
                            "page": 1,
                            "section": "입찰참가자격",
                            "text": text,
                        }
                    ]
                },
            }
        ],
        "structured_requirements": [],
    }


def _validated_requirement(original_text: str, **overrides: object) -> dict:
    item = {
        "id": "r1",
        "type": "legal_qualification",
        "operator": "exists",
        "value": {
            "text": original_text,
            "number": None,
            "boolean": True,
            "items": [],
            "attributes": [],
        },
        "original_text": original_text,
        "holder_scope": "bidder",
        "reference_date_type": "bid_deadline",
        "assessment_stage": "bid_entry",
        "failure_effect": "cannot_bid",
        "comparison_mode": "manual",
        "proof_requirements": [],
        "mandatory": True,
        "review_status": "extracted",
        "confidence": 1.0,
        "evidence": [
            {
                "source_type": "document",
                "source_id": "doc",
                "document_id": "doc",
                "block_id": "b1",
                "page": 1,
                "section": None,
                "excerpt": original_text,
            }
        ],
    }
    item.update(overrides)
    return item
