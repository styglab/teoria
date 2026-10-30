from pathlib import Path

from fastapi.testclient import TestClient

from teoria.entrypoints.admin_api import create_admin_app
from teoria.features.workflow_management.catalog import workflow_catalog
from teoria.settings import Settings


def test_mlops_app_does_not_load_semantic_artifact_or_expose_authoring_routes(
    tmp_path: Path,
):
    app = create_admin_app(
        settings=Settings(
            environment="test",
            semantic_modeling_enabled=False,
            formatid_enabled=False,
            legal_information_enabled=False,
            model_operations_enabled=True,
            runtime_artifact_store=tmp_path / "missing_artifact",
            openmetadata_enabled=False,
        )
    )
    assert app.state.admin_services.context_engine is None
    assert app.state.admin_services.metadata_service is None
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/v1/admin/deployment").json() == {
            "semantic": False,
            "formatid": False,
            "mlops": True,
        }
        assert client.get("/v1/admin/ontology-authoring/ontologies").status_code == 404
        assert client.get("/v1/admin/model-operations/status").json() == {
            "enabled": True
        }
        assert client.get("/v1/admin/specification-processing/status").json() == {
            "uploads_enabled": False,
            "results_enabled": False,
        }
        assert (
            client.post(
                "/v1/admin/specification-processing/documents?filename=test.pdf",
                content=b"test",
            ).status_code
            == 503
        )


def test_workflow_selection_does_not_offer_disabled_feature_runs():
    mlops = workflow_catalog(
        True, semantic_enabled=False, formatid_enabled=False, legal_enabled=False
    )
    assert set(mlops) == {"demo-customer-churn-pipeline"}
    formatid = workflow_catalog(
        False, semantic_enabled=False, formatid_enabled=True, legal_enabled=False
    )
    assert len(formatid) == 3
    assert all(name.startswith("specification-") for name in formatid)


def test_formatid_retains_authoring_routes_without_openmetadata_or_runtime():
    app = create_admin_app(
        settings=Settings(
            environment="test",
            semantic_modeling_enabled=False,
            formatid_enabled=True,
            legal_information_enabled=False,
            openmetadata_enabled=False,
        )
    )
    with TestClient(app) as client:
        assert client.get("/v1/admin/ontology-authoring/ontologies").status_code == 503
        assert client.get("/v1/admin/deployment").json()["formatid"] is True
    assert app.state.admin_services.context_engine is None
    assert app.state.admin_services.metadata_service is None
