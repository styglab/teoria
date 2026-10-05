from uuid import uuid4

import pytest

from teoria.intelligence.service import SuggestionService


class _Repository:
    def __init__(self) -> None:
        self.status = "pending"
        self.finished = None

    def review(self, suggestion_id, **_):
        self.status = "approved"
        return {
            "suggestion_id": str(suggestion_id),
            "target_type": "openmetadata_table",
            "target_ref": "openmetadata://table/table-1",
            "suggestion_type": "description",
            "proposed_value": {"description": "계약 원계약과 변경 이력을 관리하는 테이블"},
            "risk_level": "low",
        }

    def start_application(self, suggestion_id):
        return uuid4()

    def finish_application(self, suggestion_id, **values):
        self.status = "applied" if values["applied"] else "failed"
        self.finished = values

    def get(self, suggestion_id):
        return {"suggestion_id": str(suggestion_id), "status": self.status}


class _Client:
    async def get(self, path):
        assert path == "v1/tables/table-1"
        return {"id": "table-1", "description": None}

    async def update_table_description(self, table_id, description, *, has_description):
        assert (table_id, has_description) == ("table-1", False)
        assert description.startswith("계약 원계약")
        return {"id": "table-1", "version": 0.2}


class _BindingSuggestionRepository:
    def __init__(self) -> None:
        self.created = None

    def create(self, **payload):
        self.created = payload
        return {"suggestion_id": "suggestion-1", **payload, "status": "pending"}


class _BindingRepository:
    def list_published_property_concepts(self):
        return [{
            "concept_id": "00000000-0000-4000-8000-000000000001",
            "concept_kind": "property",
            "stable_key": "procurement.Contract.amount",
            "name": "계약금액", "description": "확정 계약금액", "value_type": "decimal",
        }]


class _ColumnClient:
    async def get(self, path, *, params=None):
        assert path == "v1/tables/table-1"
        assert params == {"fields": "columns,tags,domains"}
        return {
            "id": "table-1", "version": 1.4, "fullyQualifiedName": "svc.db.schema.contract",
            "columns": [{"name": "contract_amount", "description": "계약금액", "dataType": "NUMERIC"}],
        }


@pytest.mark.asyncio
async def test_approved_low_risk_description_is_applied() -> None:
    repository = _Repository()
    result = await SuggestionService(repository, _Client()).review_and_apply(
        uuid4(), decision="approve", reviewer="reviewer", comment=None
    )
    assert result["status"] == "applied"
    assert repository.finished["external_change_ref"] == "openmetadata://table/table-1@0.2"


@pytest.mark.asyncio
async def test_rejection_does_not_write_to_openmetadata() -> None:
    repository = _Repository()
    result = await SuggestionService(repository, None).review_and_apply(
        uuid4(), decision="reject", reviewer="reviewer", comment=None
    )
    assert result["risk_level"] == "low"
    assert repository.finished is None


@pytest.mark.asyncio
async def test_column_binding_suggestion_has_versioned_evidence_and_candidate() -> None:
    repository = _BindingSuggestionRepository()
    result = await SuggestionService(
        repository, _ColumnClient(), _BindingRepository()
    ).suggest_column_binding(table_id="table-1", column_name="contract_amount")

    assert result["suggestion_type"] == "binding"
    assert result["risk_level"] == "medium"
    assert result["proposed_value"]["ontology_stable_key"] == "procurement.Contract.amount"
    assert result["proposed_value"]["source_version"] == "1.4"
    assert repository.created["evidence"]
