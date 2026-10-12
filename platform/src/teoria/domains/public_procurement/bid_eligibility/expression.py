from __future__ import annotations

from typing import Any


def aggregate_expression(expression: Any, outcomes: dict[str, str]) -> str:
    if not isinstance(expression, dict):
        return _all(list(outcomes.values()))
    operator = expression.get("operator")
    if operator == "leaf":
        return outcomes.get(str(expression.get("requirement_id")), "needs_review")
    children = [aggregate_expression(item, outcomes) for item in expression.get("conditions", [])]
    if operator == "all":
        return _all(children)
    if operator == "any":
        return _any(children)
    if operator == "not" and len(children) == 1:
        return {
            "satisfied": "unsatisfied",
            "unsatisfied": "satisfied",
            "needs_review": "needs_review",
        }[children[0]]
    return "needs_review"


def _all(outcomes: list[str]) -> str:
    if not outcomes:
        return "needs_review"
    if "unsatisfied" in outcomes:
        return "unsatisfied"
    if "needs_review" in outcomes:
        return "needs_review"
    return "satisfied"


def _any(outcomes: list[str]) -> str:
    if not outcomes:
        return "needs_review"
    if "satisfied" in outcomes:
        return "satisfied"
    if "needs_review" in outcomes:
        return "needs_review"
    return "unsatisfied"
