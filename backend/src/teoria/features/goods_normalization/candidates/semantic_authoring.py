"""Materialize validated Codex proposals through existing Ontology/Profile Draft APIs."""
from copy import deepcopy
from uuid import UUID

from teoria.features.semantic_modeling.ontology.authoring import OntologyAuthoringRepository
from teoria.features.goods_normalization.contracts import NormalizationProfile, checksum
from teoria.features.goods_normalization.contracts.candidates import CandidateBundle
from teoria.features.goods_normalization.candidates.proposals import _check_rule_overlap, propose_candidates
from teoria.features.goods_normalization.profiles.compiler import compile_package
from teoria.features.goods_normalization.candidates.semantic_resolution import MeaningBatch, validate_decisions


async def checked_proposals(repository, base_revision_id, bundles, semantic_report):
    profile, ontology = await repository._candidate_context(base_revision_id, allow_deprecated=True)
    supplied = deepcopy(semantic_report)
    digest = supplied.pop('checksum', None)
    if checksum(supplied) != digest or supplied.get('artifact_kind') != 'goods_semantic_proposals':
        raise ValueError('semantic proposal checksum or kind mismatch')
    report = propose_candidates(bundles, profile, ontology)
    if (supplied['base_profile_checksum'] != checksum(profile)
            or supplied['candidate_report_checksum'] != report['checksum']
            or supplied['input_checksums'] != sorted({b.checksum for b in bundles})):
        raise ValueError('semantic proposals refer to different inputs')
    batch = MeaningBatch.model_validate({'decisions': supplied['decisions']})
    checked = validate_decisions(batch, report, ontology)
    if checked != batch:
        raise ValueError('semantic proposals fail source or concept validation')
    return profile, ontology, report, checked


def concept_key(namespace, group, proposed):
    if group['context']['kind'] == 'requirement':
        owner=UUID(group['context']['target_concept_ids'][0]).hex
        return namespace + '.property_' + owner + '_' + proposed.code
    if group['context']['kind']=='relation':
        endpoints=[group['context']['source_concept_id'],group['context']['destination_concept_id']]
        return namespace+'.relation_'+checksum(endpoints)[:16]+'_'+proposed.code
    return namespace + '.' + proposed.code


async def create_ontology_draft(repository, base_revision_id, bundles, semantic_report, *, version, actor,resume=False):
    profile, ontology, report, batch = await checked_proposals(repository, base_revision_id, bundles, semantic_report)
    new = [d for d in batch.decisions if d.action == 'new']
    if not new:
        return {'ontology_draft_id': None, 'new_concepts': 0}
    authoring = OntologyAuthoringRepository(repository.database_url)
    draft=None
    if resume:
        draft=next((v for v in await authoring.list_versions(profile.ontology.namespace) if v['version']==version),None)
        if draft and (draft['based_on_version_id']!=str(profile.ontology.version_id) or draft['created_by']!=actor):
            raise ValueError('existing ontology version has a different base or creator')
    if draft is None:
        draft = await authoring.create_draft(profile.ontology.namespace, version=version, actor=actor,
            based_on_version_id=profile.ontology.version_id)
    vid = UUID(draft['ontology_version_id'])
    groups = {g['group_id']: g for g in report['groups']}
    created = {}
    for decision in new:
        group = groups[decision.group_id]; context = group['context']; definition = decision.new_concept
        stable_key = concept_key(profile.ontology.namespace, group, definition)
        payload = {'code': definition.code, 'name': definition.name, 'description': definition.description,
                   'stable_key': stable_key}
        kind = {'entity': 'object', 'requirement': 'property', 'relation': 'relationship'}[context['kind']]
        if kind == 'object':
            payload['identity_policy'] = {'properties': ['observation_id']}
        elif kind == 'property':
            payload.update(object_concept_id=context['target_concept_ids'][0],
                           value_type=definition.value_type, unit=definition.unit)
        else:
            source, target = context['source_concept_id'], context['destination_concept_id']
            if decision.reverse: source, target = target, source
            payload['code']=definition.code+'_'+checksum([source,target])[:12]
            payload.update(source_object_concept_id=source, target_object_concept_id=target)
        if stable_key in created:
            if created[stable_key] != (kind, payload):
                raise ValueError('conflicting new concept definitions; Draft remains unpublished')
            continue
        item = await ensure_item(authoring,vid,kind,payload,actor) if resume else await authoring.add_item(vid, kind=kind, payload=payload, actor=actor)
        created[stable_key] = (kind, payload)
        if kind == 'object':
            identity={'code': 'observation_id',
                'name': '문서별 관찰 식별자', 'description': '문서별 추출 관찰 식별자. 실물 자산 식별자가 아니다.',
                'stable_key': stable_key + '.observation_id', 'object_concept_id': item['concept_id'],
                'value_type': 'string', 'cardinality': 'one'}
            if resume:await ensure_item(authoring,vid,'property',identity,actor)
            else:await authoring.add_item(vid,kind='property',payload=identity,actor=actor)
    return {'ontology_draft_id': str(vid), 'new_concepts': len(created),
            'semantic_report_checksum': semantic_report['checksum']}


async def materialize_profile(repository, base_revision_id, bundles, semantic_report, *,
                              published_version_id, version, actor,resume=False):
    import json
    from psycopg.rows import dict_row
    from teoria.integrations.application_database.postgres import connect
    profile, old_ontology, report, batch = await checked_proposals(repository, base_revision_id, bundles, semantic_report)
    if version == profile.version:
        raise ValueError('semantic profile requires a new version')
    authoring = OntologyAuthoringRepository(repository.database_url)
    detail = await authoring.get_version(published_version_id)
    if detail['status'] != 'published' or detail['namespace'] != profile.ontology.namespace:
        raise ValueError('semantic profile requires a published version in the same ontology')
    async with connect(repository.database_url, row_factory=dict_row) as conn:
        row = await (await conn.execute('SELECT content,checksum FROM ontology.runtime_artifacts WHERE ontology_version_id=%s',
            (published_version_id,))).fetchone()
    if row is None or checksum(row['content']) != row['checksum']:
        raise ValueError('invalid published ontology artifact')
    ontology = row['content']
    from teoria.features.goods_normalization.candidates.proposals import _concepts
    concepts = {c['stable_key']: c for c in _concepts(ontology)}
    groups = {g['group_id']: g for g in report['groups']}
    data = profile.model_dump(mode='json'); data['version'] = version
    data['ontology'] = {'version_id': str(published_version_id), 'namespace': ontology['namespace'],
                        'version': ontology['version'], 'checksum': row['checksum']}
    accepted = []
    for decision in batch.decisions:
        if decision.action == 'hold': continue
        group = groups[decision.group_id]; context = group['context']
        if decision.action == 'new':
            concept = concepts.get(concept_key(profile.ontology.namespace, group, decision.new_concept))
            if concept is None: raise ValueError('new concept has not been published')
            concept_id = concept['concept_id']
            definition = decision.new_concept
            if (concept.get('name') != definition.name or concept.get('description', '') != definition.description
                    or (context['kind'] == 'requirement' and (concept['owner'] != context['target_concept_ids'][0]
                        or concept['value_type'] != definition.value_type or concept.get('unit') != definition.unit))):
                raise ValueError('published new concept differs from proposed definition')
        else:
            concept_id = str(decision.concept_id)
        rule = {'rule_id': 'semantic_' + decision.group_id[:24]}
        if context['kind'] == 'entity':
            rule.update(aliases=group['aliases'], source_kinds=[context['source_kind']], concept_id=concept_id)
            data['entities'].append(rule)
        elif context['kind'] == 'requirement':
            rule.update(target_concept_id=context['target_concept_ids'][0], property_concept_id=concept_id,
                source_property_keys=[context['source_kind']], roles=[context['role']], scopes=[context['scope']],
                value_type=context['value_type'], units=[u.model_dump(mode='json') for u in decision.units])
            data['requirements'].append(rule)
        else:
            rule.update(source_kind=context['source_kind'], relationship_concept_id=concept_id, reverse=decision.reverse)
            data['relations'].append(rule)
        accepted.append(decision.group_id)
    if not accepted:
        raise ValueError('no accepted semantic mappings')
    draft = NormalizationProfile.model_validate(data)
    _check_rule_overlap(draft,ontology)
    compile_package(draft, ontology, revision_id=UUID(int=0), approval_actor=actor)
    comment = json.dumps({'source': 'codex_semantic_proposals', 'base_revision_id': str(base_revision_id),
        'semantic_report_checksum': semantic_report['checksum'], 'model': semantic_report['model'],
        'input_checksums': semantic_report['input_checksums'], 'group_ids': accepted}, sort_keys=True)
    if resume:
        async with connect(repository.database_url,row_factory=dict_row) as conn:
            previous=await (await conn.execute('''SELECT * FROM goods.normalization_profile_revisions
                WHERE profile_key=%s AND version=%s''',(draft.profile_key,draft.version))).fetchone()
        if previous:
            if previous['content_checksum']!=checksum(draft) or previous['created_by']!=actor:
                raise ValueError('existing profile version belongs to a different plan or creator')
            return repository._result(previous)
    return await repository.create(draft, actor=actor, provenance_comment=comment)


async def ensure_item(authoring,version_id,kind,payload,actor):
    """Recover a crash between a committed authoring write and its operation checkpoint."""
    detail=await authoring.get_version(version_id)
    objects={o['business_object_id']:o['concept_id'] for o in detail['objects']}
    candidates=[]
    if kind=='object':candidates=detail['objects']
    elif kind=='property':
        candidates=[{**p,'object_concept_id':o['concept_id']} for o in detail['objects'] for p in o['properties']]
    else:
        candidates=[{**r,'source_object_concept_id':objects[r['source_object_id']],
            'target_object_concept_id':objects[r['target_object_id']]} for r in detail['relationships']]
    previous=next((r for r in candidates if r['stable_key']==payload['stable_key']),None)
    if previous:
        if any(previous.get(k)!=v for k,v in payload.items()):
            raise ValueError('partially created concept differs from semantic plan')
        return previous
    if detail['status']!='draft':raise ValueError('cannot append missing concepts after review')
    return await authoring.add_item(version_id,kind=kind,payload=payload,actor=actor)
