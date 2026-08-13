from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row


class BidCheckReader:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def list_notices(self, *, page: int = 1, page_size: int = 50,
                     query: str | None = None, bid_status: str | None = None,
                     work_type: str | None = None, extraction_status: str | None = None,
                     review_status: str | None = None) -> dict[str, Any]:
        search = (query or "").strip()
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            clauses.append(
                "(n.notice_number ILIKE %s OR n.notice_name ILIKE %s "
                "OR COALESCE(n.notice_organization_name,'') ILIKE %s "
                "OR COALESCE(n.demand_organization_name,'') ILIKE %s)"
            )
            params.extend((f"%{search}%",) * 4)
        if bid_status:
            clauses.append("n.bid_status=%s")
            params.append(bid_status)
        if work_type:
            clauses.append("n.work_type=%s")
            params.append(work_type)
        if extraction_status == "pending":
            clauses.append("n.extraction_completeness IS NULL")
        elif extraction_status == "extracted":
            clauses.append("n.extraction_completeness IS NOT NULL")
        elif extraction_status:
            clauses.append("n.extraction_completeness=%s")
            params.append(extraction_status)
        if review_status == "required":
            clauses.append("n.requires_review IS TRUE")
        elif review_status == "not_required":
            clauses.append("n.requires_review IS FALSE")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        offset = (page - 1) * page_size
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            total = connection.execute(
                f"SELECT count(*) AS count FROM public_procurement.runtime_bid_notices n {where}",
                tuple(params),
            ).fetchone()["count"]
            rows = connection.execute(
                "SELECT n.bid_notice_id,n.notice_number,n.notice_order,n.notice_name,n.work_type,"
                "n.notice_published_at,n.bid_deadline_at,n.bid_status,n.notice_organization_name,"
                "n.demand_organization_name,n.extraction_completeness,n.requires_review,"
                "(SELECT count(*) FROM public_procurement.runtime_bid_requirements r "
                "WHERE r.bid_notice_id=n.bid_notice_id) AS requirement_count "
                f"FROM public_procurement.runtime_bid_notices n {where} "
                "ORDER BY n.notice_published_at DESC NULLS LAST,n.notice_number DESC,n.notice_order DESC "
                "LIMIT %s OFFSET %s",
                (*params, page_size, offset),
            ).fetchall()
        return {
            "items": [_json_ready(dict(row)) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }

    def get_requirements(self, bid_notice_id: str) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                "SELECT requirement_id,local_id,requirement_type,operator,value_text,original_text,"
                "proposition_text,proposition_start,proposition_end,"
                "holder_scope,reference_date_type,assessment_stage,failure_effect,comparison_mode,"
                "mandatory,review_status,confidence,evidence_summary,proof_summary,"
                "standard_rule_id,standard_rule_version,rule_arguments_text "
                "FROM public_procurement.runtime_bid_requirements WHERE bid_notice_id=%s "
                "ORDER BY local_id",
                (bid_notice_id,),
            ).fetchall()
        return [_json_ready(dict(row)) for row in rows]


def _json_ready(row: dict[str, Any]) -> dict[str, Any]:
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            row[key] = value.isoformat()
        elif key == "confidence" and value is not None:
            row[key] = float(value)
    return row
