"""Preview and prepare a reviewed blueprint in a new Draft; never publish a base.

The original version is retained. An unpublished source is provenance in the
audit event, not a falsely published based_on_version_id.
"""
from uuid import uuid4

from teoria.features.semantic_modeling.ontology.publication_contracts import publication_checksum


def blueprint_members(blueprint):
    objects = {item.code:item.stable_key for item in blueprint.objects}
    members = {}
    for obj in blueprint.objects:
        members[obj.stable_key] = {'kind':'object', 'fields':{
            'code':obj.code, 'name':obj.name, 'description':obj.description,
            'identity_policy':{'properties':obj.identity_properties}}}
        for prop in obj.properties:
            members[prop.stable_key] = {'kind':'property', 'owner':obj.stable_key,
                'fields':prop.model_dump(mode='json', exclude={'stable_key'})}
    for rel in blueprint.relationships:
        members[rel.stable_key] = {'kind':'relationship', 'source':objects[rel.source],
            'target':objects[rel.target], 'fields':rel.model_dump(mode='json', exclude={'stable_key','source','target'})}
    return members


def version_members(version):
    objects = {str(obj['business_object_id']):obj['stable_key'] for obj in version['objects']}
    members = {}
    def fields(row, names):
        return {name:row.get(name) for name in names}
    for obj in version['objects']:
        members[obj['stable_key']] = {'kind':'object', 'concept_id':str(obj['concept_id']),
            'fields':fields(obj, ('code','name','description','identity_policy'))}
        for prop in obj['properties']:
            members[prop['stable_key']] = {'kind':'property', 'concept_id':str(prop['concept_id']),
                'owner':obj['stable_key'], 'fields':fields(prop, ('code','name','description','value_type',
                    'cardinality','unit','quantity_dimension','allowed_units','temporal'))}
    for rel in version['relationships']:
        members[rel['stable_key']] = {'kind':'relationship', 'concept_id':str(rel['concept_id']),
            'source':objects[str(rel['source_object_id'])], 'target':objects[str(rel['target_object_id'])],
            'fields':fields(rel, ('code','name','description','source_cardinality','target_cardinality','temporal','transitive'))}
    return members


def plan_revision(current, blueprint, concepts, approved_bindings):
    previous, desired = version_members(current), blueprint_members(blueprint)
    added, removed, changed, blockers = [], [], [], []
    if current['namespace'] != blueprint.namespace:
        blockers.append({'code':'blueprint_namespace_mismatch'})
    if current['status'] not in {'draft','published'}:
        blockers.append({'code':'blueprint_source_must_be_draft_or_published'})
    if current['version'] == blueprint.target_version:
        blockers.append({'code':'blueprint_requires_a_new_version'})
    if current.get('rules') or current.get('metrics'):
        blockers.append({'code':'blueprint_cannot_drop_rules_or_metrics'})
    known = {row['stable_key']:row for row in concepts}
    for key, item in desired.items():
        old = previous.get(key)
        if key in known and known[key].get('retired_at') is not None:
            blockers.append({'code':'retired_concept_requires_review', 'stable_key':key})
        if old is None:
            added.append({'stable_key':key, **item})
            if key in known:
                blockers.append({'code':'historical_concept_requires_review', 'stable_key':key})
            continue
        if item['kind'] != old['kind'] or (item['kind'] == 'property' and item['owner'] != old['owner']):
            blockers.append({'code':'concept_kind_or_owner_changed', 'stable_key':key})
        if item['kind'] == old['kind'] == 'relationship' and (item['source'],item['target']) != (old['source'],old['target']):
            blockers.append({'code':'relationship_endpoints_changed', 'stable_key':key})
        before = {name:value for name,value in old.items() if name != 'concept_id'}
        if item != before:
            changed.append({'stable_key':key, 'concept_id':old['concept_id'], 'before':before, 'after':item})
    removed = [{'stable_key':key, **item} for key,item in previous.items() if key not in desired]
    removed_ids = {row['concept_id'] for row in removed}
    blockers.extend({'code':'approved_binding_would_be_removed', 'binding_id':str(row['binding_id'])}
                    for row in approved_bindings if str(row['ontology_concept_id']) in removed_ids)
    plan = {'schema_version':1, 'source_version_id':str(current['ontology_version_id']),
        'source_version':current['version'], 'source_status':current['status'],
        'namespace':current['namespace'], 'target_version':blueprint.target_version,
        'source_checksum':publication_checksum(current),
        'blueprint_checksum':publication_checksum(blueprint.model_dump(mode='json')),
        'preserved_concept_count':len(previous.keys() & desired.keys()),
        'changes':{'added':sorted(added,key=lambda row:row['stable_key']),
                   'removed':sorted(removed,key=lambda row:row['stable_key']),
                   'changed':sorted(changed,key=lambda row:row['stable_key'])},
        'blockers':sorted(blockers,key=publication_checksum), 'ready':not blockers}
    return {**plan, 'plan_checksum':publication_checksum(plan)}


async def preview(service, version_id, blueprint):
    async with service.repository.transaction() as connection:
        await service.repository.lock_version(connection, version_id)
        current = await service.repository.read_version(connection, version_id)
        concepts, bindings = await service.repository.blueprint_dependencies(connection, current['ontology_id'])
        plan = plan_revision(current, blueprint, concepts, bindings)
        if await service.repository.version_by_name(connection, current['ontology_id'], blueprint.target_version):
            plan['blockers'].append({'code':'target_version_already_exists'})
            plan['ready'] = False
            plan['plan_checksum'] = publication_checksum({k:v for k,v in plan.items() if k != 'plan_checksum'})
        return plan


async def prepare(service, version_id, blueprint, *, expected_plan_checksum, actor, rationale):
    repository = service.repository
    async with repository.transaction() as connection:
        await repository.lock_version(connection, version_id)
        current = await repository.read_version(connection, version_id)
        existing = await repository.version_by_name(connection, current['ontology_id'], blueprint.target_version)
        blueprint_checksum = publication_checksum(blueprint.model_dump(mode='json'))
        if existing is not None:
            event = await repository.blueprint_preparation_event(connection, existing['ontology_version_id'])
            detail = await repository.read_version(connection, existing['ontology_version_id'])
            if (event is not None and event['actor'] == actor
                    and event['after_value']['source_version_id'] == str(version_id)
                    and event['after_value']['plan_checksum'] == expected_plan_checksum
                    and event['after_value']['blueprint_checksum'] == blueprint_checksum
                    and detail['status'] == 'draft'
                    and publication_checksum(detail) == event['after_value']['result_checksum']):
                return {'status':'draft', 'action':'reused', 'ontology_version_id':str(existing['ontology_version_id']),
                        **event['after_value']}
            raise ValueError('target_version_exists_or_prepared_draft_changed')
        concepts, bindings = await repository.blueprint_dependencies(connection, current['ontology_id'])
        plan = plan_revision(current, blueprint, concepts, bindings)
        if plan['plan_checksum'] != expected_plan_checksum:
            raise ValueError('blueprint_plan_changed_refresh_preview')
        if not plan['ready']:
            raise ValueError('blueprint_preparation_blocked')
        old, desired = version_members(current), blueprint_members(blueprint)
        identifiers = {key:old[key]['concept_id'] if key in old else str(uuid4()) for key in desired}
        members = []
        for key, item in desired.items():
            payload = {**item['fields'], 'stable_key':key}
            if item['kind'] == 'property':
                payload['object_concept_id'] = identifiers[item['owner']]
            elif item['kind'] == 'relationship':
                payload.update(source_object_concept_id=identifiers[item['source']],
                               target_object_concept_id=identifiers[item['target']])
            members.append({'kind':item['kind'], 'concept_id':identifiers[key],
                            'new_concept':key not in old, 'payload':payload})
        identifier = await repository.insert_blueprint_draft(connection, current,
            target_version=blueprint.target_version, members=members, actor=actor)
        validation = await service._validate(connection, identifier)
        if validation['status'] != 'valid':
            raise ValueError('prepared_blueprint_validation_failed')
        detail = await repository.read_version(connection, identifier)
        result = {'source_version_id':str(version_id), 'source_status':current['status'],
            'source_checksum':plan['source_checksum'], 'plan_checksum':plan['plan_checksum'],
            'blueprint_checksum':blueprint_checksum, 'result_checksum':publication_checksum(detail),
            'version':blueprint.target_version, 'preserved_concept_count':plan['preserved_concept_count'],
            'change_counts':{key:len(rows) for key,rows in plan['changes'].items()}}
        await repository.record_event(connection, identifier, None, 'blueprint_draft_prepared', actor,
            {'source_version_id':str(version_id), 'source_checksum':plan['source_checksum'],
             'blueprint':blueprint.model_dump(mode='json')}, result, rationale)
        return {'status':'draft', 'action':'created', 'ontology_version_id':str(identifier), **result}
