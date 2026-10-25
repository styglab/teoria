"""Apply immutable context bindings; no Platform imports or runtime calls."""
from collections import Counter
import json
import re
from teoria.features.specification_processing.models import StandardArtifact
from teoria.features.specification_processing.parsing.document_evidence import literal,attribute_is_grounded
from teoria.features.specification_processing.normalization.candidate_collection import unit_context,target_type,observation_role



def canonical(data):
    return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()

def signature(doc,a,rule_set='source_only'):
    entities={e['id']:e for e in doc['entities']}
    return (tuple(sorted({target_type(entities[s],rule_set) for s in a['subject_ids']})),a['property_key'],
            unit_context(a['unit_raw']),a['data_type'],observation_role(a),a.get('semantic_scope','unknown'))

def binding_signature(binding):
    return tuple(binding.target_types),binding.property_key,binding.unit_context,binding.data_type,binding.role,binding.semantic_scope

def map_standard(corpus,standard:StandardArtifact):
    if corpus['classification_code']!=standard.classification_code:raise ValueError('standard classification differs from input')
    server=None
    if standard.rule_set=='server':
        from teoria.features.specification_processing.normalization import server_rules as server
        server.validate_classification(corpus['classification_code'])
    bindings={};duplicates=set()
    for binding in standard.bindings:
        key=binding_signature(binding)
        if key in bindings:duplicates.add(key)
        bindings[key]=binding
    rows=[]
    for doc in corpus['documents']:
        for a in doc['attributes']:
            key=signature(doc,a,standard.rule_set);binding=bindings.get(key);facts=[];reason=None
            if not a['subject_ids'] or 'unresolved' in key[0] or observation_role(a)=='unknown':reason='unresolved_subject_or_role'
            elif key in duplicates:reason='ambiguous_standard_binding'
            elif binding is None:reason='no_standard_binding'
            elif not attribute_is_grounded(doc,a):reason='source_condition_mismatch'
            else:
                for rule in binding.properties:
                    pid=rule.property_id
                    if rule.allowed_values is not None and literal(a['value_raw']) not in rule.allowed_values:
                        reason='unseen_categorical_value';break
                    if rule.rule_kind=='source_literal':
                        value={'kind':'source_constraint','text':a['value_raw'],'unit_raw':a.get('unit_raw'),
                            'resolution':'source_preserved','numeric_ordering_allowed':False}
                    elif server is None:
                        reason='domain_rule_set_not_selected';break
                    elif rule.rule_kind=='server_literal':
                        # A compound form-factor alias does not manufacture a height from plain 'rackmount'.
                        if pid=='chassis_height' and a['unit_raw']!='U' and not re.search(r'\d+(?:\.\d+)?\s*U\b',a['value_raw'],re.I):continue
                        value=server.normalized_value(pid,a)
                    else:
                        selector=server.select_typed_definition if rule.rule_kind=='typed_definition' else server.select_source_constraint
                        choice,_=selector(rule.candidate,doc,a)
                        if choice is None:reason='standard_contract_not_satisfied';break
                        choice_id=choice.get('property_id',choice.get('definition',{}).get('id'))
                        if choice_id!=pid:reason='standard_property_changed';break
                        value=choice['value']
                    facts.append({'property_id':pid,'subject_ids':a['subject_ids'],'operator':a['operator'],'operator_raw':a.get('operator_raw'),
                        'qualifiers_raw':a.get('qualifiers_raw',[]),'role':observation_role(a),
                        'semantic_scope':a.get('semantic_scope','unknown'),'value':value,
                        'evidence_ref':f"{doc['document_id']}:{a['id']}"})
            row={'document_id':doc['document_id'],'attribute_id':a['id']}
            if reason or not facts:row.update({'status':'automatically_deferred','reason':reason or 'empty_mapping'})
            else:row.update({'status':'applied','facts':facts})
            rows.append(row)
    return {'schema_version':1,'rule_set':standard.rule_set,'standard_version':standard.version,'classification_code':standard.classification_code,
        'summary':dict(Counter(r['status'] for r in rows)),'attributes':rows,'published':False}
