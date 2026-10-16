from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from teoria.persistence.postgres import connect
from psycopg.rows import dict_row

from teoria.domains.public_procurement.market_analysis.relationships.sql import (
    _ORGANIZATION_FIELD_EVENT_ROWS_QUERY,
)
from teoria.registry.loader import RegistryCatalog


class OrganizationFieldEventReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    async def find(
        self,
        catalog: RegistryCatalog,
        *,
        organization_code: str,
        work_type: str | None,
        as_of: datetime,
        large_category: str | None = None,
        middle_category: str | None = None,
        procurement_field_code: str | None = None,
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
                            _ORGANIZATION_FIELD_EVENT_ROWS_QUERY,
                            {
                                "organization_code": organization_code,
                                "work_type": work_type,
                                "large_category": large_category,
                                "middle_category": middle_category,
                                "procurement_field_code": procurement_field_code,
                                "as_of": as_of,
                            },
                        )
                    ).fetchall()
                )
            ]

    async def context(
        self,
        catalog: RegistryCatalog,
        *,
        organization_code: str,
        business_registration_number: str,
        reference_bid_notice_id: str | None,
    ) -> dict[str, Any]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        reference_number = reference_order = None
        if reference_bid_notice_id:
            reference_number, separator, reference_order = (
                reference_bid_notice_id.rpartition(":")
            )
            if not separator:
                raise ValueError(f"invalid bid notice id '{reference_bid_notice_id}'")
        async with connect(database_url, row_factory=dict_row) as connection:
            organization = await (
                await connection.execute(
                    "SELECT organization_code,organization_name FROM "
                    "public_procurement.public_organizations WHERE organization_code=%s",
                    (organization_code,),
                )
            ).fetchone()
            company = await (
                await connection.execute(
                    "SELECT %s::text AS business_registration_number,company_name FROM ("
                    "SELECT winner_name AS company_name,updated_at FROM public_procurement.bid_awards "
                    "WHERE winner_business_registration_number=%s UNION ALL "
                    "SELECT supplier_name,updated_at FROM public_procurement.contract_suppliers "
                    "WHERE business_registration_number=%s) names "
                    "WHERE company_name IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
                    (
                        business_registration_number,
                        business_registration_number,
                        business_registration_number,
                    ),
                )
            ).fetchone()
            reference = None
            if reference_number and reference_order:
                reference = await (
                    await connection.execute(
                        "SELECT notice_number||':'||notice_order AS bid_notice_id,notice_name,work_type,"
                        "estimated_price,allocated_budget,demand_organization_code,"
                        "demand_organization_name,LEAST(now(),COALESCE(bid_deadline_at,now())) AS as_of "
                        "FROM public_procurement.bid_notices WHERE notice_number=%s AND notice_order=%s",
                        (reference_number, reference_order),
                    )
                ).fetchone()
                if reference is None:
                    raise LookupError(
                        f"bid notice '{reference_bid_notice_id}' was not found"
                    )
                reference = dict(reference)
                reference["industry_codes"] = [
                    str(row["industry_code"])
                    for row in (
                        await (
                            await connection.execute(
                                "SELECT DISTINCT substring(license_restriction_name FROM '/([0-9]{4})$') "
                                "AS industry_code "
                                "FROM public_procurement.bid_notice_license_restrictions "
                                "WHERE notice_number=%s AND notice_order=%s "
                                "AND license_restriction_name~'/[0-9]{4}$'",
                                (reference_number, reference_order),
                            )
                        ).fetchall()
                    )
                ]
        return {
            "organization": dict(organization)
            if organization
            else {
                "organization_code": organization_code,
                "organization_name": None,
            },
            "company": dict(company)
            if company
            else {
                "business_registration_number": business_registration_number,
                "company_name": None,
            },
            "reference_notice": reference,
        }
