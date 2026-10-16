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
                "(n.notice_number ILIKE %s OR COALESCE(n.notice_name,'') ILIKE %s "
                "OR COALESCE(n.notice_organization_name,'') ILIKE %s "
                "OR COALESCE(n.demand_organization_name,'') ILIKE %s)"
            )
            params.extend((f"%{search}%",) * 4)
        if bid_status:
            clauses.append(f"({_BID_STATUS_SQL})=%s")
            params.append(bid_status)
        if work_type:
            clauses.append("n.work_type=%s")
            params.append(work_type)
        if extraction_status == "pending":
            clauses.append("le.completeness IS NULL")
        elif extraction_status == "extracted":
            clauses.append("le.completeness IS NOT NULL")
        elif extraction_status:
            clauses.append("le.completeness=%s")
            params.append(extraction_status)
        if review_status == "required":
            clauses.append("le.requires_review IS TRUE")
        elif review_status == "not_required":
            clauses.append("le.requires_review IS FALSE")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        offset = (page - 1) * page_size
        from_sql = f"public_procurement.bid_notices n {_LATEST_EXTRACTION_JOIN}"
        count_from_sql = "public_procurement.bid_notices n"
        if extraction_status or review_status:
            count_from_sql += f" {_LATEST_EXTRACTION_SET_JOIN}"
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            total = connection.execute(
                f"SELECT count(*) AS count FROM {count_from_sql} {where}",
                tuple(params),
            ).fetchone()["count"]
            rows = connection.execute(
                "WITH page AS MATERIALIZED ("
                "SELECT n.notice_number,n.notice_order,n.notice_name,n.work_type,"
                f"n.notice_published_at,n.bid_deadline_at,{_BID_STATUS_SQL} AS bid_status,"
                "n.notice_organization_name,n.demand_organization_name,"
                "le.extraction_id,le.completeness AS extraction_completeness,le.requires_review "
                f"FROM {from_sql} {where} "
                "ORDER BY n.notice_published_at DESC NULLS LAST,n.notice_number DESC,n.notice_order DESC "
                "LIMIT %s OFFSET %s) "
                "SELECT p.notice_number||':'||p.notice_order AS bid_notice_id,"
                "p.notice_number,p.notice_order,p.notice_name,p.work_type,p.notice_published_at,"
                "p.bid_deadline_at,p.bid_status,p.notice_organization_name,p.demand_organization_name,"
                "p.extraction_completeness,p.requires_review,count(r.requirement_id) AS requirement_count "
                "FROM page p LEFT JOIN public_procurement.bid_eligibility_requirements r "
                "ON r.extraction_id=p.extraction_id "
                "GROUP BY p.notice_number,p.notice_order,p.notice_name,p.work_type,p.notice_published_at,"
                "p.bid_deadline_at,p.bid_status,p.notice_organization_name,p.demand_organization_name,"
                "p.extraction_completeness,p.requires_review "
                "ORDER BY p.notice_published_at DESC NULLS LAST,p.notice_number DESC,p.notice_order DESC",
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


_BID_STATUS_SQL = """CASE
    WHEN n.bid_deadline_at IS NULL
         AND n.opening_at IS NOT NULL
         AND n.opening_at < now() THEN 'closed'
    WHEN n.bid_deadline_at IS NULL THEN 'unknown'
    WHEN n.bid_begin_at IS NOT NULL AND n.bid_begin_at > now() THEN 'scheduled'
    WHEN n.bid_deadline_at >= now() THEN 'open'
    ELSE 'closed'
END"""

_LATEST_EXTRACTION_JOIN = """LEFT JOIN LATERAL (
    SELECT e.extraction_id,e.completeness,e.requires_review
    FROM public_procurement.bid_eligibility_extractions e
    WHERE e.notice_number=n.notice_number
      AND e.notice_order=n.notice_order
      AND e.status='completed'
    ORDER BY e.finished_at DESC NULLS LAST,e.started_at DESC
    LIMIT 1
) le ON TRUE"""

_LATEST_EXTRACTION_SET_JOIN = """LEFT JOIN (
    SELECT DISTINCT ON (e.notice_number,e.notice_order)
        e.notice_number,e.notice_order,e.completeness,e.requires_review
    FROM public_procurement.bid_eligibility_extractions e
    WHERE e.status='completed'
    ORDER BY e.notice_number,e.notice_order,
             e.finished_at DESC NULLS LAST,e.started_at DESC
) le ON le.notice_number=n.notice_number AND le.notice_order=n.notice_order"""


def _json_ready(row: dict[str, Any]) -> dict[str, Any]:
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            row[key] = value.isoformat()
        elif key == "confidence" and value is not None:
            row[key] = float(value)
    return row
