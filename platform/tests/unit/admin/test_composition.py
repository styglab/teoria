from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from teoria.admin.composition import create_admin_services, install_admin_routers
from teoria.registry.loader import RegistryLoader
from teoria.settings import Settings

REGISTRIES = Path(__file__).parents[3] / "registries"


def test_router_installation_reuses_injected_services_without_constructing_dependencies():
    suggestions = Mock(
        list_page=AsyncMock(return_value={"items": [], "next_cursor": None})
    )
    assessments = Mock(list=AsyncMock(return_value=[]))
    law_reader = Mock()
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
        law_search_reader=law_reader,
    )
    assert services.suggestion_service is suggestion_service
    assert services.asset_context_service is context_service
    assert services.law_search_reader is law_reader
    app = FastAPI()
    # A second construction here would bypass the injected dependency or its configuration.
    with (
        patch(
            "teoria.admin.composition.AssessmentRepository", side_effect=AssertionError
        ),
        patch("teoria.admin.composition.SuggestionService", side_effect=AssertionError),
        patch(
            "teoria.admin.composition.AssetContextService", side_effect=AssertionError
        ),
        patch("teoria.admin.composition.LawSearchReader", side_effect=AssertionError),
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
