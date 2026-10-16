from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date
from typing import Any

from teoria.persistence.postgres import connect
from psycopg.rows import dict_row

from teoria.domains.public_procurement.market_analysis.participation.models import (
    ParticipationRow,
    participation_row,
)
from teoria.domains.public_procurement.market_analysis.participation.sql import (
    _BID_NOTICE_PARTICIPATIONS_QUERY,
    _COMPANY_COMPETITORS_QUERY,
    _COMPANY_PARTICIPATIONS_QUERY,
)
from teoria.registry.loader import RegistryCatalog


class CompanyParticipationReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    async def _read(
        self,
        catalog: RegistryCatalog,
        query: str,
        *,
        company_number: str,
        period_from: date,
        period_to: date,
    ) -> list[dict[str, Any]]:
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
                            query,
                            {
                                "company_number": company_number,
                                "period_from": period_from,
                                "period_to": period_to,
                            },
                        )
                    ).fetchall()
                )
            ]

    async def find(
        self, catalog: RegistryCatalog, **kwargs: Any
    ) -> list[ParticipationRow]:
        return [
            participation_row(row)
            for row in (
                await self._read(catalog, _COMPANY_PARTICIPATIONS_QUERY, **kwargs)
            )
        ]

    async def competitors(
        self, catalog: RegistryCatalog, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return await self._read(catalog, _COMPANY_COMPETITORS_QUERY, **kwargs)


class BidNoticeParticipationReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    async def find(
        self,
        catalog: RegistryCatalog,
        *,
        notice_number: str,
        notice_order: str,
    ) -> list[dict[str, Any]]:
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
                            _BID_NOTICE_PARTICIPATIONS_QUERY,
                            {
                                "notice_number": notice_number,
                                "notice_order": notice_order,
                            },
                        )
                    ).fetchall()
                )
            ]
