from __future__ import annotations

from typing import Any

from pydantic_core import to_jsonable_python

from teoria.runtime.capability.runner import CapabilityResult
from teoria.runtime.provenance import Provenance


def serialize_capability_result(
    result: CapabilityResult,
    *,
    max_objects: int = 200,
    include_property_provenance: bool = False,
) -> dict[str, Any]:
    objects = []
    for item in result.objects[:max_objects]:
        output: dict[str, Any] = {
            "ontology": item.ontology,
            "type": item.object_type,
            "id": item.object_id,
            "properties": to_jsonable_python(item.properties),
            "provenance": _serialize_provenance(item.provenance),
        }
        if include_property_provenance:
            output["property_provenance"] = {
                key: _serialize_provenance(values) for key, values in item.property_provenance.items()
            }
        objects.append(output)
    links = [
        {
            "ontology": item.ontology,
            "type": item.link_type,
            "source": item.source_object_id,
            "target": item.target_object_id,
            "provenance": _serialize_provenance(item.provenance),
        }
        for item in result.links
    ]
    return {
        "status": "success",
        "capability": result.capability_id,
        "objects": objects,
        "links": links,
        "total_objects": len(result.objects),
        "total_links": len(result.links),
        "truncated": len(result.objects) > max_objects,
    }


def _serialize_provenance(values: list[Provenance]) -> list[dict[str, Any]]:
    return [
        {
            "kind": value.kind,
            "source": value.source,
            "operation": value.operation,
            "mapping": value.mapping,
            "observed_at": value.observed_at.isoformat(),
            "record_keys": value.record_keys,
        }
        for value in values
    ]
