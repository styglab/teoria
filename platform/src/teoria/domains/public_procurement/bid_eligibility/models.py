from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from teoria.runtime.mapping.materializer import MaterializedObject


@dataclass(slots=True)
class CompanyEvidenceSnapshot:
    objects: list[MaterializedObject] = field(default_factory=list)
    unavailable_capabilities: set[str] = field(default_factory=set)
    assessment_context: dict[str, Any] = field(default_factory=dict)

    def by_type(self, object_type: str) -> list[MaterializedObject]:
        return [item for item in self.objects if item.object_type == object_type]


@dataclass(slots=True)
class EvaluationDecision:
    outcome: str
    reason_code: str
    evaluated_value_text: str
    evidence: list[MaterializedObject] = field(default_factory=list)


@dataclass(slots=True)
class RequirementEvaluation:
    requirement: MaterializedObject
    decision: EvaluationDecision


def requirement_value(properties: dict[str, Any]) -> dict[str, Any]:
    import json

    value = properties.get("value_text")
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {"text": value}
    return parsed if isinstance(parsed, dict) else {"text": str(parsed)}
