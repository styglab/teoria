"""Persist expression decisions, retaining Ontology references instead of definitions."""
from uuid import uuid4
from psycopg.types.json import Jsonb

from teoria.features.semantic_modeling.goods_dictionary.meaning_repository import GoodsMeaningRepository


EXPRESSION_SCOPES = """WITH source_scopes AS (
    SELECT d.entry_id,coalesce(o.result->'source_classifications'->>(e.value->>'document_id'),o.result->>'classification_code') AS classification_code
    FROM goods.dictionary_decisions d JOIN goods.dictionary_operations o USING(operation_id)
    CROSS JOIN LATERAL jsonb_array_elements(d.candidate->'evidence') e
    WHERE d.entry_id IS NOT NULL
    UNION SELECT source_entry_id,classification_code FROM goods.dictionary_ontology_mappings
    WHERE scope_mode IN ('classified','unclassified')
)"""


class OntologyDictionaryRepository(GoodsMeaningRepository):
    async def ontology_dependencies(self, conn, namespace):
        return await (await conn.execute("""SELECT m.mapping_id,m.status,m.ontology_version_id,
            m.ontology_checksum,m.target_concept_id,m.owner_concept_id,o.namespace,v.version
            FROM goods.dictionary_ontology_mappings m
            JOIN ontology.ontology_versions v USING(ontology_version_id)
            JOIN ontology.ontologies o USING(ontology_id)
            WHERE o.namespace=%s AND m.status IN ('draft','approved') ORDER BY m.mapping_id""", (namespace,))).fetchall()

    async def published_versions(self, conn):
        return await (await conn.execute("""SELECT a.ontology_version_id,a.checksum
            FROM ontology.runtime_artifacts a JOIN ontology.ontology_versions v USING(ontology_version_id)
            WHERE v.status='published' ORDER BY a.ontology_version_id""")).fetchall()

    async def mappings(self, conn):
        return await (await conn.execute('SELECT * FROM goods.dictionary_ontology_mappings ORDER BY created_at,mapping_id')).fetchall()

    async def mapping(self, conn, mapping_id):
        return await (await conn.execute('SELECT * FROM goods.dictionary_ontology_mappings WHERE mapping_id=%s', (mapping_id,))).fetchone()

    async def add_ontology_mapping(self, conn, proposal, evidence, actor):
        return await (await conn.execute("""INSERT INTO goods.dictionary_ontology_mappings
            (mapping_id,source_entry_id,ontology_version_id,ontology_checksum,target_concept_id,
             owner_concept_id,classification_code,scope_mode,relation,rationale,evidence,status,created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s) RETURNING *""",
            (uuid4(),proposal.source_entry_id,proposal.ontology.version_id,proposal.ontology.checksum,
             proposal.target_concept_id,proposal.owner_concept_id,proposal.classification_code,
             proposal.scope_mode,proposal.relation,proposal.rationale,Jsonb(evidence),actor))).fetchone()

    async def set_status(self, conn, kind, entity_id, status):
        if kind != 'mapping':
            raise ValueError('ontology_draft_required')
        await conn.execute('UPDATE goods.dictionary_ontology_mappings SET status=%s WHERE mapping_id=%s', (status,entity_id))

    async def source_catalog(self, conn, query, status, concept_kind, offset, limit, classification, unresolved):
        where = ["(%s::text IS NULL OR x.status=%s)", "(%s::text IS NULL OR x.kind=%s)",
                 "(%s='' OR strpos(lower(x.preferred_name || ' ' || x.stable_key),lower(%s))>0)"]
        params = [status,status,concept_kind,concept_kind,query,query]
        code = None if classification == 'unclassified' else classification
        if classification is not None:
            where.append('EXISTS (SELECT 1 FROM source_scopes sc WHERE sc.entry_id=x.entry_id AND sc.classification_code IS NOT DISTINCT FROM %s::text)')
            params.append(code)
        if unresolved:
            where.append("""1 <> (SELECT count(DISTINCT (m.ontology_version_id,m.target_concept_id))
                FROM goods.dictionary_ontology_mappings m
                JOIN ontology.ontology_versions v ON v.ontology_version_id=m.ontology_version_id
                WHERE m.source_entry_id=x.entry_id AND m.status='approved' AND v.status='published'
                AND m.relation='equivalent' AND (m.scope_mode='independent' OR m.classification_code IS NOT DISTINCT FROM %s::text)
                AND (x.kind='item_type' OR EXISTS (
                    SELECT 1 FROM goods.dictionary_ontology_mappings om
                    WHERE om.source_entry_id=x.owner_entry_id AND om.status='approved' AND om.relation='equivalent'
                    AND om.ontology_version_id=m.ontology_version_id AND om.target_concept_id=m.owner_concept_id
                    AND (om.scope_mode='independent' OR om.classification_code IS NOT DISTINCT FROM %s::text)
                    AND 1=(SELECT count(DISTINCT (am.ontology_version_id,am.target_concept_id))
                        FROM goods.dictionary_ontology_mappings am JOIN ontology.ontology_versions av ON av.ontology_version_id=am.ontology_version_id
                        WHERE am.source_entry_id=x.owner_entry_id AND am.status='approved' AND am.relation='equivalent'
                        AND av.status='published' AND (am.scope_mode='independent' OR am.classification_code IS NOT DISTINCT FROM %s::text)))))""")
            params.extend([code,code,code])
        condition = ' AND '.join(where)
        items = await (await conn.execute(f'{EXPRESSION_SCOPES} SELECT x.* FROM goods.dictionary_entries x WHERE {condition} ORDER BY x.created_at DESC,x.entry_id LIMIT %s OFFSET %s', (*params,limit,offset))).fetchall()
        total = await (await conn.execute(f'{EXPRESSION_SCOPES} SELECT count(*) AS total FROM goods.dictionary_entries x WHERE {condition}', params)).fetchone()
        return {'items': items, 'total': total['total']}

    async def classifications(self, conn, query, offset, limit):
        condition = 'classification_code IS NOT NULL AND strpos(classification_code,%s)>0'
        rows = await (await conn.execute(f'{EXPRESSION_SCOPES} SELECT classification_code,count(DISTINCT entry_id) AS expression_count FROM source_scopes WHERE {condition} GROUP BY classification_code ORDER BY classification_code LIMIT %s OFFSET %s', (query,limit,offset))).fetchall()
        total = await (await conn.execute(f'{EXPRESSION_SCOPES} SELECT count(DISTINCT classification_code) AS total FROM source_scopes WHERE {condition}', (query,))).fetchone()
        return {'items': rows, 'total': total['total']}

    async def observed_in_scope(self, conn, entry_id, classification):
        code = None if classification == 'unclassified' else classification
        return bool(await (await conn.execute(f'{EXPRESSION_SCOPES} SELECT 1 FROM source_scopes WHERE entry_id=%s AND classification_code IS NOT DISTINCT FROM %s::text LIMIT 1', (entry_id,code))).fetchone())
