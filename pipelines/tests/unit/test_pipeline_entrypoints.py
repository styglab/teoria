import importlib
from pathlib import Path

import yaml
from prefect import Flow
from teoria_pipelines.deployment_docs import load_deployments, render_deployment_docs
from teoria_pipelines.deployment_validation import validate_deployment_contracts
from teoria_pipelines.loader import PipelineLoader
from teoria_pipelines.validator import PipelineValidator

ROOT = Path(__file__).parents[2]


def test_collection_deployments_reference_owned_pipeline_definitions():
    catalog = PipelineLoader(ROOT).load()
    referenced = set()
    names = []
    for _, deployment in load_deployments(ROOT):
        names.append(deployment["name"])
        entrypoint = deployment["entrypoint"]
        if entrypoint.startswith("teoria_pipelines.metadata."):
            continue  # Metadata jobs have no Provider Connector collection contract.
        tags = deployment.get("tags", [])
        pipeline_ids = [
            tag.removeprefix("pipeline:") for tag in tags if tag.startswith("pipeline:")
        ]
        assert len(pipeline_ids) == 1, deployment["name"]
        pipeline_id = pipeline_ids[0]
        assert pipeline_id in catalog.pipelines, deployment["name"]
        domain = catalog.pipeline_paths[pipeline_id].parent.name
        assert f"domain:{domain}" in tags
        assert (
            entrypoint.rsplit(".", 1)[0] in catalog.pipelines[pipeline_id].flow_modules
        )
        referenced.add(pipeline_id)
    assert len(names) == len(set(names))
    assert referenced == catalog.pipelines.keys()


def test_wrong_pipeline_in_the_same_domain_is_rejected():
    catalog = PipelineLoader(ROOT).load()
    deployments = load_deployments(ROOT)
    deployment = next(
        item for _, item in deployments if item["name"] == "pps-contract-incremental"
    )
    deployment["tags"] = [
        "domain:public_procurement",
        "pipeline:pps_bid_notice_ingestion",
    ]
    diagnostics = validate_deployment_contracts(catalog, deployments)
    assert any(
        item.code == "deployment_pipeline_mismatch"
        and "pps-contract-incremental" in item.message
        for item in diagnostics
    )


def test_declared_operations_match_feature_implementations():
    import ast

    catalog = PipelineLoader(ROOT).load()
    all_operation_ids = {
        operation.id
        for registry in catalog.connectors.values()
        for operation in registry.connector.operations
    }
    for definition in catalog.pipelines.values():
        implemented = set()
        for module in definition.flow_modules:
            feature_root = ROOT / "src" / Path(*module.split(".")[:-1])
            for path in feature_root.glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                implemented.update(
                    node.value
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value in all_operation_ids
                )
        assert set(definition.operations) == implemented, definition.id


def test_missing_collection_definition_is_reported():
    catalog = PipelineLoader(ROOT).load()
    del catalog.pipelines["pps_bid_notice_ingestion"]
    diagnostics = PipelineValidator().validate(catalog)
    assert any(
        item.code == "missing_connector_pipeline"
        and "pps_bid_notice_api" in item.message
        for item in diagnostics
    )


def test_deployment_inventory_matches_all_manifest_values():
    document = ROOT.parent / "docs/pipelines/deployments.md"
    assert document.read_text(encoding="utf-8") == render_deployment_docs(ROOT)


def test_all_deployment_entrypoints_are_importable_feature_flows():
    for filename in ("prefect.yaml", "prefect.metadata.yaml"):
        deployments = yaml.safe_load((ROOT / filename).read_text())["deployments"]
        for deployment in deployments:
            entrypoint = deployment["entrypoint"]
            module, _, name = entrypoint.rpartition(".")
            flow = getattr(importlib.import_module(module), name)
            assert isinstance(flow, Flow), entrypoint
            assert flow.fn.__module__ == module
            assert module.startswith(
                ("teoria_pipelines.domains.", "teoria_pipelines.metadata.")
            )


def test_monthly_industry_deployment_keeps_its_existing_entrypoint():
    for module_name in ("pps_industries",):
        legacy = importlib.import_module("teoria_pipelines.flows." + module_name)
        for name in legacy.__all__:
            entrypoint = getattr(legacy, name)
            canonical = importlib.import_module(entrypoint.fn.__module__)
            assert entrypoint is getattr(canonical, name)
