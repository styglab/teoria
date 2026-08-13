from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from teoria.registry.loader import RegistryCatalog


class DatabaseSourceExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabaseQueryResult:
    rows: list[dict[str, Any]]
    pagination: dict[str, int] | None = None


class DatabaseSourceExecutor:
    OPERATORS = {"eq": sql.SQL("="), "gte": sql.SQL(">="), "lte": sql.SQL("<=")}

    def __init__(self, environment: Mapping[str, str] | None = None, *, max_rows: int = 1000) -> None:
        if max_rows < 1:
            raise ValueError("max_rows must be at least one")
        self.environment = environment if environment is not None else os.environ
        self.max_rows = max_rows

    def execute(
        self,
        catalog: RegistryCatalog,
        source_id: str,
        relation_id: str,
        query: dict[str, Any],
    ) -> DatabaseQueryResult:
        source = catalog.sources[source_id].source
        if source.type != "database":
            raise DatabaseSourceExecutionError(f"source '{source_id}' is not a database source")
        relation = next((item for item in source.relations if item.id == relation_id), None)
        if relation is None:
            raise DatabaseSourceExecutionError(
                f"unknown relation '{relation_id}' on source '{source_id}'"
            )
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise DatabaseSourceExecutionError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )

        known_fields = {item.id for item in relation.fields}
        conditions = []
        parameters = []
        for item in query.get("filters", []):
            field = item["field"]
            operator = item.get("operator", "eq")
            if field not in known_fields:
                raise DatabaseSourceExecutionError(
                    f"field '{field}' is not declared on relation '{relation_id}'"
                )
            if operator not in self.OPERATORS:
                raise DatabaseSourceExecutionError(f"unsupported database operator '{operator}'")
            conditions.append(
                sql.SQL("{} {} %s").format(sql.Identifier(field), self.OPERATORS[operator])
            )
            parameters.append(item["value"])

        search = query.get("search")
        if search:
            search_fields = search["fields"]
            unknown_search_fields = set(search_fields) - known_fields
            if unknown_search_fields:
                raise DatabaseSourceExecutionError(
                    f"search fields are not declared on relation '{relation_id}': "
                    f"{sorted(unknown_search_fields)}"
                )
            escaped = str(search["value"]).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(sql.SQL("(") + sql.SQL(" OR ").join(
                sql.SQL("{} ILIKE %s ESCAPE %s").format(sql.Identifier(field))
                for field in search_fields
            ) + sql.SQL(")"))
            for _ in search_fields:
                parameters.extend([f"%{escaped}%", "\\"])

        schema_name, table_name = relation.relation.split(".", 1)
        statement = sql.SQL("SELECT {} FROM {}.{}").format(
            sql.SQL(", ").join(sql.Identifier(item.id) for item in relation.fields),
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
        )
        if conditions:
            statement += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
        order_by = query.get("order_by") or [
            {"field": item, "direction": "asc", "nulls": None}
            for item in relation.primary_key
        ]
        unknown_order_fields = {item["field"] for item in order_by} - known_fields
        if unknown_order_fields:
            raise DatabaseSourceExecutionError(
                f"sort fields are not declared on relation '{relation_id}': {sorted(unknown_order_fields)}"
            )
        order_parts = []
        for item in order_by:
            direction = item["direction"]
            nulls = item.get("nulls")
            if direction not in {"asc", "desc"} or nulls not in {None, "first", "last"}:
                raise DatabaseSourceExecutionError("invalid database sort definition")
            part = sql.SQL("{} {}").format(sql.Identifier(item["field"]), sql.SQL(direction.upper()))
            if nulls:
                part += sql.SQL(" NULLS ") + sql.SQL(nulls.upper())
            order_parts.append(part)
        statement += sql.SQL(" ORDER BY ") + sql.SQL(", ").join(order_parts)

        pagination = query.get("pagination")
        count_statement = None
        if pagination:
            root_field = pagination["root_field"]
            if root_field not in known_fields:
                raise DatabaseSourceExecutionError(
                    f"pagination root field '{root_field}' is not declared on relation '{relation_id}'"
                )
            page = int(pagination["page"])
            page_size = int(pagination["page_size"])
            count_statement = sql.SQL("SELECT COUNT(DISTINCT {}) FROM {}.{}").format(
                sql.Identifier(root_field), sql.Identifier(schema_name), sql.Identifier(table_name)
            )
            if conditions:
                count_statement += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
            statement += sql.SQL(" LIMIT %s OFFSET %s")
            row_parameters = [*parameters, page_size, (page - 1) * page_size]
        else:
            statement += sql.SQL(" LIMIT %s")
            row_parameters = [*parameters, self.max_rows]

        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            if count_statement is not None:
                count_row = connection.execute(count_statement, parameters).fetchone()
                count_value = next(iter(count_row.values())) if isinstance(count_row, Mapping) else count_row[0]
                total_items = int(count_value)
                rows = list(connection.execute(statement, row_parameters).fetchall())
                total_pages = (total_items + page_size - 1) // page_size
                return DatabaseQueryResult(rows, {
                    "page": page,
                    "page_size": page_size,
                    "total_items": total_items,
                    "total_pages": total_pages,
                })
            return DatabaseQueryResult(
                list(connection.execute(statement, row_parameters).fetchall())
            )
