from __future__ import annotations

from uuid import UUID

from teoria.intelligence.suggestions.evidence import (
    require_current_column,
    require_current_version,
)
from teoria.intelligence.suggestions.execution import (
    ApplicationEffects,
    SuggestionApplicationError,
)
from teoria.metadata.openmetadata import OpenMetadataError


class OpenMetadataApplier:
    def __init__(self, repository, metadata_client, effects: ApplicationEffects):
        self.repository = repository
        self.metadata_client = metadata_client
        self.effects = effects

    async def apply_description(self, suggestion: dict) -> dict:
        if self.metadata_client is None:
            await self.effects.finish(
                suggestion["suggestion_id"],
                applied=False,
                error_code="openmetadata_disabled",
            )
            raise SuggestionApplicationError("OpenMetadata write-back is disabled")
        description = suggestion["proposed_value"].get("description")
        if not isinstance(description, str) or not description.strip():
            await self.effects.finish(
                suggestion["suggestion_id"],
                applied=False,
                error_code="invalid_description",
            )
            raise SuggestionApplicationError("Description must be a non-empty string")
        proposed = suggestion["proposed_value"]
        target_type = suggestion["target_type"]
        table_id = proposed.get("table_id")
        if target_type == "openmetadata_table" and not table_id:
            table_id = suggestion["target_ref"].removeprefix("openmetadata://table/")
        if not isinstance(table_id, str) or not table_id:
            await self.effects.finish(
                suggestion["suggestion_id"],
                applied=False,
                error_code="invalid_target_ref",
            )
            raise SuggestionApplicationError(
                "A valid OpenMetadata table ID is required"
            )
        try:
            if target_type == "openmetadata_column":
                table = await self.metadata_client.get(
                    f"v1/tables/{table_id}", params={"fields": "columns"}
                )
            else:
                table = await self.metadata_client.get(f"v1/tables/{table_id}")
            if target_type == "openmetadata_table":
                require_current_version(table, proposed.get("source_version"))
                await self.effects.mark_started()
                updated = await self.metadata_client.update_table_description(
                    table_id,
                    description.strip(),
                    has_description=bool(table.get("description")),
                )
                entity_type = "table"
                entity_ref = str(table.get("fullyQualifiedName") or table_id)
            elif target_type == "openmetadata_column":
                column_name = proposed.get("column_name")
                columns = table.get("columns") or []
                column_index = next(
                    (
                        index
                        for index, item in enumerate(columns)
                        if item.get("name") == column_name
                    ),
                    None,
                )
                if column_index is None:
                    raise SuggestionApplicationError(
                        f"OpenMetadata column not found: {column_name}"
                    )
                column = columns[column_index]
                require_current_column(
                    table,
                    expected_version=proposed.get("source_version"),
                    current_description=column.get("description"),
                    expected_description=proposed.get("source_description"),
                    has_expected_description="source_description" in proposed,
                )
                await self.effects.mark_started()
                updated = await self.metadata_client.update_column_description(
                    table_id,
                    column_index=column_index,
                    description=description.strip(),
                    has_description=bool(column.get("description")),
                )
                entity_type = "column"
                entity_ref = str(
                    column.get("fullyQualifiedName")
                    or proposed.get("column_fqn")
                    or column_name
                )
            else:
                raise SuggestionApplicationError(
                    f"Unsupported description target: {target_type}"
                )
        except OpenMetadataError as exc:
            await self.effects.finish(
                suggestion["suggestion_id"], applied=False, error_code=exc.code
            )
            raise SuggestionApplicationError(str(exc)) from exc
        except SuggestionApplicationError as exc:
            await self.effects.finish(
                suggestion["suggestion_id"],
                applied=False,
                error_code=exc.code,
            )
            raise
        await self.effects.finish(
            suggestion["suggestion_id"],
            applied=True,
            external_change_ref=(
                f"openmetadata://{entity_type}/{entity_ref}"
                f"@{updated.get('version', '')}"
            ),
        )
        return await self.repository.get(UUID(str(suggestion["suggestion_id"])))

    async def apply_glossary_term(self, suggestion: dict) -> dict:
        if self.metadata_client is None:
            raise SuggestionApplicationError("OpenMetadata write-back is disabled")
        payload = suggestion["proposed_value"]
        if not all(
            isinstance(payload.get(key), str) and payload[key].strip()
            for key in ("glossary", "name", "description")
        ):
            raise SuggestionApplicationError(
                "Glossary, name and description are required"
            )
        try:
            await self.effects.mark_started()
            created = await self.metadata_client.create_glossary_term(payload)
        except OpenMetadataError as exc:
            await self.effects.finish(
                suggestion["suggestion_id"], applied=False, error_code=exc.code
            )
            raise SuggestionApplicationError(str(exc)) from exc
        await self.effects.finish(
            suggestion["suggestion_id"],
            applied=True,
            external_change_ref=(
                "openmetadata://glossary_term/"
                f"{created.get('fullyQualifiedName') or created.get('id')}"
                f"@{created.get('version', '')}"
            ),
        )
        return await self.repository.get(UUID(str(suggestion["suggestion_id"])))

    async def apply_quality_test(self, suggestion: dict) -> dict:
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
        try:
            await self.effects.mark_started()
            created = await self.metadata_client.create_test_case(payload)
            created_id = created.get("id")
            if not created_id:
                raise SuggestionApplicationError(
                    "OpenMetadata가 생성된 Test Case ID를 반환하지 않았습니다.",
                    code="quality_test_verification_failed",
                )
            verified = await self.metadata_client.get_test_case(str(created_id))
        except OpenMetadataError as exc:
            await self.effects.finish(
                suggestion["suggestion_id"], applied=False, error_code=exc.code
            )
            raise SuggestionApplicationError(str(exc), code=exc.code) from exc
        except SuggestionApplicationError as exc:
            await self.effects.finish(
                suggestion["suggestion_id"], applied=False, error_code=exc.code
            )
            raise
        await self.effects.finish(
            suggestion["suggestion_id"],
            applied=True,
            external_change_ref=(
                f"openmetadata://test_case/{verified.get('fullyQualifiedName') or verified.get('id')}"
                f"@{verified.get('version', '')}"
            ),
        )
        result = await self.repository.get(UUID(str(suggestion["suggestion_id"])))
        result["resulting_test_case"] = verified
        result["application_verified"] = True
        return result

    async def apply_test_suite(self, suggestion: dict) -> dict:
        if self.metadata_client is None:
            raise SuggestionApplicationError("OpenMetadata write-back is disabled")
        payload = suggestion["proposed_value"].get("test_suite")
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("name"), str)
            or not payload["name"].strip()
        ):
            raise SuggestionApplicationError("Quality test suite requires a name")
        try:
            await self.effects.mark_started()
            created = await self.metadata_client.create_test_suite(payload)
            created_id = created.get("id")
            if not created_id:
                raise SuggestionApplicationError(
                    "OpenMetadata가 생성된 Test Suite ID를 반환하지 않았습니다.",
                    code="test_suite_verification_failed",
                )
            verified = await self.metadata_client.get_test_suite(str(created_id))
        except OpenMetadataError as exc:
            await self.effects.finish(
                suggestion["suggestion_id"], applied=False, error_code=exc.code
            )
            raise SuggestionApplicationError(str(exc), code=exc.code) from exc
        except SuggestionApplicationError as exc:
            await self.effects.finish(
                suggestion["suggestion_id"], applied=False, error_code=exc.code
            )
            raise
        await self.effects.finish(
            suggestion["suggestion_id"],
            applied=True,
            external_change_ref=(
                f"openmetadata://test_suite/{verified.get('fullyQualifiedName') or verified.get('id')}"
                f"@{verified.get('version', '')}"
            ),
        )
        result = await self.repository.get(UUID(str(suggestion["suggestion_id"])))
        result["resulting_test_suite"] = verified
        result["application_verified"] = True
        return result

    async def apply_glossary_term_assignment(self, suggestion: dict) -> dict:
        if self.metadata_client is None:
            raise SuggestionApplicationError("OpenMetadata write-back is disabled")
        proposed = suggestion["proposed_value"]
        table_id = proposed.get("table_id")
        column_name = proposed.get("column_name")
        term_fqn = proposed.get("glossary_term_fqn")
        if not all(
            isinstance(value, str) and value
            for value in (table_id, column_name, term_fqn)
        ):
            raise SuggestionApplicationError(
                "Table, column and glossary term are required"
            )
        try:
            table = await self.metadata_client.get(
                f"v1/tables/{table_id}", params={"fields": "columns"}
            )
            current_version = (
                str(table.get("version")) if table.get("version") is not None else None
            )
            if (
                proposed.get("source_version")
                and current_version != proposed["source_version"]
            ):
                raise SuggestionApplicationError(
                    "STALE_EVIDENCE: OpenMetadata entity changed; re-evaluate the suggestion",
                    code="stale_evidence",
                )
            columns = table.get("columns") or []
            column_index = next(
                (
                    index
                    for index, item in enumerate(columns)
                    if item.get("name") == column_name
                ),
                None,
            )
            if column_index is None:
                raise SuggestionApplicationError(
                    f"OpenMetadata column not found: {column_name}"
                )
            tags = columns[column_index].get("tags") or []
            already_assigned = any(
                item.get("source") == "Glossary" and item.get("tagFQN") == term_fqn
                for item in tags
            )
            await self.effects.mark_started()
            updated = await self.metadata_client.assign_column_glossary_term(
                table_id,
                column_index=column_index,
                term_fqn=term_fqn,
                already_assigned=already_assigned,
            )
        except OpenMetadataError as exc:
            await self.effects.finish(
                suggestion["suggestion_id"], applied=False, error_code=exc.code
            )
            raise SuggestionApplicationError(str(exc)) from exc
        except SuggestionApplicationError as exc:
            await self.effects.finish(
                suggestion["suggestion_id"], applied=False, error_code=exc.code
            )
            raise
        await self.effects.finish(
            suggestion["suggestion_id"],
            applied=True,
            external_change_ref=f"openmetadata://column/{proposed.get('column_fqn', column_name)}@{updated.get('version', '')}",
        )
        return await self.repository.get(UUID(str(suggestion["suggestion_id"])))
