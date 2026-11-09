"""Legacy v1 definition compatibility used by historical replay and migration fixtures.

The Admin application wires expression_link_service.ExpressionLinkService. New business
definitions are authored through Ontology, never through this legacy service.
"""
from uuid import UUID, uuid5

from teoria.domains.goods.expression_links.contracts import dictionary_checksum
from teoria.domains.goods.expression_links.legacy.meaning_repository import LegacyMeaningRepository
from teoria.domains.goods.expression_links.snapshot_contracts import scope_matches

NAMESPACE = UUID('3b790e06-dd7b-4fc3-b1d8-8832380578e9')


def eligible_mapping(mapping, concepts, classification_code):
    target=concepts.get(str(mapping['target_revision_id']))
    return (mapping['status']=='approved' and mapping['relation']=='equivalent' and target is not None
            and target['status']=='approved' and
            scope_matches(mapping,classification_code))


class LegacyMeaningService:
    def __init__(self, database_url=None, *, repository=None):
        self.repository=repository or LegacyMeaningRepository(database_url)

    async def snapshot(self):
        from teoria.domains.goods.expression_links.legacy.change_service import repository_snapshot
        async with self.repository.transaction() as conn:
            await self.repository.lock(conn)
            return (await repository_snapshot(self.repository,conn)).model_dump(mode='json')

    async def reset_meanings(self, request, *, actor):
        from teoria.domains.goods.expression_links.legacy.change_service import repository_snapshot
        from teoria.domains.goods.expression_links.snapshot_contracts import DictionaryMeaningReset
        request=DictionaryMeaningReset.model_validate(request)
        repo=self.repository
        async with repo.transaction() as conn:
            await repo.lock(conn)
            snapshot=await repository_snapshot(repo,conn)
            if snapshot.checksum!=request.expected_checksum:
                raise ValueError('dictionary_reset_snapshot_changed')
            for kind,records,id_key in [('mapping',snapshot.mappings,'mapping_id'),('concept',snapshot.concepts,'revision_id')]:
                for record in records:
                    await repo.meaning_event(conn,kind,record[id_key],'delete',actor,request.rationale)
            return {'status':'deleted',**await repo.delete_meaning_records(conn)}

    async def related_context(self, request):
        from teoria.domains.goods.expression_links.legacy.change_service import repository_snapshot, affected_scopes
        async with self.repository.transaction() as conn:
            await self.repository.lock(conn)
            snapshot=await repository_snapshot(self.repository,conn)
            entries={str(id) for id in request.source_entry_ids}
            concepts={str(id) for id in request.concept_ids}
            if request.changes:
                if request.changes.baseline_checksum!=snapshot.checksum:
                    return {'status':'stale','baseline_checksum':snapshot.checksum,'source_entry_ids':[],'documents':[]}
                entries.update(scope[0] for scope in affected_scopes(snapshot,request.changes))
            targets={str(c['revision_id']):str(c['concept_id']) for c in snapshot.concepts if c['status']=='approved'}
            while True:
                before=(len(entries),len(concepts))
                for mapping in snapshot.mappings:
                    cid=targets.get(str(mapping['target_revision_id']))
                    if mapping['status']=='approved' and cid and (str(mapping['source_entry_id']) in entries
                        or cid in concepts or str(mapping.get('owner_concept_id')) in concepts):
                        entries.add(str(mapping['source_entry_id']));concepts.add(cid)
                if before==(len(entries),len(concepts)):break
                if len(entries)>5000:
                    return {'status':'held','reason':'related_context_budget_exceeded','source_entry_ids':[],'documents':[]}
            documents=await self.repository.affected_documents(conn,entries)
            return {'status':'ready','baseline_checksum':snapshot.checksum,'source_entry_ids':sorted(entries),
                    'concept_ids':sorted(concepts),'documents':documents}

    async def apply_changes(self, operation_id, changes, *, actor):
        from teoria.domains.goods.expression_links.legacy.change_service import apply_change_set
        return await apply_change_set(self.repository,operation_id,changes,actor=actor)

    async def preview_changes(self, changes):
        from teoria.domains.goods.expression_links.legacy.change_service import repository_snapshot, preview_change_set, validate_document_coverage
        from teoria.domains.goods.expression_links.snapshot_contracts import DictionaryChangeSet
        changes=DictionaryChangeSet.model_validate(changes)
        async with self.repository.transaction() as conn:
            await self.repository.lock(conn)
            try:
                preview = preview_change_set(await repository_snapshot(self.repository,conn),changes)
            except ValueError as exc:
                return {'status':'blocked','reason':str(exc)}
            documents=await self.repository.affected_documents(conn,{r['source_entry_id'] for r in preview['impact']})
            try:
                validate_document_coverage(preview['impact'],changes,documents)
            except ValueError as exc:
                return {'status':'blocked','reason':str(exc),'affected_documents':documents}
            return {'status':'valid','snapshot':preview['snapshot'].model_dump(mode='json'),
                    'impact':preview['impact'],'affected_documents':documents}

    async def propose_concept(self, definition, *, actor):
        repo=self.repository
        async with repo.transaction() as conn:
            await repo.lock(conn)
            rows=await repo.concepts(conn)
            same=[r for r in rows if r['concept_key']==definition.key]
            digest=dictionary_checksum(definition)
            if same and same[-1]['content_checksum']==digest and same[-1]['status'] in {'draft','approved'}:
                return same[-1]
            if same and same[0]['kind']!=definition.kind:
                raise ValueError('stable concept kind cannot change')
            self._validate_applicability(definition.model_dump(mode='json'), rows)
            row=await repo.add_concept(conn,uuid5(NAMESPACE,definition.key),max([r['revision'] for r in same],default=0)+1,
                                       definition.model_dump(mode='json'),digest,actor)
            await repo.meaning_event(conn,'concept',row['revision_id'],'proposed',actor,'immutable definition proposal')
            return row

    def _validate_applicability(self, content, rows):
        approved={str(r['concept_id']) for r in rows if r['status']=='approved' and r['kind']=='item_type'}
        if any(str(x) not in approved for x in content.get('applicable_item_type_ids',[])):
            raise ValueError('applicability requires approved item type definitions')

    async def propose_mapping(self, proposal, *, actor):
        repo=self.repository
        async with repo.transaction() as conn:
            await repo.lock(conn)
            source=await repo.by_id(conn,proposal.source_entry_id)
            target=await repo.concept(conn,proposal.target_revision_id)
            await self._validate_mapping(conn,source,target,proposal.owner_concept_id)
            evidence=await repo.source_evidence(conn,proposal.source_entry_id)
            if not evidence:
                raise ValueError('mapping requires registered source evidence')
            for existing in await repo.mappings(conn):
                if existing['status'] in {'draft','approved'} and all(
                    str(existing.get(k))==str(v) for k,v in proposal.model_dump().items()):
                    return existing
            row=await repo.add_mapping(conn,proposal,evidence,actor)
            await repo.meaning_event(conn,'mapping',row['mapping_id'],'proposed',actor,proposal.rationale)
            return row

    async def _validate_mapping(self, conn, source, target, owner_id):
        if not source or not target or target['status']!='approved' or source['kind']!=target['kind']:
            raise ValueError('mapping requires source and approved target of the same kind')
        if source['kind']=='item_type':
            if owner_id:
                raise ValueError('item type mapping cannot have a characteristic owner')
        else:
            rows=await self.repository.concepts(conn)
            self._validate_applicability(target['content'], rows)
            if str(owner_id) not in target['content']['applicable_item_type_ids']:
                raise ValueError('characteristic mapping requires an applicable owner concept')

    async def decide(self, kind, entity_id, decision, *, actor):
        repo=self.repository
        async with repo.transaction() as conn:
            await repo.lock(conn)
            row=await (repo.concept(conn,entity_id) if kind=='concept' else repo.mapping(conn,entity_id))
            if row is None:
                raise KeyError(entity_id)
            wanted={'approve':'approved','reject':'rejected','deprecate':'deprecated'}[decision.action]
            if row['status']==wanted:
                return row
            allowed={'draft':{'approve','reject'},'approved':{'deprecate'}}
            if decision.action not in allowed.get(row['status'],set()):
                raise ValueError('invalid meaning lifecycle transition')
            if wanted=='approved' and kind=='concept':
                rows=await repo.concepts(conn)
                if any(r['concept_id']==row['concept_id'] and r['revision']>row['revision'] for r in rows):
                    raise ValueError('only the latest concept revision can be approved')
                self._validate_applicability(row['content'],rows)
                for old in rows:
                    if old['concept_id']==row['concept_id'] and old['status']=='approved':
                        await repo.set_status(conn,'concept',old['revision_id'],'deprecated')
                        await repo.meaning_event(conn,'concept',old['revision_id'],'superseded',actor,decision.rationale)
            if wanted=='approved' and kind=='mapping':
                await self._validate_mapping(conn,await repo.by_id(conn,row['source_entry_id']),
                    await repo.concept(conn,row['target_revision_id']),row['owner_concept_id'])
            await repo.set_status(conn,kind,entity_id,wanted)
            await repo.meaning_event(conn,kind,entity_id,decision.action,actor,decision.rationale)
            return {**row,'status':wanted}

    async def resolve(self, request):
        repo=self.repository
        async with repo.transaction() as conn:
            # One consistent authoring snapshot; never infer equivalence from spelling.
            await repo.lock(conn)
            concepts={str(r['revision_id']):r for r in await repo.concepts(conn)}
            mappings=[m for m in await repo.mappings(conn) if eligible_mapping(m,concepts,request.classification_code)]
            results={}
            async def resolve_entry(entry_id, path=frozenset()):
                key=str(entry_id)
                if key in results:return results[key]
                if key in path:return {'status':'unresolved','reason':'cyclic_owner'}
                entry=await repo.by_id(conn,entry_id)
                if not entry:return {'source_entry_id':key,'status':'unresolved','reason':'source_not_found'}
                choices=[m for m in mappings if str(m['source_entry_id'])==key]
                if entry['kind']=='characteristic':
                    owner=await resolve_entry(entry['owner_entry_id'],path|{key})
                    choices=[m for m in choices if owner['status']=='resolved' and str(m['owner_concept_id'])==owner['concept_id']]
                targets={str(m['target_revision_id']) for m in choices}
                result={'source_entry_id':key,'status':'unresolved','reason':'no_approved_scoped_equivalence'}
                if len(targets)>1:
                    result.update(status='held',reason='ambiguous_approved_mappings')
                elif targets:
                    target=concepts[next(iter(targets))]
                    result.update(status='resolved',reason='approved_scoped_equivalence',concept_id=str(target['concept_id']),
                        revision_id=str(target['revision_id']),concept_key=target['concept_key'],kind=target['kind'],
                        definition=target['content'],mapping_ids=[str(m['mapping_id']) for m in choices])
                results[key]=result
                return result
            return {'policy_version':'approved_scoped_equivalence_v1','items':[await resolve_entry(x) for x in request.source_entry_ids]}

    async def list_records(self, kind):
        async with self.repository.transaction() as conn:
            return await (self.repository.concepts(conn) if kind=='concept' else self.repository.mappings(conn))

    async def audit(self, kind, entity_id):
        async with self.repository.transaction() as conn:
            return await self.repository.meaning_audit(conn,kind,entity_id)

    async def catalog(self, kind, *, query='', status=None, concept_kind=None, offset=0, limit=25, classification=None, unresolved=False):
        async with self.repository.transaction() as conn:
            return await self.repository.catalog(conn,kind,query,status,concept_kind,offset,limit,classification,unresolved)

    async def source_evidence(self, entry_id):
        async with self.repository.transaction() as conn:
            if await self.repository.by_id(conn,entry_id) is None:
                raise KeyError(entry_id)
            return await self.repository.source_evidence(conn,entry_id)

    async def classifications(self, *, query='', offset=0, limit=25):
        async with self.repository.transaction() as conn:
            return await self.repository.classifications(conn,query,offset,limit)
