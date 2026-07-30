from pathlib import Path

import pytest

from teoria.runtime.source.executor import SourceExecutor
from teoria.runtime.source.response import ExecutionResponse
from teoria.registry.verification.source.graph import SourceVerificationServices, create_source_verification_graph


ROOT = Path(__file__).parents[3]


@pytest.mark.parametrize("profile", ["static", "build"])
@pytest.mark.asyncio
async def test_source_verification_profiles(profile: str) -> None:
    graph = create_source_verification_graph()
    state = {
        "registry_root": str(ROOT / "registries"),
        "source_id": "nts_business_registration",
        "operation_id": "get_business_registration_status",
        "profile": profile,
        "input_data": {"body": {"b_no": ["0000000000"]}},
        "diagnostics": [],
        "completed_steps": [],
        "step_results": [],
        "status": "pending",
    }

    result = await graph.ainvoke(state)

    assert result["status"] == "passed"
    assert result["diagnostics"] == []
    assert "validate_structure" in result["completed_steps"]
    if profile == "build":
        assert result["prepared_request"]["method"] == "POST"


class FakeExecutor:
    def credential(self, request) -> str:
        return "test-secret"

    async def execute(self, request) -> ExecutionResponse:
        return ExecutionResponse(
            status_code=200,
            content_type="application/json",
            headers={},
            body={"status_code": "OK", "data": [{"b_no": "0000000000", "b_stt_cd": "01"}]},
            elapsed_ms=1.0,
        )


class EmptyOptionalValuesExecutor:
    def credential(self, request) -> str:
        return "test-secret"

    async def execute(self, request) -> ExecutionResponse:
        return ExecutionResponse(
            status_code=200,
            content_type="application/json",
            headers={},
            body={"status_code": "OK", "data": [{"b_no": "0000000000", "b_stt_cd": "", "end_dt": ""}]},
            elapsed_ms=1.0,
        )


@pytest.mark.asyncio
async def test_live_profile_executes_and_validates_response() -> None:
    graph = create_source_verification_graph(SourceVerificationServices(executor=FakeExecutor()))
    result = await graph.ainvoke(
        {
            "registry_root": str(ROOT / "registries"),
            "source_id": "nts_business_registration",
            "operation_id": "get_business_registration_status",
            "profile": "live",
            "input_data": {"body": {"b_no": ["0000000000"]}},
            "diagnostics": [],
            "completed_steps": [],
            "step_results": [],
            "status": "pending",
        }
    )

    assert result["status"] == "passed"
    assert [step["name"] for step in result["step_results"]] == [
        "validate_structure",
        "build_request",
        "check_credentials",
        "execute_request",
        "validate_response",
    ]


@pytest.mark.asyncio
async def test_live_profile_is_blocked_without_credentials() -> None:
    graph = create_source_verification_graph(
        SourceVerificationServices(executor=SourceExecutor(environment={}))
    )
    result = await graph.ainvoke(
        {
            "registry_root": str(ROOT / "registries"),
            "source_id": "nts_business_registration",
            "operation_id": "get_business_registration_status",
            "profile": "live",
            "input_data": {"body": {"b_no": ["0000000000"]}},
            "diagnostics": [],
            "completed_steps": [],
            "step_results": [],
            "status": "pending",
        }
    )

    assert result["status"] == "blocked"
    assert result["diagnostics"][0]["code"] == "missing_credential"
    assert result["step_results"][-1] == {"name": "check_credentials", "status": "blocked"}


@pytest.mark.asyncio
async def test_live_profile_accepts_empty_optional_source_values() -> None:
    graph = create_source_verification_graph(
        SourceVerificationServices(executor=EmptyOptionalValuesExecutor())
    )
    result = await graph.ainvoke(
        {
            "registry_root": str(ROOT / "registries"),
            "source_id": "nts_business_registration",
            "operation_id": "get_business_registration_status",
            "profile": "live",
            "input_data": {"body": {"b_no": ["0000000000"]}},
            "diagnostics": [],
            "completed_steps": [],
            "step_results": [],
            "status": "pending",
        }
    )

    assert result["status"] == "passed"
