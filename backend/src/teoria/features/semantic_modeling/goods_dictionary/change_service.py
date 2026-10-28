"""Atomic dictionary revisions and remapping, guarded by a frozen baseline and impact coverage."""
from copy import deepcopy
import re
from uuid import UUID, uuid5

from teoria.features.semantic_modeling.goods_dictionary.contracts import dictionary_checksum
from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import (
    ConceptDefinition, DictionaryChangeSet, DictionarySnapshot, MappingProposal,
    concept_id_for_key, resolve_snapshot, snapshot_from_records,
)


def affected_scopes(before, changes):
    ids_by_key={c['concept_key']:str(c['concept_id']) for c in before.concepts}
    changed_ids = {ids_by_key.get(d.definition.key,str(concept_id_for_key(d.definition.key))) for d in changes.definitions}
    changed_ids.update(str(x) for x in changes.retire_concept_ids)
    changed_sources = {str(m.source_entry_id) for m in changes.mappings}
    sources = {str(s['entry_id']):s for s in before.sources}
    impacted = set(changed_sources)
    for mapping in before.mappings:
        if mapping['status']!='approved':
            continue
        target = next((c for c in before.concepts if str(c['revision_id'])==str(mapping['target_revision_id'])),None)
        if (target and str(target['concept_id']) in changed_ids) or str(mapping.get('owner_concept_id')) in changed_ids:
            impacted.add(str(mapping['source_entry_id']))
    # Reassigning an owner's meaning also requires reassessing its dependent expressions.
    while True:
        children = {key for key,source in sources.items() if str(source.get('owner_entry_id')) in impacted}
        if children.issubset(impacted):
            break
        impacted.update(children)
    scopes = {(str(m.source_entry_id),m.classification_code) for m in changes.mappings}
    scopes.update((str(m['source_entry_id']),m['classification_code']) for m in before.mappings
                  if m['status']=='approved' and str(m['source_entry_id']) in impacted)
    return scopes


def change_impact(before, after, changes):
    rows = []
    scopes = affected_scopes(before,changes)
    # A global replacement must also remain compatible with existing classified mappings.
    touched = {s for s,_ in scopes}
    scopes.update((str(m['source_entry_id']),m['classification_code']) for m in after.mappings
                  if m['status']=='approved' and str(m['source_entry_id']) in touched)
    for source,classification in sorted(scopes,key=lambda pair:(pair[0],pair[1] or '')):
        old = resolve_snapshot(before,[source],classification)['items'][0]
        new = resolve_snapshot(after,[source],classification)['items'][0]
        rows.append({'source_entry_id':source,'classification_code':classification,
                     'before':old,'after':new})
    return rows


def validate_document_coverage(impact, changes, documents):
    changed = {r['source_entry_id'] for r in impact
        if (r['before']['status'],r['before'].get('revision_id'))!=(r['after']['status'],r['after'].get('revision_id'))}
    unreviewed = {d['source_sha256'] for d in documents if str(d['entry_id']) in changed
                  and d['source_sha256'] not in changes.reviewed_source_sha256}
    if unreviewed:
        raise ValueError('affected_historical_documents_require_reassessment')


def preview_change_set(snapshot, changes):
    before = DictionarySnapshot.model_validate(snapshot)
    changes = DictionaryChangeSet.model_validate(changes)
    if before.checksum != changes.baseline_checksum:
        raise ValueError('dictionary_baseline_changed')
    data = deepcopy(before.content())
    concepts,mappings,sources = data['concepts'],data['mappings'],data['sources']
    source_by_id = {str(s['entry_id']):s for s in sources}
    supplied = {(str(m.source_entry_id),m.classification_code) for m in changes.mappings}
    required = affected_scopes(before,changes)
    if not required.issubset(supplied):
        raise ValueError('affected_source_mappings_require_reassessment')
    retired = {str(x) for x in changes.retire_concept_ids}
    existing_ids={c['concept_key']:str(c['concept_id']) for c in before.concepts}
    if retired & {existing_ids.get(d.definition.key,str(concept_id_for_key(d.definition.key))) for d in changes.definitions}:
        raise ValueError('cannot_revise_and_retire_same_concept')
    for change in sorted(changes.definitions,key=lambda d:d.definition.kind!='item_type'):
        definition = change.definition
        same = [c for c in concepts if c['concept_key']==definition.key]
        if same:
            latest = max(same,key=lambda c:c['revision'])
            if str(latest['revision_id'])!=str(change.base_revision_id) or latest['status']!='approved':
                raise ValueError('revision_requires_latest_approved_base')
            if latest['kind']!=definition.kind:
                raise ValueError('stable_concept_kind_cannot_change')
            if definition.kind=='characteristic':
                if latest['content']['value_kind']!=definition.value_kind:
                    raise ValueError('value_kind_change_requires_new_concept')
                old_dimension = latest['content'].get('quantity_dimension')
                if old_dimension and old_dimension!=definition.quantity_dimension:
                    raise ValueError('quantity_dimension_change_requires_new_concept')
            if latest['content']==definition.model_dump(mode='json'):
                raise ValueError('unchanged_definition')
        elif change.base_revision_id is not None:
            raise ValueError('new_definition_cannot_have_base')
        for old in same:
            if old['status']=='approved':
                old['status']='deprecated'
        content = definition.model_dump(mode='json')
        concepts.append({'concept_id':str(same[0]['concept_id']) if same else str(concept_id_for_key(definition.key)),
            'revision_id':str(uuid5(concept_id_for_key(definition.key),dictionary_checksum(content))),
            'concept_key':definition.key,'revision':max([c['revision'] for c in same],default=0)+1,
            'kind':definition.kind,'content':content,'status':'approved'})
    for concept_id in retired:
        targets = [c for c in concepts if str(c['concept_id'])==concept_id and c['status']=='approved']
        if not targets:
            raise ValueError('retirement_requires_approved_concept')
        for target in targets:
            target['status']='deprecated'
    approved = {c['concept_key']:c for c in concepts if c['status']=='approved'}
    item_ids = {str(c['concept_id']) for c in approved.values() if c['kind']=='item_type'}
    for target in approved.values():
        definition = ConceptDefinition.model_validate(target['content'])
        if any(str(x) not in item_ids for x in definition.applicable_item_type_ids):
            raise ValueError('retired_owner_still_used_by_characteristic')
    for change in changes.mappings:
        source = source_by_id.get(str(change.source_entry_id))
        target = approved.get(change.target_key)
        if not source or source['status']!='approved' or not target or source['kind']!=target['kind']:
            raise ValueError('mapping_requires_approved_source_and_same_kind_target')
        owner = approved.get(change.owner_key)
        if source['kind']=='item_type':
            if change.owner_key:
                raise ValueError('item_type_cannot_have_mapping_owner')
        elif not owner or owner['kind']!='item_type' or str(owner['concept_id']) not in target['content']['applicable_item_type_ids']:
            raise ValueError('mapping_owner_not_applicable')
        for old in mappings:
            if str(old['source_entry_id'])==str(change.source_entry_id) and old['classification_code']==change.classification_code and old['status']=='approved':
                if str(old['target_revision_id'])!=str(target['revision_id']) or old['relation']!='equivalent' or str(old.get('owner_concept_id'))!=(str(owner['concept_id']) if owner else 'None'):
                    old['status']='deprecated'
        if any(str(m['source_entry_id'])==str(change.source_entry_id) and m['classification_code']==change.classification_code
               and m['status']=='approved' and str(m['target_revision_id'])==str(target['revision_id'])
               and str(m.get('owner_concept_id'))==(str(owner['concept_id']) if owner else 'None') for m in mappings):
            continue
        mappings.append({'mapping_id':str(uuid5(UUID(str(target['concept_id'])),dictionary_checksum(change))),
            'source_entry_id':str(change.source_entry_id),'target_revision_id':str(target['revision_id']),
            'owner_concept_id':str(owner['concept_id']) if owner else None,
            'classification_code':change.classification_code,'relation':'equivalent','status':'approved'})
    after = snapshot_from_records(concepts,mappings,sources)
    impact = change_impact(before,after,changes)
    if any(row['after']['status']!='resolved' for row in impact):
        raise ValueError('change_introduces_unresolved_or_ambiguous_mapping')
    return {'snapshot':after,'impact':impact}


async def repository_snapshot(repo, conn):
    return snapshot_from_records(await repo.concepts(conn),await repo.mappings(conn),await repo.all_sources(conn))


async def apply_change_set(repo, operation_id, changes, *, actor):
    if not re.fullmatch(r'maintenance_[a-z0-9_]{1,100}',operation_id):
        raise ValueError('invalid_maintenance_operation_id')
    changes = DictionaryChangeSet.model_validate(changes)
    digest = dictionary_checksum(changes)
    async with repo.transaction() as conn:
        await repo.lock(conn)
        existing = await repo.operation(conn,operation_id)
        if existing:
            if existing['request_checksum']!=digest or existing['actor']!=actor:
                raise ValueError('maintenance_operation_conflict')
            return existing['result']
        before = await repository_snapshot(repo,conn)
        preview = preview_change_set(before,changes)  # Entire change validated before first mutation.
        documents = await repo.affected_documents(conn,{r['source_entry_id'] for r in preview['impact']})
        validate_document_coverage(preview['impact'],changes,documents)
        await repo.begin(conn,operation_id,digest,actor)
        for change in sorted(changes.definitions,key=lambda d:d.definition.kind!='item_type'):
            rows = await repo.concepts(conn)
            same = [c for c in rows if c['concept_key']==change.definition.key]
            content = change.definition.model_dump(mode='json')
            for old in same:
                if old['status']=='approved':
                    await repo.set_status(conn,'concept',old['revision_id'],'deprecated')
                    await repo.meaning_event(conn,'concept',old['revision_id'],'superseded',actor,changes.rationale)
            row = await repo.add_concept(conn,same[0]['concept_id'] if same else concept_id_for_key(change.definition.key),
                max([c['revision'] for c in same],default=0)+1,content,dictionary_checksum(content),actor)
            await repo.meaning_event(conn,'concept',row['revision_id'],'proposed',actor,changes.rationale)
            await repo.set_status(conn,'concept',row['revision_id'],'approved')
            await repo.meaning_event(conn,'concept',row['revision_id'],'approve',actor,changes.rationale)
        for concept_id in changes.retire_concept_ids:
            for row in await repo.concepts(conn):
                if str(row['concept_id'])==str(concept_id) and row['status']=='approved':
                    await repo.set_status(conn,'concept',row['revision_id'],'deprecated')
                    await repo.meaning_event(conn,'concept',row['revision_id'],'deprecate',actor,changes.rationale)
        targets = {c['concept_key']:c for c in await repo.concepts(conn) if c['status']=='approved'}
        for change in changes.mappings:
            evidence = await repo.source_evidence(conn,change.source_entry_id)
            if not evidence:
                raise ValueError('mapping_requires_registered_evidence')
            kept = False
            owner_id = targets[change.owner_key]['concept_id'] if change.owner_key else None
            for old in await repo.mappings(conn):
                if str(old['source_entry_id'])==str(change.source_entry_id) and old['classification_code']==change.classification_code and old['status']=='approved':
                    if str(old['target_revision_id'])==str(targets[change.target_key]['revision_id']) and old['relation']=='equivalent' and str(old.get('owner_concept_id'))==str(owner_id):
                        kept = True
                        continue
                    await repo.set_status(conn,'mapping',old['mapping_id'],'deprecated')
                    await repo.meaning_event(conn,'mapping',old['mapping_id'],'deprecate',actor,change.rationale)
            if kept:
                continue
            proposal = MappingProposal(source_entry_id=change.source_entry_id,
                target_revision_id=targets[change.target_key]['revision_id'],classification_code=change.classification_code,
                owner_concept_id=targets[change.owner_key]['concept_id'] if change.owner_key else None,rationale=change.rationale)
            row = await repo.add_mapping(conn,proposal,evidence,actor)
            await repo.meaning_event(conn,'mapping',row['mapping_id'],'proposed',actor,change.rationale)
            await repo.set_status(conn,'mapping',row['mapping_id'],'approved')
            await repo.meaning_event(conn,'mapping',row['mapping_id'],'approve',actor,change.rationale)
        after = await repository_snapshot(repo,conn)
        result = {'operation_id':operation_id,'status':'applied','baseline_checksum':before.checksum,
                  'snapshot_checksum':after.checksum,'snapshot':after.model_dump(mode='json'),
                  'impact':change_impact(before,after,changes)}
        result['affected_documents'] = documents
        # UUID values must be JSON-safe before recording the idempotent operation result.
        for document in result['affected_documents']:
            document['entry_id'] = str(document['entry_id'])
        await repo.finish(conn,operation_id,result)
        return result
