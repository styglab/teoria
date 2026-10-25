import copy
import json
import runpy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from teoria.features.metadata_management.intelligence.suggestions.contracts import (
    SuggestionInput,
    metadata_proposal_bundle_schema,
)

ROOT = (Path(__file__).resolve().parents[5])
SKILL = ROOT / ".agents/skills/enrich-metadata-asset"
validate_bundle = runpy.run_path(str(SKILL / "scripts/submit_proposals.py"))["validate"]


def bundle():
    return {
        "bundle_version": "1.0",
        "suggestions": [
            {
                "target_type": "openmetadata_column",
                "target_ref": "openmetadata://column/service.db.schema.table.amount",
                "suggestion_type": "description",
                "proposed_value": {
                    "table_id": "table-id",
                    "column_name": "amount",
                    "column_fqn": "service.db.schema.table.amount",
                    "description": "계약 금액",
                    "source_version": "1.0",
                    "source_description": None,
                },
                "confidence": 0.6,
                "risk_level": "medium",
                "model_provider": "test",
                "model_name": "synthetic",
                "policy_version": "metadata-asset-analysis-v1",
                "evidence": [
                    {"evidence_type": "source_document", "source_ref": "test://spec"}
                ],
            }
        ],
    }


def test_skill_schema_is_exported_from_the_server_suggestion_contract():
    stored = json.loads((SKILL / "references/proposal_bundle.schema.json").read_text())
    assert stored == metadata_proposal_bundle_schema()
    Draft202012Validator.check_schema(stored)
    for item in validate_bundle(bundle()):
        SuggestionInput.model_validate(item)


@pytest.mark.parametrize(
    "change",
    [
        "missing_source_description",
        "invalid_confidence",
        "wrong_target_prefix",
        "unknown_field",
        "missing_evidence",
        "invalid_evidence_time",
    ],
)
def test_skill_submission_rejects_invalid_or_unreviewable_proposals(change):
    value = copy.deepcopy(bundle())
    item = value["suggestions"][0]
    if change == "missing_source_description":
        del item["proposed_value"]["source_description"]
    elif change == "invalid_confidence":
        item["confidence"] = True
    elif change == "wrong_target_prefix":
        item["target_ref"] = "openmetadata://table/service.db.schema.table"
    elif change == "unknown_field":
        item["actor"] = "untrusted-actor"
    elif change == "missing_evidence":
        item["evidence"] = []
    else:
        item["evidence"][0]["observed_at"] = "invalid-date"
    with pytest.raises(ValueError):
        validate_bundle(value)
