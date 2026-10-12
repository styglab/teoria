from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ApplicationClaim:
    application_id: UUID
    token: UUID
    target_system: str


class ApplicationStateError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code
