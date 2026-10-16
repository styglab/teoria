from __future__ import annotations

from datetime import date
from typing import Any

from teoria.domains.public_procurement.bid_eligibility.evaluators import evaluate_requirement
from teoria.domains.public_procurement.bid_eligibility.expression import aggregate_expression
from teoria.domains.public_procurement.bid_eligibility.models import (
    CompanyEvidenceSnapshot,
    RequirementEvaluation,
)
from teoria.registry.loader import RegistryCatalog
from teoria.runtime.mapping.materializer import MaterializedObject

from .assessment_policy import (
    KEY_OUTCOME_CATEGORIES,
    RULE_OUTCOME_CATEGORIES,
    TYPE_OUTCOME_CATEGORIES,
)
from .expression_projection import _parse_expression, _project_expression


def _key_outcomes(
    notice: MaterializedObject,
    evaluations: list[RequirementEvaluation],
) -> dict[str, dict[str, Any]]:
    evaluations = _participation_evaluations(evaluations)
    grouped: dict[str, list[RequirementEvaluation]] = {
        category: [] for category in KEY_OUTCOME_CATEGORIES
    }
    for evaluation in evaluations:
        grouped[_requirement_outcome_category(evaluation.requirement)].append(evaluation)

    extraction_incomplete = notice.properties.get("extraction_completeness") in {
        "partial", "api_only",
    }
    expression = _parse_expression(notice.properties.get("requirement_expression"))
    result: dict[str, dict[str, Any]] = {}
    for category, category_evaluations in grouped.items():
        if not category_evaluations:
            result[category] = {
                "applicability": "unknown" if extraction_incomplete else "not_applicable",
                "outcome": "needs_review" if extraction_incomplete else None,
                "satisfied_count": 0,
                "unsatisfied_count": 0,
                "needs_review_count": 0,
                "requirement_ids": [],
            }
            continue
        category_outcomes = {
            str(item.requirement.properties.get("local_id")): item.decision.outcome
            for item in category_evaluations
        }
        projected = _project_expression(expression, set(category_outcomes))
        if projected is None:
            mandatory_outcomes = {
                str(item.requirement.properties.get("local_id")): item.decision.outcome
                for item in category_evaluations
                if item.requirement.properties.get("mandatory", True)
            }
            outcome = aggregate_expression(None, mandatory_outcomes or category_outcomes)
        else:
            outcome = aggregate_expression(projected, category_outcomes)
        result[category] = {
            "applicability": "applicable",
            "outcome": outcome,
            "satisfied_count": sum(item.decision.outcome == "satisfied" for item in category_evaluations),
            "unsatisfied_count": sum(item.decision.outcome == "unsatisfied" for item in category_evaluations),
            "needs_review_count": sum(item.decision.outcome == "needs_review" for item in category_evaluations),
            "requirement_ids": [
                item.requirement.properties.get("requirement_id")
                for item in category_evaluations
            ],
        }
    return result


def evaluate_requirement_category(
    notice: MaterializedObject,
    requirements: list[MaterializedObject],
    snapshot: CompanyEvidenceSnapshot,
    reference_date: date,
    catalog: RegistryCatalog,
    category: str,
) -> tuple[dict[str, Any], list[RequirementEvaluation]]:
    """Evaluate one requirement category with the canonical eligibility rules."""
    selected = [
        requirement for requirement in requirements
        if _requirement_outcome_category(requirement) == category
        and (requirement.properties.get("assessment_stage") or "bid_entry") == "bid_entry"
    ]
    evaluations = [
        RequirementEvaluation(
            requirement=requirement,
            decision=evaluate_requirement(requirement, snapshot, reference_date, catalog),
        )
        for requirement in selected
    ]
    return _key_outcomes(notice, evaluations)[category], evaluations


def _requirement_outcome_category(requirement: MaterializedObject) -> str:
    rule_id = str(requirement.properties.get("standard_rule_id") or "")
    if rule_id in RULE_OUTCOME_CATEGORIES:
        return RULE_OUTCOME_CATEGORIES[rule_id]
    requirement_type = str(requirement.properties.get("requirement_type") or "")
    return TYPE_OUTCOME_CATEGORIES.get(requirement_type, "custom")


def _aggregate_assessment(
    notice: MaterializedObject,
    evaluations: list[RequirementEvaluation],
) -> tuple[str, dict[str, int]]:
    evaluations = _participation_evaluations(evaluations)
    outcomes = {
        str(item.requirement.properties.get("local_id")): item.decision.outcome
        for item in evaluations
    }
    expression = _project_expression(
        _parse_expression(notice.properties.get("requirement_expression")), set(outcomes),
    )
    if not evaluations:
        overall = "satisfied"
    elif expression is None:
        mandatory_outcomes = {
            str(item.requirement.properties.get("local_id")): item.decision.outcome
            for item in evaluations
            if item.requirement.properties.get("mandatory", True)
        }
        overall = aggregate_expression(None, mandatory_outcomes)
    else:
        overall = aggregate_expression(expression, outcomes)
    incomplete_coverage = notice.properties.get("extraction_completeness") in {
        "partial", "api_only",
    }
    if incomplete_coverage and overall == "satisfied":
        overall = "needs_review"
    counts = {
        value: sum(item.decision.outcome == value for item in evaluations)
        for value in ("satisfied", "unsatisfied", "needs_review")
    }
    return overall, counts


def _participation_evaluations(
    evaluations: list[RequirementEvaluation],
) -> list[RequirementEvaluation]:
    return [
        item for item in evaluations
        if (item.requirement.properties.get("assessment_stage") or "bid_entry") == "bid_entry"
    ]
