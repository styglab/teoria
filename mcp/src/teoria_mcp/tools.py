from __future__ import annotations

from typing import Any

import mcp.types as types

from teoria_mcp.runtime_client import RuntimeAPIClient
from teoria_mcp.schema import capability_output_schema


class CapabilityMCPService:
    def __init__(self, capabilities: list[dict[str, Any]], runtime_client: RuntimeAPIClient) -> None:
        self.capabilities = {item["id"]: item for item in capabilities}
        self.runtime_client = runtime_client

    def list_tools(self) -> list[types.Tool]:
        tools = []
        for capability in self.capabilities.values():
            returned = ", ".join(capability["returns"])
            tools.append(
                types.Tool(
                    name=capability["id"],
                    title=capability["name"],
                    description=(
                        f"{capability['description']}. 반환 의미 타입: {returned}. "
                        "반환된 온톨로지 속성은 필요한 후속 도구의 입력으로 사용할 수 있다."
                    ),
                    inputSchema=_mcp_input_schema(capability["input_schema"]),
                    outputSchema=capability_output_schema(),
                )
            )
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        if name not in self.capabilities:
            raise ValueError(f"unknown capability '{name}'")
        supplied = dict(arguments or {})
        options = supplied.pop("_options", {})
        return await self.runtime_client.execute(name, supplied, options)


def _mcp_input_schema(runtime_schema: dict[str, Any]) -> dict[str, Any]:
    schema = {**runtime_schema, "properties": dict(runtime_schema.get("properties", {}))}
    schema["properties"]["_options"] = {
        "type": "object",
        "description": "MCP 응답 표현 옵션이며 원천 API 요청에는 전달되지 않는다.",
        "properties": {
            "include_property_provenance": {"type": "boolean", "default": False},
            "max_objects": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
        },
        "additionalProperties": False,
    }
    return schema
