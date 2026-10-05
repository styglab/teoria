from fastapi.testclient import TestClient

from teoria.admin.semantic_api import create_semantic_router
from fastapi import FastAPI


class _Repository:
    def get_property_context(self, namespace: str, object_code: str, property_code: str):
        if property_code == "missing":
            return None
        return {
            "ontology_ref": f"{namespace}.{object_code}.{property_code}",
            "property_name": "계약금액",
            "bindings": [{"target_type": "data_asset"}],
        }


def _client(repository) -> TestClient:
    app = FastAPI()
    app.include_router(create_semantic_router(repository))
    return TestClient(app)


def test_property_context_returns_property_and_bindings() -> None:
    response = _client(_Repository()).get("/v1/admin/semantic/properties/procurement/Contract/amount")
    assert response.status_code == 200
    assert response.json()["ontology_ref"] == "procurement.Contract.amount"
    assert response.json()["bindings"][0]["target_type"] == "data_asset"


def test_property_context_handles_missing_database_and_property() -> None:
    assert _client(None).get("/v1/admin/semantic/properties/procurement/Contract/amount").status_code == 503
    assert _client(_Repository()).get("/v1/admin/semantic/properties/procurement/Contract/missing").status_code == 404
