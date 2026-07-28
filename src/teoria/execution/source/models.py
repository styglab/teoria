from typing import Any, Literal

from pydantic import BaseModel, Field


class AuthenticationRequirement(BaseModel):
    type: str
    location: Literal["query", "header"]
    name: str
    environment_variable: str


class PreparedRequest(BaseModel):
    source_id: str
    operation_id: str
    method: str
    url: str
    query: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    authentication: AuthenticationRequirement | None = None

    def safe_dump(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ExecutionResponse(BaseModel):
    status_code: int
    content_type: str
    headers: dict[str, str]
    body: Any
    elapsed_ms: float
