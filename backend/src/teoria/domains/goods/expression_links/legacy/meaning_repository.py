"""Explicit v1 local-definition mutation compatibility; not wired by the Admin application."""
from uuid import uuid4
from psycopg.types.json import Jsonb

from teoria.domains.goods.expression_links.history_repository import ExpressionHistoryRepository


class LegacyMeaningRepository(ExpressionHistoryRepository):
    async def delete_meaning_records(self, conn):
        # Source expressions and audit events are separate from replaceable meaning records.
        mappings=await conn.execute('DELETE FROM goods.concept_mappings')
        concepts=await conn.execute('DELETE FROM goods.concept_revisions')
        return {'mappings':mappings.rowcount,'definitions':concepts.rowcount}

    async def add_concept(self, conn, concept_id, revision, content, digest, actor):
        return await (await conn.execute('''INSERT INTO goods.concept_revisions
        (revision_id,concept_id,concept_key,revision,kind,content,content_checksum,status,created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'draft',%s) RETURNING *''',
        (uuid4(),concept_id,content['key'],revision,content['kind'],Jsonb(content),digest,actor))).fetchone()

    async def add_mapping(self, conn, proposal, evidence, actor):
        return await (await conn.execute('''INSERT INTO goods.concept_mappings
        (mapping_id,source_entry_id,target_revision_id,classification_code,owner_concept_id,relation,rationale,evidence,status,created_by,scope_mode)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s,%s) RETURNING *''',
        (uuid4(),proposal.source_entry_id,proposal.target_revision_id,proposal.classification_code,proposal.owner_concept_id,
         proposal.relation,proposal.rationale,Jsonb(evidence),actor,proposal.scope_mode))).fetchone()

    async def set_status(self, conn, kind, entity_id, status):
        if kind=='concept':
            await conn.execute('UPDATE goods.concept_revisions SET status=%s WHERE revision_id=%s',(status,entity_id))
        elif kind=='mapping':
            await conn.execute('UPDATE goods.concept_mappings SET status=%s WHERE mapping_id=%s',(status,entity_id))
        else:
            raise ValueError('unknown meaning entity')
