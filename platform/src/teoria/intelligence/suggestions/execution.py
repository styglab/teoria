from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from teoria.intelligence.suggestions.repository import SuggestionRepository


@dataclass(frozen=True)
class ApplicationClaim:
    application_id: UUID
    token: UUID
    target_system: str


class ApplicationStateError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


class SuggestionApplicationError(RuntimeError):
    def __init__(
        self, message: str, *, code: str = "suggestion_application_failed"
    ) -> None:
        self.code = code
        super().__init__(message)


@dataclass
class ApplicationSession:
    claim: ApplicationClaim
    finished: bool = False


application_session: ContextVar[ApplicationSession | None] = ContextVar(
    "suggestion_application_session", default=None
)


class ApplicationEffects:
    """Record effect boundaries under the current application claim."""

    def __init__(self, repository: SuggestionRepository):
        self.repository = repository

    async def mark_started(self) -> None:
        session = application_session.get()
        if session is None:
            raise SuggestionApplicationError(
                "Application claim is required", code="application_claim_lost"
            )
        await self.repository.mark_effect_started(session.claim)

    async def finish(self, suggestion_id, **values) -> None:
        session = application_session.get()
        if session is None:
            raise SuggestionApplicationError(
                "Application claim is required", code="application_claim_lost"
            )
        if values["applied"]:
            await self.repository.record_effect_result(
                session.claim, values["external_change_ref"]
            )
        await self.repository.finish_application(
            UUID(str(suggestion_id)), claim_token=session.claim.token, **values
        )
        session.finished = True
