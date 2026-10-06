from __future__ import annotations

from datetime import date
from decimal import Decimal
import re
from typing import Any

from teoria.context.repository import ContextRepository
from teoria.context.runtime_client import ContextRuntimeClient
from teoria.metadata.openmetadata import OpenMetadataClient, OpenMetadataError


class ContextEngine:
    """Compose the minimum governed context required by an AI consumer."""

    def __init__(
        self,
        repository: ContextRepository,
        metadata_client: OpenMetadataClient | None,
        runtime_client: ContextRuntimeClient | None = None,
    ) -> None:
        self.repository = repository
        self.metadata_client = metadata_client
        self.runtime_client = runtime_client

    async def resolve(self, term: str, *, purpose: str | None = None) -> dict[str, Any] | None:
        resolved = self.repository.resolve_property(term)
        if resolved is None:
            return None
        metadata_bindings = [
            item for item in resolved["bindings"]
            if item["target_type"] in {"glossary_term", "data_asset"}
        ]
        api_fields = [
            {
                "source_id": item["api_source_id"],
                "operation_id": item["api_operation_id"],
                "object_id": item["api_object_id"],
                "field_path": item["api_field_path"],
                "contract_version": item["api_contract_version"],
                "registry_version": item["api_registry_version"],
                "purpose": item["purpose"],
                "authority": item["authority"],
                "priority": item["priority"],
            }
            for item in resolved["bindings"] if item["target_type"] == "api_field"
        ]
        capability_bindings = [
            item for item in resolved["bindings"] + resolved["object_capabilities"]
            if item["target_type"].startswith("capability")
        ]
        seen_capabilities: set[tuple[str, str, str | None]] = set()
        capabilities = []
        for item in capability_bindings:
            identity = (item["capability_id"], item["target_scope"], item["field_path"])
            if identity in seen_capabilities:
                continue
            seen_capabilities.add(identity)
            capabilities.append(
            {
                "capability_id": item["capability_id"],
                "scope": item["target_scope"],
                "field_path": item["field_path"],
                "contract_version": item["contract_version"],
                "registry_version": item["registry_version"],
                "binding_type": item["binding_type"],
                "purpose": item["purpose"],
                "authority": item["authority"],
                "priority": item["priority"],
            }
            )
        capabilities.sort(key=lambda item: (item["priority"], item["capability_id"]))
        selected_route = self._select_route(capabilities, purpose=purpose) if purpose else None
        metadata, warnings = await self._metadata(metadata_bindings)
        if not api_fields:
            warnings.append("no_approved_api_field_binding")
        result = {
            "query": term,
            "concept": {
                "stable_key": resolved["stable_key"],
                "name": resolved["name"],
                "description": resolved["description"],
                "value_type": resolved["value_type"],
                "unit": resolved["unit"],
                "business_object": {
                    "stable_key": f'{resolved["namespace"]}.{resolved["object_code"]}',
                    "name": resolved["object_name"],
                },
            },
            "ontology": {
                "namespace": resolved["namespace"],
                "version": resolved["ontology_version"],
                "artifact_id": resolved["artifact_id"],
                "artifact_schema_version": resolved["schema_version"],
                "artifact_checksum": resolved["checksum"],
            },
            "metadata": metadata,
            "api_fields": api_fields,
            "capabilities": capabilities,
            "selected_route": selected_route,
            "evidence": [
                {
                    "type": item["target_type"],
                    "locator": item["target_locator"],
                    "authority": item["authority"],
                    "confidence": item["confidence"],
                    "last_verified_at": item["last_verified_at"],
                }
                for item in resolved["bindings"]
            ],
            "data_freshness": None,
            "data_freshness_status": "unavailable",
            "warnings": warnings + ([] if capabilities else ["no_approved_capability_binding"]),
        }
        return result

    async def query(self, question: str, *, as_of: date | None = None) -> dict[str, Any]:
        if self.runtime_client is None:
            raise RuntimeError("context runtime is unavailable")
        parsed = self._parse_contract_amount_question(question, as_of=as_of or date.today())
        context = await self.resolve("계약금액", purpose="analytics")
        if context is None:
            raise ValueError("Contract.amount context is unavailable")
        route = context["selected_route"]
        if route is None:
            raise ValueError("approved analytics capability binding is unavailable")
        capability_id = route["capability_id"]

        organization = await self._resolve_organization(parsed["organization_query"])
        inputs = {
            "concluded_date_from": parsed["period_from"],
            "concluded_date_to": parsed["period_to"],
            "contracting_organization_code": organization["organization_code"],
            "sort": "concluded_desc",
            "page": 1,
            "page_size": 100,
        }
        plan = {
            "capability_id": capability_id,
            "inputs": inputs,
            "amount_property": "current_contract_amount",
            "amount_basis": "procurement.Contract.currentAmount",
            "selection_reason": route["selection_reason"],
        }
        total = Decimal(0)
        amount_count = 0
        contract_ids: set[str] = set()
        pages = 0
        registry = None
        total_pages = 1
        while inputs["page"] <= total_pages:
            response = await self.runtime_client.execute(capability_id, inputs)
            pages += 1
            registry = response.get("registry", registry)
            pagination = response.get("pagination") or {}
            total_pages = int(pagination.get("total_pages") or 1)
            for item in response.get("objects", []):
                if item.get("type") != "contract":
                    continue
                properties = item.get("properties") or {}
                contract_id = properties.get("unified_contract_number") or item.get("id")
                if not contract_id or contract_id in contract_ids:
                    continue
                contract_ids.add(str(contract_id))
                amount = properties.get("current_contract_amount")
                if amount is not None:
                    total += Decimal(str(amount))
                    amount_count += 1
            inputs = {**inputs, "page": inputs["page"] + 1}

        return {
            "question": question,
            "interpretation": {
                "organization": organization,
                "period_from": parsed["period_from"],
                "period_to": parsed["period_to"],
                "period_years": parsed["period_years"],
                "concept": context["concept"],
            },
            "execution_plan": plan,
            "result": {
                "contract_event_count": len(contract_ids),
                "amount_available_contract_count": amount_count,
                "contract_amount": int(total),
                "currency": "KRW",
                "amount_basis": "current_contract_amount",
                "amount_completeness": "complete" if amount_count == len(contract_ids) else "partial",
            },
            "validation": {
                "published_artifact_checksum": context["ontology"]["artifact_checksum"],
                "approved_capability_binding": True,
                "runtime_registry": registry,
                "executed_pages": pages,
            },
            "evidence": context["evidence"],
            "warnings": context["warnings"],
        }

    @staticmethod
    def _select_route(capabilities: list[dict[str, Any]], *, purpose: str) -> dict[str, Any] | None:
        candidates = [item for item in capabilities if item.get("purpose") == purpose]
        if not candidates:
            return None
        selected = min(candidates, key=lambda item: (item["priority"], item["capability_id"]))
        return {
            **selected,
            "selection_reason": f"approved_{purpose}_binding_with_lowest_priority",
        }

    async def _resolve_organization(self, query: str) -> dict[str, str]:
        response = await self.runtime_client.execute(
            "search_public_organizations",
            {"query": query, "sort": "name_asc", "page": 1, "page_size": 100},
        )
        candidates = []
        normalized_query = self._normalize_organization_name(query)
        for item in response.get("objects", []):
            if item.get("type") != "public_organization":
                continue
            properties = item.get("properties") or {}
            name = str(properties.get("name") or "")
            code = properties.get("organization_code")
            if not name or not code:
                continue
            normalized_name = self._normalize_organization_name(name)
            score = 0 if normalized_name == normalized_query else 1 if normalized_name.startswith(normalized_query) else 2
            headquarters = 0 if name.endswith("본부") else 1
            candidates.append((score, headquarters, len(name), name, str(code)))
        if not candidates:
            raise ValueError(f"organization not found: {query}")
        candidates.sort()
        best = candidates[0]
        if best[0] == 2:
            raise ValueError(f"organization match is ambiguous: {query}")
        return {"organization_code": best[4], "organization_name": best[3], "query": query}

    @staticmethod
    def _normalize_organization_name(value: str) -> str:
        normalized = re.sub(r"\s+", "", value).strip()
        return normalized.removesuffix("본부")

    @staticmethod
    def _parse_contract_amount_question(question: str, *, as_of: date) -> dict[str, Any]:
        if "계약금액" not in question:
            raise ValueError("only Contract.amount questions are supported in this vertical slice")
        years_match = re.search(r"최근\s*(\d+)\s*(?:개\s*회계)?년", question)
        if years_match is None:
            raise ValueError("a recent fiscal-year period is required")
        years = int(years_match.group(1))
        if not 1 <= years <= 20:
            raise ValueError("period_years must be between 1 and 20")
        organization = question[:years_match.start()].strip().removesuffix("의").strip()
        if not organization:
            raise ValueError("organization name is required")
        return {
            "organization_query": organization,
            "period_years": years,
            "period_from": date(as_of.year - years + 1, 1, 1).isoformat(),
            "period_to": as_of.isoformat(),
        }

    async def _metadata(self, bindings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        items = []
        warnings: list[str] = []
        for binding in bindings:
            item = {
                "entity_type": binding["entity_type"],
                "fully_qualified_name": binding["fully_qualified_name"],
                "external_version": binding["external_version"],
                "last_verified_at": binding["last_verified_at"],
                "available": self.metadata_client is not None,
            }
            if self.metadata_client and binding["entity_type"] == "column" and binding["fully_qualified_name"]:
                table_fqn = binding["fully_qualified_name"].rsplit(".", 1)[0]
                try:
                    table = await self.metadata_client.get_table_by_name(table_fqn)
                    item["table_description"] = table.get("description")
                    item["table_updated_at"] = table.get("updatedAt")
                except OpenMetadataError as exc:
                    item["available"] = False
                    warnings.append(exc.code)
            items.append(item)
        return items, sorted(set(warnings))
