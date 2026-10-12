from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from teoria.runtime.mapping.materializer import MaterializedLink, MaterializedObject
from teoria_provider_api.models import ExecutionResponse


class CapabilityExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        capability_id: str,
        source_id: str | None = None,
        operation_id: str | None = None,
        page: int | None = None,
        attempts: int | None = None,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.capability_id = capability_id
        self.source_id = source_id
        self.operation_id = operation_id
        self.page = page
        self.attempts = attempts
        self.retryable = retryable
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "capability": self.capability_id,
            "source": self.source_id,
            "operation": self.operation_id,
            "page": self.page,
            "attempts": self.attempts,
            "retryable": self.retryable,
        }


class CapabilityResult(BaseModel):
    capability_id: str
    objects: list[MaterializedObject] = Field(default_factory=list)
    links: list[MaterializedLink] = Field(default_factory=list)
    responses: list[ExecutionResponse] | None = None
    outcome: dict[str, Any] | None = None
    pagination: dict[str, int] | None = None
    pagination_by_step: dict[str, dict[str, int]] | None = None


