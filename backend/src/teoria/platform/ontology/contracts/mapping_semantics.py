"""Verify API record mappings against the publication and reviewed field Binding."""
from copy import deepcopy
from datetime import date
import hashlib

from teoria.platform.ontology.contracts.api_field import resolve_api_field_contract
from teoria.platform.ontology.authoring.value_policy import validate_property_unit
from teoria.platform.ontology.authoring.publication_contracts import PublishedOntology
from teoria.platform.ontology.contracts.artifact_format import canonical_json


class MappingSemanticError(ValueError):
    pass


def base_type(catalog, value_type):
    if value_type in catalog.data_types:
        value_type = catalog.data_types[value_type].base_type
    return {'decimal':'number','float':'number','double':'number','int':'integer','text':'string'}.get(value_type, value_type)


def compile_mapping_semantics(catalog, ontologies, bindings, *, on_date=None):
    """No name matching, DB reads, or inferred equivalence. Old mappings stay ungoverned."""
    result = {}
    contexts = {}
    approved = {str(b['binding_id']): b for b in bindings if b.get('binding_id') and b.get('status') == 'approved'}
    on_date = on_date or date.today()
    for mapping_id, mapping in catalog.mappings.items():
        owners = {}
        for target, rules in mapping.bindings.items():
            for index, rule in enumerate(rules):
                meaning = rule.meaning
                if meaning is None:
                    continue
                location = f'{mapping_id}:{target}:{index}'
                def require(condition, code):
                    if not condition:
                        raise MappingSemanticError(f'{code}: {location}')
                reference = meaning.ontology
                artifact = next((a for a in ontologies if
                    str(a.get('ontology_version_id')) == str(reference.version_id)
                    and a.get('namespace') == reference.namespace and a.get('version') == reference.version), None)
                require(artifact is not None, 'mapping_ontology_publication_missing')
                content = artifact['content']
                require((content.get('namespace'),content.get('version')) == (reference.namespace,reference.version), 'mapping_ontology_identity_mismatch')
                digest = hashlib.sha256(canonical_json(content)).hexdigest()
                require(digest == reference.checksum == artifact['checksum'].removeprefix('sha256:'), 'mapping_ontology_checksum_mismatch')
                PublishedOntology(ontology=reference, content=content)
                properties = {str(p['concept_id']): (p,o) for o in content['objects'] for p in o['properties']}
                require(str(meaning.concept_id) in properties, 'mapping_property_concept_missing')
                prop, owner = properties[str(meaning.concept_id)]
                parts = rule.field.split('.', 3)
                require(len(parts) == 4 and parts[2] == 'response', 'mapping_response_field_required')
                source_id, operation_id, _, field_path = parts
                source = catalog.sources.get(source_id)
                require(source is not None and source.source.type == 'api', 'mapping_api_source_required')
                operation = next((o for o in source.source.operations if o.id == operation_id), None)
                require(operation is not None, 'mapping_operation_missing')
                contract = resolve_api_field_contract(catalog, source_id=source_id, operation_id=operation_id,
                    object_id=operation.response.data.ref, field_path=field_path)
                binding = approved.get(str(meaning.api_field_binding_id))
                require(binding is not None, 'mapping_approved_api_binding_required')
                expected = {'api_source_id':source_id, 'api_operation_id':operation_id,
                            'api_object_id':contract['object_id'], 'api_field_path':field_path,
                            'api_contract_version':contract['contract_version']}
                require(binding.get('target_type') == 'api_field' and
                        str(binding.get('ontology_concept_id')) == str(meaning.concept_id) and
                        all(binding.get(k) == v for k,v in expected.items()), 'mapping_api_binding_target_mismatch')
                require(binding.get('binding_type') in {'represents','equivalent'}, 'mapping_binding_is_not_equivalence')
                require(not binding.get('condition'), 'mapping_conditional_binding_requires_review')
                require(bool(binding.get('approved_by')), 'mapping_binding_approval_actor_required')
                for field, compare in [('valid_from', lambda d: d <= on_date), ('valid_to', lambda d: on_date <= d)]:
                    if binding.get(field):
                        require(compare(date.fromisoformat(str(binding[field]))), 'mapping_binding_outside_validity')
                object_type, property_id = target.rsplit('.',1)
                materialization = mapping.materializations.get(source_id + '.' + operation_id)
                role = rule.role or object_type
                materialized = materialization.objects.get(role) if materialization is not None else None
                runtime_type = (materialized.type if '.' in materialized.type else mapping.ontology + '.' + materialized.type) if materialized else None
                require(runtime_type == mapping.ontology + '.' + object_type, 'mapping_materialized_owner_mismatch')
                require(property_id not in materialized.timestamp_properties and property_id != materialized.id_property,
                        'mapping_semantic_property_cannot_be_generated')
                require(rule.decode is None, 'mapping_governed_codec_requires_review')
                require(not rule.qualifiers, 'mapping_governed_qualifiers_require_review')
                require(not any(property_id in other.qualifiers for other_target,other_rules in mapping.bindings.items()
                        if other_target.rsplit('.',1)[0] == object_type for other in other_rules),
                        'mapping_qualifier_overwrites_semantic_property')
                runtime = catalog.runtime_contracts.get(mapping.ontology)
                obj = next((o for o in runtime.object_types if o.id == object_type), None) if runtime else None
                runtime_prop = next((p for p in obj.properties if p.id == property_id), None) if obj else None
                require(runtime_prop is not None and runtime_prop.collection == 'scalar'
                        and prop.get('cardinality','optional') != 'many', 'mapping_scalar_property_required')
                expected_type = base_type(catalog, prop['value_type'])
                actual_type = base_type(catalog, runtime_prop.data_type)
                require(expected_type == actual_type, 'mapping_runtime_property_type_mismatch')
                source_type = base_type(catalog, contract['data_type'])
                require(source_type == expected_type or {source_type,expected_type} <= {'integer','number'}, 'mapping_source_property_type_mismatch')
                require(expected_type in {'number','integer','string'}, 'mapping_unsupported_semantic_type')
                context = (str(meaning.concept_id), str(reference.version_id), reference.checksum, meaning.information_kind, meaning.scope)
                projection = (mapping.ontology, target)
                require(contexts.setdefault(projection, context) == context, 'mapping_property_mixes_observation_contexts')
                if meaning.unit:
                    require(expected_type in {'number','integer'}, 'mapping_numeric_unit_required')
                    validate_property_unit(prop, meaning.unit)
                else:
                    require(prop.get('unit') is None, 'mapping_explicit_unit_conversion_required')
                previous = owners.setdefault(object_type, str(owner['concept_id']))
                require(previous == str(owner['concept_id']), 'mapping_runtime_object_has_multiple_semantic_owners')
                if meaning.effective_at_field:
                    timestamp = resolve_api_field_contract(catalog, source_id=source_id, operation_id=operation_id,
                        object_id=contract['object_id'], field_path=meaning.effective_at_field)
                    require(base_type(catalog,timestamp['data_type']) in {'string','date','datetime'}, 'mapping_effective_time_field_type_mismatch')
                result[(mapping_id,target,index)] = deepcopy({'meaning':meaning.model_dump(mode='json'),
                    'field':rule.field, 'decode':rule.decode, 'property':prop, 'source_type':source_type, 'value_type':expected_type,
                    'valid_from':binding.get('valid_from'), 'valid_to':binding.get('valid_to'),
                    'mapping_checksum':hashlib.sha256(canonical_json(mapping.model_dump(mode='json'))).hexdigest(),
                    'source_contract_checksum':hashlib.sha256(canonical_json(source.model_dump(mode='json',by_alias=True))).hexdigest(),
                    'object_concept_id':str(owner['concept_id']), 'api_field_binding_id':str(meaning.api_field_binding_id)})
    return result
