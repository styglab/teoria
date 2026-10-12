from __future__ import annotations

from collections.abc import Mapping

from datetime import date

import os

from typing import Any

import psycopg

from psycopg.rows import dict_row

from teoria.registry.loader import RegistryCatalog

from ..sql import (
    _PROCUREMENT_OUTCOME_AWARDS_QUERY,
    _PROCUREMENT_OUTCOME_CONTRACTS_QUERY,
)


class ProcurementOutcomeReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def find(
        self, catalog: RegistryCatalog, *, organization_code: str,
        period_from: date, period_to: date,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            awards = [dict(row) for row in connection.execute(
                _PROCUREMENT_OUTCOME_AWARDS_QUERY,
                {
                    "organization_code": organization_code,
                    "period_from": period_from, "period_to": period_to,
                },
            ).fetchall()]
            contracts = [dict(row) for row in connection.execute(
                _PROCUREMENT_OUTCOME_CONTRACTS_QUERY,
                {
                    "organization_code": organization_code,
                    "period_from": period_from, "period_to": period_to,
                },
            ).fetchall()]
        return awards, contracts
