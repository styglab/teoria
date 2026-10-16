from __future__ import annotations

import json
from typing import Any


def _project_expression(expression: Any, requirement_ids: set[str]) -> dict[str, Any] | None:
    if not isinstance(expression, dict):
        return None
    operator = expression.get("operator")
    if operator == "leaf":
        return expression if str(expression.get("requirement_id")) in requirement_ids else None
    children = [
        projected
        for item in expression.get("conditions", [])
        if (projected := _project_expression(item, requirement_ids)) is not None
    ]
    if not children:
        return None
    if operator == "not":
        return {"operator": "not", "requirement_id": None, "conditions": children[:1]}
    if operator not in {"all", "any"}:
        return None
    if len(children) == 1:
        return children[0]
    return {"operator": operator, "requirement_id": None, "conditions": children}


def _parse_expression(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except ValueError:
            return None
    return None
