"""Read-only, paginated document/version catalog; no artifact bodies in SQL."""

from datetime import date

from psycopg.rows import dict_row

from teoria.integrations.data_operations.persistence.connection import connect

# A source version in the same classification and notice is one catalog entry.
# Different notices remain separate provenance even when file bytes match.
BASE = """
WITH observations AS (
 SELECT i.run_id, i.document_id, i.filename, i.source_uri,
        coalesce(d.source_sha256, i.source_sha256) AS source_sha256,
        coalesce(d.notice_number, i.notice_number) AS notice_number,
        r.classification_code, r.mode, r.started_at, r.finished_at, r.status AS run_status,
        CASE WHEN r.status IN ('failed','running') THEN r.status ELSE coalesce(d.status,'failed') END AS status,
        coalesce(d.result_summary, '{}'::jsonb) AS result_summary,
        EXISTS(SELECT 1 FROM public_procurement.specification_processing_artifacts a
               WHERE a.run_id=r.run_id AND
                 (a.object_key='specification_processing/'||r.run_id||'/documents/'||i.document_id||'/result.json'
                  OR a.object_key='specification_processing/'||r.run_id||'/extracted.json'
                  OR a.object_key='extracted.json')) AS has_artifact
 FROM public_procurement.specification_processing_inputs i
 JOIN public_procurement.specification_processing_runs r USING(run_id)
 LEFT JOIN public_procurement.specification_processing_documents d USING(run_id, document_id)
 WHERE {source_filter}
), identified AS (
 SELECT *, md5(jsonb_build_array(classification_code, coalesce(notice_number,''),
              coalesce(source_sha256, source_uri, run_id||':'||document_id))::text) AS catalog_id,
        (has_artifact AND status IN ('extracted','partial') AND run_status IN ('completed','partial')) AS successful
 FROM observations
), ranked AS (
 SELECT *, row_number() OVER(PARTITION BY catalog_id ORDER BY successful DESC, started_at DESC, run_id DESC, document_id) AS result_rank,
        row_number() OVER(PARTITION BY catalog_id ORDER BY started_at DESC, run_id DESC, document_id) AS latest_rank,
        count(*) OVER(PARTITION BY catalog_id) AS attempt_count
 FROM identified
), entries AS (
 SELECT chosen.*, latest.run_id AS latest_run_id, latest.document_id AS latest_document_id,
        latest.started_at AS latest_started_at, latest.run_status AS latest_run_status,
        latest.status AS latest_status,
        coalesce(latest.filename, chosen.filename, chosen.document_id) AS display_name
 FROM ranked chosen JOIN ranked latest USING(catalog_id)
 WHERE chosen.result_rank=1 AND latest.latest_rank=1
)
"""
COLUMNS = """catalog_id,display_name AS filename,classification_code,notice_number,source_sha256,
run_id,document_id,mode,status,run_status,result_summary,started_at,finished_at,attempt_count,
latest_run_id,latest_document_id,latest_started_at,latest_status,latest_run_status,
successful AS result_available"""


def source_filter(classification: str = ""):
    if classification == "unclassified":
        return "r.classification_code IS NULL", []
    if classification:
        return "r.classification_code=%s", [classification]
    return "TRUE", []


class DocumentCatalogRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    async def documents(self, *, classification="", query="", status="all", since: date | None = None,
                        until: date | None = None, sort="recent", offset=0, limit=25):
        condition, params = source_filter(classification)
        sql = BASE.replace("{source_filter}", condition)
        filters = []
        if query.strip():
            filters.append("(strpos(lower(display_name),lower(%s))>0 OR strpos(coalesce(notice_number,''),%s)>0)")
            params += [query.strip(), query.strip()]
        if status != "all":
            filters.append("latest_status=%s")
            params.append(status)
        if since:
            filters.append("latest_started_at >= %s::date")
            params.append(since)
        if until:
            filters.append("latest_started_at < %s::date + interval '1 day'")
            params.append(until)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        order = "display_name,catalog_id" if sort == "name" else "latest_started_at DESC,catalog_id"
        async with connect(self.database_url, row_factory=dict_row) as conn:
            # One statement snapshot keeps the page and total consistent, including empty pages.
            result = await (await conn.execute(sql + f""", filtered AS (SELECT * FROM entries{where}),
                page AS (SELECT {COLUMNS} FROM filtered ORDER BY {order} LIMIT %s OFFSET %s)
                SELECT coalesce((SELECT jsonb_agg(to_jsonb(page)) FROM page),'[]'::jsonb) AS items,
                       (SELECT count(*) FROM filtered) AS total""", [*params, limit, offset])).fetchone()
        return dict(result)

    async def classifications(self, *, query="", offset=0, limit=100):
        sql = BASE.replace("{source_filter}", "TRUE")
        async with connect(self.database_url, row_factory=dict_row) as conn:
            row = await (await conn.execute(sql + """, groups AS (
              SELECT classification_code, count(*) AS documents,
                     count(*) FILTER(WHERE successful) AS results
              FROM entries GROUP BY classification_code
            ), filtered AS (SELECT * FROM groups WHERE strpos(coalesce(classification_code,''),%s)>0),
            page AS (SELECT * FROM filtered ORDER BY classification_code NULLS LAST LIMIT %s OFFSET %s)
            SELECT coalesce((SELECT jsonb_agg(to_jsonb(page)) FROM page),'[]'::jsonb) AS items,
                   (SELECT count(*) FROM filtered) AS total,
                   (SELECT count(*) FROM entries) AS documents""", [query.strip(), limit, offset])).fetchone()
        return dict(row)

    async def entry(self, catalog_id):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            return await (await conn.execute(BASE.replace("{source_filter}", "TRUE") +
                f"SELECT {COLUMNS} FROM entries WHERE catalog_id=%s", [catalog_id])).fetchone()

    async def history(self, catalog_id, *, offset=0, limit=25):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            row = await (await conn.execute(BASE.replace("{source_filter}", "TRUE") + """,
              history AS (SELECT run_id,document_id,filename,notice_number,status,run_status,mode,started_at,finished_at
                          FROM identified WHERE catalog_id=%s),
              page AS (SELECT * FROM history ORDER BY started_at DESC,run_id DESC,document_id LIMIT %s OFFSET %s)
              SELECT coalesce((SELECT jsonb_agg(to_jsonb(page)) FROM page),'[]'::jsonb) AS items,
                     (SELECT count(*) FROM history) AS total""", [catalog_id, limit, offset])).fetchone()
        return dict(row)

    async def index_runs(self, limit):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            return await (await conn.execute("""SELECT r.run_id,r.artifact_root
               FROM public_procurement.specification_processing_runs r
               WHERE EXISTS(SELECT 1 FROM public_procurement.specification_processing_artifacts a
                            WHERE a.run_id=r.run_id AND (a.object_key LIKE '%%/extracted.json' OR a.object_key='extracted.json'))
                 AND (EXISTS(SELECT 1 FROM public_procurement.specification_processing_inputs i
                             WHERE i.run_id=r.run_id AND i.filename IS NULL)
                      OR NOT EXISTS(SELECT 1 FROM public_procurement.specification_processing_artifacts a
                                    WHERE a.run_id=r.run_id AND a.object_key LIKE '%%/documents/%%/result.json'))
               ORDER BY r.started_at DESC,r.run_id LIMIT %s""", [limit])).fetchall()

    async def index_metadata(self, run_id, documents, references):
        async with connect(self.database_url) as conn:
            for document in documents:
                source = document.get('source') or {}
                await conn.execute("""INSERT INTO public_procurement.specification_processing_inputs
                    (run_id,document_id,filename,source_uri,source_sha256,notice_number) VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(run_id,document_id) DO UPDATE SET
                    filename=coalesce(EXCLUDED.filename,specification_processing_inputs.filename),
                    source_uri=coalesce(EXCLUDED.source_uri,specification_processing_inputs.source_uri),
                    source_sha256=coalesce(specification_processing_inputs.source_sha256,EXCLUDED.source_sha256)
                    WHERE specification_processing_inputs.source_sha256 IS NULL
                       OR specification_processing_inputs.source_sha256=EXCLUDED.source_sha256""",
                    [run_id,document['document_id'],source.get('original_name') or source.get('filename'),
                     source.get('origin_uri'),source.get('sha256'),document.get('notice_number')])
            for ref in references:
                await conn.execute("""INSERT INTO public_procurement.specification_processing_artifacts
                    (run_id,object_key,uri,sha256,size_bytes,media_type) VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(run_id,object_key) DO UPDATE SET uri=EXCLUDED.uri,sha256=EXCLUDED.sha256,
                    size_bytes=EXCLUDED.size_bytes,media_type=EXCLUDED.media_type""",
                    [run_id,ref['key'],ref['uri'],ref['sha256'],ref['size_bytes'],ref['media_type']])
