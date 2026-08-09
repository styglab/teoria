from __future__ import annotations

from collections import defaultdict
from typing import Any


def expression(operator: str, conditions: list[dict] | None = None,
               requirement_id: str | None = None) -> dict:
    return {"operator": operator, "requirement_id": requirement_id,
            "conditions": conditions or []}


def compile_eligibility_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Compile AI-extracted facts into the stable persisted requirement contract."""
    requirements = facts["requirements"]
    known_ids = {item["id"] for item in requirements}
    placements: dict[str, list[dict]] = {}
    for item in requirements:
        logic = item.get("logic")
        if not isinstance(logic, dict) or not logic.get("placements"):
            raise ValueError("requirement_logic_missing")
        placements[item["id"]] = _normalize_placements(logic["placements"])
    _validate_alternative_placements(placements)

    common = _compile_scope(placements, "common")
    single = _compile_scope(placements, "single")
    consortium = _compile_scope(placements, "consortium")
    mode_scopes = [item for item in (single, consortium) if item is not None]
    mode = None
    if len(mode_scopes) == 1:
        mode = mode_scopes[0]
    elif len(mode_scopes) == 2:
        mode = expression("any", mode_scopes)
    root = _combine("all", [item for item in (common, mode) if item is not None])
    if root is None:
        root = expression("all")

    compiled_requirements = [
        {key: value for key, value in item.items() if key != "logic"}
        for item in requirements
    ]
    result = {
        "schema_version": "1.2.0",
        "requirements": compiled_requirements,
        "expression": root,
        "unresolved_candidates": facts["unresolved_candidates"],
    }
    validate_compiled_expression(result, known_ids)
    return result


def _normalize_placements(placements: list[dict]) -> list[dict]:
    """Remove placements that are logically subsumed by an unconditional global fact."""
    unique: list[dict] = []
    for placement in placements:
        if placement not in unique:
            unique.append(placement)
    global_placement = {
        "scope": "common", "alternative_group": None, "alternative_branch": None,
    }
    if global_placement in unique and any(
        item.get("alternative_group") or item.get("alternative_branch") for item in unique
    ):
        raise ValueError("unconditional_requirement_has_alternative_placement")
    return [global_placement] if global_placement in unique else unique


def _validate_alternative_placements(placements: dict[str, list[dict]]) -> None:
    groups: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for requirement_id, items in placements.items():
        for item in items:
            group = item.get("alternative_group")
            branch = item.get("alternative_branch")
            if group and branch:
                groups[(item["scope"], group)][branch].add(requirement_id)
    for branches in groups.values():
        membership: dict[str, int] = defaultdict(int)
        for requirement_ids in branches.values():
            for requirement_id in requirement_ids:
                membership[requirement_id] += 1
        if any(count > 1 for count in membership.values()):
            raise ValueError("requirement_reused_across_alternative_branches")
        branch_sets = list(branches.values())
        for index, left in enumerate(branch_sets):
            for right in branch_sets[index + 1:]:
                if left <= right or right <= left:
                    raise ValueError("absorbed_alternative_branch")


def _compile_scope(placements: dict[str, list[dict]], scope: str) -> dict | None:
    unconditional: list[str] = []
    groups: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for requirement_id, requirement_placements in placements.items():
        for placement in requirement_placements:
            if placement["scope"] != scope:
                continue
            group = placement.get("alternative_group")
            branch = placement.get("alternative_branch")
            if group is None and branch is None:
                if requirement_id not in unconditional:
                    unconditional.append(requirement_id)
            elif group and branch:
                if requirement_id not in groups[group][branch]:
                    groups[group][branch].append(requirement_id)
            else:
                raise ValueError("incomplete_alternative_placement")

    conditions = [expression("leaf", requirement_id=item) for item in unconditional]
    for branches in groups.values():
        branch_expressions = [
            _combine("all", [expression("leaf", requirement_id=item) for item in ids])
            for ids in branches.values()
        ]
        branch_expressions = [item for item in branch_expressions if item is not None]
        if branch_expressions:
            conditions.append(_combine("any", branch_expressions))
    return _combine("all", conditions)


def _combine(operator: str, conditions: list[dict]) -> dict | None:
    unique: list[dict] = []
    seen: set[str] = set()
    for item in conditions:
        key = repr(item)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    if not unique:
        return None
    if len(unique) == 1:
        return unique[0]
    return expression(operator, unique)


def validate_compiled_expression(result: dict[str, Any], known_ids: set[str] | None = None) -> None:
    """Enforce structural invariants independently from the extraction model."""
    expected = known_ids or {item["id"] for item in result["requirements"]}
    counts: dict[str, int] = defaultdict(int)

    def walk(node: dict, ancestors: tuple[str, ...] = ()) -> set[str]:
        operator = node.get("operator")
        conditions = node.get("conditions")
        requirement_id = node.get("requirement_id")
        if operator == "leaf":
            if requirement_id not in expected or conditions:
                raise ValueError("invalid_expression_leaf")
            counts[requirement_id] += 1
            return {requirement_id}
        if operator not in {"all", "any", "not"} or requirement_id is not None:
            raise ValueError("invalid_expression_node")
        if operator == "not" and len(conditions) != 1:
            raise ValueError("invalid_expression_not")
        child_sets = [walk(child, (*ancestors, operator)) for child in conditions]
        if operator == "all":
            for index, child_ids in enumerate(child_sets):
                sibling_ids = set().union(*(ids for i, ids in enumerate(child_sets) if i != index))
                if child_ids & sibling_ids:
                    raise ValueError("redundant_conjunctive_requirement")
        return set().union(*child_sets) if child_sets else set()

    referenced = walk(result["expression"])
    if referenced != expected:
        raise ValueError("expression_requirement_coverage")
