from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field, field_validator


class LawSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=200)
    law_id: str | None = None
    assessment_date: date = Field(default_factory=lambda: datetime.now(ZoneInfo("Asia/Seoul")).date())
    version_scope: Literal["as_of", "all"] = "as_of"
    match: Literal["any", "all"] = "any"
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        terms = list(dict.fromkeys(value.split()))
        if not terms or len(terms) > 8 or len(" ".join(terms)) < 2:
            raise ValueError("provide 1 to 8 keywords, at least two characters")
        return " ".join(terms)

    @field_validator("law_id")
    @classmethod
    def normalize_law_id(cls, value):
        if value is not None:
            if not value.isascii() or not value.isdigit() or len(value) > 12:
                raise ValueError("law_id must be a numeric identifier")
            return str(int(value))
        return value


def _pattern(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class LawSearchReader:
    """Admin diagnostics read a bounded view; Runtime registration comes later."""

    def __init__(self, database_url: str):
        self.database_url = database_url

    def search(self, request: LawSearchRequest) -> dict:
        terms = request.query.split()
        conditions = []
        conditions_params = []
        for term in terms:
            conditions.append("(law_name ILIKE %s ESCAPE '\\' OR title ILIKE %s ESCAPE '\\' OR content ILIKE %s ESCAPE '\\')")
            conditions_params.extend([_pattern(term)] * 3)
        joined = (" AND " if request.match == "all" else " OR ").join(conditions)
        scores = []
        score_params = []
        for term in terms:
            scores.append("CASE WHEN title ILIKE %s ESCAPE '\\' THEN 3 WHEN content ILIKE %s ESCAPE '\\' THEN 2 "
                          "WHEN law_name ILIKE %s ESCAPE '\\' THEN 1 ELSE 0 END")
            score_params.extend([_pattern(term)] * 3)
        parameters = []
        # This is a publication/effective-date candidate, not a legal conclusion.
        # Select repeal rows before filtering them out, so an older law cannot
        # be resurrected merely because the latest row is a repeal.
        cte = "WITH candidates AS (SELECT * FROM legal_information.law_search_documents WHERE is_latest_snapshot"
        if request.law_id:
            cte += " AND law_id=%s"
            parameters.append(request.law_id)
        cte += ")"
        if request.version_scope == "as_of":
            cte += (", versions AS (SELECT DISTINCT ON (law_id) law_id,mst,effective_date "
                    "FROM legal_information.law_search_versions WHERE effective_date<=%s AND promulgation_date<=%s "
                    "ORDER BY law_id,effective_date DESC,promulgation_date DESC,mst::bigint DESC), "
                    "scoped AS (SELECT c.* FROM candidates c JOIN versions v USING(law_id,mst,effective_date) "
                    "WHERE c.amendment_type NOT IN ('폐지','타법폐지','일괄폐지') "
                    "AND (c.provision_effective_date IS NULL OR c.provision_effective_date<=%s))")
            parameters += [request.assessment_date] * 3
        else:
            cte += ", scoped AS (SELECT * FROM candidates)"
        query = cte + ", matched AS (SELECT *, (" + " + ".join(scores) + ") AS keyword_score FROM scoped WHERE " + joined + ") "
        query += ("SELECT target_id,law_id,mst,law_name,effective_date,promulgation_date,promulgation_number,"
                  "amendment_type,catalog_status,last_catalog_at,snapshot_id,source_record_hash,parser_version,"
                  "path,kind,number,title,provision_effective_date,keyword_score,LEFT(content,1000) AS excerpt,"
                  "length(content)>1000 AS excerpt_truncated FROM matched "
                  "ORDER BY keyword_score DESC,law_id,effective_date DESC,mst DESC,path LIMIT %s")
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            connection.execute("SET LOCAL statement_timeout='5s'")
            rows = connection.execute(query, [*parameters, *score_params, *conditions_params, request.limit + 1]).fetchall()
            if request.version_scope == "as_of":
                gap_query = ("SELECT law_id,mst,law_name,effective_date FROM ("
                             "SELECT DISTINCT ON (law_id) * FROM legal_information.law_search_versions "
                             "WHERE effective_date<=%s AND promulgation_date<=%s "
                             "ORDER BY law_id,effective_date DESC,promulgation_date DESC,mst::bigint DESC) v "
                             "WHERE NOT available")
                gap_params = [request.assessment_date] * 2
                if request.law_id:
                    gap_query += " AND law_id=%s"
                    gap_params.append(request.law_id)
                gaps = connection.execute(gap_query + " ORDER BY law_id LIMIT 50", gap_params).fetchall()
            else:
                gaps = []
        items = rows[:request.limit]
        for item in items:
            item["source_publication_url"] = f"https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq={item['mst']}"
        return {"items": items, "has_more": len(rows) > request.limit, "query": request.query,
                "search_method": "keyword", "version_scope": request.version_scope,
                "assessment_date": request.assessment_date, "unavailable_versions": gaps,
                "legal_applicability_confirmed": False}

    def get_document(self, snapshot_id: UUID, path: str, *, max_chars: int = 20000) -> dict | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            connection.execute("SET LOCAL statement_timeout='5s'")
            row = connection.execute(
                "SELECT target_id,law_id,mst,law_name,effective_date,promulgation_date,promulgation_number,"
                "snapshot_id,source_record_hash,parser_version,path,kind,number,title,"
                "provision_effective_date,LEFT(content,%s) AS content,length(content)>%s AS content_truncated "
                "FROM legal_information.law_search_documents WHERE snapshot_id=%s AND path=%s",
                (max_chars,max_chars,snapshot_id,path)).fetchone()
        return row
