"""Transient asset context. Source systems keep authority and stored state."""

import asyncio
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from teoria.metadata.openmetadata.mapper import table_detail
from teoria.metadata.openmetadata import OpenMetadataError


def asset_targets(document: dict) -> tuple[list[str], list[str]]:
    """Exact authoritative FQNs; never match a neighboring asset by prefix."""
    assets = {document['fullyQualifiedName']}
    terms = set()

    def collect(node):
        for tag in node.get('tags') or []:
            if tag.get('source') == 'Glossary' and tag.get('tagFQN'):
                terms.add(tag['tagFQN'])
        for column in node.get('columns') or node.get('children') or []:
            if column.get('fullyQualifiedName'):
                assets.add(column['fullyQualifiedName'])
            collect(column)

    collect(document)
    return sorted(assets), sorted(terms)


class AssetApplicationReader:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def __call__(self, table_id: str, assets: list[str], terms: list[str]) -> dict:
        targets = assets + terms
        refs = targets + [table_id, f'openmetadata://table/{table_id}', f'openmetadata://table/{assets[0]}']
        refs += [f'openmetadata://column/{fqn}' for fqn in assets]
        refs += [f'openmetadata://glossaryTerm/{fqn}' for fqn in terms]
        with psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=3,
                             options="-c default_transaction_read_only=on -c statement_timeout=3000") as connection:
            bindings = connection.execute(
                """SELECT b.binding_id,b.status,b.binding_type,b.authority,b.approved_by,
                          c.stable_key,c.concept_kind,o.namespace,t.entity_type,t.fully_qualified_name
                     FROM binding.ontology_bindings b
                     JOIN binding.metadata_targets t USING (metadata_target_id)
                     JOIN ontology.concepts c ON c.concept_id=b.ontology_concept_id
                     JOIN ontology.ontologies o ON o.ontology_id=c.ontology_id
                    WHERE t.system='openmetadata' AND (
                         t.fully_qualified_name=ANY(%s) OR
                         (t.entity_type='table' AND t.external_entity_id=%s))
                    ORDER BY b.created_at DESC,b.binding_id LIMIT 51""",
                (targets, table_id),
            ).fetchall()
            suggestions = connection.execute(
                """SELECT s.suggestion_id,s.target_ref,s.suggestion_type,s.status,s.confidence,
                          s.risk_level,s.created_at,r.decision,r.reviewer,r.reviewed_at,
                          a.status AS application_status,a.applied_at,a.error_code AS application_error_code
                     FROM intelligence.suggestions s
                     LEFT JOIN LATERAL (
                         SELECT decision,reviewer,reviewed_at FROM intelligence.reviews r
                         WHERE r.suggestion_id=s.suggestion_id ORDER BY reviewed_at DESC LIMIT 1
                     ) r ON true
                     LEFT JOIN LATERAL (
                         SELECT status,applied_at,error_code FROM intelligence.change_applications a
                         WHERE a.suggestion_id=s.suggestion_id ORDER BY attempted_at DESC NULLS LAST LIMIT 1
                     ) a ON true
                    WHERE s.target_ref=ANY(%s)
                    ORDER BY s.created_at DESC,s.suggestion_id LIMIT 51""",
                (refs,),
            ).fetchall()
        return {'bindings': bindings[:50], 'suggestions': suggestions[:50],
                'bindings_truncated': len(bindings)>50, 'suggestions_truncated': len(suggestions)>50}


async def section_read(reader, *args):
    if reader is None:
        return {'status': 'unconfigured', 'reason': 'connection_not_configured'}
    try:
        return {'status': 'available', 'data': await asyncio.to_thread(reader, *args)}
    except psycopg.errors.UndefinedTable:
        return {'status': 'unavailable', 'reason': 'schema_not_ready'}
    except (psycopg.Error, TimeoutError, OSError):
        return {'status': 'unavailable', 'reason': 'source_unavailable'}


class AssetContextService:
    def __init__(self, client, *, database_service: str, operations_reader=None, application_reader=None):
        self.client = client
        self.database_service = database_service
        self.operations_reader = operations_reader
        self.application_reader = application_reader

    async def get(self, table_id: str):
        document = await self.client.get(f'v1/tables/{table_id}', params={
            'fields': 'owners,tags,domains,columns,database,databaseSchema,testSuite'})
        if str(document.get('id', '')).lower() != table_id.lower():
            raise OpenMetadataError('openmetadata_invalid_response', 'Table identity does not match')
        assets, terms = asset_targets(document)
        database = (document.get('database') or {}).get('name')
        schema = (document.get('databaseSchema') or {}).get('name')
        service = (document.get('service') or {}).get('name')
        operations_args = (database, schema, document['name'])
        operations_reader = self.operations_reader if service == self.database_service and database and schema else None
        operations, application = await asyncio.gather(
            section_read(operations_reader, *operations_args),
            section_read(self.application_reader, table_id, assets, terms),
        )
        if operations_reader is None and self.operations_reader is not None:
            operations = {'status': 'not_linked', 'reason': 'outside_configured_data_source'}
        elif operations.get('status') == 'available' and not operations['data']:
            operations['status'] = 'not_linked'
        return {'observed_at': datetime.now(timezone.utc),
                'technical': table_detail(document).model_dump(mode='json'),
                'operations': {**operations, 'source': 'teoria_data.pipeline_audit'},
                'business': {**application, 'source': 'teoria_app', 'glossary_terms': terms}}
