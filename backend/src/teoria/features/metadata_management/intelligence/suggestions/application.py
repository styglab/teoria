from __future__ import annotations

from uuid import UUID

from teoria.features.metadata_management.intelligence.suggestions.appliers.drafts import (
    DraftApplier,
)
from teoria.features.metadata_management.intelligence.suggestions.appliers.openmetadata import (
    OpenMetadataApplier,
)
from teoria.features.metadata_management.intelligence.suggestions.execution import (
    ApplicationEffects,
    ApplicationSession,
    ApplicationStateError,
    SuggestionApplicationError,
    application_session,
)


class SuggestionApplicationService:
    def __init__(
        self,
        repository,
        metadata_client,
        binding_repository=None,
        ontology_service=None,
    ):
        self.repository = repository
        self.metadata_client = metadata_client
        self.effects = ApplicationEffects(repository)
        self.metadata = OpenMetadataApplier(repository, metadata_client, self.effects)
        self.drafts = DraftApplier(
            repository,
            metadata_client,
            binding_repository,
            ontology_service,
            self.effects,
        )

    async def review_and_apply(
        self, suggestion_id: UUID, *, decision: str, reviewer: str, comment: str | None
    ) -> dict:
        current = await self.repository.get(suggestion_id)
        if decision == "approve" and current.get("status") == "applied":
            return current
        if decision == "approve" and current.get("suggestion_type") == "binding":
            await self.drafts.validate_binding_evidence(current)
        if decision == "approve" and current.get("status") in {"approved", "failed"}:
            suggestion = current
        else:
            suggestion = await self.repository.review(
                suggestion_id, decision=decision, reviewer=reviewer, comment=comment
            )
        if decision != "approve":
            return suggestion
        return await self._apply_approved(suggestion, reviewer=reviewer)

    async def _apply_approved(self, suggestion: dict, *, reviewer: str) -> dict:
        kind = suggestion["suggestion_type"]
        target = (
            "teoria_binding"
            if kind == "binding"
            else "teoria_ontology"
            if kind == "ontology_change"
            else "openmetadata"
        )
        try:
            claim = await self.repository.start_application(
                UUID(str(suggestion["suggestion_id"])),
                target_system=target,
                actor=reviewer,
            )
        except ApplicationStateError as exc:
            if exc.code == "application_already_applied":
                return await self.repository.get(UUID(str(suggestion["suggestion_id"])))
            raise SuggestionApplicationError(str(exc), code=exc.code) from exc
        session = ApplicationSession(claim)
        token = application_session.set(session)
        try:
            return await self._dispatch_suggestion(suggestion, reviewer=reviewer)
        except (SuggestionApplicationError, ValueError, KeyError) as exc:
            if not session.finished:
                await self.effects.finish(
                    suggestion["suggestion_id"],
                    applied=False,
                    error_code=getattr(exc, "code", "application_failed"),
                )
            raise
        finally:
            application_session.reset(token)

    async def _dispatch_suggestion(self, suggestion: dict, *, reviewer: str) -> dict:
        if suggestion["suggestion_type"] == "binding":
            return await self.drafts.apply_binding_suggestion(
                suggestion, reviewer=reviewer
            )
        if suggestion["suggestion_type"] == "glossary_term_assignment":
            return await self.metadata.apply_glossary_term_assignment(suggestion)
        if suggestion["suggestion_type"] == "glossary_term":
            return await self.metadata.apply_glossary_term(suggestion)
        if suggestion["suggestion_type"] == "ontology_change":
            return await self.drafts.apply_ontology_change(
                suggestion, reviewer=reviewer
            )
        if suggestion["suggestion_type"] == "test_suite":
            return await self.metadata.apply_test_suite(suggestion)
        if suggestion["suggestion_type"] == "quality_test":
            return await self.metadata.apply_quality_test(suggestion)
        if suggestion["suggestion_type"] == "description":
            return await self.metadata.apply_description(suggestion)
        await self.effects.finish(
            suggestion["suggestion_id"],
            applied=False,
            error_code="unsupported_suggestion_type",
        )
        raise SuggestionApplicationError(
            f"Unsupported suggestion type: {suggestion['suggestion_type']}"
        )

    async def reconcile_application(self, suggestion_id: UUID, *, actor: str) -> dict:
        suggestion = await self.repository.get(suggestion_id)
        if suggestion["status"] == "applied":
            return suggestion
        application = await self.repository.get_application(suggestion_id)
        if not application:
            raise SuggestionApplicationError(
                "No application exists", code="application_not_found"
            )
        if application["lease_active"] and application["status"] == "applying":
            raise SuggestionApplicationError(
                "Application is running", code="application_in_progress"
            )
        external_ref = application.get("external_change_ref")
        verified = bool(application.get("effect_succeeded_at") and external_ref)
        proposed = suggestion["proposed_value"]
        if not verified and suggestion["suggestion_type"] in {
            "description",
            "glossary_term_assignment",
        }:
            expected_value = proposed.get(
                "description"
                if suggestion["suggestion_type"] == "description"
                else "glossary_term_fqn"
            )
            if (
                not application.get("effect_started_at")
                or not isinstance(expected_value, str)
                or not expected_value.strip()
            ):
                raise SuggestionApplicationError(
                    "No valid attempted effect exists to reconcile",
                    code="application_reconciliation_required",
                )
            if self.metadata_client is None:
                raise SuggestionApplicationError("OpenMetadata is unavailable")
            table_id = proposed.get("table_id") or suggestion[
                "target_ref"
            ].removeprefix("openmetadata://table/")
            table = await self.metadata_client.get(
                f"v1/tables/{table_id}", params={"fields": "columns"}
            )
            if suggestion["target_type"] == "openmetadata_column":
                target = next(
                    (
                        c
                        for c in table.get("columns", [])
                        if c.get("name") == proposed.get("column_name")
                    ),
                    None,
                )
                if target is None:
                    raise SuggestionApplicationError(
                        "Target column is missing", code="application_target_missing"
                    )
            else:
                target = table
            if suggestion["suggestion_type"] == "description":
                verified = target.get("description") == expected_value.strip()
            else:
                verified = any(
                    t.get("source") == "Glossary"
                    and t.get("tagFQN") == proposed.get("glossary_term_fqn")
                    for t in target.get("tags", [])
                )
            entity_type = (
                "column"
                if suggestion["target_type"] == "openmetadata_column"
                else "table"
            )
            external_ref = f"openmetadata://{entity_type}/{target.get('fullyQualifiedName') or proposed.get('column_fqn') or table_id}@{table.get('version', '')}"
        if not verified:
            raise SuggestionApplicationError(
                "The existing effect needs independent verification; another write is blocked",
                code="application_reconciliation_required",
            )
        await self.repository.reconcile_application(
            suggestion_id,
            claim_token=application.get("claim_token"),
            external_change_ref=external_ref,
            actor=actor,
        )
        return await self.repository.get(suggestion_id)
