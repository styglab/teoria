from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
import re
from psycopg.types.json import Jsonb

from teoria_pipelines.models import (
    BidNoticeKey,
    CollectionWindow,
    LoadSummary,
    NormalizedBatch,
    NormalizedBidResultBatch,
    NormalizedBidNoticeBatch,
    RawProviderRecord,
)

from teoria_pipelines.persistence.postgres_store.support import (
    _filter_covered_unavailable_documents,
    _sanitize_postgres_value,
    _validate_industry_snapshot,
    eligibility_requires_review,
)


class ContractStoreMixin:
    """contracts persistence operations."""

    def upsert_normalized(self, batch: NormalizedBatch) -> LoadSummary:
        with psycopg.connect(self.database_url) as connection:
            self._upsert_many(connection, "public_procurement.contracts", batch.contracts,
                              ("unified_contract_number",))
            self._upsert_many(connection, "public_procurement.public_organizations",
                              batch.organizations, ("organization_code",))
            self._upsert_many(connection, "public_procurement.contract_suppliers",
                              batch.suppliers, ("unified_contract_number", "supplier_sequence"))
            self._upsert_many(connection, "public_procurement.contract_demand_organizations",
                              batch.demand_organizations,
                              ("unified_contract_number", "demand_organization_sequence"))
        return LoadSummary(
            contracts=len(batch.contracts),
            suppliers=len(batch.suppliers),
            organizations=len(batch.organizations),
            demand_organizations=len(batch.demand_organizations),
        )

    def replace_procurement_industries(self, rows: list[dict[str, Any]]) -> int:
        snapshot_at = datetime.now(timezone.utc)
        codes = [row["industry_code"] for row in rows]
        with psycopg.connect(self.database_url) as connection:
            previous_active_count = connection.execute(
                "SELECT count(*) FROM public_procurement.procurement_industries WHERE is_active"
            ).fetchone()[0]
            _validate_industry_snapshot(rows, previous_active_count)
            for row in rows:
                values = dict(row)
                columns = tuple(values)
                connection.execute(
                    f"INSERT INTO public_procurement.procurement_industries ({', '.join(columns)}) "
                    f"VALUES ({', '.join('%(' + column + ')s' for column in columns)}) "
                    "ON CONFLICT (industry_code) DO UPDATE SET "
                    + ", ".join(
                        f"{column}=EXCLUDED.{column}" for column in columns
                        if column not in {"industry_code", "first_seen_at"}
                    ) + ", missing_snapshot_count=0,updated_at=now()",
                    values,
                )
            connection.execute(
                "UPDATE public_procurement.procurement_industries SET "
                "missing_snapshot_count=missing_snapshot_count+1,"
                "is_active=CASE WHEN missing_snapshot_count+1>=2 THEN false ELSE is_active END,"
                "updated_at=%s WHERE NOT (industry_code = ANY(%s))",
                (snapshot_at, codes),
            )
        return len(rows)

    def resolve_requirement_industries(self, result: dict[str, Any]) -> None:
        with psycopg.connect(self.database_url) as connection:
            for requirement in result.get("requirements", []):
                if requirement.get("type") != "industry_license":
                    continue
                value = requirement.get("value") or {}
                attributes = value.get("attributes") or []
                if any(str(item.get("name", "")).casefold() == "industry_code" for item in attributes):
                    continue
                name = str(value.get("text") or "").strip()
                normalized = re.sub(r"[^0-9a-z가-힣]+", "", name.casefold())
                if not normalized:
                    continue
                rows = connection.execute(
                    "SELECT industry_code,industry_name FROM public_procurement.procurement_industries "
                    "WHERE is_active AND regexp_replace(lower(industry_name),'[^0-9a-z가-힣]+','','g')=%s",
                    (normalized,),
                ).fetchall()
                if len(rows) == 1:
                    attributes.extend([
                        {"name": "industry_code", "value": rows[0][0]},
                        {"name": "industry_name", "value": rows[0][1]},
                    ])
                    value["attributes"] = attributes
                    requirement["value"] = value

