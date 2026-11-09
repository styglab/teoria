"""Read-only coordination of goods authoring dependencies before Ontology review."""
from teoria.platform.ontology.contracts.artifact_format import canonical_json


def concept_signatures(content):
    """Ignore revision row IDs; compare meaning, ownership and property constraints."""
    objects = {str(o['business_object_id']):str(o['concept_id']) for o in content['objects']}
    result = {}
    for obj in content['objects']:
        result[str(obj['concept_id'])] = {k:obj.get(k) for k in ('stable_key','name','description','identity_policy')}
        for prop in obj['properties']:
            result[str(prop['concept_id'])] = {**{k:prop.get(k) for k in
                ('stable_key','name','description','value_type','cardinality','unit','quantity_dimension','allowed_units','temporal')},
                'owner_concept_id':str(obj['concept_id'])}
    for collection in ('relationships','rules','metrics'):
        for item in content.get(collection, []):
            row = {k:v for k,v in item.items() if k not in {
                'relationship_type_id','business_rule_id','metric_id','ontology_version_id','status','concept_id'}}
            for field in ('source_object_id','target_object_id','subject_object_id'):
                if field in row:
                    row[field] = objects.get(str(row[field]), 'missing_revision:' + str(row[field]))
            result[str(item['concept_id'])] = row
    return result


def dependency_impact(before, after, dependencies):
    old, new = concept_signatures(before), concept_signatures(after)
    changed = {key for key in old.keys() & new.keys() if canonical_json(old[key]) != canonical_json(new[key])}
    removed = old.keys() - new.keys()
    affected = changed | removed
    rows = []
    for dependency in dependencies:
        ids = sorted(set(dependency['concept_ids']) & affected)
        # Even unchanged stable IDs require a deliberate switch to a new pinned publication.
        rows.append({**dependency,'affected_concept_ids':ids,
                     'reason':'concept_removed' if set(ids) & removed else 'concept_changed' if ids else 'pinned_version_review',
                     'requires_review':True,'existing_snapshot_preserved':True})
    return {'changed_concept_ids':sorted(changed),'removed_concept_ids':sorted(removed),
            'added_concept_ids':sorted(new.keys()-old.keys()),
            'review_required_count':len(rows),'dependencies':rows}


class GoodsOntologyImpactService:
    def __init__(self, ontology, profiles, expressions, bindings, catalog):
        self.ontology, self.profiles, self.expressions = ontology, profiles, expressions
        self.bindings, self.catalog = bindings, catalog

    async def report(self, version_id):
        detail = await self.ontology.get_version(version_id)
        base_id = detail.get('based_on_version_id')
        if not base_id:
            return {'status':'no_base_version','review_required_count':0,'dependencies':[]}
        before = await self.ontology.get_version(base_id)
        if before['namespace'] != detail['namespace']:
            raise ValueError('ontology impact requires the same namespace')
        namespace = detail['namespace']
        dependencies = [*await self.profiles.ontology_dependencies(namespace),
                        *await self.expressions.ontology_dependencies(namespace)]
        for mapping_id, mapping in self.catalog.mappings.items():
            for target, rules in mapping.bindings.items():
                for index, rule in enumerate(rules):
                    if rule.meaning is not None and rule.meaning.ontology.namespace == namespace:
                        dependencies.append({'kind':'api_mapping','id':f'{mapping_id}:{target}:{index}',
                            'status':'registry_contract','ontology':rule.meaning.ontology.model_dump(mode='json'),
                            'concept_ids':[str(rule.meaning.concept_id)],
                            'api_field_binding_id':str(rule.meaning.api_field_binding_id)})
        bindings = await self.bindings.list_bindings(ontology_namespace=namespace,status='approved',limit=100000)
        if len(bindings) >= 100000:
            raise ValueError('ontology dependency inspection exceeds the binding budget')
        dependencies.extend({'kind':'semantic_binding','id':str(b['binding_id']),'status':b['status'],
                             'concept_ids':[str(b['ontology_concept_id'])]} for b in bindings)
        return {'status':'review_required' if dependencies else 'no_dependencies',
                'base_version_id':str(base_id),'version_id':str(version_id),
                **dependency_impact(before, detail, dependencies)}
