from __future__ import annotations

from uuid import UUID

from teoria.features.metadata_management.intelligence.suggestions.execution import (
    ApplicationEffects,
    SuggestionApplicationError,
)


class DraftApplier:
    def __init__(
        self,
        repository,
        metadata_client,
        binding_repository,
        ontology_repository,
        effects: ApplicationEffects,
    ):
        self.repository = repository
        self.metadata_client = metadata_client
        self.binding_repository = binding_repository
        self.ontology_repository = ontology_repository
        self.effects = effects

    async def apply_ontology_change(self, suggestion: dict, *, reviewer: str) -> dict:
        if self.ontology_repository is None:
            raise SuggestionApplicationError("Ontology authoring service is required")
        proposed = suggestion["proposed_value"]
        namespace = proposed.get("namespace")
        version = proposed.get("version")
        operation = proposed.get("operation")
        kind = proposed.get("kind")
        if not all(
            isinstance(value, str) and value
            for value in (
                namespace,
                version,
                operation,
                kind,
            )
        ):
            raise SuggestionApplicationError(
                "Ontology namespace, version, operation and kind are required"
            )
        try:
            base_id = proposed.get("based_on_version_id")
            await self.effects.mark_started()
            draft = await self.ontology_repository.create_draft(
                namespace,
                version=version,
                actor=reviewer,
                based_on_version_id=UUID(base_id) if base_id else None,
            )
            draft_id = UUID(str(draft["ontology_version_id"]))
            if operation == "add":
                change = await self.ontology_repository.add_item(
                    draft_id,
                    kind=kind,
                    payload=proposed.get("item") or {},
                    actor=reviewer,
                )
            elif operation == "update":
                change = await self.ontology_repository.update_item(
                    draft_id,
                    kind=kind,
                    concept_id=UUID(str(proposed["concept_id"])),
                    changes=proposed.get("changes") or {},
                    actor=reviewer,
                )
            else:
                raise SuggestionApplicationError(
                    f"Unsupported ontology operation: {operation}"
                )
        except (KeyError, ValueError, SuggestionApplicationError) as exc:
            await self.effects.finish(
                suggestion["suggestion_id"],
                applied=False,
                error_code="ontology_draft_failed",
            )
            raise SuggestionApplicationError(str(exc)) from exc
        await self.effects.finish(
            suggestion["suggestion_id"],
            applied=True,
            external_change_ref=f"teoria://ontology/draft/{draft_id}",
        )
        result = await self.repository.get(UUID(str(suggestion["suggestion_id"])))
        result["resulting_ontology_draft"] = draft
        result["resulting_ontology_change"] = change
        return result

    async def apply_binding_suggestion(
        self, suggestion: dict, *, reviewer: str
    ) -> dict:
        if self.metadata_client is None or self.binding_repository is None:
            raise SuggestionApplicationError(
                "Metadata and binding services are required"
            )
        proposed = suggestion["proposed_value"]
        try:
            await self.effects.mark_started()
            binding = await self.binding_repository.create_openmetadata_binding(
                ontology_ref_type=proposed["ontology_ref_type"],
                ontology_ref_id=None,
                ontology_concept_id=UUID(proposed["ontology_concept_id"]),
                target_type="data_asset",
                external_entity_id=proposed["external_entity_id"],
                entity_type=proposed["entity_type"],
                fully_qualified_name=proposed["fully_qualified_name"],
                external_version=proposed.get("external_version"),
                binding_type=proposed["binding_type"],
                purpose="metadata_intelligence_suggestion",
                authority="supplemental",
                priority=100,
                confidence=float(suggestion["confidence"]),
                provenance={
                    "suggestion_id": suggestion["suggestion_id"],
                    "reviewer": reviewer,
                },
                created_by=reviewer,
            )
        except Exception as exc:
            await self.effects.finish(
                suggestion["suggestion_id"],
                applied=False,
                error_code="binding_draft_failed",
            )
            raise SuggestionApplicationError(str(exc)) from exc
        await self.effects.finish(
            suggestion["suggestion_id"],
            applied=True,
            external_change_ref=f"teoria://binding/{binding['binding_id']}",
        )
        result = await self.repository.get(UUID(suggestion["suggestion_id"]))
        result["resulting_binding"] = binding
        return result

    async def validate_binding_evidence(self, suggestion: dict) -> None:
        if self.metadata_client is None or self.binding_repository is None:
            raise SuggestionApplicationError(
                "Metadata and binding services are required"
            )
        proposed = suggestion["proposed_value"]
        table = await self.metadata_client.get(f"v1/tables/{proposed['table_id']}")
        current_version = (
            str(table.get("version")) if table.get("version") is not None else None
        )
        if current_version != proposed.get("source_version"):
            raise SuggestionApplicationError(
                "STALE_EVIDENCE: OpenMetadata entity changed; re-evaluate the suggestion",
                code="stale_evidence",
            )
