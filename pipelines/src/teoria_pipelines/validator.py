from __future__ import annotations

from pathlib import Path

from teoria_provider.validator import ProviderContractValidator
from teoria_pipelines.diagnostics import Diagnostic
from teoria_pipelines.loader import PipelineCatalog


class PipelineValidator:
    """Validate contracts owned by the Data Pipelines project."""

    def validate(
        self,
        catalog: PipelineCatalog,
        *,
        connector_id: str | None = None,
    ) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        connectors = catalog.connectors.items()
        if connector_id is not None:
            connector = catalog.connectors.get(connector_id)
            if connector is None:
                return [Diagnostic("unknown_connector", f"unknown connector '{connector_id}'", catalog.root / "connectors")]
            connectors = [(connector_id, connector)]

        for current_id, registry in connectors:
            path = catalog.connector_paths[current_id]
            if path.stem != registry.connector.id:
                diagnostics.append(
                    Diagnostic(
                        "connector_filename_mismatch",
                        f"filename must match connector id '{registry.connector.id}.yaml'",
                        path,
                        location="connector.id",
                    )
                )
            diagnostics.extend(
                ProviderContractValidator().validate(
                    registry.connector,
                    path=path,
                    root="connector",
                    allow_unknown_data_types=True,
                )
            )

        self._validate_references(catalog, diagnostics)
        if connector_id is None:
            self._validate_pipelines(catalog, diagnostics)
        return diagnostics

    @staticmethod
    def _validate_pipelines(
        catalog: PipelineCatalog,
        diagnostics: list[Diagnostic],
    ) -> None:
        for pipeline_id, pipeline in catalog.pipelines.items():
            path = catalog.pipeline_paths[pipeline_id]
            if path.stem != pipeline.id:
                diagnostics.append(
                    Diagnostic(
                        "pipeline_filename_mismatch",
                        f"filename must match pipeline id '{pipeline.id}.yaml'",
                        path,
                        location="pipeline.id",
                    )
                )
            connector = catalog.connectors.get(pipeline.connector)
            if connector is None:
                diagnostics.append(
                    Diagnostic(
                        "unknown_pipeline_connector",
                        f"unknown connector '{pipeline.connector}'",
                        path,
                        location="pipeline.connector",
                    )
                )
            else:
                operation_ids = {item.id for item in connector.connector.operations}
                for index, operation_id in enumerate(pipeline.operations):
                    if operation_id not in operation_ids:
                        diagnostics.append(
                            Diagnostic(
                                "unknown_pipeline_operation",
                                f"unknown connector operation '{operation_id}'",
                                path,
                                location=f"pipeline.operations.{index}",
                            )
                        )

    @staticmethod
    def _validate_references(catalog: PipelineCatalog, diagnostics: list[Diagnostic]) -> None:
        for connector_id, connector_registry in catalog.connectors.items():
            source_document = connector_registry.connector.specification.source_document
            reference = catalog.references.get(connector_id)
            if source_document and reference is None:
                diagnostics.append(
                    Diagnostic(
                        "missing_connector_reference",
                        f"connector '{connector_id}' declares source_document but has no provider reference metadata",
                        catalog.connector_paths[connector_id],
                        location="connector.specification.source_document",
                    )
                )
                continue
            if reference is None:
                continue
            metadata_path = catalog.reference_paths[connector_id]
            if reference.target != "connector":
                diagnostics.append(
                    Diagnostic(
                        "reference_target_mismatch",
                        f"reference for connector '{connector_id}' must use target: connector",
                        metadata_path,
                        location="target",
                    )
                )
            if reference.status == "draft":
                diagnostics.append(
                    Diagnostic(
                        "draft_reference_for_registered_connector",
                        f"connector '{connector_id}' is registered but its provider reference is still draft",
                        metadata_path,
                        location="status",
                    )
                )
            expected_registry = catalog.connector_paths[connector_id].resolve()
            actual_registry = (catalog.root / reference.registry).resolve()
            if actual_registry != expected_registry:
                diagnostics.append(
                    Diagnostic(
                        "reference_registry_mismatch",
                        f"reference points to '{reference.registry}', expected '{catalog.connector_paths[connector_id]}'",
                        metadata_path,
                        location="registry",
                    )
                )
            file_names = {item.path for item in reference.files}
            if source_document and source_document not in file_names:
                diagnostics.append(
                    Diagnostic(
                        "source_document_mismatch",
                        f"source_document '{source_document}' is not listed in provider reference files",
                        catalog.connector_paths[connector_id],
                        location="connector.specification.source_document",
                    )
                )

        for connector_id, reference in catalog.references.items():
            metadata_path = catalog.reference_paths[connector_id]
            for index, item in enumerate(reference.files):
                if not (metadata_path.parent / item.path).is_file():
                    diagnostics.append(
                        Diagnostic(
                            "reference_file_not_found",
                            f"reference file '{item.path}' does not exist",
                            metadata_path,
                            location=f"files.{index}.path",
                        )
                    )
            if reference.status == "active" and connector_id not in catalog.connectors:
                diagnostics.append(
                    Diagnostic(
                        "unknown_reference_target",
                        f"provider reference points to unknown connector '{reference.source}'",
                        metadata_path,
                        location="source",
                    )
                )
