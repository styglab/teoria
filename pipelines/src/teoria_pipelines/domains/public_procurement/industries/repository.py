from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from teoria_pipelines.persistence.connection import connect

from teoria_pipelines.domains.public_procurement.repository import (
    ProcurementRunRepository,
)


class IndustryRepository(ProcurementRunRepository):
    """Validated industry snapshot persistence."""

    async def replace_procurement_industries(self, rows: list[dict[str, Any]]) -> int:
        snapshot_at = datetime.now(timezone.utc)
        codes = [row["industry_code"] for row in rows]
        async with connect(self.database_url) as connection:
            previous_active_count = (
                await (
                    await connection.execute(
                        "SELECT count(*) FROM public_procurement.procurement_industries WHERE is_active"
                    )
                ).fetchone()
            )[0]
            _validate_industry_snapshot(rows, previous_active_count)
            for row in rows:
                values = dict(row)
                columns = tuple(values)
                await connection.execute(
                    f"INSERT INTO public_procurement.procurement_industries ({', '.join(columns)}) "
                    f"VALUES ({', '.join('%(' + column + ')s' for column in columns)}) "
                    "ON CONFLICT (industry_code) DO UPDATE SET "
                    + ", ".join(
                        f"{column}=EXCLUDED.{column}"
                        for column in columns
                        if column not in {"industry_code", "first_seen_at"}
                    )
                    + ", missing_snapshot_count=0,updated_at=now()",
                    values,
                )
            await connection.execute(
                "UPDATE public_procurement.procurement_industries SET "
                "missing_snapshot_count=missing_snapshot_count+1,"
                "is_active=CASE WHEN missing_snapshot_count+1>=2 THEN false ELSE is_active END,"
                "updated_at=%s WHERE NOT (industry_code = ANY(%s))",
                (snapshot_at, codes),
            )
        return len(rows)


def _validate_industry_snapshot(
    rows: list[dict[str, Any]], previous_active_count: int
) -> None:
    if not rows:
        raise ValueError("empty_industry_snapshot")
    codes = [str(row.get("industry_code") or "") for row in rows]
    if any(
        not code
        or not row.get("industry_name")
        or not row.get("classification_code")
        or not row.get("classification_name")
        or not row.get("source_registered_at")
        for code, row in zip(codes, rows, strict=True)
    ):
        raise ValueError("invalid_industry_snapshot_required_field")
    if len(codes) != len(set(codes)):
        raise ValueError("duplicate_industry_code_in_snapshot")
    if previous_active_count and len(rows) < previous_active_count * 0.9:
        raise ValueError("industry_snapshot_count_dropped_over_10_percent")
