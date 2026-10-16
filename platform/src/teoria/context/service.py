from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from dataclasses import dataclass

from teoria.context.query import ContextQueryHandler
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
    """Resolve governed context and policy-check domain query plans and execution."""

    def __init__(
        self,
        repository: ContextRepository,
        metadata_client: OpenMetadataClient | None,
        runtime_client: ContextRuntimeClient | None = None,
        policy: ContextExecutionPolicy | None = None,
        policy_evaluator: PolicyEvaluator | None = None,
        *,
        query_handler: ContextQueryHandler | None = None,
    ) -> None:
        self.repository = repository
        self.metadata_client = metadata_client
        self.runtime_client = runtime_client
        self.policy = policy or ContextExecutionPolicy()
        self.policy_evaluator = policy_evaluator or DisabledPolicyEvaluator()

        if query_handler is None:
            from teoria.context.composition import create_query_handler

            query_handler = create_query_handler(
                self.resolve, runtime_client, self.policy
            )
        self.query_handler = query_handler

    async def resolve(
        self, term: str, *, purpose: str | None = None
    ) -> dict[str, Any] | None:
        resolved = await self.repository.resolve_property(term)
        if resolved is None:
            return None
        metadata_bindings = [
            item
            for item in resolved["bindings"]
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
            for item in resolved["bindings"]
            if item["target_type"] == "api_field"
        ]
        capability_bindings = [
            item
            for item in resolved["bindings"] + resolved["object_capabilities"]
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
        selected_route = (
            self._select_route(capabilities, purpose=purpose) if purpose else None
        )
        metadata, warnings = await self._metadata(metadata_bindings)
        if not api_fields and not metadata_bindings:
            warnings.append("no_approved_api_field_binding")
        metadata_update_values = [
            item["table_updated_at"]
            for item in metadata
            if item.get("table_updated_at")
        ]
        result = {
            "query": term,
            "concept": {
                "stable_key": resolved["stable_key"],
                "name": resolved["name"],
                "description": resolved["description"],
                "value_type": resolved["value_type"],
                "unit": resolved["unit"],
                "business_object": {
                    "stable_key": f"{resolved['namespace']}.{resolved['object_code']}",
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
            "metadata_updated_at": max(metadata_update_values)
            if metadata_update_values
            else None,
            "data_freshness": None,
            "data_freshness_status": "unavailable",
            "warnings": warnings
            + ([] if capabilities else ["no_approved_capability_binding"]),
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
        resource = self.query_handler.describe(question)
        decision = await self.policy_evaluator.decide(
            principal=principal,
            action="context.plan",
            resource=resource,
            context={"as_of": resolved_as_of.isoformat(), "question": question},
        )
        if not decision.allow:
            raise PolicyDeniedError(decision)
        plan = await self.query_handler.plan(
            question,
            as_of=resolved_as_of,
            principal=principal,
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
            question,
            as_of=as_of,
            actor=actor,
            roles=roles,
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
        return await self.query_handler.execute(plan, principal, decision)

    @staticmethod
    def _select_route(
        capabilities: list[dict[str, Any]], *, purpose: str
    ) -> dict[str, Any] | None:
        candidates = [item for item in capabilities if item.get("purpose") == purpose]
        if not candidates:
            return None
        selected = min(
            candidates, key=lambda item: (item["priority"], item["capability_id"])
        )
        return {
            **selected,
            "selection_reason": f"approved_{purpose}_binding_with_lowest_priority",
        }

    async def _metadata(
        self, bindings: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
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
            if (
                self.metadata_client
                and binding["entity_type"] == "column"
                and binding["fully_qualified_name"]
            ):
                table_fqn = binding["fully_qualified_name"].rsplit(".", 1)[0]
                try:
                    table = await self.metadata_client.get_table_by_name(table_fqn)
                    item["table_description"] = table.get("description")
                    updated_at = table.get("updatedAt")
                    if isinstance(updated_at, (int, float)):
                        updated_at = datetime.fromtimestamp(
                            updated_at / 1000, tz=timezone.utc
                        ).isoformat()
                    item["table_updated_at"] = updated_at
                    item["quality"] = {
                        "status": "available"
                        if table.get("testSuite")
                        else "unavailable",
                        "test_suite": table.get("testSuite"),
                    }
                except OpenMetadataError as exc:
                    item["available"] = False
                    warnings.append(exc.code)
            items.append(item)
        return items, sorted(set(warnings))
