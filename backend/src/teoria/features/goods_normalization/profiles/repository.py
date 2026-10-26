"""Profile persistence; callers supply the connection for atomic state changes and audit."""

from uuid import uuid4
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from teoria.integrations.application_database.postgres import connect


class NormalizationProfileRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def transaction(self):
        return connect(self.database_url, row_factory=dict_row)

    async def get(self, conn, revision_id, *, lock=False):
        row = await (
            await conn.execute(
                "SELECT * FROM goods.normalization_profile_revisions WHERE revision_id=%s"
                + (" FOR UPDATE" if lock else ""),
                (revision_id,),
            )
        ).fetchone()
        if row is None:
            raise KeyError(str(revision_id))
        return row

    async def insert(self, conn, profile, *, actor, digest):
        return await (
            await conn.execute(
                """INSERT INTO goods.normalization_profile_revisions
            (revision_id,profile_key,version,ontology_version_id,content,content_checksum,created_by,updated_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (
                    uuid4(),
                    profile.profile_key,
                    profile.version,
                    profile.ontology.version_id,
                    Jsonb(profile.model_dump(mode="json")),
                    digest,
                    actor,
                    actor,
                ),
            )
        ).fetchone()

    async def update(self, conn, revision_id, profile, *, actor, digest):
        return await (
            await conn.execute(
                """UPDATE goods.normalization_profile_revisions
            SET ontology_version_id=%s,content=%s,content_checksum=%s,updated_by=%s,updated_at=now()
            WHERE revision_id=%s RETURNING *""",
                (
                    profile.ontology.version_id,
                    Jsonb(profile.model_dump(mode="json")),
                    digest,
                    actor,
                    revision_id,
                ),
            )
        ).fetchone()

    async def set_status(self, conn, revision_id, *, status, package, actor):
        return await (
            await conn.execute(
                """UPDATE goods.normalization_profile_revisions
            SET status=%s,package=%s,updated_by=%s,updated_at=now() WHERE revision_id=%s RETURNING *""",
                (
                    status,
                    Jsonb(package) if package is not None else None,
                    actor,
                    revision_id,
                ),
            )
        ).fetchone()

    async def record_event(self, conn, row, action, actor, comment):
        await conn.execute(
            """INSERT INTO goods.normalization_profile_events
            (event_id,revision_id,action,actor,content_checksum,comment) VALUES (%s,%s,%s,%s,%s,%s)""",
            (
                uuid4(),
                row["revision_id"],
                action,
                actor,
                row["content_checksum"],
                comment,
            ),
        )

    async def audit(self, conn, revision_id):
        return await (
            await conn.execute(
                """SELECT event_id,action,actor,content_checksum,comment,created_at
            FROM goods.normalization_profile_events WHERE revision_id=%s ORDER BY created_at,event_id""",
                (revision_id,),
            )
        ).fetchall()

    async def find_revision(self, conn, profile_key, version):
        return await (
            await conn.execute(
                """SELECT * FROM goods.normalization_profile_revisions
            WHERE profile_key=%s AND version=%s""",
                (profile_key, version),
            )
        ).fetchone()
