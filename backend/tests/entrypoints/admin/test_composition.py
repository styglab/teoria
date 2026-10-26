from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from teoria.entrypoints.composition.admin import (
    create_admin_services,
    install_admin_routers,
)
from teoria.features.semantic_modeling.registry.loader import RegistryLoader
from teoria.settings import Settings

REGISTRIES = Path("archive/procurement_services/platform/registries")


def test_router_installation_reuses_injected_services_without_constructing_dependencies():
    suggestions = Mock(
        list_page=AsyncMock(return_value={"items": [], "next_cursor": None})
    )
    assessments = Mock(list=AsyncMock(return_value=[]))
    context_service = Mock()
    suggestion_service = Mock(
        list_page=AsyncMock(return_value={"items": [], "next_cursor": None})
    )
    services = create_admin_services(
        settings=Settings(),
        catalog=RegistryLoader(REGISTRIES).load(),
        suggestion_repository=suggestions,
        assessment_repository=assessments,
        suggestion_service=suggestion_service,
        asset_context_service=context_service,
    )
    assert services.suggestion_service is suggestion_service
    assert services.asset_context_service is context_service
    app = FastAPI()
    # A second construction here would bypass the injected dependency or its configuration.
    with (
        patch(
            "teoria.entrypoints.composition.admin.AssessmentRepository",
            side_effect=AssertionError,
        ),
        patch(
            "teoria.entrypoints.composition.admin.SuggestionService",
            side_effect=AssertionError,
        ),
        patch(
            "teoria.entrypoints.composition.admin.AssetContextService",
            side_effect=AssertionError,
        ),
    ):
        install_admin_routers(app, services)
    http = TestClient(app)
    assert http.get("/v1/admin/intelligence/suggestions").json()["items"] == []
    assert (
        http.get(
            "/v1/admin/intelligence/asset-assessments",
            params={"table_id": "00000000-0000-4000-8000-000000000001"},
        ).status_code
        == 200
    )
    suggestion_service.list_page.assert_awaited_once_with(
        status=None, limit=50, after=None, table_id=None
    )
    suggestions.list_page.assert_not_called()
    assessments.list.assert_called_once()
