from uuid import uuid4

import pytest

from teoria.intelligence.suggestions.execution import ApplicationClaim
from teoria.intelligence.suggestions.execution import SuggestionApplicationError
from teoria.intelligence.suggestions.evidence import require_current_column
from teoria.intelligence.suggestions.service import SuggestionService


class _Repository:
    def __init__(self) -> None:
        self.status = "pending"
        self.finished = None

    async def review(self, suggestion_id, **_):
        self.status = "approved"
        return {
            "suggestion_id": str(suggestion_id),
            "target_type": "openmetadata_table",
            "target_ref": "openmetadata://table/table-1",
            "suggestion_type": "description",
            "proposed_value": {
                "description": "계약 원계약과 변경 이력을 관리하는 테이블"
            },
            "risk_level": "low",
        }

    async def start_application(
        self, suggestion_id, *, target_system="openmetadata", actor="reviewer"
    ):
        return ApplicationClaim(uuid4(), uuid4(), target_system)

    async def mark_effect_started(self, claim):
        pass

    async def record_effect_result(self, claim, external_change_ref):
        pass

    async def finish_application(self, suggestion_id, **values):
        self.status = "applied" if values["applied"] else "failed"
        self.finished = values

    async def get(self, suggestion_id):
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

    async def create(self, **payload):
        self.created = payload
        return {"suggestion_id": "suggestion-1", **payload, "status": "pending"}


class _BindingRepository:
    async def list_published_property_concepts(self):
        return [
            {
                "concept_id": "00000000-0000-4000-8000-000000000001",
                "concept_kind": "property",
                "stable_key": "procurement.Contract.amount",
                "name": "계약금액",
                "description": "확정 계약금액",
                "value_type": "decimal",
            }
        ]


class _ColumnClient:
    async def get(self, path, *, params=None):
        assert path == "v1/tables/table-1"
        assert params == {"fields": "columns,tags,domains"}
        return {
            "id": "table-1",
            "version": 1.4,
            "fullyQualifiedName": "svc.db.schema.contract",
            "columns": [
                {
                    "name": "contract_amount",
                    "description": "계약금액",
                    "dataType": "NUMERIC",
                }
            ],
        }


class _DescriptionSuggestionClient:
    async def get(self, path, *, params=None):
        assert path == "v1/tables/table-1"
        assert params == {"fields": "columns"}
        return {
            "id": "table-1",
            "version": 1.7,
            "fullyQualifiedName": "svc.db.schema.contract",
            "columns": [
                {
                    "name": "amount",
                    "description": "기존 설명",
                    "fullyQualifiedName": "svc.db.schema.contract.amount",
                }
            ],
        }


class _GlossaryRepository(_Repository):
    async def review(self, suggestion_id, **_):
        self.status = "approved"
        return {
            "suggestion_id": str(suggestion_id),
            "target_type": "openmetadata_column",
            "target_ref": "openmetadata://column/svc.db.schema.contract.amount",
            "suggestion_type": "glossary_term_assignment",
            "proposed_value": {
                "table_id": "table-1",
                "column_name": "amount",
                "column_fqn": "svc.db.schema.contract.amount",
                "glossary_term_fqn": "Procurement.ContractAmount",
            },
            "risk_level": "medium",
        }

    async def start_application(
        self, suggestion_id, *, target_system="openmetadata", actor="reviewer"
    ):
        return await super().start_application(suggestion_id)


class _GlossaryClient:
    def __init__(self):
        self.assignment = None

    async def get(self, path, *, params=None):
        assert params == {"fields": "columns"}
        return {
            "id": "table-1",
            "version": 0.3,
            "columns": [{"name": "amount", "tags": []}],
        }

    async def assign_column_glossary_term(self, table_id, **values):
        self.assignment = (table_id, values)
        return {"id": table_id, "version": 0.4}


class _ColumnDescriptionRepository(_Repository):
    async def review(self, suggestion_id, **_):
        self.status = "approved"
        return {
            "suggestion_id": str(suggestion_id),
            "target_type": "openmetadata_column",
            "target_ref": "openmetadata://column/svc.db.schema.contract.amount",
            "suggestion_type": "description",
            "proposed_value": {
                "table_id": "table-1",
                "column_name": "amount",
                "column_fqn": "svc.db.schema.contract.amount",
                "source_version": "0.3",
                "description": "계약 금액",
            },
            "risk_level": "low",
        }


class _ColumnDescriptionClient:
    def __init__(self):
        self.update = None

    async def get(self, path, *, params=None):
        assert path == "v1/tables/table-1"
        assert params == {"fields": "columns"}
        return {
            "id": "table-1",
            "version": 0.3,
            "columns": [
                {
                    "name": "amount",
                    "description": None,
                    "fullyQualifiedName": "svc.db.schema.contract.amount",
                }
            ],
        }

    async def update_column_description(self, table_id, **values):
        self.update = (table_id, values)
        return {"id": table_id, "version": 0.4}


class _ExternalSuggestionRepository(_Repository):
    def __init__(self, suggestion_type, target_type, proposed_value):
        super().__init__()
        self.suggestion_type = suggestion_type
        self.target_type = target_type
        self.proposed_value = proposed_value

    async def review(self, suggestion_id, **_):
        self.status = "approved"
        return {
            "suggestion_id": str(suggestion_id),
            "target_type": self.target_type,
            "target_ref": "target",
            "suggestion_type": self.suggestion_type,
            "proposed_value": self.proposed_value,
            "risk_level": "medium",
        }


class _ExternalClient:
    def __init__(self):
        self.glossary = None
        self.test_suite = None
        self.test_case = None

    async def create_glossary_term(self, payload):
        self.glossary = payload
        return {
            "id": "term-1",
            "fullyQualifiedName": "Procurement.Amount",
            "version": 0.1,
        }

    async def create_test_case(self, payload):
        self.test_case = payload
        return {
            "id": "test-1",
            "fullyQualifiedName": "amount_non_negative",
            "version": 0.1,
        }

    async def get_test_case(self, test_case_id):
        assert test_case_id == "test-1"
        return {
            "id": "test-1",
            "fullyQualifiedName": "amount_non_negative",
            "version": 0.1,
        }

    async def create_test_suite(self, payload):
        self.test_suite = payload
        return {
            "id": "suite-1",
            "fullyQualifiedName": "contract_quality",
            "version": 0.1,
        }

    async def get_test_suite(self, test_suite_id):
        assert test_suite_id == "suite-1"
        return {
            "id": "suite-1",
            "fullyQualifiedName": "contract_quality",
            "version": 0.1,
        }


class _OntologySuggestionRepository(_ExternalSuggestionRepository):
    async def start_application(
        self, suggestion_id, *, target_system="openmetadata", actor="reviewer"
    ):
        self.target_system = target_system
        return await super().start_application(suggestion_id)


class _OntologyRepository:
    def __init__(self):
        self.added = None

    async def create_draft(
        self, namespace, *, version, actor, based_on_version_id=None
    ):
        assert (namespace, version, actor, based_on_version_id) == (
            "teoria",
            "0.1.4",
            "reviewer",
            None,
        )
        return {"ontology_version_id": "00000000-0000-4000-8000-000000000010"}

    async def add_item(self, version_id, *, kind, payload, actor):
        self.added = (str(version_id), kind, payload, actor)
        return {"concept_id": "00000000-0000-4000-8000-000000000011"}


@pytest.mark.asyncio
async def test_approved_low_risk_description_is_applied() -> None:
    repository = _Repository()
    result = await SuggestionService(repository, _Client()).review_and_apply(
        uuid4(), decision="approve", reviewer="reviewer", comment=None
    )
    assert result["status"] == "applied"
    assert (
        repository.finished["external_change_ref"] == "openmetadata://table/table-1@0.2"
    )


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
    ).suggest_column_binding(
        table_id="table-1", column_name="contract_amount", submitted_by="user:admin"
    )

    assert result["suggestion_type"] == "binding"
    assert result["risk_level"] == "medium"
    assert (
        result["proposed_value"]["ontology_stable_key"] == "procurement.Contract.amount"
    )
    assert result["proposed_value"]["source_version"] == "1.4"
    assert repository.created["evidence"]
    assert repository.created["submitted_by"] == "user:admin"


@pytest.mark.asyncio
async def test_manual_description_change_is_a_versioned_review_suggestion() -> None:
    repository = _BindingSuggestionRepository()
    result = await SuggestionService(
        repository, _DescriptionSuggestionClient()
    ).suggest_description_change(
        table_id="table-1",
        column_name="amount",
        description=" 계약 체결 금액 ",
        submitted_by="user:metadata-admin",
    )

    assert result["status"] == "pending"
    assert repository.created["target_type"] == "openmetadata_column"
    assert repository.created["proposed_value"] == {
        "description": "계약 체결 금액",
        "table_id": "table-1",
        "column_name": "amount",
        "column_fqn": "svc.db.schema.contract.amount",
        "source_version": "1.7",
        "source_description": "기존 설명",
    }
    assert repository.created["submitted_by"] == "user:metadata-admin"
    assert repository.created["evidence"][0]["provenance"] == {
        "source_version": "1.7",
        "submitted_by": "user:metadata-admin",
    }


@pytest.mark.asyncio
async def test_glossary_assignment_is_reviewed_and_applied() -> None:
    repository = _GlossaryRepository()
    client = _GlossaryClient()
    result = await SuggestionService(repository, client).review_and_apply(
        uuid4(), decision="approve", reviewer="reviewer", comment="verified"
    )
    assert result["status"] == "applied"
    assert client.assignment == (
        "table-1",
        {
            "column_index": 0,
            "term_fqn": "Procurement.ContractAmount",
            "already_assigned": False,
        },
    )


@pytest.mark.asyncio
async def test_approved_column_description_is_version_checked_and_applied() -> None:
    repository = _ColumnDescriptionRepository()
    client = _ColumnDescriptionClient()
    result = await SuggestionService(repository, client).review_and_apply(
        uuid4(), decision="approve", reviewer="reviewer", comment=None
    )
    assert result["status"] == "applied"
    assert client.update == (
        "table-1",
        {"column_index": 0, "description": "계약 금액", "has_description": False},
    )
    assert repository.finished["external_change_ref"] == (
        "openmetadata://column/svc.db.schema.contract.amount@0.4"
    )


def test_column_description_allows_table_version_advanced_by_sibling_change() -> None:
    require_current_column(
        {"version": 0.4},
        expected_version="0.3",
        current_description=None,
        expected_description=None,
        has_expected_description=True,
    )


def test_column_description_rejects_changed_target_column() -> None:
    with pytest.raises(SuggestionApplicationError, match="제안 생성 후 변경") as error:
        require_current_column(
            {"version": 0.4},
            expected_version="0.3",
            current_description="다른 사용자가 입력한 설명",
            expected_description=None,
            has_expected_description=True,
        )
    assert error.value.code == "stale_evidence"


@pytest.mark.asyncio
async def test_approved_glossary_term_is_created() -> None:
    payload = {"glossary": "Procurement", "name": "Amount", "description": "금액"}
    repository = _ExternalSuggestionRepository(
        "glossary_term", "openmetadata_glossary", payload
    )
    client = _ExternalClient()
    result = await SuggestionService(repository, client).review_and_apply(
        uuid4(), decision="approve", reviewer="reviewer", comment=None
    )
    assert result["status"] == "applied"
    assert client.glossary == payload


@pytest.mark.asyncio
async def test_approved_quality_test_is_created() -> None:
    test_case = {
        "name": "amount_non_negative",
        "testDefinition": "columnValuesToBeBetween",
        "entityLink": "<#E::table::svc.db.schema.contract::columns::amount>",
    }
    repository = _ExternalSuggestionRepository(
        "quality_test",
        "openmetadata_column",
        {"test_case": test_case},
    )
    client = _ExternalClient()
    result = await SuggestionService(repository, client).review_and_apply(
        uuid4(), decision="approve", reviewer="reviewer", comment=None
    )
    assert result["status"] == "applied"
    assert client.test_case == test_case
    assert result["application_verified"] is True


@pytest.mark.asyncio
async def test_approved_test_suite_is_created_independently() -> None:
    test_suite = {
        "name": "contract_quality",
        "basicEntityReference": "svc.db.schema.contract",
    }
    repository = _ExternalSuggestionRepository(
        "test_suite", "openmetadata_table", {"test_suite": test_suite}
    )
    client = _ExternalClient()
    result = await SuggestionService(repository, client).review_and_apply(
        uuid4(), decision="approve", reviewer="reviewer", comment=None
    )
    assert result["status"] == "applied"
    assert client.test_suite == test_suite
    assert result["resulting_test_suite"]["id"] == "suite-1"
    assert result["application_verified"] is True


@pytest.mark.asyncio
async def test_approved_ontology_change_creates_draft_but_does_not_publish() -> None:
    item = {
        "code": "currency",
        "name": "통화",
        "value_type": "string",
        "object_concept_id": "00000000-0000-4000-8000-000000000012",
    }
    repository = _OntologySuggestionRepository(
        "ontology_change",
        "ontology",
        {
            "namespace": "teoria",
            "version": "0.1.4",
            "operation": "add",
            "kind": "property",
            "item": item,
        },
    )
    ontology = _OntologyRepository()
    result = await SuggestionService(
        repository, None, ontology_repository=ontology
    ).review_and_apply(uuid4(), decision="approve", reviewer="reviewer", comment=None)
    assert result["status"] == "applied"
    assert repository.target_system == "teoria_ontology"
    assert ontology.added[1:] == ("property", item, "reviewer")
    assert result["resulting_ontology_draft"]["ontology_version_id"].endswith("0010")
