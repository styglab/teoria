import operator
from typing import Annotated, Any, Literal, TypedDict


class SourceVerificationState(TypedDict, total=False):
    registry_root: str
    source_id: str
    operation_id: str
    profile: Literal["static", "build", "live"]
    input_data: dict[str, Any]

    prepared_request: dict[str, Any]
    response: dict[str, Any]
    diagnostics: Annotated[list[dict[str, Any]], operator.add]
    completed_steps: Annotated[list[str], operator.add]
    step_results: Annotated[list[dict[str, str]], operator.add]
    status: str
