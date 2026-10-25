from pathlib import Path

import yaml

from teoria_pipelines.deployment_docs import load_deployments
from teoria_pipelines.deployment_validation import validate_deployment_contracts
from teoria_pipelines.loader import PipelineLoader

ROOT = Path(__file__).parents[2]


def test_only_explicit_specification_and_metadata_jobs_are_active():
    catalog = PipelineLoader(ROOT).load()
    assert set(catalog.connectors) == {"moleg_law_api"}
    assert set(catalog.pipelines) == {"moleg_law_ingestion"}
    deployments = load_deployments(ROOT)
    assert {d["name"] for _, d in deployments} == {
        "specification-standard-management", "specification-document-processing",
        "openmetadata-postgres-metadata-sync",
        "moleg-law-daily", "moleg-law-weekly-reconciliation",
    }
    assert validate_deployment_contracts(catalog, deployments) == []
    for _, d in deployments:
        if "specification" in d["name"]:
            assert d["schedules"] == []
            assert d["work_pool"] == {"name": "teoria-specification", "work_queue_name": "documents"}
            assert "manifest" not in d["parameters"]


def test_document_jobs_cannot_get_automatic_schedules():
    catalog = PipelineLoader(ROOT).load()
    job = yaml.safe_load((ROOT / "prefect.yaml").read_text())["deployments"][0]
    job["schedules"] = [{"cron": "0 * * * *", "timezone": "Asia/Seoul"}]
    diagnostics = validate_deployment_contracts(catalog, [(ROOT / "prefect.yaml", job)])
    assert diagnostics[0].code == "invalid_specification_deployment"
