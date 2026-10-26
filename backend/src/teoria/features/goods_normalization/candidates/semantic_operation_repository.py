"""Durable operation checkpoints and session-scoped serialization."""

from contextlib import asynccontextmanager
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from teoria.integrations.application_database.postgres import connect


class SemanticOperationRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    async def get(self, operation_id):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            return await (
                await conn.execute(
                    "SELECT * FROM goods.semantic_operations WHERE operation_id=%s",
                    (operation_id,),
                )
            ).fetchone()

    async def ensure(self, operation_id, digest, actor):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            await conn.execute(
                """INSERT INTO goods.semantic_operations(operation_id,input_checksum,actor,status)
                VALUES (%s,%s,%s,'running') ON CONFLICT DO NOTHING""",
                (operation_id, digest, actor),
            )
            row = await (
                await conn.execute(
                    "SELECT * FROM goods.semantic_operations WHERE operation_id=%s",
                    (operation_id,),
                )
            ).fetchone()
            if row["input_checksum"] != digest or row["actor"] != actor:
                raise ValueError(
                    "operation ID belongs to different inputs or principal"
                )
            return row

    async def save(self, operation_id, state, status, error=None):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            return await (
                await conn.execute(
                    """UPDATE goods.semantic_operations SET checkpoint=%s,status=%s,
                error_code=%s,updated_at=now() WHERE operation_id=%s RETURNING *""",
                    (Jsonb(state), status, error, operation_id),
                )
            ).fetchone()

    @asynccontextmanager
    async def serialized(self, operation_id):
        # This connection owns no authoring transaction/row locks. Checkpoints commit separately.
        async with connect(self.database_url) as conn:
            acquired = (
                await (
                    await conn.execute(
                        "SELECT pg_try_advisory_lock(hashtextextended(%s,0))",
                        ("goods_semantic:" + operation_id,),
                    )
                ).fetchone()
            )[0]
            try:
                yield acquired
            finally:
                if acquired:
                    await conn.execute(
                        "SELECT pg_advisory_unlock(hashtextextended(%s,0))",
                        ("goods_semantic:" + operation_id,),
                    )
