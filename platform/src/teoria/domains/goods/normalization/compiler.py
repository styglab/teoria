"""Project referenced concepts from a verified published Ontology snapshot."""
from uuid import UUID
from teoria_goods_normalization import Concept, NormalizationPackage, NormalizationProfile, checksum


def resolve_profile_template(template: dict,ontology: dict,*,version_id: UUID) -> NormalizationProfile:
    """Author with stable keys; persist resolved stable IDs, never generated local concepts."""
    from copy import deepcopy
    data=deepcopy(template)
    if 'ontology' in data:raise ValueError('ontology reference is resolved from the selected published artifact')
    keys={o['stable_key']:o['concept_id'] for o in ontology['objects']}
    keys.update({p['stable_key']:p['concept_id'] for o in ontology['objects'] for p in o['properties']})
    keys.update({r['stable_key']:r['concept_id'] for r in ontology['relationships']})
    for collection,fields in [('entities',['concept_id']),('requirements',['target_concept_id','property_concept_id']),
                               ('relations',['relationship_concept_id'])]:
        rows=data.get(collection,[])
        if not isinstance(rows,list):raise ValueError('template rules must be lists')
        for rule in rows:
            if not isinstance(rule,dict):raise ValueError('template rule must be an object')
            for field in fields:
                value=rule.get(field)
                if not isinstance(value,str) or value not in keys:raise ValueError('unknown stable concept key in template')
                rule[field]=keys[value]
    data['ontology']={'version_id':str(version_id),'namespace':ontology['namespace'],'version':ontology['version'],'checksum':checksum(ontology)}
    return NormalizationProfile.model_validate(data)


def compile_package(profile: NormalizationProfile, ontology: dict, *, revision_id: UUID,
                    approval_actor: str) -> NormalizationPackage:
    if checksum(ontology)!=profile.ontology.checksum:raise ValueError('ontology artifact checksum mismatch')
    if (ontology['namespace'],ontology['version'])!=(profile.ontology.namespace,profile.ontology.version):
        raise ValueError('ontology namespace or version mismatch')
    concepts=[]
    objects={str(o['business_object_id']):o['concept_id'] for o in ontology['objects']}
    for obj in ontology['objects']:
        concepts.append(Concept(concept_id=obj['concept_id'],stable_key=obj['stable_key'],kind='object'))
        for prop in obj['properties']:
            concepts.append(Concept(concept_id=prop['concept_id'],stable_key=prop['stable_key'],kind='property',
                            object_concept_id=obj['concept_id'],value_type=prop['value_type'],unit=prop.get('unit')))
    for rel in ontology['relationships']:
        concepts.append(Concept(concept_id=rel['concept_id'],stable_key=rel['stable_key'],kind='relationship',
                        source_object_concept_id=objects[str(rel['source_object_id'])],
                        target_object_concept_id=objects[str(rel['target_object_id'])]))
    needed={r.concept_id for r in profile.entities}
    needed.update(r.target_concept_id for r in profile.requirements)
    needed.update(r.property_concept_id for r in profile.requirements)
    needed.update(r.relationship_concept_id for r in profile.relations)
    for concept in concepts:
        if concept.concept_id in needed and concept.kind=='relationship':
            needed.update([concept.source_object_concept_id,concept.target_object_concept_id])
    body={'schema_version':2,'artifact_kind':'goods_normalization_package','profile_revision_id':str(revision_id),
          'profile_checksum':checksum(profile),'profile':profile.model_dump(mode='json'),
          'concepts':[c.model_dump(mode='json') for c in sorted(concepts,key=lambda c:str(c.concept_id)) if c.concept_id in needed],
          'approval_actor':approval_actor}
    return NormalizationPackage.model_validate({**body,'checksum':checksum(body)})
