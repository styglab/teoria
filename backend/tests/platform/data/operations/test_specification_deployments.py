from pathlib import Path


from teoria.integrations.prefect.deployment_docs import load_deployments
from teoria.integrations.prefect.deployment_manifests import deployment_path, load_deployment_manifest
from teoria.integrations.prefect.deployment_validation import validate_deployment_contracts
from teoria.platform.data.operations.loader import PipelineLoader

ROOT = (Path(__file__).resolve().parents[5] / 'backend')


def test_active_jobs_include_only_owned_workflows():
    catalog = PipelineLoader(ROOT).load()
    assert set(catalog.connectors) == {"moleg_law_api"}
    assert set(catalog.pipelines) == {"moleg_law_ingestion"}
    deployments = load_deployments(ROOT)
    assert {d["name"] for _, d in deployments} == {
        "specification-standard-management", "specification-document-processing",
        "specification-standard-workflow",
        "openmetadata-postgres-metadata-sync",
        "moleg-law-daily", "moleg-law-weekly-reconciliation",
        "model-train", "model-deploy", "model-stop",
    }
    assert validate_deployment_contracts(catalog, deployments) == []
    for _, d in deployments:
        if "specification" in d["name"]:
            assert d["schedules"] == []
            assert d["work_pool"] == {"name": "teoria-specification", "work_queue_name": "documents"}
            assert "manifest" not in d["parameters"]


def test_document_jobs_cannot_get_automatic_schedules():
    catalog = PipelineLoader(ROOT).load()
    job = load_deployment_manifest(ROOT, "ingestion")["deployments"][0]
    job["schedules"] = [{"cron": "0 * * * *", "timezone": "Asia/Seoul"}]
    diagnostics = validate_deployment_contracts(catalog, [(deployment_path(ROOT, "ingestion"), job)])
    assert diagnostics[0].code == "invalid_specification_deployment"
