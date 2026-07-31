from typing import Any, Mapping

from teoria_provider.diagnostics import Diagnostic
from teoria_provider.errors import ProviderExecutionError
from teoria_provider.executor import MissingCredentialError, ProviderExecutor
from teoria_provider.request_builder import ProviderRequestBuilder, RequestBuildError
from teoria_provider.response_validator import ProviderResponseValidator

from teoria_pipelines.loader import PipelineCatalog
from teoria_pipelines.validator import PipelineValidator


async def verify_connector(pipeline_catalog: PipelineCatalog, *, connector_id: str,
                           operation_id: str | None, profile: str,
                           input_data: dict[str, Any], executor: ProviderExecutor | None = None,
                           data_types: Mapping[str, Any] | None = None) -> dict[str, Any]:
    diagnostics = PipelineValidator().validate(pipeline_catalog, connector_id=connector_id)
    steps = [{"name": "validate_structure", "status": "failed" if diagnostics else "passed"}]
    if diagnostics:
        return _result("failed", diagnostics, steps)
    if profile == "static":
        return _result("passed", [], steps)
    if not operation_id:
        diagnostic = Diagnostic("missing_verification_target", "operation is required for build/live profile",
            pipeline_catalog.root / "connectors")
        steps.append({"name": "build_request", "status": "failed"})
        return _result("failed", [diagnostic], steps)
    registry = pipeline_catalog.connectors[connector_id]
    path = pipeline_catalog.connector_paths[connector_id]
    try:
        request = ProviderRequestBuilder().build(registry.connector, operation_id, input_data,
            data_types=data_types, path=path)
    except RequestBuildError as exc:
        steps.append({"name": "build_request", "status": "failed"})
        return _result("failed", exc.diagnostics, steps)
    steps.append({"name": "build_request", "status": "passed"})
    prepared_request = request.safe_dump()
    if profile == "build":
        return _result("passed", [], steps, prepared_request=prepared_request)
    executor = executor or ProviderExecutor()
    try:
        executor.credential(request)
    except MissingCredentialError as exc:
        steps.append({"name": "check_credentials", "status": "blocked"})
        return _result("blocked", [Diagnostic("missing_credential", str(exc), pipeline_catalog.root,
            location=connector_id)], steps, prepared_request=prepared_request)
    steps.append({"name": "check_credentials", "status": "passed"})
    try:
        response = await executor.execute(request)
    except ProviderExecutionError as exc:
        steps.append({"name": "execute_request", "status": "failed"})
        return _result("failed", [Diagnostic(exc.code, str(exc), pipeline_catalog.root,
            location=operation_id)], steps, prepared_request=prepared_request)
    steps.append({"name": "execute_request", "status": "passed"})
    response_diagnostics = ProviderResponseValidator().validate(registry.connector, operation_id,
        response, data_types=data_types, path=path)
    steps.append({"name": "validate_response", "status": "failed" if response_diagnostics else "passed"})
    return _result("failed" if response_diagnostics else "passed", response_diagnostics, steps,
        prepared_request=prepared_request, response=response.model_dump(mode="json"))


def _result(status: str, diagnostics: list[Diagnostic], steps: list[dict[str, str]],
            **values: Any) -> dict[str, Any]:
    return {"status": status, "diagnostics": [item.to_dict() for item in diagnostics],
            "step_results": steps, **values}
