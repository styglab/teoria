from __future__ import annotations

from datetime import date
import pytest

from teoria.context.service import ContextEngine


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
        return {"description": "계약 테이블", "updatedAt": 1}


class RuntimeClient:
    def __init__(self) -> None:
        self.calls = []

    async def execute(self, capability_id, inputs, *, max_objects=1000):
        self.calls.append((capability_id, dict(inputs)))
        if capability_id == "search_public_organizations":
            return {"objects": [
                {"type": "public_organization", "properties": {"organization_code": "Z013443", "name": "근로복지공단고양지사"}},
                {"type": "public_organization", "properties": {"organization_code": "Z004905", "name": "근로복지공단본부"}},
            ]}
        return {
            "objects": [
                {"type": "contract", "id": "contract-1", "properties": {"unified_contract_number": "C1", "current_contract_amount": "100"}},
                {"type": "public_organization", "properties": {"organization_code": "Z004905"}},
            ],
            "pagination": {"page": 1, "page_size": 100, "total_items": 1, "total_pages": 1},
            "registry": {"version": "2026.10.04.13", "status": "published"},
        }


@pytest.mark.asyncio
async def test_contract_amount_context_composes_governed_sources() -> None:
    result = await ContextEngine(Repository(), MetadataClient()).resolve("계약금액")
    assert result["concept"]["stable_key"] == "procurement.Contract.currentAmount"
    assert result["capabilities"][0]["capability_id"] == "search_public_procurement_contracts"
    assert result["metadata"][0]["table_description"] == "계약 테이블"
    assert result["data_freshness"] is None
    assert result["warnings"] == ["no_approved_api_field_binding"]


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
        "contract_event_count": 1,
        "amount_available_contract_count": 1,
        "contract_amount": 100,
        "currency": "KRW",
        "amount_basis": "current_contract_amount",
        "amount_completeness": "complete",
    }
    assert runtime.calls[1][1]["contracting_organization_code"] == "Z004905"
