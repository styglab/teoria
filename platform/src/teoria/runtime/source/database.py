from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from teoria.registry.loader import RegistryCatalog


class DatabaseSourceExecutionError(RuntimeError):
    pass


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
    ) -> list[dict[str, Any]]:
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

        schema_name, table_name = relation.relation.split(".", 1)
        statement = sql.SQL("SELECT {} FROM {}.{}").format(
            sql.SQL(", ").join(sql.Identifier(item.id) for item in relation.fields),
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
        )
        if conditions:
            statement += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
        statement += sql.SQL(" ORDER BY {} LIMIT %s").format(
            sql.SQL(", ").join(sql.Identifier(item) for item in relation.primary_key)
        )
        parameters.append(self.max_rows)

        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            return list(connection.execute(statement, parameters).fetchall())
