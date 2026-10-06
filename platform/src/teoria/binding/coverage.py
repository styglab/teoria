from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from teoria.registry.loader import RegistryCatalog


def build_capability_binding_coverage(
    catalog: RegistryCatalog,
    approved_bindings: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    bound: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"capability": set(), "input": set(), "output": set()}
    )
    for item in approved_bindings:
        capability_id = item.get("capability_id")
        scope = item.get("capability_target_scope") or item.get("target_scope")
        if not capability_id or scope not in {"capability", "input", "output"}:
            continue
        field_path = item.get("capability_field_path") or item.get("field_path")
        bound[capability_id][scope].add(field_path or "*")

    items = []
    totals = {
        "capability_count": len(catalog.capabilities),
        "capability_bound_count": 0,
        "input_count": 0,
        "bound_input_count": 0,
        "output_count": 0,
        "bound_output_count": 0,
    }
    for capability_id, capability in sorted(catalog.capabilities.items()):
        input_fields = set(capability.inputs)
        output_fields = set(capability.returns)
        bound_inputs = input_fields & bound[capability_id]["input"]
        bound_outputs = output_fields & bound[capability_id]["output"]
        capability_bound = bool(bound[capability_id]["capability"])
        covered = capability_bound or bool(bound_inputs or bound_outputs)
        if covered:
            totals["capability_bound_count"] += 1
        totals["input_count"] += len(input_fields)
        totals["bound_input_count"] += len(bound_inputs)
        totals["output_count"] += len(output_fields)
        totals["bound_output_count"] += len(bound_outputs)
        fully_covered = (
            capability_bound
            and len(bound_inputs) == len(input_fields)
            and len(bound_outputs) == len(output_fields)
        )
        items.append(
            {
                "capability_id": capability_id,
                "status": "covered" if fully_covered else "partial" if covered else "unbound",
                "capability_bound": capability_bound,
                "inputs": {
                    "total": len(input_fields),
                    "bound": len(bound_inputs),
                    "unbound_fields": sorted(input_fields - bound_inputs),
                },
                "outputs": {
                    "total": len(output_fields),
                    "bound": len(bound_outputs),
                    "unbound_fields": sorted(output_fields - bound_outputs),
                },
            }
        )
    totals["capability_coverage_rate"] = (
        totals["capability_bound_count"] / totals["capability_count"]
        if totals["capability_count"] else None
    )
    return {"summary": totals, "items": items}
