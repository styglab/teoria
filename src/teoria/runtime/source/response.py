from typing import Any

from pydantic import BaseModel


class ExecutionResponse(BaseModel):
    status_code: int
    content_type: str
    headers: dict[str, str]
    body: Any
    elapsed_ms: float
