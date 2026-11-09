"""Async persistence for immutable definitions and reviewable mappings."""
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from teoria.features.semantic_modeling.goods_dictionary.repository import GoodsDictionaryRepository

# Observed product scope is independent of the reusable source-expression identity.
# Missing historical scope stays unknown; no label matching or code inference.
SOURCE_SCOPES = """WITH source_scopes AS (
    SELECT d.entry_id,coalesce(o.result->'source_classifications'->>(e.value->>'document_id'),o.result->>'classification_code') AS classification_code
    FROM goods.dictionary_decisions d
    JOIN goods.dictionary_operations o ON o.operation_id=d.operation_id
    CROSS JOIN LATERAL jsonb_array_elements(d.candidate->'evidence') e
    WHERE d.entry_id IS NOT NULL
    UNION
    SELECT source_entry_id,classification_code FROM goods.concept_mappings
    WHERE scope_mode IN ('classified','unclassified')
)"""

class GoodsMeaningRepository(GoodsDictionaryRepository):
    async def delete_meaning_records(self, conn):
        # Source expressions and audit events are separate from replaceable meaning records.
        mappings=await conn.execute('DELETE FROM goods.concept_mappings')
        concepts=await conn.execute('DELETE FROM goods.concept_revisions')
        return {'mappings':mappings.rowcount,'definitions':concepts.rowcount}

    async def all_sources(self, conn):
        return await (await conn.execute('SELECT entry_id,kind,owner_entry_id,status,preferred_name FROM goods.dictionary_entries ORDER BY entry_id')).fetchall()

    async def affected_documents(self, conn, entry_ids):
        return await (await conn.execute('''SELECT DISTINCT d.entry_id,d.operation_id,
        e.value->>'document_id' AS document_id,e.value->>'source_sha256' AS source_sha256
        FROM goods.dictionary_decisions d
        CROSS JOIN LATERAL jsonb_array_elements(d.candidate->'evidence') e
        WHERE d.entry_id=ANY(%s)
        ORDER BY d.entry_id,d.operation_id,document_id,source_sha256''',
        ([UUID(str(id)) for id in entry_ids],))).fetchall()

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

    async def meaning_event(self, conn, kind, entity_id, action, actor, rationale):
        await conn.execute('''INSERT INTO goods.meaning_events(event_id,entity_kind,entity_id,action,actor,rationale)
        VALUES (%s,%s,%s,%s,%s,%s)''',(uuid4(),kind,entity_id,action,actor,rationale))

    async def meaning_audit(self, conn, kind, entity_id):
        return await (await conn.execute('''SELECT * FROM goods.meaning_events
        WHERE entity_kind=%s AND entity_id=%s ORDER BY created_at,event_id''',(kind,entity_id))).fetchall()

    async def catalog(self, conn, kind, query, status, concept_kind, offset, limit, classification=None, unresolved=False):
        if kind == 'concept':
            table = 'goods.concept_revisions x'
            columns = 'x.*,x.concept_key AS search_key,x.content->>\'preferred_name\' AS display_name'
            search = "x.concept_key || ' ' || (x.content->>'preferred_name') || ' ' || (x.content->>'definition')"
        elif kind == 'mapping':
            table = ('goods.concept_mappings x JOIN goods.dictionary_entries s ON s.entry_id=x.source_entry_id '
                     'JOIN goods.concept_revisions c ON c.revision_id=x.target_revision_id')
            columns = "x.*,s.preferred_name AS source_name,c.concept_key,c.content,s.kind"
            search = "s.preferred_name || ' ' || c.concept_key || ' ' || x.rationale"
        else:
            table = 'goods.dictionary_entries x'
            columns = 'x.*'
            search = "x.preferred_name || ' ' || x.stable_key"
        kind_column = 's.kind' if kind == 'mapping' else 'x.kind'
        where = f"(%s::text IS NULL OR x.status=%s) AND (%s::text IS NULL OR {kind_column}=%s) AND (%s='' OR strpos(lower({search}),lower(%s))>0)"
        values = (status,status,concept_kind,concept_kind,query,query)
        if classification is not None:
            code = None if classification == 'unclassified' else classification
            if kind == 'source':
                scope = "EXISTS (SELECT 1 FROM source_scopes sc WHERE sc.entry_id=x.entry_id AND sc.classification_code IS NOT DISTINCT FROM %s::text)"
            elif kind == 'concept':
                scope = """EXISTS (SELECT 1 FROM goods.concept_mappings m
                    WHERE m.target_revision_id=x.revision_id AND (
                    (m.scope_mode!='independent' AND m.classification_code IS NOT DISTINCT FROM %s::text)
                    OR (m.scope_mode='independent' AND EXISTS (SELECT 1 FROM source_scopes sc
                        WHERE sc.entry_id=m.source_entry_id AND sc.classification_code IS NOT DISTINCT FROM %s::text))))"""
            else:
                scope = """((x.scope_mode!='independent' AND x.classification_code IS NOT DISTINCT FROM %s::text)
                    OR (x.scope_mode='independent' AND EXISTS (SELECT 1 FROM source_scopes sc
                        WHERE sc.entry_id=x.source_entry_id AND sc.classification_code IS NOT DISTINCT FROM %s::text)))"""
            where += ' AND ' + scope
            values += (code,) if kind == 'source' else (code,code)
        if unresolved:
            # An approved expression registration alone does not establish its meaning.
            where += """ AND 1 <> (SELECT count(DISTINCT m.target_revision_id) FROM goods.concept_mappings m
                JOIN goods.concept_revisions c ON c.revision_id=m.target_revision_id
                WHERE m.source_entry_id=x.entry_id AND m.status='approved' AND c.status='approved'
                AND m.relation='equivalent' AND (m.scope_mode='independent'
                  OR m.classification_code IS NOT DISTINCT FROM %s::text)
                AND (x.kind='item_type' OR m.owner_concept_id::text=(
                    SELECT CASE WHEN count(DISTINCT oc.concept_id)=1 THEN min(oc.concept_id::text) END
                    FROM goods.concept_mappings om JOIN goods.concept_revisions oc ON oc.revision_id=om.target_revision_id
                    WHERE om.source_entry_id=x.owner_entry_id AND om.status='approved' AND oc.status='approved'
                    AND om.relation='equivalent' AND (om.scope_mode='independent'
                        OR om.classification_code IS NOT DISTINCT FROM %s::text))))"""
            code = None if classification == 'unclassified' else classification
            values += (code,code)
        identifier = {'concept':'revision_id','mapping':'mapping_id','source':'entry_id'}[kind]
        rows = await (await conn.execute(f'{SOURCE_SCOPES} SELECT {columns} FROM {table} WHERE {where} ORDER BY x.created_at DESC,x.{identifier} LIMIT %s OFFSET %s',(*values,limit,offset))).fetchall()
        count = await (await conn.execute(f'{SOURCE_SCOPES} SELECT count(*) AS total FROM {table} WHERE {where}',values)).fetchone()
        return {'items':rows,'total':count['total']}

    async def classifications(self, conn, query, offset, limit):
        condition = "classification_code IS NOT NULL AND strpos(classification_code,%s)>0"
        rows = await (await conn.execute(f"""{SOURCE_SCOPES}
            SELECT classification_code,count(DISTINCT entry_id) AS expression_count
            FROM source_scopes WHERE {condition} GROUP BY classification_code
            ORDER BY classification_code LIMIT %s OFFSET %s""", (query,limit,offset))).fetchall()
        count = await (await conn.execute(f"""{SOURCE_SCOPES}
            SELECT count(DISTINCT classification_code) AS total FROM source_scopes WHERE {condition}""",(query,))).fetchone()
        return {'items':rows,'total':count['total']}
