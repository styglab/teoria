from __future__ import annotations

from uuid import UUID


from teoria.features.semantic_modeling.binding.repository import BindingRepository
from teoria.features.metadata_management.intelligence.suggestions.application import (
    SuggestionApplicationService,
)
from teoria.features.metadata_management.intelligence.suggestions.contracts import (
    SuggestionInput,
)
from teoria.features.metadata_management.intelligence.suggestions.generation import (
    ProposalService,
)
from teoria.features.metadata_management.intelligence.suggestions.repository import (
    SuggestionRepository,
)
from teoria.features.metadata_management.catalog.asset_context import (
    asset_targets,
    suggestion_target_refs,
)
from teoria.integrations.openmetadata import OpenMetadataClient, OpenMetadataError
from teoria.integrations.openmetadata.mapper import table_detail
from teoria.features.semantic_modeling.ontology.service import OntologyAuthoringService


class SuggestionService:
    """Admin operations composed from proposal creation and approved application."""

    def __init__(
        self,
        repository: SuggestionRepository,
        metadata_client: OpenMetadataClient | None,
        binding_repository: BindingRepository | None = None,
        ontology_service: OntologyAuthoringService | None = None,
    ) -> None:
        self.repository = repository
        self.metadata_client = metadata_client
        self.binding_repository = binding_repository
        self.ontology_service = ontology_service

        self.proposals = ProposalService(
            repository, metadata_client, binding_repository
        )
        self.applications = SuggestionApplicationService(
            repository, metadata_client, binding_repository, ontology_service
        )

    async def suggest_column_binding(
        self, *, table_id: str, column_name: str, submitted_by: str
    ) -> dict:
        return await self.proposals.suggest_column_binding(
            table_id=table_id, column_name=column_name, submitted_by=submitted_by
        )

    async def suggest_description_change(
        self,
        *,
        table_id: str,
        description: str,
        submitted_by: str,
        column_name: str | None = None,
    ) -> dict:
        return await self.proposals.suggest_description_change(
            table_id=table_id,
            description=description,
            submitted_by=submitted_by,
            column_name=column_name,
        )

    async def review_and_apply(
        self, suggestion_id: UUID, *, decision: str, reviewer: str, comment: str | None
    ) -> dict:
        return await self.applications.review_and_apply(
            suggestion_id, decision=decision, reviewer=reviewer, comment=comment
        )

    async def reconcile_application(self, suggestion_id: UUID, *, actor: str) -> dict:
        return await self.applications.reconcile_application(suggestion_id, actor=actor)

    async def get(self, suggestion_id: UUID) -> dict:
        return await self.repository.get(suggestion_id)

    async def create(self, payload: SuggestionInput, *, submitted_by: str) -> dict:
        return await self.repository.create(
            **payload.model_dump(mode="json", exclude={"evidence"}),
            submitted_by=submitted_by,
            evidence=[item.model_dump(mode="json") for item in payload.evidence],
        )

    async def list_page(
        self,
        *,
        status: str | None,
        limit: int,
        after: str | None,
        table_id: UUID | None = None,
    ) -> dict:
        refs = None
        if table_id is not None:
            document = await self._table_document(table_id)
            try:
                refs = suggestion_target_refs(str(table_id), *asset_targets(document))
            except KeyError as exc:
                raise OpenMetadataError(
                    "openmetadata_invalid_response", "Table references are incomplete"
                ) from exc
        return await self.repository.list_page(
            status=status, limit=limit, after=after, target_refs=refs
        )

    async def target(self, suggestion_id: UUID) -> dict:
        suggestion = await self.get(suggestion_id)
        table_id = UUID(str(suggestion["proposed_value"].get("table_id", "")))
        document = await self._table_document(table_id)
        return table_detail(document).model_dump(mode="json")

    async def _table_document(self, table_id: UUID) -> dict:
        if self.metadata_client is None:
            raise OpenMetadataError(
                "openmetadata_disabled", "OpenMetadata is not configured"
            )
        document = await self.metadata_client.get(
            f"v1/tables/{table_id}",
            params={"fields": "columns,tags"},
        )
        if str(document.get("id", "")).lower() != str(table_id):
            raise OpenMetadataError(
                "openmetadata_invalid_response", "Table identity does not match"
            )
        return document

    async def application_attempts(
        self,
        suggestion_id: UUID,
        *,
        limit: int,
        after: UUID | None,
    ) -> dict:
        return await self.repository.application_attempts(
            suggestion_id, limit=limit, after=after
        )

    async def retry_application(self, suggestion_id: UUID, *, actor: str) -> dict:
        suggestion = await self.get(suggestion_id)
        if suggestion["status"] not in {"approved", "failed"}:
            raise ValueError("Only previously approved applications can be retried")
        # Reuse the fenced application claim; retry never approves a pending suggestion.
        return await self.review_and_apply(
            suggestion_id,
            decision="approve",
            reviewer=actor,
            comment=None,
        )
