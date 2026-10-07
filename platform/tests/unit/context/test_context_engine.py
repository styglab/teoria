from __future__ import annotations

from datetime import date
import pytest

from teoria.context.service import ContextEngine
from teoria.context.repository import BundleContextRepository
from teoria.policy import PolicyDecision, PolicyDeniedError


class Repository:
    def resolve_property(self, term: str):
        assert term == "계약금액"
        return {
            "stable_key": "procurement.Contract.currentAmount", "name": "계약금액",
            "description": "계약 금액", "value_type": "money", "unit": "KRW",
            "namespace": "procurement", "object_code": "Contract", "object_name": "계약",
            "ontology_version": "0.5.0", "artifact_id": "artifact-1",
            "schema_version": "1.0", "checksum": "checksum",
            "bindings": [{
                "target_type": "data_asset", "target_locator": "openmetadata://column/x",
                "authority": "authoritative", "confidence": 1.0, "last_verified_at": "2026-10-06",
                "entity_type": "column", "fully_qualified_name": "svc.db.schema.contracts.amount",
                "external_version": "1.0",
                "purpose": "analytics", "priority": 10,
                "binding_type": "represents",
                "capability_id": None, "target_scope": None, "field_path": None,
            }, {
                "target_type": "capability_output", "target_locator": "capability://search_public_procurement_contracts/output/public_procurement.contract",
                "authority": "preferred", "confidence": 1.0, "last_verified_at": None,
                "capability_id": "search_public_procurement_contracts", "target_scope": "output",
                "field_path": "public_procurement.contract", "contract_version": "2026.10.06.3",
                "registry_version": "2026.10.06.3", "purpose": "analytics", "priority": 10,
                "binding_type": "provides_property",
            }],
            "object_capabilities": [],
        }


class MetadataClient:
    async def get_table_by_name(self, fqn: str):
        assert fqn == "svc.db.schema.contracts"
        return {"description": "계약 테이블", "updatedAt": 1, "testSuite": None}


class RuntimeClient:
    def __init__(self) -> None:
        self.calls = []

    async def execute(
        self, capability_id, inputs, *, max_objects=1000,
        actor=None, roles=frozenset(), service=None,
    ):
        self.calls.append((capability_id, dict(inputs)))
        if capability_id == "search_public_organizations":
            return {"objects": [
                {"type": "public_organization", "properties": {"organization_code": "Z013443", "name": "근로복지공단고양지사"}},
                {"type": "public_organization", "properties": {"organization_code": "Z004905", "name": "근로복지공단본부"}},
            ]}
        return {
            "objects": [
                {"type": "contract", "id": "contract-1", "properties": {"unified_contract_number": "C1", "current_contract_amount": "100", "source_registered_at": "2026-10-05T01:02:03+00:00"}},
                {"type": "public_organization", "properties": {"organization_code": "Z004905"}},
            ],
            "pagination": {"page": 1, "page_size": 100, "total_items": 1, "total_pages": 1},
            "registry": {"version": "2026.10.04.13", "status": "published"},
        }


class BidNoticeRepository:
    def resolve_property(self, term: str):
        assert term == "게시일시"
        return {
            "stable_key": "procurement.BidNotice.publishedAt", "name": "게시일시",
            "description": "입찰공고 게시 시각", "value_type": "datetime", "unit": None,
            "namespace": "teoria", "object_code": "BidNotice", "object_name": "입찰공고",
            "ontology_version": "0.1.3", "artifact_id": "artifact-2",
            "schema_version": "1.0", "checksum": "bid-checksum",
            "bindings": [{
                "target_type": "capability_output", "target_locator": "capability://search_bid_notices/output/public_procurement.bid_notice",
                "authority": "preferred", "confidence": 1.0, "last_verified_at": "2026-10-07",
                "capability_id": "search_bid_notices", "target_scope": "output",
                "field_path": "public_procurement.bid_notice", "contract_version": "test",
                "registry_version": "test", "purpose": "discovery", "priority": 10,
                "binding_type": "provides_property",
            }],
            "object_capabilities": [],
        }


class BidNoticeRuntime(RuntimeClient):
    async def execute(
        self, capability_id, inputs, *, max_objects=1000,
        actor=None, roles=frozenset(), service=None,
    ):
        self.calls.append((capability_id, dict(inputs)))
        if capability_id == "search_public_organizations":
            return await super().execute(
                capability_id, inputs, max_objects=max_objects,
                actor=actor, roles=roles, service=service,
            )
        assert capability_id == "search_bid_notices"
        return {
            "objects": [{"type": "bid_notice", "id": "N1:00", "properties": {
                "bid_notice_id": "N1:00", "notice_name": "소프트웨어 구축 용역",
                "notice_organization_name": "근로복지공단본부", "bid_status": "open",
                "work_type": "service", "estimated_price": 150_000_000,
                "notice_published_at": "2026-10-01T00:00:00Z",
                "bid_deadline_at": "2026-10-10T00:00:00Z",
                "source_changed_at": "2026-10-06T10:00:00Z",
            }}],
            "pagination": {"total_items": 1, "total_pages": 1},
            "registry": {"version": "test", "status": "published"},
        }


def test_bundle_context_repository_uses_frozen_ontology_and_bindings() -> None:
    bundle = type("Bundle", (), {
        "ontologies": [{
            "namespace": "procurement", "version": "0.5.0",
            "artifact_id": "artifact-1", "schema_version": "1.0",
            "checksum": "ontology-checksum",
            "content": {"objects": [{
                "code": "Contract", "name": "계약",
                "stable_key": "procurement.Contract",
                "properties": [{
                    "code": "currentAmount", "name": "계약금액",
                    "stable_key": "procurement.Contract.currentAmount",
                    "description": "계약 금액", "value_type": "money", "unit": "KRW",
                }],
            }]},
        }],
        "bindings": [{
            "status": "approved",
            "ontology_stable_key": "procurement.Contract.currentAmount",
            "target_type": "capability_output",
            "target_locator": "capability://search_contracts/output/amount",
            "capability_id": "search_contracts",
            "capability_target_scope": "output",
            "capability_field_path": "contract.current_amount",
            "capability_contract_version": "1.0",
            "capability_registry_version": "2026.10.06.1",
            "binding_type": "provides_property", "purpose": "analytics",
            "authority": "preferred", "priority": 10, "confidence": 1.0,
        }],
    })()

    resolved = BundleContextRepository(bundle).resolve_property("계약금액")

    assert resolved["stable_key"] == "procurement.Contract.currentAmount"
    assert resolved["bindings"][0]["target_scope"] == "output"
    assert resolved["bindings"][0]["registry_version"] == "2026.10.06.1"


@pytest.mark.asyncio
async def test_contract_amount_context_composes_governed_sources() -> None:
    result = await ContextEngine(Repository(), MetadataClient()).resolve("계약금액")
    assert result["concept"]["stable_key"] == "procurement.Contract.currentAmount"
    assert result["capabilities"][0]["capability_id"] == "search_public_procurement_contracts"
    assert result["metadata"][0]["table_description"] == "계약 테이블"
    assert result["metadata_updated_at"] == "1970-01-01T00:00:00.001000+00:00"
    assert result["data_freshness"] is None
    assert result["data_freshness_status"] == "unavailable"
    assert result["metadata"][0]["quality"]["status"] == "unavailable"
    assert result["warnings"] == []


@pytest.mark.asyncio
async def test_contract_amount_context_selects_analytics_route() -> None:
    result = await ContextEngine(Repository(), MetadataClient()).resolve(
        "계약금액", purpose="analytics"
    )

    assert result["selected_route"]["capability_id"] == "search_public_procurement_contracts"
    assert result["selected_route"]["selection_reason"] == (
        "approved_analytics_binding_with_lowest_priority"
    )
    assert result["api_fields"] == []


@pytest.mark.asyncio
async def test_contract_amount_question_builds_and_executes_capability_plan() -> None:
    runtime = RuntimeClient()
    result = await ContextEngine(Repository(), MetadataClient(), runtime).query(
        "근로복지공단의 최근 5년 계약금액을 알려줘",
        as_of=date(2026, 10, 6),
    )

    assert result["interpretation"]["organization"]["organization_code"] == "Z004905"
    assert result["interpretation"]["period_from"] == "2022-01-01"
    assert result["interpretation"]["period_to"] == "2026-10-06"
    assert result["execution_plan"]["capability_id"] == "search_public_procurement_contracts"
    assert result["result"] == {
        "status": "complete",
        "contract_event_count": 1,
        "amount_available_contract_count": 1,
        "contract_amount": 100,
        "currency": "KRW",
        "amount_basis": "current_contract_amount",
        "amount_completeness": "complete",
    }
    assert result["policy"]["decision"] == "allowed"
    assert result["policy"]["max_period_years"] == 10
    assert result["validation"]["data_freshness"] == "2026-10-05T01:02:03+00:00"
    assert result["validation"]["metadata_quality_status"] == "unavailable"
    assert runtime.calls[1][1]["contracting_organization_code"] == "Z004905"


@pytest.mark.asyncio
async def test_context_plan_is_policy_checked_without_executing_target_capability() -> None:
    class CapturingPolicy:
        def __init__(self):
            self.actions = []

        async def decide(self, **request):
            self.actions.append(request["action"])
            return PolicyDecision(allow=True, reason="test_allow")

    runtime = RuntimeClient()
    policy = CapturingPolicy()
    plan = await ContextEngine(
        Repository(), MetadataClient(), runtime, policy_evaluator=policy,
    ).plan(
        "근로복지공단의 최근 5년 계약금액을 알려줘",
        as_of=date(2026, 10, 6),
        actor="user:test",
    )

    assert plan["schema_version"] == "1.0"
    assert plan["query_type"] == "contract_amount"
    assert plan["concept"]["stable_key"] == "procurement.Contract.currentAmount"
    assert plan["capability_id"] == "search_public_procurement_contracts"
    assert policy.actions == ["context.plan"]
    assert [call[0] for call in runtime.calls] == ["search_public_organizations"]


@pytest.mark.asyncio
async def test_context_plan_stops_when_policy_denies() -> None:
    class DenyPolicy:
        async def decide(self, **request):
            return PolicyDecision(
                allow=False, reason="missing_context_permission", decision_id="deny-1"
            )

    runtime = RuntimeClient()
    with pytest.raises(PolicyDeniedError) as exc:
        await ContextEngine(
            Repository(), MetadataClient(), runtime,
            policy_evaluator=DenyPolicy(),
        ).plan(
            "근로복지공단의 최근 5년 계약금액을 알려줘",
            as_of=date(2026, 10, 6),
            actor="user:test",
        )

    assert exc.value.decision.decision_id == "deny-1"
    assert runtime.calls == []


@pytest.mark.asyncio
async def test_context_query_rejects_period_outside_policy() -> None:
    with pytest.raises(ValueError, match="between 1 and 10"):
        await ContextEngine(Repository(), MetadataClient(), RuntimeClient()).query(
            "근로복지공단의 최근 11년 계약금액을 알려줘",
            as_of=date(2026, 10, 6),
        )


@pytest.mark.asyncio
async def test_context_query_preserves_partial_page_failure() -> None:
    class PartialRuntime(RuntimeClient):
        async def execute(
            self, capability_id, inputs, *, max_objects=1000,
            actor=None, roles=frozenset(), service=None,
        ):
            if capability_id == "search_public_organizations":
                return await super().execute(
                    capability_id, inputs, max_objects=max_objects,
                    actor=actor, roles=roles, service=service,
                )
            if inputs["page"] == 2:
                raise RuntimeError("page unavailable")
            return {
                "objects": [{"type": "contract", "id": "contract-1", "properties": {"unified_contract_number": "C1", "current_contract_amount": "100"}}],
                "pagination": {"page": 1, "page_size": 100, "total_items": 101, "total_pages": 2},
                "registry": {"version": "test", "status": "published"},
            }

    result = await ContextEngine(Repository(), MetadataClient(), PartialRuntime()).query(
        "근로복지공단의 최근 5년 계약금액을 알려줘", as_of=date(2026, 10, 6)
    )
    assert result["result"]["status"] == "partial"
    assert result["result"]["amount_completeness"] == "unknown"
    assert result["validation"]["failed_pages"] == [2]
    assert "runtime_page_failed" in result["warnings"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("question", "expected"), [
    ("최근 30일 동안 게시된 용역 입찰공고를 찾아줘", {"work_type": "service"}),
    ("추정가격 1억 원 이상인 소프트웨어 관련 공고를 찾아줘", {"query": "소프트웨어", "estimated_price_min": 100_000_000}),
    ("근로복지공단이 게시한 현재 접수 중인 입찰공고를 찾아줘", {"bid_status": "open", "notice_organization_code": "Z004905"}),
])
async def test_bid_notice_questions_build_governed_search_plan(question, expected) -> None:
    runtime = BidNoticeRuntime()
    result = await ContextEngine(BidNoticeRepository(), None, runtime).query(
        question, as_of=date(2026, 10, 7), actor="user:test",
    )
    assert result["query_type"] == "bid_notice_search"
    assert result["execution_plan"]["capability_id"] == "search_bid_notices"
    assert result["result"]["total_items"] == 1
    assert result["result"]["notices"][0]["bid_notice_id"] == "N1:00"
    assert result["validation"]["data_freshness"] == "2026-10-06T10:00:00Z"
    for key, value in expected.items():
        assert result["execution_plan"]["inputs"][key] == value
