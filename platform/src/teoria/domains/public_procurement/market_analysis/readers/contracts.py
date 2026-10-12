from __future__ import annotations

from collections.abc import Mapping

import os

from typing import Any

import psycopg

from psycopg.rows import dict_row

from teoria.registry.loader import RegistryCatalog

from ..sql import (
    _CONTRACT_SUPPLIERS_BATCH_QUERY,
)


class ContractSupplierBatchReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def find(
        self, catalog: RegistryCatalog, *, unified_contract_numbers: list[str],
    ) -> list[dict[str, Any]]:
        if not unified_contract_numbers:
            return []
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            return [dict(row) for row in connection.execute(
                _CONTRACT_SUPPLIERS_BATCH_QUERY,
                {"unified_contract_numbers": unified_contract_numbers},
            ).fetchall()]
