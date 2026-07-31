from typing import Any


class ProviderExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, source_id: str, operation_id: str,
                 attempts: int, retryable: bool, http_status: int | None = None) -> None:
        self.code = code
        self.source_id = source_id
        self.operation_id = operation_id
        self.attempts = attempts
        self.retryable = retryable
        self.http_status = http_status
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "source": self.source_id,
                "operation": self.operation_id, "attempts": self.attempts,
                "retryable": self.retryable, "http_status": self.http_status}
