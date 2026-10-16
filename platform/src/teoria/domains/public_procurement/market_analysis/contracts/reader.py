from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from teoria.persistence.postgres import connect
from psycopg.rows import dict_row

from teoria.domains.public_procurement.market_analysis.contracts.sql import (
    _CONTRACT_SUPPLIERS_BATCH_QUERY,
)
from teoria.registry.loader import RegistryCatalog


class ContractSupplierBatchReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    async def find(
        self,
        catalog: RegistryCatalog,
        *,
        unified_contract_numbers: list[str],
    ) -> list[dict[str, Any]]:
        if not unified_contract_numbers:
            return []
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        async with connect(database_url, row_factory=dict_row) as connection:
            return [
                dict(row)
                for row in (
                    await (
                        await connection.execute(
                            _CONTRACT_SUPPLIERS_BATCH_QUERY,
                            {"unified_contract_numbers": unified_contract_numbers},
                        )
                    ).fetchall()
                )
            ]
