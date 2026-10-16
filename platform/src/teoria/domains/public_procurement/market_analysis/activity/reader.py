from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date
from typing import Any

from teoria.persistence.postgres import connect
from psycopg.rows import dict_row

from teoria.domains.public_procurement.market_analysis.activity.sql import (
    _PROCUREMENT_ACTIVITY_COMPANY_PARTICIPATION_QUERY,
    _PROCUREMENT_ACTIVITY_CONTRACTS_QUERY,
    _PROCUREMENT_ACTIVITY_NOTICES_QUERY,
)
from teoria.domains.public_procurement.market_analysis.classification import (
    _enrich_procurement_classification,
)
from teoria.domains.public_procurement.market_analysis.outcomes.sql import (
    _PROCUREMENT_OUTCOME_AWARDS_QUERY,
)
from teoria.registry.loader import RegistryCatalog


class ProcurementActivityReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    async def find(
        self,
        catalog: RegistryCatalog,
        *,
        organization_code: str,
        period_from: date,
        period_to: date,
        company_number: str | None,
    ) -> tuple[
        list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], set[str]
    ]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        params = {
            "organization_code": organization_code,
            "period_from": period_from,
            "period_to": period_to,
        }
        async with connect(database_url, row_factory=dict_row) as connection:
            notices = [
                dict(row)
                for row in (
                    await (
                        await connection.execute(
                            _PROCUREMENT_ACTIVITY_NOTICES_QUERY,
                            params,
                        )
                    ).fetchall()
                )
            ]
            awards = [
                dict(row)
                for row in (
                    await (
                        await connection.execute(
                            _PROCUREMENT_OUTCOME_AWARDS_QUERY,
                            params,
                        )
                    ).fetchall()
                )
            ]
            contracts = [
                dict(row)
                for row in (
                    await (
                        await connection.execute(
                            _PROCUREMENT_ACTIVITY_CONTRACTS_QUERY,
                            params,
                        )
                    ).fetchall()
                )
            ]
            await _enrich_procurement_classification(connection, contracts)
            participated_notice_ids: set[str] = set()
            if company_number:
                participated_notice_ids = {
                    str(row["bid_notice_id"])
                    for row in (
                        await (
                            await connection.execute(
                                _PROCUREMENT_ACTIVITY_COMPANY_PARTICIPATION_QUERY,
                                {**params, "company_number": company_number},
                            )
                        ).fetchall()
                    )
                }
        return notices, awards, contracts, participated_notice_ids
