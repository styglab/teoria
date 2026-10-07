from __future__ import annotations

from uuid import UUID

from teoria.intelligence.repository import SuggestionRepository
from teoria.binding.repository import BindingRepository
from teoria.intelligence.binding_candidates import rank_binding_candidates
from teoria.metadata.openmetadata import OpenMetadataClient, OpenMetadataError
from teoria.ontology.authoring import OntologyAuthoringRepository


class SuggestionApplicationError(RuntimeError):
    def __init__(self, message: str, *, code: str = "suggestion_application_failed") -> None:
        self.code = code
        super().__init__(message)


class SuggestionService:
    def __init__(
        self, repository: SuggestionRepository,
        metadata_client: OpenMetadataClient | None,
        binding_repository: BindingRepository | None = None,
        ontology_repository: OntologyAuthoringRepository | None = None,
    ) -> None:
        self.repository = repository
        self.metadata_client = metadata_client
        self.binding_repository = binding_repository
        self.ontology_repository = ontology_repository

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
        if suggestion["suggestion_type"] == "glossary_term_assignment":
            return await self._apply_glossary_term_assignment(suggestion)
        if suggestion["suggestion_type"] == "glossary_term":
            return await self._apply_glossary_term(suggestion)
        if suggestion["suggestion_type"] == "ontology_change":
            return self._apply_ontology_change(suggestion, reviewer=reviewer)
        if suggestion["suggestion_type"] == "test_suite":
            return await self._apply_test_suite(suggestion)
        if suggestion["suggestion_type"] == "quality_test":
            return await self._apply_quality_test(suggestion)
        if suggestion["suggestion_type"] == "description":
            return await self._apply_description(suggestion)
        self.repository.finish_application(
            suggestion_id, applied=False, error_code="unsupported_suggestion_type"
        )
        raise SuggestionApplicationError(
            f"Unsupported suggestion type: {suggestion['suggestion_type']}"
        )

    async def _apply_description(self, suggestion: dict) -> dict:
        if self.metadata_client is None:
            self.repository.finish_application(
                suggestion["suggestion_id"], applied=False,
                error_code="openmetadata_disabled",
            )
            raise SuggestionApplicationError("OpenMetadata write-back is disabled")
        description = suggestion["proposed_value"].get("description")
        if not isinstance(description, str) or not description.strip():
            self.repository.finish_application(
                suggestion["suggestion_id"], applied=False,
                error_code="invalid_description",
            )
            raise SuggestionApplicationError("Description must be a non-empty string")
        proposed = suggestion["proposed_value"]
        target_type = suggestion["target_type"]
        table_id = proposed.get("table_id")
        if target_type == "openmetadata_table" and not table_id:
            table_id = suggestion["target_ref"].removeprefix("openmetadata://table/")
        if not isinstance(table_id, str) or not table_id:
            self.repository.finish_application(
                suggestion["suggestion_id"], applied=False,
                error_code="invalid_target_ref",
            )
            raise SuggestionApplicationError("A valid OpenMetadata table ID is required")
        self.repository.start_application(suggestion["suggestion_id"])
        try:
            if target_type == "openmetadata_column":
                table = await self.metadata_client.get(
                    f"v1/tables/{table_id}", params={"fields": "columns"}
                )
            else:
                table = await self.metadata_client.get(f"v1/tables/{table_id}")
            if target_type == "openmetadata_table":
                self._require_current_version(table, proposed.get("source_version"))
                updated = await self.metadata_client.update_table_description(
                    table_id, description.strip(),
                    has_description=bool(table.get("description")),
                )
                entity_type = "table"
                entity_ref = str(table.get("fullyQualifiedName") or table_id)
            elif target_type == "openmetadata_column":
                column_name = proposed.get("column_name")
                columns = table.get("columns") or []
                column_index = next(
                    (index for index, item in enumerate(columns) if item.get("name") == column_name),
                    None,
                )
                if column_index is None:
                    raise SuggestionApplicationError(
                        f"OpenMetadata column not found: {column_name}"
                    )
                column = columns[column_index]
                self._require_current_column(
                    table,
                    expected_version=proposed.get("source_version"),
                    current_description=column.get("description"),
                    expected_description=proposed.get("source_description"),
                    has_expected_description="source_description" in proposed,
                )
                updated = await self.metadata_client.update_column_description(
                    table_id, column_index=column_index, description=description.strip(),
                    has_description=bool(column.get("description")),
                )
                entity_type = "column"
                entity_ref = str(
                    column.get("fullyQualifiedName")
                    or proposed.get("column_fqn") or column_name
                )
            else:
                raise SuggestionApplicationError(
                    f"Unsupported description target: {target_type}"
                )
        except OpenMetadataError as exc:
            self.repository.finish_application(
                suggestion["suggestion_id"], applied=False, error_code=exc.code
            )
            raise SuggestionApplicationError(str(exc)) from exc
        except SuggestionApplicationError as exc:
            self.repository.finish_application(
                suggestion["suggestion_id"], applied=False,
                error_code=exc.code,
            )
            raise
        self.repository.finish_application(
            suggestion["suggestion_id"],
            applied=True,
            external_change_ref=(
                f"openmetadata://{entity_type}/{entity_ref}"
                f"@{updated.get('version', '')}"
            ),
        )
        return self.repository.get(UUID(str(suggestion["suggestion_id"])))

    async def _apply_glossary_term(self, suggestion: dict) -> dict:
        if self.metadata_client is None:
            raise SuggestionApplicationError("OpenMetadata write-back is disabled")
        payload = suggestion["proposed_value"]
        if not all(isinstance(payload.get(key), str) and payload[key].strip()
                   for key in ("glossary", "name", "description")):
            raise SuggestionApplicationError(
                "Glossary, name and description are required"
            )
        self.repository.start_application(suggestion["suggestion_id"])
        try:
            created = await self.metadata_client.create_glossary_term(payload)
        except OpenMetadataError as exc:
            self.repository.finish_application(
                suggestion["suggestion_id"], applied=False, error_code=exc.code
            )
            raise SuggestionApplicationError(str(exc)) from exc
        self.repository.finish_application(
            suggestion["suggestion_id"], applied=True,
            external_change_ref=(
                "openmetadata://glossary_term/"
                f"{created.get('fullyQualifiedName') or created.get('id')}"
                f"@{created.get('version', '')}"
            ),
        )
        return self.repository.get(UUID(str(suggestion["suggestion_id"])))

    async def _apply_quality_test(self, suggestion: dict) -> dict:
        if self.metadata_client is None:
            raise SuggestionApplicationError("OpenMetadata write-back is disabled")
        payload = suggestion["proposed_value"].get("test_case")
        if not isinstance(payload, dict) or not all(
            isinstance(payload.get(key), str) and payload[key].strip()
            for key in ("name", "testDefinition", "entityLink")
        ):
            raise SuggestionApplicationError(
                "Quality test requires name, testDefinition and entityLink"
            )
        self.repository.start_application(suggestion["suggestion_id"])
        try:
            created = await self.metadata_client.create_test_case(payload)
            created_id = created.get("id")
            if not created_id:
                raise SuggestionApplicationError(
                    "OpenMetadata가 생성된 Test Case ID를 반환하지 않았습니다.",
                    code="quality_test_verification_failed",
                )
            verified = await self.metadata_client.get_test_case(str(created_id))
        except OpenMetadataError as exc:
            self.repository.finish_application(
                suggestion["suggestion_id"], applied=False, error_code=exc.code
            )
            raise SuggestionApplicationError(str(exc), code=exc.code) from exc
        except SuggestionApplicationError as exc:
            self.repository.finish_application(
                suggestion["suggestion_id"], applied=False, error_code=exc.code
            )
            raise
        self.repository.finish_application(
            suggestion["suggestion_id"], applied=True,
            external_change_ref=(
                f"openmetadata://test_case/{verified.get('fullyQualifiedName') or verified.get('id')}"
                f"@{verified.get('version', '')}"
            ),
        )
        result = self.repository.get(UUID(str(suggestion["suggestion_id"])))
        result["resulting_test_case"] = verified
        result["application_verified"] = True
        return result

    async def _apply_test_suite(self, suggestion: dict) -> dict:
        if self.metadata_client is None:
            raise SuggestionApplicationError("OpenMetadata write-back is disabled")
        payload = suggestion["proposed_value"].get("test_suite")
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("name"), str)
            or not payload["name"].strip()
        ):
            raise SuggestionApplicationError("Quality test suite requires a name")
        self.repository.start_application(suggestion["suggestion_id"])
        try:
            created = await self.metadata_client.create_test_suite(payload)
            created_id = created.get("id")
            if not created_id:
                raise SuggestionApplicationError(
                    "OpenMetadata가 생성된 Test Suite ID를 반환하지 않았습니다.",
                    code="test_suite_verification_failed",
                )
            verified = await self.metadata_client.get_test_suite(str(created_id))
        except OpenMetadataError as exc:
            self.repository.finish_application(
                suggestion["suggestion_id"], applied=False, error_code=exc.code
            )
            raise SuggestionApplicationError(str(exc), code=exc.code) from exc
        except SuggestionApplicationError as exc:
            self.repository.finish_application(
                suggestion["suggestion_id"], applied=False, error_code=exc.code
            )
            raise
        self.repository.finish_application(
            suggestion["suggestion_id"], applied=True,
            external_change_ref=(
                f"openmetadata://test_suite/{verified.get('fullyQualifiedName') or verified.get('id')}"
                f"@{verified.get('version', '')}"
            ),
        )
        result = self.repository.get(UUID(str(suggestion["suggestion_id"])))
        result["resulting_test_suite"] = verified
        result["application_verified"] = True
        return result

    def _apply_ontology_change(self, suggestion: dict, *, reviewer: str) -> dict:
        if self.ontology_repository is None:
            raise SuggestionApplicationError("Ontology authoring service is required")
        proposed = suggestion["proposed_value"]
        namespace = proposed.get("namespace")
        version = proposed.get("version")
        operation = proposed.get("operation")
        kind = proposed.get("kind")
        if not all(isinstance(value, str) and value for value in (
            namespace, version, operation, kind,
        )):
            raise SuggestionApplicationError(
                "Ontology namespace, version, operation and kind are required"
            )
        self.repository.start_application(
            suggestion["suggestion_id"], target_system="teoria_ontology"
        )
        try:
            base_id = proposed.get("based_on_version_id")
            draft = self.ontology_repository.create_draft(
                namespace, version=version, actor=reviewer,
                based_on_version_id=UUID(base_id) if base_id else None,
            )
            draft_id = UUID(str(draft["ontology_version_id"]))
            if operation == "add":
                change = self.ontology_repository.add_item(
                    draft_id, kind=kind, payload=proposed.get("item") or {},
                    actor=reviewer,
                )
            elif operation == "update":
                change = self.ontology_repository.update_item(
                    draft_id, kind=kind,
                    concept_id=UUID(str(proposed["concept_id"])),
                    changes=proposed.get("changes") or {}, actor=reviewer,
                )
            else:
                raise SuggestionApplicationError(
                    f"Unsupported ontology operation: {operation}"
                )
        except (KeyError, ValueError, SuggestionApplicationError) as exc:
            self.repository.finish_application(
                suggestion["suggestion_id"], applied=False,
                error_code="ontology_draft_failed",
            )
            raise SuggestionApplicationError(str(exc)) from exc
        self.repository.finish_application(
            suggestion["suggestion_id"], applied=True,
            external_change_ref=f"teoria://ontology/draft/{draft_id}",
        )
        result = self.repository.get(UUID(str(suggestion["suggestion_id"])))
        result["resulting_ontology_draft"] = draft
        result["resulting_ontology_change"] = change
        return result

    @staticmethod
    def _require_current_version(table: dict, expected: str | None) -> None:
        current = str(table.get("version")) if table.get("version") is not None else None
        if expected and current != expected:
            raise SuggestionApplicationError(
                "OpenMetadata 대상이 제안 생성 후 변경되었습니다. 제안을 다시 분석해 주세요.",
                code="stale_evidence",
            )

    @classmethod
    def _require_current_column(
        cls,
        table: dict,
        *,
        expected_version: str | None,
        current_description: object,
        expected_description: object,
        has_expected_description: bool,
    ) -> None:
        current_version = str(table.get("version")) if table.get("version") is not None else None
        if not expected_version or current_version == expected_version:
            return
        # OpenMetadata versions the whole table. Applying a sibling column suggestion
        # therefore advances the table version even though this column is unchanged.
        if has_expected_description and current_description == expected_description:
            return
        # Backward compatibility for suggestions created before source_description was
        # captured: an empty target is still safe to enrich after a sibling update.
        if not has_expected_description and current_description in (None, ""):
            return
        cls._require_current_version(table, expected_version)

    async def _apply_glossary_term_assignment(self, suggestion: dict) -> dict:
        if self.metadata_client is None:
            raise SuggestionApplicationError("OpenMetadata write-back is disabled")
        proposed = suggestion["proposed_value"]
        table_id = proposed.get("table_id")
        column_name = proposed.get("column_name")
        term_fqn = proposed.get("glossary_term_fqn")
        if not all(isinstance(value, str) and value for value in (table_id, column_name, term_fqn)):
            raise SuggestionApplicationError("Table, column and glossary term are required")
        self.repository.start_application(suggestion["suggestion_id"])
        try:
            table = await self.metadata_client.get(f"v1/tables/{table_id}", params={"fields": "columns"})
            current_version = str(table.get("version")) if table.get("version") is not None else None
            if proposed.get("source_version") and current_version != proposed["source_version"]:
                raise SuggestionApplicationError(
                    "STALE_EVIDENCE: OpenMetadata entity changed; re-evaluate the suggestion"
                )
            columns = table.get("columns") or []
            column_index = next((index for index, item in enumerate(columns) if item.get("name") == column_name), None)
            if column_index is None:
                raise SuggestionApplicationError(f"OpenMetadata column not found: {column_name}")
            tags = columns[column_index].get("tags") or []
            already_assigned = any(
                item.get("source") == "Glossary" and item.get("tagFQN") == term_fqn for item in tags
            )
            updated = await self.metadata_client.assign_column_glossary_term(
                table_id, column_index=column_index, term_fqn=term_fqn,
                already_assigned=already_assigned,
            )
        except OpenMetadataError as exc:
            self.repository.finish_application(suggestion["suggestion_id"], applied=False, error_code=exc.code)
            raise SuggestionApplicationError(str(exc)) from exc
        except SuggestionApplicationError:
            self.repository.finish_application(suggestion["suggestion_id"], applied=False, error_code="invalid_glossary_assignment")
            raise
        self.repository.finish_application(
            suggestion["suggestion_id"], applied=True,
            external_change_ref=f"openmetadata://column/{proposed.get('column_fqn', column_name)}@{updated.get('version', '')}",
        )
        return self.repository.get(UUID(str(suggestion["suggestion_id"])))

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
