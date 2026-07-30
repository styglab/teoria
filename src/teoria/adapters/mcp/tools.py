from __future__ import annotations

from typing import Any

import mcp.types as types
from pydantic_core import to_jsonable_python

from teoria.runtime.capability.runner import CapabilityResult, CapabilityRunner
from teoria.runtime.provenance import Provenance
from teoria.adapters.mcp.schema import capability_input_schema, capability_output_schema, coerce_capability_inputs
from teoria.registry.loader import RegistryCatalog


class CapabilityMCPService:
    def __init__(self, catalog: RegistryCatalog, runner: CapabilityRunner | None = None) -> None:
        self.catalog = catalog
        self.runner = runner or CapabilityRunner()

    def list_tools(self) -> list[types.Tool]:
        tools = []
        for capability in self.catalog.capabilities.values():
            returned = ", ".join(capability.returns)
            tools.append(
                types.Tool(
                    name=capability.id,
                    title=capability.name,
                    description=(
                        f"{capability.description}. 반환 의미 타입: {returned}. "
                        "반환된 온톨로지 속성은 필요한 후속 도구의 입력으로 사용할 수 있다."
                    ),
                    inputSchema=capability_input_schema(self.catalog, capability),
                    outputSchema=capability_output_schema(),
                )
            )
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        capability = self.catalog.capabilities.get(name)
        if capability is None:
            raise ValueError(f"unknown capability '{name}'")
        supplied = dict(arguments or {})
        options = supplied.pop("_options", {})
        inputs = coerce_capability_inputs(self.catalog, capability, supplied)
        result = await self.runner.run(self.catalog, name, inputs)
        return self._serialize_result(
            result,
            max_objects=int(options.get("max_objects", 200)),
            include_property_provenance=bool(options.get("include_property_provenance", False)),
        )

    @classmethod
    def _serialize_result(
        cls,
        result: CapabilityResult,
        *,
        max_objects: int,
        include_property_provenance: bool,
    ) -> dict[str, Any]:
        objects = []
        for item in result.objects[:max_objects]:
            output: dict[str, Any] = {
                "ontology": item.ontology,
                "type": item.object_type,
                "id": item.object_id,
                "properties": to_jsonable_python(item.properties),
                "provenance": cls._serialize_provenance(item.provenance),
            }
            if include_property_provenance:
                output["property_provenance"] = {
                    key: cls._serialize_provenance(values)
                    for key, values in item.property_provenance.items()
                }
            objects.append(output)
        links = [
            {
                "ontology": item.ontology,
                "type": item.link_type,
                "source": item.source_object_id,
                "target": item.target_object_id,
                "provenance": cls._serialize_provenance(item.provenance),
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

    @staticmethod
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
