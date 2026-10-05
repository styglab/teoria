from __future__ import annotations

from uuid import UUID

from teoria.intelligence.repository import SuggestionRepository
from teoria.binding.repository import BindingRepository
from teoria.intelligence.binding_candidates import rank_binding_candidates
from teoria.metadata.openmetadata import OpenMetadataClient, OpenMetadataError


class SuggestionApplicationError(RuntimeError):
    pass


class SuggestionService:
    def __init__(self, repository: SuggestionRepository, metadata_client: OpenMetadataClient | None, binding_repository: BindingRepository | None = None) -> None:
        self.repository = repository
        self.metadata_client = metadata_client
        self.binding_repository = binding_repository

    async def suggest_column_binding(self, *, table_id: str, column_name: str) -> dict:
        if self.metadata_client is None or self.binding_repository is None:
            raise SuggestionApplicationError("Metadata and binding services are required")
        table = await self.metadata_client.get(
            f"v1/tables/{table_id}", params={"fields": "columns,tags,domains"}
        )
        column = next((item for item in table.get("columns", []) if item.get("name") == column_name), None)
        if column is None:
            raise KeyError(column_name)
        candidates = rank_binding_candidates(column, self.binding_repository.list_published_property_concepts())
        if not candidates:
            raise ValueError("No compatible published Ontology property candidates")
        best = candidates[0]
        column_fqn = column.get("fullyQualifiedName") or f"{table.get('fullyQualifiedName')}.{column_name}"
        target_ref = f"openmetadata://column/{column_fqn}"
        proposed_value = {
            "ontology_concept_id": best.concept_id,
            "ontology_ref_type": best.concept_kind,
            "ontology_stable_key": best.stable_key,
            "external_entity_id": column_fqn,
            "entity_type": "column",
            "fully_qualified_name": column_fqn,
            "external_version": str(table.get("version")) if table.get("version") is not None else None,
            "table_id": str(table.get("id") or table_id),
            "source_version": str(table.get("version")) if table.get("version") is not None else None,
            "binding_type": "represents",
            "alternatives": [
                {"ontology_concept_id": item.concept_id, "stable_key": item.stable_key, "score": item.score}
                for item in candidates[1:]
            ],
        }
        evidence = [
            {
                "evidence_type": item["type"],
                "source_ref": target_ref,
                "excerpt": str(item),
                "provenance": {"score": item.get("score"), "source_version": proposed_value["source_version"]},
            }
            for item in best.evidence
        ]
        return self.repository.create(
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
            evidence=evidence,
        )

    async def review_and_apply(
        self,
        suggestion_id: UUID,
        *,
        decision: str,
        reviewer: str,
        comment: str | None,
    ) -> dict:
        current = self.repository.get(suggestion_id)
        if decision == "approve" and current.get("suggestion_type") == "binding":
            await self._validate_binding_evidence(current)
        suggestion = self.repository.review(
            suggestion_id, decision=decision, reviewer=reviewer, comment=comment
        )
        if decision != "approve":
            return suggestion
        if suggestion["suggestion_type"] == "binding":
            return await self._apply_binding_suggestion(suggestion, reviewer=reviewer)
        if suggestion["risk_level"] != "low":
            return suggestion
        if self.metadata_client is None:
            self.repository.finish_application(suggestion_id, applied=False, error_code="openmetadata_disabled")
            raise SuggestionApplicationError("OpenMetadata write-back is disabled")
        if suggestion["target_type"] != "openmetadata_table" or suggestion["suggestion_type"] != "description":
            self.repository.finish_application(suggestion_id, applied=False, error_code="unsupported_suggestion_target")
            raise SuggestionApplicationError("Only OpenMetadata table description suggestions are supported")
        description = suggestion["proposed_value"].get("description")
        if not isinstance(description, str) or not description.strip():
            self.repository.finish_application(suggestion_id, applied=False, error_code="invalid_description")
            raise SuggestionApplicationError("Description must be a non-empty string")
        table_id = suggestion["target_ref"].removeprefix("openmetadata://table/")
        if not table_id or table_id == suggestion["target_ref"]:
            self.repository.finish_application(suggestion_id, applied=False, error_code="invalid_target_ref")
            raise SuggestionApplicationError("Target must be an OpenMetadata table reference")
        self.repository.start_application(suggestion_id)
        try:
            table = await self.metadata_client.get(f"v1/tables/{table_id}")
            updated = await self.metadata_client.update_table_description(
                table_id, description.strip(), has_description=bool(table.get("description"))
            )
        except OpenMetadataError as exc:
            self.repository.finish_application(suggestion_id, applied=False, error_code=exc.code)
            raise SuggestionApplicationError(str(exc)) from exc
        self.repository.finish_application(
            suggestion_id,
            applied=True,
            external_change_ref=f"openmetadata://table/{updated.get('id', table_id)}@{updated.get('version', '')}",
        )
        return self.repository.get(suggestion_id)

    async def _apply_binding_suggestion(self, suggestion: dict, *, reviewer: str) -> dict:
        if self.metadata_client is None or self.binding_repository is None:
            raise SuggestionApplicationError("Metadata and binding services are required")
        proposed = suggestion["proposed_value"]
        self.repository.start_application(suggestion["suggestion_id"], target_system="teoria_binding")
        try:
            binding = self.binding_repository.create_openmetadata_binding(
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
                provenance={"suggestion_id": suggestion["suggestion_id"], "reviewer": reviewer},
                created_by=reviewer,
            )
        except Exception as exc:
            self.repository.finish_application(suggestion["suggestion_id"], applied=False, error_code="binding_draft_failed")
            raise SuggestionApplicationError(str(exc)) from exc
        self.repository.finish_application(
            suggestion["suggestion_id"], applied=True,
            external_change_ref=f"teoria://binding/{binding['binding_id']}",
        )
        result = self.repository.get(UUID(suggestion["suggestion_id"]))
        result["resulting_binding"] = binding
        return result

    async def _validate_binding_evidence(self, suggestion: dict) -> None:
        if self.metadata_client is None or self.binding_repository is None:
            raise SuggestionApplicationError("Metadata and binding services are required")
        proposed = suggestion["proposed_value"]
        table = await self.metadata_client.get(f"v1/tables/{proposed['table_id']}")
        current_version = str(table.get("version")) if table.get("version") is not None else None
        if current_version != proposed.get("source_version"):
            raise SuggestionApplicationError(
                "STALE_EVIDENCE: OpenMetadata entity changed; re-evaluate the suggestion"
            )
