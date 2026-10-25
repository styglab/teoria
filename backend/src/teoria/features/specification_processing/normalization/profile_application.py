"""Apply a pinned semantic package to observations without calling Platform services."""
from collections import Counter
from decimal import Decimal,localcontext
import hashlib
import json
from teoria.features.goods_normalization.contracts import NormalizationPackage
from teoria.features.specification_processing.parsing.document_evidence import attribute_is_grounded,literal
from teoria.features.specification_processing.extraction.value_normalization import number
from teoria.features.specification_processing.normalization.candidate_collection import observation_role


def observation_id(document,run_id,kind,local_id):
    key=[document['source']['sha256'],document['document_id'],run_id,kind,local_id]
    return hashlib.sha256(json.dumps(key,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def apply_profile(corpus,package: NormalizationPackage,*,run_id: str):
    if corpus['classification_code']!=package.profile.classification_code:raise ValueError('normalization profile classification mismatch')
    profile=package.profile;concepts={str(c.concept_id):c for c in package.concepts}
    documents=[];attribute_rows=[];candidates=[];entity_counts=Counter();relation_counts=Counter()
    for doc in corpus['documents']:
        entities={};nodes={n['node_id']:n['text'] for n in doc['parsed_document']['nodes']}
        for entity in doc['entities']:
            evidence=entity.get('evidence',[])
            grounded=bool(literal(entity['name'])) and any(literal(entity['name']) in literal(nodes.get(e.get('node_id'),'')) for e in evidence)
            choices=[r for r in profile.entities if entity['kind'] in r.source_kinds and literal(entity['name']) in {literal(a) for a in r.aliases}]
            row={'observation_id':observation_id(doc,run_id,'entity',entity['id']),'source_entity_id':entity['id'],
                 'name_raw':entity['name'],'evidence':evidence,'status':'applied' if grounded and len(choices)==1 else 'automatically_deferred'}
            if row['status']=='applied':row.update(concept_id=str(choices[0].concept_id),
                concept_key=concepts[str(choices[0].concept_id)].stable_key,rule_id=choices[0].rule_id)
            else:
                row['reason']='ungrounded_entity' if not grounded else 'ambiguous_entity_rule' if choices else 'no_entity_rule'
                candidates.append({'kind':'entity','document_id':doc['document_id'],**row})
            entities[entity['id']]=row;entity_counts[row['status']]+=1
        requirements=[]
        for a in doc['attributes']:
            subjects=[entities[s] for s in a['subject_ids'] if s in entities]
            target_types={s.get('concept_id') for s in subjects}
            role=observation_role(a);scope=a.get('semantic_scope','unknown')
            if ('semantic_scope' not in a and a.get('origin')=='validated_inventory_quantity'
                    and a['property_key']=='quantity' and a.get('evidence',{}).get('scope')=='explicit inventory target only'):
                scope='per_component'
            choices=[r for r in profile.requirements if target_types=={str(r.target_concept_id)} and
                     a['property_key'] in r.source_property_keys and role in r.roles and scope in r.scopes]
            reason=None;value=None;chosen=None
            if not subjects or len(subjects)!=len(a['subject_ids']) or None in target_types:reason='unresolved_subject'
            elif not attribute_is_grounded(doc,a):reason='source_condition_mismatch'
            elif len(choices)!=1:reason='ambiguous_requirement_rule' if choices else 'no_requirement_rule'
            else:
                chosen=choices[0]
                if chosen.value_type=='number':
                    policy=next((u for u in chosen.units if u.source_unit==a.get('unit_raw')),None)
                    raw=number(a['value_raw']) if a.get('data_type')=='number' else None
                    if policy is None:reason='unsupported_source_unit'
                    elif raw is None or a['operator'] not in {'eq','gte','lte','gt','lt'}:reason='unsupported_numeric_predicate'
                    else:
                        with localcontext() as context:
                            context.prec=max(28,len(raw)+len(str(policy.multiplier))+10)
                            converted=Decimal(raw)*policy.multiplier
                        if concepts[str(chosen.property_concept_id)].value_type=='integer' and converted!=converted.to_integral_value():
                            reason='non_integral_count'
                        else:value={'kind':'number','decimal':format(converted,'f'),'unit':policy.canonical_unit}
                elif a['operator'] not in {'raw','eq','one_of'}:reason='text_ordering_unresolved'
                elif a.get('unit_raw') is not None:reason='unexpected_unit_on_text_value'
                else:value={'kind':chosen.value_type,'text':a['value_raw']}
            row={'document_id':doc['document_id'],'attribute_id':a['id'],'status':'automatically_deferred' if reason else 'applied'}
            if reason:
                row['reason']=reason;candidates.append({'kind':'requirement',**row,'source_property_key':a['property_key'],
                    'source_entity_ids':a['subject_ids'],'value_raw':a['value_raw'],'unit_raw':a.get('unit_raw'),
                    'operator':a['operator'],'operator_raw':a.get('operator_raw'),'qualifiers_raw':a.get('qualifiers_raw',[]),
                    'evidence':a['evidence'],'role':role,'semantic_scope':scope})
            else:
                fact={'observation_id':observation_id(doc,run_id,'requirement',a['id']),
                      'property_concept_id':str(chosen.property_concept_id),'subject_observation_ids':[s['observation_id'] for s in subjects],
                      'property_stable_key':concepts[str(chosen.property_concept_id)].stable_key,
                      'rule_id':chosen.rule_id,'operator':a['operator'],'operator_raw':a.get('operator_raw'),
                      'qualifiers_raw':a.get('qualifiers_raw',[]),'role':role,'semantic_scope':scope,'value':value,
                      'value_raw':a['value_raw'],'unit_raw':a.get('unit_raw'),'evidence':a['evidence'],
                      'evidence_ref':f"{doc['document_id']}:{a['id']}"}
                row['facts']=[fact];requirements.append(fact)
            attribute_rows.append(row)
        relations=[]
        for relation in doc['relations']:
            source=entities.get(relation['source_id']);target=entities.get(relation['target_id'])
            choices=[]
            for rule in profile.relations:
                if rule.source_kind!=relation['kind']:continue
                left,right=(target,source) if rule.reverse else (source,target)
                meaning=concepts[str(rule.relationship_concept_id)]
                if (left and right and left.get('concept_id')==str(meaning.source_object_concept_id)
                        and right.get('concept_id')==str(meaning.target_object_concept_id)):
                    choices.append(rule)
            choice=choices[0] if len(choices)==1 else None
            if choice and choice.reverse:source,target=target,source
            concept=concepts.get(str(choice.relationship_concept_id)) if choice else None
            valid=bool(source and target and concept and relation.get('evidence') and
                       all(e.get('node_id') in nodes and nodes[e['node_id']].strip() for e in relation['evidence']) and
                       source.get('concept_id')==str(concept.source_object_concept_id) and
                       target.get('concept_id')==str(concept.target_object_concept_id))
            if valid:
                relations.append({'observation_id':observation_id(doc,run_id,'relation',relation['id']),
                    'relationship_concept_id':str(choice.relationship_concept_id),'source_observation_id':source['observation_id'],
                    'relationship_stable_key':concept.stable_key,
                    'target_observation_id':target['observation_id'],'source_relation_id':relation['id'],
                    'rule_id':choice.rule_id,'basis':relation.get('basis','unknown'),'evidence':relation['evidence']})
            else:candidates.append({'kind':'relation','document_id':doc['document_id'],'source_relation_id':relation['id'],
                                    'source_kind':relation['kind'],'reason':'unresolved_relation_mapping'})
            relation_counts['applied' if valid else 'automatically_deferred']+=1
        documents.append({'document_id':doc['document_id'],'entities':list(entities.values()),'requirements':requirements,'relations':relations})
    normalized={'schema_version':2,'artifact_kind':'goods_normalized_observations','standard_version':profile.version,
                'run_id':run_id,'profile_revision_id':str(package.profile_revision_id),
                'profile_key':profile.profile_key,'package_checksum':package.checksum,'ontology':profile.ontology.model_dump(mode='json'),
                'classification_code':profile.classification_code,'documents':documents,'attributes':attribute_rows,
                'summary':dict(Counter(r['status'] for r in attribute_rows)),'entity_summary':dict(entity_counts),
                'relation_summary':dict(relation_counts),'unresolved_observations':candidates,'published':False}
    proposals={'schema_version':2,'status':'unresolved_observation_candidates','published':False,
               'profile_revision_id':str(package.profile_revision_id),'ontology':profile.ontology.model_dump(mode='json'),
               'candidates':candidates,'summary':{'unresolved_observations':len(candidates)}}
    from teoria.features.specification_processing.normalization.profile_candidates import collect_profile_candidates
    proposals['bundle']=collect_profile_candidates(corpus,normalized,package)
    return normalized,proposals
