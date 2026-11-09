"""Govern source-expression links; the Ontology owns every new business definition."""
from uuid import UUID

from teoria.domains.goods.expression_links.contracts import dictionary_checksum
from teoria.platform.ontology.authoring.publication_contracts import PublishedOntology
from teoria.domains.goods.expression_links.expression_link_repository import ExpressionLinkRepository
from teoria.domains.goods.expression_links.expression_contracts import (
    OntologyMappingProposal, expression_snapshot, published_concepts, resolve_expression_snapshot,
)


class ExpressionLinkService:
    def __init__(self, database_url=None, *, repository=None, ontology_authoring):
        self.repository = repository or ExpressionLinkRepository(database_url)
        self.ontology_authoring = ontology_authoring

    async def ontology_dependencies(self, namespace):
        async with self.repository.transaction() as conn:
            rows = await self.repository.ontology_dependencies(conn, namespace)
        return [{'kind':'expression_mapping','id':str(r['mapping_id']),'status':r['status'],
                 'ontology':{'version_id':str(r['ontology_version_id']),'checksum':r['ontology_checksum'],
                             'namespace':r['namespace'],'version':r['version']},
                 'concept_ids':[str(x) for x in (r['target_concept_id'],r['owner_concept_id']) if x is not None]}
                for r in rows]

    async def _artifact(self, version_id, checksum, conn, *, allow_deprecated=False):
        artifact = await self.ontology_authoring.published_artifact(
            UUID(str(version_id)), expected_checksum=checksum, connection=conn,
            lock=True, allow_deprecated=allow_deprecated)
        if artifact is None or dictionary_checksum(artifact['content']) != artifact['checksum']:
            raise ValueError('verified_published_ontology_required')
        content = artifact['content']
        reference = {'version_id': str(version_id), 'namespace': content['namespace'],
                     'version': content['version'], 'checksum': artifact['checksum']}
        return PublishedOntology(ontology=reference, content=content).model_dump(mode='json')

    async def _snapshot(self, conn):
        artifacts = [await self._artifact(v['ontology_version_id'], v['checksum'], conn)
                     for v in await self.repository.published_versions(conn)]
        versions = {a['ontology']['version_id']: a['ontology']['checksum'] for a in artifacts}
        # A newly published version never silently changes a reviewed link's meaning.
        mappings = [m for m in await self.repository.mappings(conn)
                    if versions.get(str(m['ontology_version_id'])) == m['ontology_checksum']]
        fields = ('mapping_id','source_entry_id','ontology_version_id','target_concept_id',
                  'owner_concept_id','classification_code','scope_mode','relation','status')
        return expression_snapshot(artifacts, [{k: m[k] for k in fields} for m in mappings],
                                   await self.repository.all_sources(conn))

    async def snapshot(self):
        async with self.repository.transaction() as conn:
            await self.repository.lock(conn)
            return (await self._snapshot(conn)).model_dump(mode='json')

    async def resolve(self, request):
        async with self.repository.transaction() as conn:
            await self.repository.lock(conn)
            return resolve_expression_snapshot(await self._snapshot(conn), request.source_entry_ids, request.classification_code)

    async def propose_concept(self, definition, *, actor):
        raise ValueError('ontology_draft_required: define business meaning in Ontology authoring')

    async def apply_changes(self, operation_id, changes, *, actor):
        raise ValueError('ontology_draft_required: local dictionary definitions are historical')

    async def preview_changes(self, changes):
        return {'status': 'blocked', 'reason': 'ontology_draft_required'}

    async def reset_meanings(self, request, *, actor):
        raise ValueError('historical_dictionary_records_are_preserved')

    async def _validate(self, conn, source_id, version_id, checksum, target_id, owner_id):
        source = await self.repository.by_id(conn, source_id)
        artifact = await self._artifact(version_id, checksum, conn)
        target = next((c for c in published_concepts(artifact['content'], artifact['ontology'])
                       if c['concept_id'] == str(target_id)), None)
        if source is None or target is None or source['kind'] != target['kind']:
            raise ValueError('mapping requires a source and published target of the same kind')
        owner = str(owner_id) if owner_id else None
        if target['owner_concept_id'] != owner:
            raise ValueError('mapping owner must match the published property owner')
        evidence = await self.repository.source_evidence(conn, source_id)
        if not evidence:
            raise ValueError('mapping requires registered source evidence')
        return target, evidence

    async def propose_mapping(self, proposal, *, actor):
        if not isinstance(proposal, OntologyMappingProposal):
            raise ValueError('published_ontology_reference_required')
        async with self.repository.transaction() as conn:
            await self.repository.lock(conn)
            target, evidence = await self._validate(conn, proposal.source_entry_id,
                proposal.ontology.version_id, proposal.ontology.checksum,
                proposal.target_concept_id, proposal.owner_concept_id)
            if target['ontology'] != proposal.ontology.model_dump(mode='json'):
                raise ValueError('ontology_reference_identity_mismatch')
            row = await self.repository.add_ontology_mapping(conn, proposal, evidence, actor)
            await self.repository.meaning_event(conn, 'mapping', row['mapping_id'], 'proposed', actor, proposal.rationale)
            return row

    async def decide(self, kind, entity_id, decision, *, actor):
        if kind != 'mapping':
            raise ValueError('ontology_draft_required')
        async with self.repository.transaction() as conn:
            await self.repository.lock(conn)
            row = await self.repository.mapping(conn, entity_id)
            if row is None:
                raise KeyError(entity_id)
            wanted = {'approve':'approved','reject':'rejected','deprecate':'deprecated'}[decision.action]
            if wanted == row['status']:
                return row
            if decision.action not in {'draft': {'approve','reject'}, 'approved': {'deprecate'}}.get(row['status'], set()):
                raise ValueError('invalid meaning lifecycle transition')
            if wanted == 'approved':
                await self._validate(conn, row['source_entry_id'], row['ontology_version_id'],
                    row['ontology_checksum'], row['target_concept_id'], row['owner_concept_id'])
            await self.repository.set_status(conn, 'mapping', entity_id, wanted)
            await self.repository.meaning_event(conn, 'mapping', entity_id, decision.action, actor, decision.rationale)
            return {**row, 'status': wanted}

    async def related_context(self, request):
        async with self.repository.transaction() as conn:
            entries = {str(x) for x in request.source_entry_ids}
            concepts = {str(x) for x in request.concept_ids}
            for mapping in await self.repository.mappings(conn):
                if str(mapping['target_concept_id']) in concepts or str(mapping.get('owner_concept_id')) in concepts:
                    entries.add(str(mapping['source_entry_id']))
            return {'status': 'ready', 'source_entry_ids': sorted(entries),
                    'documents': await self.repository.affected_documents(conn, entries)}

    async def catalog(self, kind, *, query='', status=None, concept_kind=None, offset=0,
                      limit=25, classification=None, unresolved=False, historical=False):
        if historical:
            if kind == 'source':
                raise ValueError('historical catalog contains only definitions and mappings')
            async with self.repository.transaction() as conn:
                result = await self.repository.catalog(conn, kind, query, status, concept_kind,
                    offset, limit, classification)
            return {**result, 'items': [{**r, 'historical': True} for r in result['items']]}
        async with self.repository.transaction() as conn:
            await self.repository.lock(conn)
            if kind == 'source':
                return await self.repository.source_catalog(conn, query, status, concept_kind, offset, limit, classification, unresolved)
            snapshot = await self._snapshot(conn)
            concepts = {(c['ontology']['version_id'], c['concept_id']): c for c in snapshot.concepts}
            if kind == 'concept':
                rows = list(concepts.values())
                if classification is not None:
                    links = await self._scoped_links(conn, snapshot.mappings, classification)
                    keys = {(str(m['ontology_version_id']), str(m['target_concept_id'])) for m in links}
                    rows = [c for key, c in concepts.items() if key in keys]
            else:
                links = await self.repository.mappings(conn)
                if classification is not None:
                    links = await self._scoped_links(conn, links, classification)
                sources = {str(s['entry_id']): s for s in snapshot.sources}
                rows = []
                for mapping in links:
                    key = (str(mapping['ontology_version_id']), str(mapping['target_concept_id']))
                    target = concepts.get(key)
                    if target is None:
                        artifact = await self._artifact(mapping['ontology_version_id'], mapping['ontology_checksum'], conn, allow_deprecated=True)
                        target = next(c for c in published_concepts(artifact['content'], artifact['ontology']) if c['concept_id'] == str(mapping['target_concept_id']))
                    rows.append({**target, **mapping, 'source_name': sources[str(mapping['source_entry_id'])]['preferred_name'],
                                 'requires_review': key not in concepts})
            rows = [r for r in rows if (status is None or r['status'] == status)
                    and (concept_kind is None or r['kind'] == concept_kind)
                    and (not query or query.lower() in (' '.join([r.get('source_name',''), r['concept_key'], r['content']['preferred_name'], r['content']['definition']])).lower())]
            rows.sort(key=lambda r: (r['concept_key'], str(r.get('mapping_id',''))))
            return {'items': rows[offset:offset+limit], 'total': len(rows)}

    async def _scoped_links(self, conn, links, classification):
        code = None if classification == 'unclassified' else classification
        return [m for m in links if (m['scope_mode'] != 'independent' and m['classification_code'] == code)
                or (m['scope_mode'] == 'independent' and await self.repository.observed_in_scope(conn, m['source_entry_id'], classification))]

    async def list_records(self, kind):
        return (await self.catalog(kind, limit=500))['items']

    async def audit(self, kind, entity_id):
        # Definition history remains available. Canonical definition edits use Ontology audit.
        async with self.repository.transaction() as conn:
            return await self.repository.meaning_audit(conn, kind, entity_id)

    async def source_evidence(self, entry_id):
        async with self.repository.transaction() as conn:
            if await self.repository.by_id(conn, entry_id) is None:
                raise KeyError(entry_id)
            return await self.repository.source_evidence(conn, entry_id)

    async def classifications(self, *, query='', offset=0, limit=25):
        async with self.repository.transaction() as conn:
            return await self.repository.classifications(conn, query, offset, limit)

    async def import_legacy_definitions(self, request, *, actor):
        """An explicit, resumable Draft proposal. Never publish or create expression links."""
        detail = await self.ontology_authoring.get_version(request.ontology_draft_id)
        if detail['status'] != 'draft':
            raise ValueError('editable_ontology_draft_required')
        async with self.repository.transaction() as conn:
            legacy = await self.repository.concepts(conn)
        by_id = {str(c['revision_id']): c for c in legacy}
        selected = []
        for revision_id in request.revision_ids:
            row = by_id.get(str(revision_id))
            if row is None:
                raise KeyError(revision_id)
            selected.append(row)
        # Include the exact approved owner definition, never infer owners from names.
        for row in list(selected):
            for owner_id in row['content'].get('applicable_item_type_ids', []):
                owners = [c for c in legacy if str(c['concept_id']) == str(owner_id)
                          and c['status'] == 'approved' and c['kind'] == 'item_type']
                if len(owners) != 1:
                    raise ValueError('legacy owner requires an explicit approved definition')
                if owners[0] not in selected:
                    selected.append(owners[0])
        results = []
        owners = {}
        for row in sorted(selected, key=lambda r: (r['kind'] != 'item_type', r['concept_key'])):
            content = row['content']
            source_id = str(row['revision_id'])
            result = {'legacy_revision_id': source_id, 'legacy_concept_id': str(row['concept_id'])}
            if row['kind'] == 'characteristic' and (content.get('value_kind') not in {'number','text'}
                or len(content['applicable_item_type_ids']) != 1):
                results.append({**result, 'status':'held', 'reason':'manual_property_modeling_required'})
                continue
            key = detail['namespace'] + '.dictionary_' + content['key']
            payload = {'code': 'dictionary_' + content['key'], 'stable_key': key,
                       'name': content['preferred_name'], 'description': content['definition']}
            kind = 'object' if row['kind'] == 'item_type' else 'property'
            if kind == 'property':
                owner = owners.get(str(content['applicable_item_type_ids'][0]))
                if owner is None:
                    raise ValueError('import the owner before its property')
                payload.update(object_concept_id=owner, value_type='decimal' if content['value_kind'] == 'number' else 'string',
                               unit=content.get('canonical_unit'), quantity_dimension=content.get('quantity_dimension'),
                               allowed_units=content.get('allowed_units', []))
            existing = (detail['objects'] if kind == 'object' else [
                {**p, 'object_concept_id': o['concept_id']} for o in detail['objects'] for p in o['properties']])
            previous = next((x for x in existing if x['stable_key'] == key), None)
            if previous is not None:
                if any(previous.get(k) != v for k,v in payload.items()):
                    raise ValueError('existing_draft_concept_differs_from_legacy_proposal')
                item = previous
            else:
                item = await self.ontology_authoring.add_item(request.ontology_draft_id, kind=kind,
                    payload={**payload, 'dictionary_origin': {**result, 'references': content.get('references', []),
                             'rationale': request.rationale}}, actor=actor)
            if kind == 'object':
                owners[str(row['concept_id'])] = str(item['concept_id'])
            results.append({**result, 'status':'draft', 'concept_id': str(item['concept_id']), 'stable_key':key})
            detail = await self.ontology_authoring.get_version(request.ontology_draft_id)
        return {'ontology_draft_id':str(request.ontology_draft_id), 'status':'proposed',
                'published':False, 'expression_links_created':False, 'items':results}
