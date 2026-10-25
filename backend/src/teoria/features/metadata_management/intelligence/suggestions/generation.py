from __future__ import annotations

from teoria.features.metadata_management.intelligence.suggestions.binding_candidates import rank_binding_candidates
from teoria.features.metadata_management.intelligence.suggestions.execution import SuggestionApplicationError


class ProposalService:
    def __init__(self, repository, metadata_client, binding_repository=None):
        self.repository = repository
        self.metadata_client = metadata_client
        self.binding_repository = binding_repository

    async def suggest_column_binding(
        self, *, table_id: str, column_name: str, submitted_by: str
    ) -> dict:
        if self.metadata_client is None or self.binding_repository is None:
            raise SuggestionApplicationError(
                "Metadata and binding services are required"
            )
        table = await self.metadata_client.get(
            f"v1/tables/{table_id}", params={"fields": "columns,tags,domains"}
        )
        column = next(
            (
                item
                for item in table.get("columns", [])
                if item.get("name") == column_name
            ),
            None,
        )
        if column is None:
            raise KeyError(column_name)
        candidates = rank_binding_candidates(
            column, (await self.binding_repository.list_published_property_concepts())
        )
        if not candidates:
            raise ValueError("No compatible published Ontology property candidates")
        best = candidates[0]
        column_fqn = (
            column.get("fullyQualifiedName")
            or f"{table.get('fullyQualifiedName')}.{column_name}"
        )
        target_ref = f"openmetadata://column/{column_fqn}"
        proposed_value = {
            "ontology_concept_id": best.concept_id,
            "ontology_ref_type": best.concept_kind,
            "ontology_stable_key": best.stable_key,
            "external_entity_id": column_fqn,
            "entity_type": "column",
            "fully_qualified_name": column_fqn,
            "external_version": str(table.get("version"))
            if table.get("version") is not None
            else None,
            "table_id": str(table.get("id") or table_id),
            "source_version": str(table.get("version"))
            if table.get("version") is not None
            else None,
            "binding_type": "represents",
            "alternatives": [
                {
                    "ontology_concept_id": item.concept_id,
                    "stable_key": item.stable_key,
                    "score": item.score,
                }
                for item in candidates[1:]
            ],
        }
        evidence = [
            {
                "evidence_type": item["type"],
                "source_ref": target_ref,
                "excerpt": str(item),
                "provenance": {
                    "score": item.get("score"),
                    "source_version": proposed_value["source_version"],
                },
            }
            for item in best.evidence
        ]
        return await self.repository.create(
            target_type="openmetadata_column",
            target_ref=target_ref,
            suggestion_type="binding",
            proposed_value=proposed_value,
            confidence=best.score,
            rationale=f"Deterministic candidate retrieval selected {best.stable_key}",
            risk_level="medium",
            model_provider="teoria",
            model_name="deterministic-binding-candidate-retriever",
            model_version="1.0",
            policy_version="binding-suggestion-v1",
            submitted_by=submitted_by,
            evidence=evidence,
        )

    async def suggest_description_change(
        self,
        *,
        table_id: str,
        description: str,
        submitted_by: str,
        column_name: str | None = None,
    ) -> dict:
        if self.metadata_client is None:
            raise SuggestionApplicationError("OpenMetadata write-back is disabled")
        normalized = description.strip()
        if not normalized:
            raise ValueError("Description is required")
        fields = {"fields": "columns"} if column_name else None
        table = await self.metadata_client.get(f"v1/tables/{table_id}", params=fields)
        table_fqn = str(table.get("fullyQualifiedName") or table_id)
        source_version = (
            str(table.get("version")) if table.get("version") is not None else None
        )
        if column_name:
            column = next(
                (
                    item
                    for item in table.get("columns", [])
                    if item.get("name") == column_name
                ),
                None,
            )
            if column is None:
                raise KeyError(column_name)
            source_description = column.get("description")
            column_fqn = str(
                column.get("fullyQualifiedName") or f"{table_fqn}.{column_name}"
            )
            target_type = "openmetadata_column"
            target_ref = f"openmetadata://column/{column_fqn}"
            proposed_value = {
                "description": normalized,
                "table_id": str(table.get("id") or table_id),
                "column_name": column_name,
                "column_fqn": column_fqn,
                "source_version": source_version,
                "source_description": source_description,
            }
        else:
            source_description = table.get("description")
            target_type = "openmetadata_table"
            target_ref = f"openmetadata://table/{table_fqn}"
            proposed_value = {
                "description": normalized,
                "table_id": str(table.get("id") or table_id),
                "fully_qualified_name": table_fqn,
                "source_version": source_version,
                "source_description": source_description,
            }
        if source_description == normalized:
            raise ValueError("Description is unchanged")
        return await self.repository.create(
            target_type=target_type,
            target_ref=target_ref,
            suggestion_type="description",
            proposed_value=proposed_value,
            confidence=1.0,
            rationale="인증된 관리자가 자산 상세에서 제출한 메타데이터 변경안",
            risk_level="low",
            model_provider="teoria",
            model_name="admin-metadata-editor",
            model_version="1.0",
            policy_version="manual-metadata-change-v1",
            submitted_by=submitted_by,
            evidence=[
                {
                    "evidence_type": "openmetadata_current_value",
                    "source_ref": target_ref,
                    "excerpt": source_description,
                    "provenance": {
                        "source_version": source_version,
                        "submitted_by": submitted_by,
                    },
                }
            ],
        )
