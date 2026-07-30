from datetime import date
from pathlib import Path

import pytest

from teoria.runtime.capability.runner import CapabilityResult
from teoria.adapters.mcp.tools import CapabilityMCPService
from teoria.registry.loader import RegistryLoader


ROOT = Path(__file__).parents[3]


class CapturingRunner:
    def __init__(self) -> None:
        self.call = None

    async def run(self, catalog, capability_id, inputs):
        self.call = (catalog, capability_id, inputs)
        return CapabilityResult(capability_id=capability_id)


def test_generates_tools_from_all_capabilities() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    tools = {tool.name: tool for tool in CapabilityMCPService(catalog).list_tools()}

    assert set(tools) == set(catalog.capabilities)
    profile_input = tools["get_company_profile"].inputSchema["properties"]["corporate_registration_number"]
    assert profile_input["type"] == "string"
    assert profile_input["pattern"] == "^[0-9]{13}$"
    verification_business = tools["verify_business_registration"].inputSchema["properties"]["businesses"]["items"]
    assert verification_business["properties"]["opened_date"]["format"] == "date"
    assert "business_registration_number" in verification_business["required"]


@pytest.mark.asyncio
async def test_coerces_json_dates_before_capability_execution() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    runner = CapturingRunner()
    service = CapabilityMCPService(catalog, runner=runner)

    result = await service.call_tool(
        "verify_business_registration",
        {
            "businesses": [
                {
                    "business_registration_number": "0000000000",
                    "opened_date": "2020-01-02",
                    "representative_name": "홍길동",
                }
            ]
        },
    )

    assert runner.call[1] == "verify_business_registration"
    assert runner.call[2]["businesses"][0]["opened_date"] == date(2020, 1, 2)
    assert result == {
        "status": "success",
        "capability": "verify_business_registration",
        "objects": [],
        "links": [],
        "total_objects": 0,
        "total_links": 0,
        "truncated": False,
    }
