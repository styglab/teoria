"""SQL queries for processing runs and their artifact references."""

from psycopg.rows import dict_row

from teoria.domains.goods.data_processing.catalog.repository import (
    DocumentCatalogRepository,
)
from teoria.integrations.data_database.connection import connect


class ProcessingQueries:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.catalog = DocumentCatalogRepository(database_url)

    async def runs(self, offset: int, limit: int):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            rows = await (
                await conn.execute(
                    """SELECT run_id,mode,classification_code,status,summary,error_code,started_at,finished_at
                FROM public_procurement.specification_processing_runs ORDER BY started_at DESC,run_id LIMIT %s OFFSET %s""",
                    (limit, offset),
                )
            ).fetchall()
            total = await (
                await conn.execute(
                    "SELECT count(*) AS total FROM public_procurement.specification_processing_runs"
                )
            ).fetchone()
            return {"items": rows, "total": total["total"]}

    async def operations(self, days: int):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            runs = await (
                await conn.execute(
                    """SELECT status,count(*) AS count FROM public_procurement.specification_processing_runs
                WHERE started_at >= now() - make_interval(days => %s) GROUP BY status""",
                    (days,),
                )
            ).fetchall()
            documents = await (
                await conn.execute(
                    """SELECT d.status,count(*) AS count FROM public_procurement.specification_processing_documents d
                JOIN public_procurement.specification_processing_runs r USING(run_id)
                WHERE r.started_at >= now() - make_interval(days => %s) GROUP BY d.status""",
                    (days,),
                )
            ).fetchall()
            versions = await (
                await conn.execute(
                    """SELECT summary->>'processor_revision' AS processor_revision,
                summary->'quality'->>'model_requested' AS model_requested,count(*) AS runs,
                count(*) FILTER (WHERE summary ? 'quality') AS measured_runs,
                count(*) FILTER (WHERE summary->'automatic_application_standard'->>'status'='approved') AS approved,
                count(*) FILTER (WHERE summary->'automatic_application_standard'->>'status'='held') AS held,
                sum(COALESCE((summary->'quality'->>'validation_errors')::int,0)) AS validation_errors,
                sum(COALESCE((summary->'quality'->>'accepted_attributes')::int,0)) AS accepted_attributes,
                sum(COALESCE((summary->'quality'->>'quarantined_attributes')::int,0)) AS quarantined_attributes,
                sum(COALESCE((summary->'quality'->>'applied_attributes')::int,0)) AS applied_attributes,
                sum(COALESCE((summary->'quality'->>'held_attributes')::int,0)) AS held_attributes
                FROM public_procurement.specification_processing_runs
                WHERE started_at >= now()-make_interval(days => %s)
                GROUP BY 1,2 ORDER BY max(started_at) DESC LIMIT 20""",
                    (days,),
                )
            ).fetchall()
            return {
                "days": days,
                "runs": {r["status"]: r["count"] for r in runs},
                "documents": {d["status"]: d["count"] for d in documents},
                "quality_versions": versions,
                "quality_evaluation": "not_attached",
            }

    async def standard_candidates(self, offset, limit):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            condition = "mode='standard_management' AND status IN ('completed','partial') AND standard_uri IS NOT NULL"
            rows = await (
                await conn.execute(
                    f"SELECT run_id,classification_code,status,started_at FROM public_procurement.specification_processing_runs WHERE {condition} ORDER BY started_at DESC,run_id LIMIT %s OFFSET %s",
                    (limit, offset),
                )
            ).fetchall()
            total = await (
                await conn.execute(
                    f"SELECT count(*) AS total FROM public_procurement.specification_processing_runs WHERE {condition}"
                )
            ).fetchone()
            return {"items": rows, "total": total["total"]}

    async def detail(self, run_id: str):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            row = await (
                await conn.execute(
                    """SELECT run_id,mode,classification_code,status,summary,error_code,started_at,finished_at,
                standard_uri,standard_sha256 FROM public_procurement.specification_processing_runs WHERE run_id=%s""",
                    (run_id,),
                )
            ).fetchone()
            if row is None:
                return None
            documents = await (
                await conn.execute(
                    """SELECT document_id,status,source_sha256,result_summary FROM
                public_procurement.specification_processing_documents WHERE run_id=%s ORDER BY document_id""",
                    (run_id,),
                )
            ).fetchall()
            artifacts = await (
                await conn.execute(
                    """SELECT object_key AS key,uri,sha256,size_bytes,media_type FROM
                public_procurement.specification_processing_artifacts WHERE run_id=%s ORDER BY object_key""",
                    (run_id,),
                )
            ).fetchall()
            return {"run": row, "documents": documents, "artifacts": artifacts}

    async def inputs(self, run_id: str):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            return await (
                await conn.execute(
                    """SELECT i.document_id,i.filename,i.source_uri,
                COALESCE(d.source_sha256,i.source_sha256) AS sha256,i.notice_number
                FROM public_procurement.specification_processing_inputs i
                LEFT JOIN public_procurement.specification_processing_documents d USING(run_id,document_id)
                WHERE i.run_id=%s ORDER BY i.document_id""",
                    (run_id,),
                )
            ).fetchall()
