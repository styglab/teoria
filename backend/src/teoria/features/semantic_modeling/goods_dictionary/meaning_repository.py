"""Async persistence for immutable definitions and reviewable mappings."""
from uuid import uuid4

from psycopg.types.json import Jsonb
from teoria.features.semantic_modeling.goods_dictionary.repository import GoodsDictionaryRepository


class GoodsMeaningRepository(GoodsDictionaryRepository):
    async def concepts(self, conn):
        return await (await conn.execute('SELECT * FROM goods.concept_revisions ORDER BY concept_key,revision')).fetchall()

    async def concept(self, conn, revision_id):
        return await (await conn.execute('SELECT * FROM goods.concept_revisions WHERE revision_id=%s', (revision_id,))).fetchone()

    async def add_concept(self, conn, concept_id, revision, content, digest, actor):
        return await (await conn.execute('''INSERT INTO goods.concept_revisions
        (revision_id,concept_id,concept_key,revision,kind,content,content_checksum,status,created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'draft',%s) RETURNING *''',
        (uuid4(),concept_id,content['key'],revision,content['kind'],Jsonb(content),digest,actor))).fetchone()

    async def source_evidence(self, conn, entry_id):
        rows=await (await conn.execute('''SELECT candidate->'evidence' AS evidence
        FROM goods.dictionary_decisions WHERE entry_id=%s ORDER BY created_at,decision_id LIMIT 20''',(entry_id,))).fetchall()
        return [e for row in rows for e in row['evidence']]

    async def mappings(self, conn):
        return await (await conn.execute('SELECT * FROM goods.concept_mappings ORDER BY created_at,mapping_id')).fetchall()

    async def mapping(self, conn, mapping_id):
        return await (await conn.execute('SELECT * FROM goods.concept_mappings WHERE mapping_id=%s',(mapping_id,))).fetchone()

    async def add_mapping(self, conn, proposal, evidence, actor):
        return await (await conn.execute('''INSERT INTO goods.concept_mappings
        (mapping_id,source_entry_id,target_revision_id,classification_code,owner_concept_id,relation,rationale,evidence,status,created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s) RETURNING *''',
        (uuid4(),proposal.source_entry_id,proposal.target_revision_id,proposal.classification_code,proposal.owner_concept_id,
         proposal.relation,proposal.rationale,Jsonb(evidence),actor))).fetchone()

    async def set_status(self, conn, kind, entity_id, status):
        if kind=='concept':
            await conn.execute('UPDATE goods.concept_revisions SET status=%s WHERE revision_id=%s',(status,entity_id))
        elif kind=='mapping':
            await conn.execute('UPDATE goods.concept_mappings SET status=%s WHERE mapping_id=%s',(status,entity_id))
        else:
            raise ValueError('unknown meaning entity')

    async def meaning_event(self, conn, kind, entity_id, action, actor, rationale):
        await conn.execute('''INSERT INTO goods.meaning_events(event_id,entity_kind,entity_id,action,actor,rationale)
        VALUES (%s,%s,%s,%s,%s,%s)''',(uuid4(),kind,entity_id,action,actor,rationale))

    async def meaning_audit(self, conn, kind, entity_id):
        return await (await conn.execute('''SELECT * FROM goods.meaning_events
        WHERE entity_kind=%s AND entity_id=%s ORDER BY created_at,event_id''',(kind,entity_id))).fetchall()
