from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date
from typing import Any

from teoria.persistence.postgres import connect
from psycopg.rows import dict_row

from teoria.domains.public_procurement.market_analysis.outcomes.sql import (
    _PROCUREMENT_OUTCOME_AWARDS_QUERY,
    _PROCUREMENT_OUTCOME_CONTRACTS_QUERY,
)
from teoria.registry.loader import RegistryCatalog


class ProcurementOutcomeReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    async def find(
        self,
        catalog: RegistryCatalog,
        *,
        organization_code: str,
        period_from: date,
        period_to: date,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        async with connect(database_url, row_factory=dict_row) as connection:
            awards = [
                dict(row)
                for row in (
                    await (
                        await connection.execute(
                            _PROCUREMENT_OUTCOME_AWARDS_QUERY,
                            {
                                "organization_code": organization_code,
                                "period_from": period_from,
                                "period_to": period_to,
                            },
                        )
                    ).fetchall()
                )
            ]
            contracts = [
                dict(row)
                for row in (
                    await (
                        await connection.execute(
                            _PROCUREMENT_OUTCOME_CONTRACTS_QUERY,
                            {
                                "organization_code": organization_code,
                                "period_from": period_from,
                                "period_to": period_to,
                            },
                        )
                    ).fetchall()
                )
            ]
        return awards, contracts
