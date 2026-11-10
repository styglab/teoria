"""Approval metadata and audit only; no document observation bodies."""
from uuid import uuid4
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from teoria.integrations.application_database.postgres import connect


class InterpretationRepository:
    def __init__(self, database_url):
        self.database_url = database_url

    def transaction(self):
        return connect(self.database_url, row_factory=dict_row)

    async def get(self, conn, revision_id, *, lock=False):
        row = await (await conn.execute(
            'SELECT * FROM goods.interpretation_revisions WHERE revision_id=%s' + (' FOR UPDATE' if lock else ''),
            (revision_id,))).fetchone()
        if row is None:
            raise KeyError(str(revision_id))
        return row

    async def insert(self, conn, request, reference, package, *, actor):
        from teoria.domains.goods.normalization.contracts import checksum
        await conn.execute('''INSERT INTO goods.interpretation_revisions
            (revision_id,review_id,request_ref,request_checksum,profile_revision_id,ontology_version_id,
             ontology_checksum,package_checksum,created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (review_id) DO NOTHING''',
            (uuid4(), request.review_id, Jsonb(reference), checksum(request), package.profile_revision_id,
             package.profile.ontology.version_id, package.profile.ontology.checksum, package.checksum, actor))
        row = await (await conn.execute(
            'SELECT * FROM goods.interpretation_revisions WHERE review_id=%s FOR UPDATE', (request.review_id,))).fetchone()
        if row['request_checksum'] != checksum(request) or row['created_by'] != actor:
            raise ValueError('interpretation_review_id_conflict')
        return row

    async def set_status(self, conn, row, status, *, actor):
        return await (await conn.execute('''UPDATE goods.interpretation_revisions
            SET status=%s, approved_by=CASE WHEN %s='approved' THEN %s ELSE approved_by END,
                updated_at=now() WHERE revision_id=%s RETURNING *''',
            (status, status, actor, row['revision_id']))).fetchone()

    async def event(self, conn, row, action, actor, *, comment=None, artifact=None, event_key=''):
        await conn.execute('''INSERT INTO goods.interpretation_events
            (event_id,revision_id,action,event_key,actor,request_checksum,comment,artifact_ref)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (revision_id,action,event_key) DO NOTHING''',
            (uuid4(), row['revision_id'], action, event_key, actor, row['request_checksum'], comment,
             Jsonb(artifact) if artifact else None))

    async def audit(self, conn, revision_id):
        return await (await conn.execute('''SELECT event_id,action,event_key,actor,request_checksum,
            comment,artifact_ref,created_at FROM goods.interpretation_events
            WHERE revision_id=%s ORDER BY created_at,event_id''', (revision_id,))).fetchall()
