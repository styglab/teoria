"""Dictionary persistence; the service owns review decisions and transaction order."""
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from teoria.integrations.application_database.postgres import connect


class GoodsDictionaryRepository:
    def __init__(self, database_url):
        self.database_url = database_url

    def transaction(self):
        return connect(self.database_url, row_factory=dict_row)

    async def lock(self, conn):
        # One short, bounded authoring transaction; no inference or HTTP under lock.
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('goods_dictionary_v1', 0))")

    async def operation(self, conn, operation_id):
        return await (await conn.execute(
            "SELECT * FROM goods.dictionary_operations WHERE operation_id=%s", (operation_id,)
        )).fetchone()

    async def begin(self, conn, operation_id, digest, actor):
        await conn.execute(
            "INSERT INTO goods.dictionary_operations(operation_id,request_checksum,actor,result) VALUES (%s,%s,%s,%s)",
            (operation_id, digest, actor, Jsonb({})),
        )

    async def finish(self, conn, operation_id, result):
        await conn.execute("UPDATE goods.dictionary_operations SET result=%s WHERE operation_id=%s", (Jsonb(result), operation_id))

    async def by_key(self, conn, stable_key):
        return await (await conn.execute("SELECT * FROM goods.dictionary_entries WHERE stable_key=%s", (stable_key,))).fetchone()

    async def by_id(self, conn, entry_id):
        return await (await conn.execute("SELECT * FROM goods.dictionary_entries WHERE entry_id=%s", (entry_id,))).fetchone()

    async def insert_entry(self, conn, body, digest, actor, policy):
        return await (await conn.execute(
            """INSERT INTO goods.dictionary_entries
            (entry_id,kind,stable_key,preferred_name,owner_entry_id,content,content_checksum,status,approved_by,approval_mode,policy_version)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'approved',%s,'automatic_policy',%s) RETURNING *""",
            (uuid4(), body['kind'], body['stable_key'], body['preferred_name'], body.get('owner_entry_id'), Jsonb(body), digest, actor, policy),
        )).fetchone()

    async def decision(self, conn, operation_id, candidate, result, digest, actor, policy):
        await conn.execute(
            """INSERT INTO goods.dictionary_decisions
            (decision_id,operation_id,candidate_key,status,reason,entry_id,candidate,evidence_digest,actor,policy_version)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (uuid4(),operation_id,candidate.candidate_key,result['status'],result['reason'],result.get('entry_id'),
             Jsonb(candidate.model_dump(mode='json')),digest,actor,policy),
        )

    async def event(self, conn, operation_id, key, action, reason, actor, policy, entry_id=None):
        await conn.execute(
            """INSERT INTO goods.dictionary_events
            (event_id,operation_id,candidate_key,entry_id,action,actor,approval_mode,policy_version,reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (uuid4(),operation_id,key,entry_id,action,actor,'automatic_policy' if action=='approved' else None,policy,reason),
        )

    async def entries(self, conn, query, kind, limit):
        return await (await conn.execute(
            """SELECT entry_id,kind,stable_key,preferred_name,owner_entry_id,content,status,approved_by,approval_mode,policy_version,created_at
            FROM goods.dictionary_entries WHERE (%s::text IS NULL OR kind=%s)
            AND (%s='' OR strpos(lower(preferred_name),lower(%s))>0)
            ORDER BY preferred_name,entry_id LIMIT %s""", (kind,kind,query,query,limit)
        )).fetchall()

    async def audit(self, conn, entry_id):
        return await (await conn.execute(
            "SELECT * FROM goods.dictionary_events WHERE entry_id=%s ORDER BY created_at,event_id", (entry_id,)
        )).fetchall()
