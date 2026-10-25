from __future__ import annotations

from pydantic_core import to_jsonable_python

from teoria.features.metadata_management.intelligence.asset_assessment.models import AssessmentResponse


def assessment_response(row: dict, suggestion_ids: list) -> dict:
    result = to_jsonable_python(row)
    for finding in result["findings"]:
        if finding.get("scope") != "disclosure_assessment":
            for key in (
                "information_type",
                "internal_processing",
                "disclosure_recommendation",
                "protection_recommendation",
                "tag_candidates",
            ):
                finding.pop(key, None)
    result.pop("claim_token", None)
    result.pop("request_key", None)
    result["suggestion_ids"] = [str(identifier) for identifier in suggestion_ids]
    return AssessmentResponse.model_validate(result).model_dump(
        mode="json", exclude_unset=True
    )
