import pytest

from teoria_mcp.tools import CapabilityMCPService


CAPABILITIES = [
    {
        "id": "find_contracts",
        "name": "Find contracts",
        "description": "Find contracts by date",
        "returns": ["public_procurement.contract"],
        "input_schema": {
            "type": "object",
            "properties": {"date_from": {"type": "string", "format": "date"}},
            "required": ["date_from"],
            "additionalProperties": False,
        },
    }
]


class CapturingRuntimeClient:
    def __init__(self) -> None:
        self.call = None

    async def execute(self, capability_id, inputs, options):
        self.call = capability_id, inputs, options
        return {"status": "success", "capability": capability_id}


def test_generates_tools_from_runtime_api_metadata() -> None:
    service = CapabilityMCPService(CAPABILITIES, CapturingRuntimeClient())
    tool = service.list_tools()[0]

    assert tool.name == "find_contracts"
    assert tool.inputSchema["properties"]["date_from"]["format"] == "date"
    assert "_options" in tool.inputSchema["properties"]


@pytest.mark.asyncio
async def test_delegates_execution_to_runtime_api() -> None:
    client = CapturingRuntimeClient()
    service = CapabilityMCPService(CAPABILITIES, client)

    result = await service.call_tool(
        "find_contracts",
        {"date_from": "2026-01-01", "_options": {"max_objects": 10}},
    )

    assert client.call == ("find_contracts", {"date_from": "2026-01-01"}, {"max_objects": 10})
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_rejects_unknown_capability_before_runtime_call() -> None:
    service = CapabilityMCPService(CAPABILITIES, CapturingRuntimeClient())
    with pytest.raises(ValueError, match="unknown capability"):
        await service.call_tool("unknown", {})
