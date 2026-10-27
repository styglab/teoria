"""Validate deployment ownership against the collection inventory without importing flows."""

from pathlib import Path
from typing import Any

from teoria.integrations.data_operations.diagnostics import Diagnostic
from teoria.integrations.data_operations.loader import PipelineCatalog


def validate_deployment_contracts(
    catalog: PipelineCatalog, deployments: list[tuple[Path, dict[str, Any]]]
) -> list[Diagnostic]:
    diagnostics = []
    if not catalog.connectors and not catalog.pipelines and not deployments:
        diagnostics.append(
            Diagnostic(
                "empty_pipeline_project",
                "pipeline project contains no Connector, Pipeline or deployment definitions",
                catalog.root,
            )
        )
    names = set()
    referenced = set()
    for path, deployment in deployments:
        name = deployment["name"]
        if name in names:
            diagnostics.append(
                Diagnostic(
                    "duplicate_deployment", f"duplicate deployment '{name}'", path
                )
            )
        names.add(name)
        module = deployment["entrypoint"].rsplit(".", 1)[0]
        if module in {
            "teoria.features.specification_processing.flows",
            "teoria.features.specification_processing.standard_workflow",
        }:
            if (
                deployment["entrypoint"].rsplit(".", 1)[-1]
                not in {
                    "standard_management_flow",
                    "document_processing_flow",
                    "standard_workflow_flow",
                }
                or "feature:specification_processing" not in deployment.get("tags", [])
                or deployment.get("schedules")
            ):
                diagnostics.append(
                    Diagnostic(
                        "invalid_specification_deployment",
                        f"'{name}' must be an explicit-input specification flow without schedules",
                        path,
                    )
                )
            continue
        if module == "teoria.features.model_operations.flows":
            if deployment["entrypoint"].rsplit(".", 1)[-1] not in {
                "seed_demo_customers", "train_demo_customer_churn", "deploy_demo_customer_churn"
            } or "feature:model_operations" not in deployment.get("tags", []) or deployment.get("schedules"):
                diagnostics.append(Diagnostic("invalid_model_operations_deployment",
                    f"'{name}' must be an explicit manual model operations flow", path))
            continue
        if module.startswith("teoria.features.metadata_management.ingestion."):
            continue
        tags = deployment.get("tags", [])
        ids = [
            tag.removeprefix("pipeline:") for tag in tags if tag.startswith("pipeline:")
        ]
        if len(ids) != 1 or ids[0] not in catalog.pipelines:
            diagnostics.append(
                Diagnostic(
                    "invalid_deployment_pipeline",
                    f"'{name}' requires one known pipeline tag",
                    path,
                )
            )
            continue
        pipeline_id = ids[0]
        definition = catalog.pipelines[pipeline_id]
        domain = catalog.pipeline_paths[pipeline_id].parent.name
        if module not in definition.flow_modules or f"domain:{domain}" not in tags:
            diagnostics.append(
                Diagnostic(
                    "deployment_pipeline_mismatch",
                    f"'{name}' flow '{module}' is not owned by '{pipeline_id}' in '{domain}'",
                    path,
                )
            )
        referenced.add(pipeline_id)
    for pipeline_id in sorted(catalog.pipelines.keys() - referenced):
        diagnostics.append(
            Diagnostic(
                "pipeline_without_deployment",
                f"pipeline '{pipeline_id}' has no deployment",
                catalog.pipeline_paths[pipeline_id],
            )
        )
    return diagnostics
