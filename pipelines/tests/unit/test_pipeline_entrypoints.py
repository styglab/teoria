import importlib
from pathlib import Path

import yaml
from prefect import Flow


ROOT = Path(__file__).parents[2]


def test_all_deployment_entrypoints_are_importable_feature_flows():
    for filename in ("prefect.yaml", "prefect.metadata.yaml"):
        deployments = yaml.safe_load((ROOT / filename).read_text())["deployments"]
        for deployment in deployments:
            entrypoint = deployment["entrypoint"]
            module, _, name = entrypoint.rpartition(".")
            flow = getattr(importlib.import_module(module), name)
            assert isinstance(flow, Flow), entrypoint
            assert flow.fn.__module__ == module
            assert module.startswith(("teoria_pipelines.domains.", "teoria_pipelines.metadata."))


def test_existing_deployment_paths_alias_the_same_flow_objects():
    for module_name in ("pps_contracts", "pps_bid_notices", "pps_bid_results", "pps_industries", "bid_eligibility", "openmetadata"):
        legacy = importlib.import_module("teoria_pipelines.flows." + module_name)
        for name in legacy.__all__:
            entrypoint = getattr(legacy, name)
            canonical = importlib.import_module(entrypoint.fn.__module__)
            assert entrypoint is getattr(canonical, name)
