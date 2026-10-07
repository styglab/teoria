from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.runner import CapabilityExecutionError, CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.provenance import Provenance


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    decimal_value = Decimal(str(value))
    return (
        int(decimal_value)
        if decimal_value == decimal_value.to_integral_value()
        else float(decimal_value)
    )


def _encode_cursor(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(encoded).decode().rstrip("=")


def _decode_cursor(value: str, *, capability_id: str) -> dict[str, Any]:
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(payload, dict):
            raise ValueError
        return payload
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CapabilityExecutionError(
            "invalid_cursor", "cursor is not a valid relationship graph cursor",
            capability_id=capability_id,
        ) from exc


def _canonical_graph_version(value: Any, *, capability_id: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
    except ValueError as exc:
        raise CapabilityExecutionError(
            "invalid_graph_version", "graph_version must be an ISO 8601 timestamp",
            capability_id=capability_id,
        ) from exc
    return parsed.astimezone(timezone.utc).isoformat()


class ProcurementRelationshipGraphReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def _database_url(self, catalog: RegistryCatalog) -> str:
        source = catalog.sources["teoria_public_procurement"].source
        value = self.environment.get(source.access.connection_env)
        if not value:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        return value

    @staticmethod
    def _resolve_version(connection: Any, graph_version: str | None) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM public_procurement.procurement_relationship_graph_versions "
            "WHERE status='published' AND (%s::timestamptz IS NULL OR graph_version=%s) "
            "ORDER BY graph_version DESC LIMIT 1",
            (graph_version, graph_version),
        ).fetchone()
        if row is None:
            raise LookupError("published procurement relationship graph version was not found")
        return dict(row)

    def overview(
        self, catalog: RegistryCatalog, *, graph_version: str | None,
        period_from_year: int, period_to_year: int, group_by: str,
        work_type: str | None, large_category: str | None,
        middle_category: str | None, field_code: str | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        parameters = {
            "period_from_year": period_from_year,
            "period_to_year": period_to_year,
            "work_type": work_type,
            "large_category": large_category,
            "middle_category": middle_category,
            "field_code": field_code,
        }
        with psycopg.connect(self._database_url(catalog), row_factory=dict_row) as connection:
            version = self._resolve_version(connection, graph_version)
            parameters["graph_version"] = version["graph_version"]
            if not any((work_type, large_category, middle_category, field_code)):
                clusters = [dict(row) for row in connection.execute("""
                    SELECT cluster_id,work_type,field_code,field_name,
                           large_category,middle_category,organization_count,
                           company_count,link_count,contract_count,
                           total_attributed_contract_amount
                    FROM public_procurement.procurement_relationship_graph_overviews
                    WHERE graph_version=%(graph_version)s
                      AND period_from_year=%(period_from_year)s
                      AND period_to_year=%(period_to_year)s
                      AND group_by=%(group_by)s
                    ORDER BY total_attributed_contract_amount DESC NULLS LAST,
                             cluster_id
                """, {**parameters, "group_by": group_by}).fetchall()]
                totals_row = connection.execute("""
                    SELECT organization_count,company_count,link_count
                    FROM public_procurement.procurement_relationship_graph_overviews
                    WHERE graph_version=%(graph_version)s
                      AND period_from_year=%(period_from_year)s
                      AND period_to_year=%(period_to_year)s
                      AND group_by='total' AND cluster_id='*'
                """, parameters).fetchone()
                if clusters and totals_row is not None:
                    return version, clusters, dict(totals_row)
            grouping = (
                "aggregate.work_type" if group_by == "work_type"
                else "aggregate.cluster_id"
            )
            clusters = [dict(row) for row in connection.execute(f"""
                WITH filtered AS MATERIALIZED (
                    SELECT {grouping} AS group_key,aggregate.work_type,
                           aggregate.field_code,aggregate.field_name,
                           aggregate.large_category,aggregate.middle_category,
                           aggregate.organization_code,aggregate.company_number,
                           aggregate.contract_count,
                           aggregate.total_attributed_contract_amount
                    FROM public_procurement.procurement_relationship_graph_aggregates aggregate
                    WHERE aggregate.graph_version=%(graph_version)s
                      AND aggregate.contract_year
                          BETWEEN %(period_from_year)s AND %(period_to_year)s
                      AND (%(work_type)s::text IS NULL OR aggregate.work_type=%(work_type)s)
                      AND (%(large_category)s::text IS NULL
                           OR aggregate.large_category=%(large_category)s)
                      AND (%(middle_category)s::text IS NULL
                           OR aggregate.middle_category=%(middle_category)s)
                      AND (%(field_code)s::text IS NULL OR aggregate.field_code=%(field_code)s)
                ), metrics AS (
                    SELECT group_key AS cluster_id,max(work_type) AS work_type,
                           CASE WHEN %(group_by)s='field' THEN max(field_code) END AS field_code,
                           CASE WHEN %(group_by)s='field' THEN max(field_name) END AS field_name,
                           max(large_category) AS large_category,
                           max(middle_category) AS middle_category,
                           sum(contract_count) AS contract_count,
                           sum(total_attributed_contract_amount)
                             AS total_attributed_contract_amount
                    FROM filtered GROUP BY group_key
                ), organizations AS (
                    SELECT group_key AS cluster_id,count(*) AS organization_count
                    FROM (SELECT group_key,organization_code FROM filtered
                          GROUP BY group_key,organization_code) grouped
                    GROUP BY group_key
                ), companies AS (
                    SELECT group_key AS cluster_id,count(*) AS company_count
                    FROM (SELECT group_key,company_number FROM filtered
                          GROUP BY group_key,company_number) grouped
                    GROUP BY group_key
                ), links AS (
                    SELECT group_key AS cluster_id,count(*) AS link_count
                    FROM (SELECT group_key,organization_code,company_number FROM filtered
                          GROUP BY group_key,organization_code,company_number) grouped
                    GROUP BY group_key
                )
                SELECT metrics.*,organizations.organization_count,
                       companies.company_count,links.link_count
                FROM metrics JOIN organizations USING (cluster_id)
                JOIN companies USING (cluster_id) JOIN links USING (cluster_id)
                ORDER BY total_attributed_contract_amount DESC NULLS LAST,cluster_id
            """, {**parameters, "group_by": group_by}).fetchall()]
            totals = dict(connection.execute("""
                WITH filtered AS MATERIALIZED (
                    SELECT organization_code,company_number
                    FROM public_procurement.procurement_relationship_graph_aggregates aggregate
                    WHERE aggregate.graph_version=%(graph_version)s
                      AND aggregate.contract_year
                          BETWEEN %(period_from_year)s AND %(period_to_year)s
                      AND (%(work_type)s::text IS NULL OR aggregate.work_type=%(work_type)s)
                      AND (%(large_category)s::text IS NULL
                           OR aggregate.large_category=%(large_category)s)
                      AND (%(middle_category)s::text IS NULL
                           OR aggregate.middle_category=%(middle_category)s)
                      AND (%(field_code)s::text IS NULL OR aggregate.field_code=%(field_code)s)
                )
                SELECT
                  (SELECT count(*) FROM (
                     SELECT organization_code FROM filtered GROUP BY organization_code
                   ) grouped) AS organization_count,
                  (SELECT count(*) FROM (
                     SELECT company_number FROM filtered GROUP BY company_number
                   ) grouped) AS company_count,
                  (SELECT count(*) FROM (
                     SELECT organization_code,company_number FROM filtered
                     GROUP BY organization_code,company_number
                   ) grouped) AS link_count
            """, parameters).fetchone())
        return version, clusters, totals

    def entities(
        self, catalog: RegistryCatalog, *, graph_version: str,
        cluster_id: str, period_from_year: int, period_to_year: int,
        after_company_number: str | None, page_size: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], bool]:
        parameters = {
            "graph_version": graph_version,
            "cluster_id": cluster_id,
            "period_from_year": period_from_year,
            "period_to_year": period_to_year,
            "after_company_number": after_company_number,
            "page_size": page_size + 1,
        }
        with psycopg.connect(self._database_url(catalog), row_factory=dict_row) as connection:
            version = self._resolve_version(connection, graph_version)
            parameters["graph_version"] = version["graph_version"]
            totals = dict(connection.execute("""
                SELECT count(DISTINCT organization_code) AS organization_count,
                       count(DISTINCT company_number) AS company_count,
                       count(DISTINCT (organization_code,company_number)) AS link_count
                FROM public_procurement.procurement_relationship_graph_aggregates
                WHERE graph_version=%(graph_version)s AND cluster_id=%(cluster_id)s
                  AND contract_year BETWEEN %(period_from_year)s AND %(period_to_year)s
            """, parameters).fetchone())
            companies = [dict(row) for row in connection.execute("""
                SELECT node_id AS business_registration_number,
                       max(node_name) AS company_name,
                       sum(contract_count) AS contract_count,
                       sum(total_attributed_contract_amount) AS total_attributed_contract_amount,
                       sum(known_amount_count) AS known_amount_count,
                       min(first_contract_date) AS first_contract_date,
                       max(latest_contract_date) AS latest_contract_date,
                       CASE WHEN bool_and(amount_completeness='complete') THEN 'complete'
                            WHEN bool_and(amount_completeness='unknown') THEN 'unknown'
                            ELSE 'partial' END AS amount_completeness
                FROM public_procurement.procurement_relationship_graph_nodes
                WHERE graph_version=%(graph_version)s AND cluster_id=%(cluster_id)s
                  AND node_type='company'
                  AND contract_year BETWEEN %(period_from_year)s AND %(period_to_year)s
                  AND (%(after_company_number)s::text IS NULL
                       OR node_id>%(after_company_number)s)
                GROUP BY node_id ORDER BY node_id LIMIT %(page_size)s
            """, parameters).fetchall()]
            has_more = len(companies) > page_size
            companies = companies[:page_size]
            company_numbers = [
                str(item["business_registration_number"]) for item in companies
            ]
            if not company_numbers:
                return version, [], [], totals, False
            link_parameters = {**parameters, "company_numbers": company_numbers}
            links = [dict(row) for row in connection.execute("""
                WITH metrics AS (
                    SELECT organization_code,max(organization_name) AS organization_name,
                           company_number,max(company_name) AS company_name,
                           sum(contract_count) AS contract_count,
                           sum(total_attributed_contract_amount)
                             AS total_attributed_contract_amount,
                           sum(known_attributed_amount_count) AS known_amount_count,
                           min(first_contract_date) AS first_contract_date,
                           max(latest_contract_date) AS latest_contract_date,
                           CASE WHEN bool_and(amount_completeness='complete') THEN 'complete'
                                WHEN bool_and(amount_completeness='unknown') THEN 'unknown'
                                ELSE 'partial' END AS amount_completeness
                    FROM public_procurement.procurement_relationship_graph_aggregates
                    WHERE graph_version=%(graph_version)s AND cluster_id=%(cluster_id)s
                      AND contract_year BETWEEN %(period_from_year)s AND %(period_to_year)s
                      AND company_number=ANY(%(company_numbers)s::text[])
                    GROUP BY organization_code,company_number
                ), roles AS (
                    SELECT organization_code,company_number,array_agg(DISTINCT role ORDER BY role)
                             AS company_roles
                    FROM public_procurement.procurement_relationship_graph_aggregates aggregate
                    CROSS JOIN LATERAL unnest(aggregate.company_roles) role
                    WHERE graph_version=%(graph_version)s AND cluster_id=%(cluster_id)s
                      AND contract_year BETWEEN %(period_from_year)s AND %(period_to_year)s
                      AND company_number=ANY(%(company_numbers)s::text[])
                    GROUP BY organization_code,company_number
                )
                SELECT metrics.*,roles.company_roles
                FROM metrics JOIN roles USING (organization_code,company_number)
                ORDER BY company_number,organization_code
            """, link_parameters).fetchall()]
            organization_ids = sorted({str(item["organization_code"]) for item in links})
            organizations = [dict(row) for row in connection.execute("""
                WITH metrics AS (
                    SELECT node_id AS organization_code,
                           max(node_name) AS organization_name,
                           sum(contract_count) AS contract_count,
                           sum(total_contract_amount) AS total_contract_amount,
                           sum(known_amount_count) AS known_amount_count,
                           min(first_contract_date) AS first_contract_date,
                           max(latest_contract_date) AS latest_contract_date,
                           CASE WHEN bool_and(amount_completeness='complete') THEN 'complete'
                                WHEN bool_and(amount_completeness='unknown') THEN 'unknown'
                                ELSE 'partial' END AS amount_completeness
                    FROM public_procurement.procurement_relationship_graph_nodes
                    WHERE graph_version=%(graph_version)s AND cluster_id=%(cluster_id)s
                      AND node_type='organization'
                      AND contract_year BETWEEN %(period_from_year)s AND %(period_to_year)s
                      AND node_id=ANY(%(organization_ids)s::text[])
                    GROUP BY node_id
                ), relationship_counts AS (
                    SELECT organization_code,count(*) AS connected_company_count
                    FROM (
                        SELECT organization_code,company_number
                        FROM public_procurement.procurement_relationship_graph_aggregates
                        WHERE graph_version=%(graph_version)s AND cluster_id=%(cluster_id)s
                          AND contract_year
                              BETWEEN %(period_from_year)s AND %(period_to_year)s
                          AND organization_code=ANY(%(organization_ids)s::text[])
                        GROUP BY organization_code,company_number
                    ) grouped GROUP BY organization_code
                )
                SELECT metrics.*,relationship_counts.connected_company_count
                FROM metrics JOIN relationship_counts USING (organization_code)
                ORDER BY organization_code
            """, {**parameters, "organization_ids": organization_ids}).fetchall()]
        connected_organizations: dict[str, int] = {}
        for link in links:
            company_number = str(link["company_number"])
            connected_organizations[company_number] = (
                connected_organizations.get(company_number, 0) + 1
            )
        nodes = [
            {
                "id": f"company:{item['business_registration_number']}",
                "type": "procurement_supplier",
                "connected_organization_count": connected_organizations.get(
                    str(item["business_registration_number"]), 0
                ),
                **item,
            }
            for item in companies
        ] + [
            {"id": f"organization:{item['organization_code']}",
             "type": "public_organization", **item}
            for item in organizations
        ]
        return version, nodes, links, totals, has_more


def _result_object(
    capability_id: str, object_type: str, object_id: str,
    properties: dict[str, Any], *, observed_at: datetime,
) -> MaterializedObject:
    provenance = Provenance(
        kind="execution", source="teoria_runtime",
        operation=f"market_context.{capability_id}",
        mapping="public_procurement_relationship_graph_snapshot",
        observed_at=observed_at, record_keys=[object_id],
    )
    return MaterializedObject(
        ontology="public_procurement", object_type=object_type,
        object_id=object_id, properties=properties, provenance=[provenance],
        property_provenance={key: [provenance] for key in properties},
    )


def _graph_completeness() -> dict[str, Any]:
    return {
        "status": "partial",
        "relationship_population": "classified_contract_relationship_graph_snapshot",
        "missing_reasons": ["unclassified_contracts_not_in_relationship_ledger"],
    }


async def execute_procurement_relationship_graph_summary(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: ProcurementRelationshipGraphReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    from_year = int(inputs["period_from_year"])
    to_year = int(inputs["period_to_year"])
    if from_year > to_year:
        raise CapabilityExecutionError(
            "invalid_period_range", "period_from_year must not exceed period_to_year",
            capability_id=capability_id,
        )
    group_by = str(inputs.get("group_by", "field"))
    if group_by not in {"field", "work_type"}:
        raise CapabilityExecutionError(
            "invalid_group_by", f"unsupported group_by '{group_by}'",
            capability_id=capability_id,
        )
    resolved_reader = reader or ProcurementRelationshipGraphReader()
    try:
        version, clusters, totals = await asyncio.to_thread(
            resolved_reader.overview, catalog,
            graph_version=inputs.get("graph_version"), period_from_year=from_year,
            period_to_year=to_year, group_by=group_by,
            work_type=inputs.get("work_type"), large_category=inputs.get("large_category"),
            middle_category=inputs.get("middle_category"), field_code=inputs.get("field_code"),
        )
    except (LookupError, RuntimeError, psycopg.Error) as exc:
        raise CapabilityExecutionError(
            "graph_snapshot_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc
    graph_version = version["graph_version"].isoformat()
    properties = {
        "procurement_relationship_graph_summary_id": graph_version,
        "graph_version": graph_version,
        "cluster_count": len(clusters),
    }
    return CapabilityResult(
        capability_id=capability_id,
        objects=[_result_object(
            capability_id, "procurement_relationship_graph_summary", graph_version,
            properties, observed_at=datetime.now(timezone.utc),
        )],
        outcome={
            "graph_version": graph_version,
            "total_nodes": int(totals.get("organization_count") or 0)
                           + int(totals.get("company_count") or 0),
            "total_links": int(totals.get("link_count") or 0),
            "returned_nodes": 0,
            "returned_links": 0,
            "next_cursor": None,
            "truncated": False,
            "group_by": group_by,
            "clusters": clusters,
            "analysis_basis": {"period_from_year": from_year, "period_to_year": to_year},
            "data_completeness": _graph_completeness(),
            "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
        },
    )


async def execute_procurement_relationship_graph_entities(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: ProcurementRelationshipGraphReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    graph_version = _canonical_graph_version(
        inputs["graph_version"], capability_id=capability_id,
    )
    cluster_id = str(inputs["cluster_id"])
    from_year = int(inputs["period_from_year"])
    to_year = int(inputs["period_to_year"])
    if from_year > to_year:
        raise CapabilityExecutionError(
            "invalid_period_range", "period_from_year must not exceed period_to_year",
            capability_id=capability_id,
        )
    page_size = int(inputs.get("page_size", 500))
    cursor = inputs.get("cursor")
    after_company = None
    if cursor:
        payload = _decode_cursor(str(cursor), capability_id=capability_id)
        expected = {
            "graph_version": graph_version, "cluster_id": cluster_id,
            "period_from_year": from_year, "period_to_year": to_year,
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise CapabilityExecutionError(
                "cursor_scope_mismatch",
                "cursor does not match graph_version, cluster, or period",
                capability_id=capability_id,
            )
        after_company = str(payload.get("after_company_number") or "") or None
    resolved_reader = reader or ProcurementRelationshipGraphReader()
    try:
        version, nodes, link_rows, totals, has_more = await asyncio.to_thread(
            resolved_reader.entities, catalog, graph_version=graph_version,
            cluster_id=cluster_id, period_from_year=from_year,
            period_to_year=to_year, after_company_number=after_company,
            page_size=page_size,
        )
    except (LookupError, RuntimeError, psycopg.Error) as exc:
        raise CapabilityExecutionError(
            "graph_snapshot_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc
    links = [{
        "id": f"organization:{row['organization_code']}-company:{row['company_number']}",
        "source": f"organization:{row['organization_code']}",
        "target": f"company:{row['company_number']}",
        "type": "organization_company_procurement",
        "properties": {
            "contract_count": int(row["contract_count"]),
            "total_attributed_contract_amount": _number(
                row.get("total_attributed_contract_amount")
            ),
            "known_amount_count": int(row["known_amount_count"]),
            "amount_completeness": row["amount_completeness"],
            "first_contract_date": row["first_contract_date"],
            "latest_contract_date": row["latest_contract_date"],
            "company_roles": row["company_roles"],
            "relationship_status": "confirmed",
        },
    } for row in link_rows]
    company_numbers = sorted(
        node["business_registration_number"]
        for node in nodes if node["type"] == "procurement_supplier"
    )
    next_cursor = None
    if has_more and company_numbers:
        next_cursor = _encode_cursor({
            "graph_version": graph_version, "cluster_id": cluster_id,
            "period_from_year": from_year, "period_to_year": to_year,
            "after_company_number": company_numbers[-1],
        })
    resolved_version = version["graph_version"].isoformat()
    properties = {
        "procurement_relationship_graph_entities_id": f"{resolved_version}:{cluster_id}",
        "graph_version": resolved_version,
        "cluster_id": cluster_id,
        "returned_node_count": len(nodes),
        "returned_link_count": len(links),
    }
    return CapabilityResult(
        capability_id=capability_id,
        objects=[_result_object(
            capability_id, "procurement_relationship_graph_entities",
            properties["procurement_relationship_graph_entities_id"], properties,
            observed_at=datetime.now(timezone.utc),
        )],
        outcome={
            "graph_version": resolved_version,
            "total_nodes": int(totals.get("organization_count") or 0)
                           + int(totals.get("company_count") or 0),
            "total_links": int(totals.get("link_count") or 0),
            "returned_nodes": len(nodes),
            "returned_links": len(links),
            "next_cursor": next_cursor,
            "truncated": has_more,
            "pagination_unit": "company_nodes",
            "nodes": nodes,
            "links": links,
            "analysis_basis": {
                "cluster_id": cluster_id,
                "period_from_year": from_year,
                "period_to_year": to_year,
            },
            "data_completeness": _graph_completeness(),
            "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
        },
    )
