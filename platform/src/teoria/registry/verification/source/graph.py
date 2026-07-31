from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from teoria.runtime.source.executor import MissingCredentialError, SourceExecutor
from teoria.runtime.source.errors import SourceExecutionError
from teoria.runtime.source.request import PreparedRequest
from teoria.runtime.source.response import ExecutionResponse
from teoria.runtime.source.request_builder import RequestBuildError, SourceRequestBuilder
from teoria.runtime.source.response_validator import SourceResponseValidator
from teoria.registry.diagnostics import Diagnostic
from teoria.registry.loader import RegistryLoadError, RegistryLoader
from teoria.registry.validator import RegistryValidator
from teoria.registry.verification.source.state import SourceVerificationState


class SourceVerificationServices:
    def __init__(
        self,
        request_builder: SourceRequestBuilder | None = None,
        executor: SourceExecutor | None = None,
        response_validator: SourceResponseValidator | None = None,
    ) -> None:
        self.request_builder = request_builder or SourceRequestBuilder()
        self.executor = executor or SourceExecutor()
        self.response_validator = response_validator or SourceResponseValidator()


def _diagnostics(items: list[Diagnostic]) -> list[dict[str, Any]]:
    return [item.to_dict() for item in items]


def create_source_verification_graph(services: SourceVerificationServices | None = None):
    services = services or SourceVerificationServices()

    async def validate_structure(state: SourceVerificationState) -> dict[str, Any]:
        try:
            catalog = RegistryLoader(state["registry_root"]).load()
            diagnostics = RegistryValidator().validate(catalog, source_id=state.get("source_id"))
        except RegistryLoadError as exc:
            diagnostics = exc.diagnostics
        return {
            "diagnostics": _diagnostics(diagnostics),
            "completed_steps": ["validate_structure"],
            "step_results": [{"name": "validate_structure", "status": "failed" if diagnostics else "passed"}],
            "status": "failed" if diagnostics else "running",
        }

    async def build_request(state: SourceVerificationState) -> dict[str, Any]:
        source_id = state.get("source_id")
        operation_id = state.get("operation_id")
        if not source_id or not operation_id:
            diagnostic = Diagnostic("missing_verification_target", "source_id and operation_id are required for build/live profile", Path(state["registry_root"]))
            return {"diagnostics": [diagnostic.to_dict()], "completed_steps": ["build_request"], "step_results": [{"name": "build_request", "status": "failed"}], "status": "failed"}
        try:
            catalog = RegistryLoader(state["registry_root"]).load()
            request = services.request_builder.build(catalog, source_id, operation_id, state.get("input_data", {}))
        except RequestBuildError as exc:
            return {"diagnostics": _diagnostics(exc.diagnostics), "completed_steps": ["build_request"], "step_results": [{"name": "build_request", "status": "failed"}], "status": "failed"}
        return {"prepared_request": request.safe_dump(), "completed_steps": ["build_request"], "step_results": [{"name": "build_request", "status": "passed"}], "status": "running"}

    async def execute_request(state: SourceVerificationState) -> dict[str, Any]:
        request = PreparedRequest.model_validate(state["prepared_request"])
        try:
            response = await services.executor.execute(request)
        except SourceExecutionError as exc:
            diagnostic = Diagnostic(exc.code, str(exc), Path(state["registry_root"]), location=request.operation_id)
            return {"diagnostics": [diagnostic.to_dict()], "completed_steps": ["execute_request"], "step_results": [{"name": "execute_request", "status": "failed"}], "status": "failed"}
        return {"response": response.model_dump(mode="json"), "completed_steps": ["execute_request"], "step_results": [{"name": "execute_request", "status": "passed"}], "status": "running"}

    async def check_credentials(state: SourceVerificationState) -> dict[str, Any]:
        request = PreparedRequest.model_validate(state["prepared_request"])
        try:
            services.executor.credential(request)
        except MissingCredentialError as exc:
            diagnostic = Diagnostic("missing_credential", str(exc), Path(state["registry_root"]), location=request.source_id)
            return {"diagnostics": [diagnostic.to_dict()], "completed_steps": ["check_credentials"], "step_results": [{"name": "check_credentials", "status": "blocked"}], "status": "blocked"}
        return {"completed_steps": ["check_credentials"], "step_results": [{"name": "check_credentials", "status": "passed"}], "status": "running"}

    async def validate_response(state: SourceVerificationState) -> dict[str, Any]:
        catalog = RegistryLoader(state["registry_root"]).load()
        response = ExecutionResponse.model_validate(state["response"])
        diagnostics = services.response_validator.validate(catalog, state["source_id"], state["operation_id"], response)
        return {
            "diagnostics": _diagnostics(diagnostics),
            "completed_steps": ["validate_response"],
            "step_results": [{"name": "validate_response", "status": "failed" if diagnostics else "passed"}],
            "status": "failed" if diagnostics else "passed",
        }

    def after_structure(state: SourceVerificationState) -> str:
        if state.get("status") == "failed":
            return "end"
        if state.get("profile") == "static":
            return "complete"
        return "build_request"

    async def complete(state: SourceVerificationState) -> dict[str, Any]:
        return {"completed_steps": ["complete"], "step_results": [{"name": "complete", "status": "passed"}], "status": "passed"}

    def after_build(state: SourceVerificationState) -> str:
        if state.get("status") == "failed":
            return "end"
        if state.get("profile") == "build":
            return "complete"
        return "check_credentials"

    def after_credentials(state: SourceVerificationState) -> str:
        return "execute_request" if state.get("status") == "running" else "end"

    def after_execute(state: SourceVerificationState) -> str:
        return "validate_response" if state.get("status") == "running" else "end"

    builder = StateGraph(SourceVerificationState)
    builder.add_node("validate_structure", validate_structure)
    builder.add_node("build_request", build_request)
    builder.add_node("check_credentials", check_credentials)
    builder.add_node("execute_request", execute_request)
    builder.add_node("validate_response", validate_response)
    builder.add_node("complete", complete)
    builder.add_edge(START, "validate_structure")
    builder.add_conditional_edges("validate_structure", after_structure, {"end": END, "complete": "complete", "build_request": "build_request"})
    builder.add_conditional_edges("build_request", after_build, {"end": END, "complete": "complete", "check_credentials": "check_credentials"})
    builder.add_conditional_edges("check_credentials", after_credentials, {"end": END, "execute_request": "execute_request"})
    builder.add_conditional_edges("execute_request", after_execute, {"end": END, "validate_response": "validate_response"})
    builder.add_edge("validate_response", END)
    builder.add_edge("complete", END)
    return builder.compile()
