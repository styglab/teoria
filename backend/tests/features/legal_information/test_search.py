from datetime import date
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from teoria.features.access_control.auth import AdminAuthorizer
from teoria.features.legal_information.admin_api import create_law_search_router
from teoria.features.legal_information.search import LawSearchRequest, _pattern
from teoria.settings import Settings


@pytest.mark.parametrize(
    "query", ["  ", "x", " ".join("word" + str(i) for i in range(9))]
)
def test_search_rejects_empty_tiny_or_unbounded_queries(query):
    with pytest.raises(ValidationError):
        LawSearchRequest(query=query)


def test_search_normalizes_keywords_and_escapes_sql_wildcards():
    request = LawSearchRequest(query="개인정보  민감정보 개인정보", law_id="0011357")
    assert request.query == "개인정보 민감정보" and request.law_id == "11357"
    assert _pattern("a_%") == "%a\\_\\%%"


def test_admin_search_is_authenticated_and_documents_pin_snapshot_and_path():
    reader = Mock(search=AsyncMock(), get_document=AsyncMock())
    reader.search.return_value = {"items": [], "legal_applicability_confirmed": False}
    reader.get_document.return_value = {"content": "synthetic legal document"}
    app = FastAPI()
    app.include_router(
        create_law_search_router(
            reader,
            AdminAuthorizer(
                Settings(admin_auth_mode="bearer", admin_api_token="test-token")
            ),
        )
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    endpoint = "/v1/admin/legal-information/search"
    assert client.post(endpoint, json={"query": "개인정보"}).status_code == 401
    result = client.post(
        endpoint,
        json={"query": "개인정보", "assessment_date": "2026-10-12"},
        headers=headers,
    )
    assert result.status_code == 200
    assert reader.search.call_args.args[0].assessment_date == date(2026, 10, 12)
    snapshot = uuid4()
    assert (
        client.get(
            f"/v1/admin/legal-information/documents/{snapshot}",
            params={"path": "/법령/조문/조문단위[1]"},
            headers=headers,
        ).status_code
        == 200
    )
    assert reader.get_document.call_args.args[0] == snapshot
    reader.get_document.return_value = None
    assert (
        client.get(
            f"/v1/admin/legal-information/documents/{snapshot}",
            params={"path": "missing"},
            headers=headers,
        ).status_code
        == 404
    )
