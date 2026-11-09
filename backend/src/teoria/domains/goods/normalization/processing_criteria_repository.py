"""Application DB references to immutable standard and dictionary snapshots."""

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from teoria.integrations.application_database.postgres import connect


class ApplicationStandardsRepository:
    def __init__(self, database_url):
        self.database_url = database_url

    async def list(self, offset=0, limit=25):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            rows = await (
                await conn.execute(
                    "SELECT * FROM goods.application_standards ORDER BY created_at DESC,release_id LIMIT %s OFFSET %s",
                    (limit, offset),
                )
            ).fetchall()
            total = await (
                await conn.execute(
                    "SELECT count(*) AS total FROM goods.application_standards"
                )
            ).fetchone()
            return {"items": rows, "total": total["total"]}

    async def get(self, release_id):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            row = await (
                await conn.execute(
                    "SELECT * FROM goods.application_standards WHERE release_id=%s",
                    (release_id,),
                )
            ).fetchone()
            if row is None:
                raise KeyError(release_id)
            return row

    async def create(self, body):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            inserted = await (
                await conn.execute(
                    """INSERT INTO goods.application_standards
                (release_id,name,source_run_id,classification_code,standard_kind,standard_ref,dictionary_ref,
                 dictionary_checksum,content_checksum,approved_by,rationale)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (release_id) DO NOTHING RETURNING *""",
                    (
                        body["release_id"],
                        body["name"],
                        body["source_run_id"],
                        body["classification_code"],
                        body["standard_kind"],
                        Jsonb(body["standard_ref"]),
                        Jsonb(body["dictionary_ref"]),
                        body["dictionary_checksum"],
                        body["content_checksum"],
                        body["approved_by"],
                        body["rationale"],
                    ),
                )
            ).fetchone()
            if inserted is not None:
                return inserted
            row = await (await conn.execute(
                'SELECT * FROM goods.application_standards WHERE release_id=%s', (body['release_id'],)
            )).fetchone()
            if row is None or row['status'] != 'approved' or any(
                row[key] != body[key] for key in ('name','source_run_id','classification_code','standard_kind',
                    'standard_ref','dictionary_ref','dictionary_checksum','content_checksum','approved_by','rationale')
            ):
                raise ValueError('application_standard_idempotency_conflict')
            return row
