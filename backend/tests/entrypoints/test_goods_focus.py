from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from teoria.entrypoints.admin.api import create_admin_app
from teoria.features.runtime.context.service import ContextEngine
from teoria.features.semantic_modeling.ontology.blueprint import OntologyBlueprint, apply_ontology_blueprint
from teoria.features.semantic_modeling.ontology.migration import OntologyMigrationManifest, build_migration_report
from teoria.features.semantic_modeling.registry.loader import RegistryLoader
from teoria.settings import Settings


ROOT = (Path(__file__).resolve().parents[3])
MANIFEST = ROOT / "backend/ontology_migrations/pending/2026_10_goods_focus/ontology_v2.yaml"


def test_active_catalog_cannot_discover_retired_services():
    catalog = RegistryLoader(ROOT / "backend/registries").load()
    assert catalog.sources == catalog.capabilities == catalog.mappings == catalog.runtime_contracts == {}
    client = TestClient(create_admin_app(settings=Settings(), catalog=catalog))
    assert client.get("/v1/admin/capabilities").json() == {"capabilities": []}
    assert client.get("/v1/admin/overview").json()["validation"]["status"] == "valid"


async def test_retired_contracts_have_explicit_dispositions():
    active = RegistryLoader(ROOT / "backend/registries").load()
    legacy = RegistryLoader(ROOT / "archive/procurement_services/platform/registries").load()
    manifest = OntologyMigrationManifest.load(MANIFEST)
    old_objects = {f"{key}.{obj.id}" for key, contract in legacy.runtime_contracts.items()
                   for obj in contract.object_types}
    assert set(manifest.objects) == old_objects
    assert (await build_migration_report(active, manifest))["status"] == "valid"
    # An unretired reference must still be rejected instead of silently ignored.
    manifest.objects[next(iter(old_objects))].classification = "RUNTIME_PROJECTION"
    assert (await build_migration_report(active, manifest))["status"] == "invalid"


async def test_goods_blueprint_creates_a_draft_without_publication():
    blueprint = OntologyBlueprint.load(ROOT / "backend/ontology_blueprints/goods.yaml")
    repo = AsyncMock()
    repo.list_versions.return_value = []
    repo.create_ontology.return_value = {"ontology_version_id": "00000000-0000-4000-8000-000000000001"}
    repo.add_item.return_value = {"concept_id": "00000000-0000-4000-8000-000000000002"}
    repo.validate.return_value = {"status": "valid"}
    result = await apply_ontology_blueprint(repo, blueprint, actor="user:test")
    assert result["status"] == "draft"
    assert {obj.code for obj in blueprint.objects} == {"specification_document", "item", "requirement"}
    repo.publish.assert_not_called()
    assert all(call.kwargs["actor"] == "user:test" for call in repo.add_item.await_args_list)


async def test_context_does_not_fall_back_to_retired_procurement_queries():
    engine = ContextEngine(object(), None, object())
    with pytest.raises(ValueError, match="No active domain query handler"):
        await engine.plan("최근 5년 계약금액")
