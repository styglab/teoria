from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date
from typing import Any

from teoria.persistence.postgres import connect
from psycopg.rows import dict_row

from teoria.domains.public_procurement.market_analysis.bid_context.sql import (
    _BID_CONTEXT_COMPETITION_QUERY,
    _BID_CONTEXT_PEER_COMPETITION_QUERY,
    _BID_CONTEXT_PEER_CONTRACTS_QUERY,
    _BID_RELATIONSHIP_NOTICE_QUERY,
    _BID_RELATIONSHIP_PARTICIPANTS_QUERY,
)
from teoria.domains.public_procurement.market_analysis.classification import (
    _enrich_procurement_classification,
)
from teoria.domains.public_procurement.market_analysis.profiles.models import (
    ProfileActivityRow,
    profile_activity_row,
)
from teoria.domains.public_procurement.market_analysis.profiles.sql import (
    _ORGANIZATION_COMPANY_FIRST_AWARD_OR_CONTRACT_QUERY,
    _PROCUREMENT_PROFILE_ACTIVITIES_QUERY,
    _PROCUREMENT_PROFILE_NOTICES_QUERY,
)
from teoria.registry.loader import RegistryCatalog


class ProcurementProfileReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    async def activities(
        self,
        catalog: RegistryCatalog,
        *,
        organization_code: str | None,
        company_numbers: list[str],
        period_from: date,
        period_to: date,
    ) -> list[ProfileActivityRow]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        async with connect(database_url, row_factory=dict_row) as connection:
            rows = [
                dict(row)
                for row in (
                    await (
                        await connection.execute(
                            _PROCUREMENT_PROFILE_ACTIVITIES_QUERY,
                            {
                                "organization_code": organization_code,
                                "company_numbers": company_numbers,
                                "period_from": period_from,
                                "period_to": period_to,
                            },
                        )
                    ).fetchall()
                )
            ]
            await _enrich_procurement_classification(connection, rows)
            return [profile_activity_row(row) for row in rows]

    async def notice_publications(
        self,
        catalog: RegistryCatalog,
        *,
        organization_code: str,
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
                            _PROCUREMENT_PROFILE_NOTICES_QUERY,
                            {
                                "organization_code": organization_code,
                                "period_from": period_from,
                                "period_to": period_to,
                            },
                        )
                    ).fetchall()
                )
            ]

    async def organization_award_history(
        self,
        catalog: RegistryCatalog,
        *,
        organization_code: str,
        history_from: date,
        history_to: date,
        work_type: str | None = None,
        large_category: str | None = None,
        middle_category: str | None = None,
        field_code: str | None = None,
    ) -> tuple[dict[str, date], date | None]:
        """Return first filtered contract dates in the history and target windows."""
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        async with connect(database_url, row_factory=dict_row) as connection:
            rows = await (
                await connection.execute(
                    _ORGANIZATION_COMPANY_FIRST_AWARD_OR_CONTRACT_QUERY,
                    {
                        "organization_code": organization_code,
                        "history_from": history_from,
                        "history_to": history_to,
                        "work_type": work_type,
                        "large_category": large_category,
                        "middle_category": middle_category,
                        "field_code": field_code,
                    },
                )
            ).fetchall()
        first_dates = {
            str(row["company_number"]): row["first_activity_date"]
            for row in rows
            if row.get("company_number") and row.get("first_activity_date")
        }
        return first_dates, history_from

    async def bid_context(
        self,
        catalog: RegistryCatalog,
        *,
        bid_notice_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        notice_number, separator, notice_order = bid_notice_id.rpartition(":")
        if not separator:
            raise ValueError(f"invalid bid notice id '{bid_notice_id}'")
        async with connect(database_url, row_factory=dict_row) as connection:
            notice = await (
                await connection.execute(
                    _BID_RELATIONSHIP_NOTICE_QUERY,
                    {"notice_number": notice_number, "notice_order": notice_order},
                )
            ).fetchone()
            if notice is None:
                raise LookupError(f"bid notice '{bid_notice_id}' was not found")
            participants = await (
                await connection.execute(
                    _BID_RELATIONSHIP_PARTICIPANTS_QUERY,
                    {"notice_number": notice_number, "notice_order": notice_order},
                )
            ).fetchall()
        return dict(notice), [dict(row) for row in participants]

    async def bid_competition(
        self,
        catalog: RegistryCatalog,
        *,
        organization_code: str,
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
                            _BID_CONTEXT_COMPETITION_QUERY,
                            {
                                "organization_code": organization_code,
                                "period_from": period_from,
                                "period_to": period_to,
                            },
                        )
                    ).fetchall()
                )
            ]

    async def peer_field_market(
        self,
        catalog: RegistryCatalog,
        *,
        period_from: date,
        period_to: date,
        history_from: date,
        work_type: str,
        large_category: str | None,
        middle_category: str | None,
        field_code: str | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Load official-field contract/company events and competition in two set queries."""
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        parameters = {
            "period_from": period_from,
            "period_to": period_to,
            "history_from": history_from,
            "work_type": work_type,
            "large_category": large_category,
            "middle_category": middle_category,
            "field_code": field_code,
        }
        async with connect(database_url, row_factory=dict_row) as connection:
            contracts = [
                dict(row)
                for row in (
                    await (
                        await connection.execute(
                            _BID_CONTEXT_PEER_CONTRACTS_QUERY,
                            parameters,
                        )
                    ).fetchall()
                )
            ]
            competition = [
                dict(row)
                for row in (
                    await (
                        await connection.execute(
                            _BID_CONTEXT_PEER_COMPETITION_QUERY,
                            parameters,
                        )
                    ).fetchall()
                )
            ]
        return contracts, competition

    async def peer_field_contracts(
        self, catalog: RegistryCatalog, **parameters: Any
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
                            _BID_CONTEXT_PEER_CONTRACTS_QUERY,
                            parameters,
                        )
                    ).fetchall()
                )
            ]
