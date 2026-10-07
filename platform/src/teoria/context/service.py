from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import re
from typing import Any
from dataclasses import dataclass

from teoria.context.repository import ContextRepository
from teoria.context.runtime_client import ContextRuntimeClient
from teoria.metadata.openmetadata import OpenMetadataClient, OpenMetadataError
from teoria.policy import (
    DisabledPolicyEvaluator,
    PolicyDeniedError,
    PolicyEvaluator,
    PolicyPrincipal,
)


@dataclass(frozen=True)
class ContextExecutionPolicy:
    max_period_years: int = 10
    max_pages: int = 100


class ContextEngine:
    """Compose the minimum governed context required by an AI consumer."""

    def __init__(
        self,
        repository: ContextRepository,
        metadata_client: OpenMetadataClient | None,
        runtime_client: ContextRuntimeClient | None = None,
        policy: ContextExecutionPolicy | None = None,
        policy_evaluator: PolicyEvaluator | None = None,
    ) -> None:
        self.repository = repository
        self.metadata_client = metadata_client
        self.runtime_client = runtime_client
        self.policy = policy or ContextExecutionPolicy()
        self.policy_evaluator = policy_evaluator or DisabledPolicyEvaluator()

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
        if not api_fields and not metadata_bindings:
            warnings.append("no_approved_api_field_binding")
        metadata_update_values = [item["table_updated_at"] for item in metadata if item.get("table_updated_at")]
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
            "metadata_updated_at": max(metadata_update_values) if metadata_update_values else None,
            "data_freshness": None,
            "data_freshness_status": "unavailable",
            "warnings": warnings + ([] if capabilities else ["no_approved_capability_binding"]),
        }
        return result

    async def plan(
        self,
        question: str,
        *,
        as_of: date | None = None,
        actor: str = "anonymous",
        roles: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        if self.runtime_client is None:
            raise RuntimeError("context runtime is unavailable")
        principal = PolicyPrincipal(actor=actor, roles=roles, service="admin-api")
        resolved_as_of = as_of or date.today()
        is_bid_notice_query = "공고" in question and "계약금액" not in question
        query_type = "bid_notice_search" if is_bid_notice_query else "contract_amount"
        capability_id = (
            "search_bid_notices"
            if is_bid_notice_query
            else "search_public_procurement_contracts"
        )
        concept = (
            "procurement.BidNotice.publishedAt"
            if is_bid_notice_query
            else "procurement.Contract.currentAmount"
        )
        decision = await self.policy_evaluator.decide(
            principal=principal,
            action="context.plan",
            resource={
                "type": "semantic_query",
                "query_type": query_type,
                "concept": concept,
                "capability_id": capability_id,
            },
            context={"as_of": resolved_as_of.isoformat(), "question": question},
        )
        if not decision.allow:
            raise PolicyDeniedError(decision)
        if is_bid_notice_query:
            plan = await self._plan_bid_notices(
                question, as_of=resolved_as_of, principal=principal,
            )
        else:
            plan = await self._plan_contract_amount(
                question, as_of=resolved_as_of, principal=principal,
            )
        plan["policy"] = decision.model_dump(mode="json")
        return plan

    async def query(
        self,
        question: str,
        *,
        as_of: date | None = None,
        actor: str = "anonymous",
        roles: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        plan = await self.plan(
            question, as_of=as_of, actor=actor, roles=roles,
        )
        principal = PolicyPrincipal(actor=actor, roles=roles, service="admin-api")
        decision = await self.policy_evaluator.decide(
            principal=principal,
            action="context.execute",
            resource={
                "type": "semantic_query",
                "query_type": plan["query_type"],
                "concept": plan["concept"]["stable_key"],
                "capability_id": plan["capability_id"],
            },
            context={"as_of": plan["as_of"], "inputs": plan["inputs"]},
        )
        if not decision.allow:
            raise PolicyDeniedError(decision)
        if plan["query_type"] == "bid_notice_search":
            return await self._execute_bid_notice_plan(plan, principal, decision)
        return await self._execute_contract_amount_plan(plan, principal, decision)

    async def _plan_contract_amount(
        self, question: str, *, as_of: date, principal: PolicyPrincipal,
    ) -> dict[str, Any]:
        parsed = self._parse_contract_amount_question(
            question,
            as_of=as_of,
            max_period_years=self.policy.max_period_years,
        )
        context = await self.resolve("계약금액", purpose="analytics")
        if context is None:
            raise ValueError("Contract.amount context is unavailable")
        route = context["selected_route"]
        if route is None:
            raise ValueError("approved analytics capability binding is unavailable")
        capability_id = route["capability_id"]

        organization = await self._resolve_organization(
            parsed["organization_query"], principal=principal,
        )
        inputs = {
            "concluded_date_from": parsed["period_from"],
            "concluded_date_to": parsed["period_to"],
            "contracting_organization_code": organization["organization_code"],
            "sort": "concluded_desc",
            "page": 1,
            "page_size": 100,
        }
        return {
            "schema_version": "1.0",
            "query_type": "contract_amount",
            "question": question,
            "as_of": as_of.isoformat(),
            "concept": context["concept"],
            "ontology": context["ontology"],
            "capability_id": capability_id,
            "inputs": inputs,
            "interpretation": {
                "organization": organization,
                "period_from": parsed["period_from"],
                "period_to": parsed["period_to"],
                "period_years": parsed["period_years"],
            },
            "amount_property": "current_contract_amount",
            "amount_basis": "procurement.Contract.currentAmount",
            "selection_reason": route["selection_reason"],
            "evidence": context["evidence"],
            "metadata_quality_status": self._metadata_quality_status(context),
            "warnings": list(context["warnings"]),
        }

    async def _execute_contract_amount_plan(
        self,
        plan: dict[str, Any],
        principal: PolicyPrincipal,
        decision: Any,
    ) -> dict[str, Any]:
        capability_id = plan["capability_id"]
        inputs = dict(plan["inputs"])
        total = Decimal(0)
        amount_count = 0
        source_freshness_values: list[str] = []
        contract_ids: set[str] = set()
        pages = 0
        registry = None
        total_pages = 1
        failed_pages: list[int] = []
        execution_warnings: list[str] = []
        while inputs["page"] <= total_pages:
            if pages >= self.policy.max_pages:
                execution_warnings.append("context_page_limit_reached")
                break
            try:
                response = await self.runtime_client.execute(
                    capability_id,
                    inputs,
                    actor=principal.actor,
                    roles=principal.roles,
                    service=principal.service,
                )
            except RuntimeError:
                if pages == 0:
                    raise
                failed_pages.append(inputs["page"])
                execution_warnings.append("runtime_page_failed")
                break
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
                source_freshness = properties.get("source_registered_at")
                if source_freshness:
                    source_freshness_values.append(str(source_freshness))
            inputs = {**inputs, "page": inputs["page"] + 1}

        return {
            "query_type": "contract_amount",
            "question": plan["question"],
            "interpretation": {
                **plan["interpretation"],
                "concept": plan["concept"],
            },
            "execution_plan": plan,
            "result": {
                "status": "partial" if execution_warnings else "complete",
                "contract_event_count": len(contract_ids),
                "amount_available_contract_count": amount_count,
                "contract_amount": int(total),
                "currency": "KRW",
                "amount_basis": "current_contract_amount",
                "amount_completeness": "unknown" if execution_warnings else "complete" if amount_count == len(contract_ids) else "partial",
            },
            "policy": {
                "decision": "allowed" if decision.allow else "denied",
                "reason": decision.reason,
                "decision_id": decision.decision_id,
                "actor": principal.actor,
                "roles": sorted(principal.roles),
                "max_period_years": self.policy.max_period_years,
                "max_pages": self.policy.max_pages,
                "validated_period_years": plan["interpretation"]["period_years"],
            },
            "validation": {
                "published_artifact_checksum": plan["ontology"]["artifact_checksum"],
                "approved_capability_binding": True,
                "runtime_registry": registry,
                "executed_pages": pages,
                "failed_pages": failed_pages,
                "data_freshness": max(source_freshness_values) if source_freshness_values else None,
                "data_freshness_status": "available" if source_freshness_values else "unavailable",
                "metadata_quality_status": plan["metadata_quality_status"],
            },
            "evidence": plan["evidence"],
            "warnings": plan["warnings"] + execution_warnings,
        }

    async def _plan_bid_notices(
        self, question: str, *, as_of: date, principal: PolicyPrincipal,
    ) -> dict[str, Any]:
        parsed = self._parse_bid_notice_question(question, as_of=as_of)
        context = await self.resolve("게시일시", purpose="discovery")
        if context is None or context["selected_route"] is None:
            raise ValueError("approved bid notice discovery binding is unavailable")
        inputs: dict[str, Any] = {
            "notice_published_at_from": parsed["period_from"],
            "notice_published_at_to": parsed["period_to"],
            "notice_status": "active",
            "sort": "deadline_asc" if parsed.get("bid_status") == "open" else "published_desc",
            "page": 1,
            "page_size": 20,
        }
        for key in ("query", "work_type", "bid_status", "estimated_price_min"):
            if parsed.get(key) is not None:
                inputs[key] = parsed[key]
        organization = None
        if parsed.get("organization_query"):
            organization = await self._resolve_organization(
                parsed["organization_query"], principal=principal,
            )
            inputs["notice_organization_code"] = organization["organization_code"]
        return {
            "schema_version": "1.0",
            "query_type": "bid_notice_search",
            "question": question,
            "as_of": as_of.isoformat(),
            "concept": context["concept"],
            "ontology": context["ontology"],
            "capability_id": "search_bid_notices",
            "inputs": inputs,
            "selection_reason": context["selected_route"]["selection_reason"],
            "interpretation": {
                "period_from": parsed["period_from"],
                "period_to": parsed["period_to"],
                "period_defaulted": parsed["period_defaulted"],
                "organization": organization,
                "filters": {
                    key: value for key, value in inputs.items()
                    if key not in {"page", "page_size", "sort"}
                },
            },
            "evidence": context["evidence"],
            "metadata_quality_status": self._metadata_quality_status(context),
            "warnings": list(context["warnings"]) + (
                ["default_period_applied"] if parsed["period_defaulted"] else []
            ),
        }

    async def _execute_bid_notice_plan(
        self,
        plan: dict[str, Any],
        principal: PolicyPrincipal,
        decision: Any,
    ) -> dict[str, Any]:
        response = await self.runtime_client.execute(
            plan["capability_id"],
            plan["inputs"],
            actor=principal.actor,
            roles=principal.roles,
            service=principal.service,
        )
        notices = []
        freshness_values = []
        for item in response.get("objects", []):
            if item.get("type") != "bid_notice":
                continue
            properties = item.get("properties") or {}
            notices.append({
                "bid_notice_id": properties.get("bid_notice_id") or item.get("id"),
                "notice_name": properties.get("notice_name"),
                "notice_organization_name": properties.get("notice_organization_name"),
                "notice_published_at": properties.get("notice_published_at"),
                "bid_deadline_at": properties.get("bid_deadline_at"),
                "bid_status": properties.get("bid_status"),
                "work_type": properties.get("work_type"),
                "estimated_price": properties.get("estimated_price"),
                "detail_url": properties.get("detail_url") or properties.get("notice_url"),
            })
            if properties.get("source_changed_at"):
                freshness_values.append(str(properties["source_changed_at"]))
        pagination = response.get("pagination") or {}
        return {
            "query_type": "bid_notice_search",
            "question": plan["question"],
            "interpretation": {
                **plan["interpretation"],
                "concept": plan["concept"],
            },
            "execution_plan": plan,
            "result": {
                "status": "complete", "total_items": int(pagination.get("total_items") or len(notices)),
                "returned_items": len(notices), "notices": notices,
            },
            "policy": {
                "decision": "allowed" if decision.allow else "denied",
                "reason": decision.reason,
                "decision_id": decision.decision_id,
                "actor": principal.actor,
                "roles": sorted(principal.roles),
                "max_period_years": self.policy.max_period_years,
                "default_period_days": 365,
            },
            "validation": {
                "published_artifact_checksum": plan["ontology"]["artifact_checksum"],
                "approved_capability_binding": True, "runtime_registry": response.get("registry"),
                "executed_pages": 1, "failed_pages": [],
                "data_freshness": max(freshness_values) if freshness_values else None,
                "data_freshness_status": "available" if freshness_values else "unavailable",
                "metadata_quality_status": plan["metadata_quality_status"],
            },
            "evidence": plan["evidence"],
            "warnings": plan["warnings"],
        }

    @staticmethod
    def _metadata_quality_status(context: dict[str, Any]) -> str:
        return (
            "available"
            if any(
                item.get("quality", {}).get("status") == "available"
                for item in context["metadata"]
            )
            else "unavailable"
        )

    @staticmethod
    def _parse_bid_notice_question(question: str, *, as_of: date) -> dict[str, Any]:
        if "공고" not in question:
            raise ValueError("bid notice question is required")
        days_match = re.search(r"최근\s*(\d+)\s*일", question)
        days = int(days_match.group(1)) if days_match else 365
        if not 1 <= days <= 3650:
            raise ValueError("recent days must be between 1 and 3650")
        amount_match = re.search(r"추정가격\s*(\d+(?:\.\d+)?)\s*억\s*원?\s*이상", question)
        work_type = next((value for token, value in (("용역", "service"), ("물품", "goods"), ("공사", "construction")) if token in question), None)
        organization_match = re.search(r"(.+?)(?:이|가)\s*게시한", question)
        query = "소프트웨어" if "소프트웨어" in question else None
        return {
            "period_from": datetime.combine(as_of - timedelta(days=days - 1), datetime.min.time()).isoformat(),
            "period_to": datetime.combine(as_of, datetime.max.time()).isoformat(),
            "period_defaulted": days_match is None,
            "query": query,
            "work_type": work_type,
            "bid_status": "open" if any(token in question for token in ("접수 중", "진행 중", "현재 접수")) else None,
            "estimated_price_min": int(float(amount_match.group(1)) * 100_000_000) if amount_match else None,
            "organization_query": organization_match.group(1).strip() if organization_match else None,
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

    async def _resolve_organization(
        self,
        query: str,
        *,
        principal: PolicyPrincipal | None = None,
    ) -> dict[str, str]:
        resolved_principal = principal or PolicyPrincipal(actor="anonymous")
        response = await self.runtime_client.execute(
            "search_public_organizations",
            {"query": query, "sort": "name_asc", "page": 1, "page_size": 100},
            actor=resolved_principal.actor,
            roles=resolved_principal.roles,
            service=resolved_principal.service,
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
    def _parse_contract_amount_question(question: str, *, as_of: date, max_period_years: int = 20) -> dict[str, Any]:
        if "계약금액" not in question:
            raise ValueError("only Contract.amount questions are supported in this vertical slice")
        years_match = re.search(r"최근\s*(\d+)\s*(?:개\s*회계)?년", question)
        if years_match is None:
            raise ValueError("a recent fiscal-year period is required")
        years = int(years_match.group(1))
        if not 1 <= years <= max_period_years:
            raise ValueError(f"period_years must be between 1 and {max_period_years}")
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
                    updated_at = table.get("updatedAt")
                    if isinstance(updated_at, (int, float)):
                        updated_at = datetime.fromtimestamp(updated_at / 1000, tz=timezone.utc).isoformat()
                    item["table_updated_at"] = updated_at
                    item["quality"] = {
                        "status": "available" if table.get("testSuite") else "unavailable",
                        "test_suite": table.get("testSuite"),
                    }
                except OpenMetadataError as exc:
                    item["available"] = False
                    warnings.append(exc.code)
            items.append(item)
        return items, sorted(set(warnings))
