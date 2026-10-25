"""Deterministic source-case scoring; counts of outputs never stand in for accuracy."""
from collections import Counter
import json
import re
import unicodedata

# Freeze the grader independently of the production normalization/grounding functions.
def literal(value):return re.sub(r'\s+','',unicodedata.normalize('NFKC',value))


def source_quote(document,attribute):
    nodes={n['node_id']:n['text'] for n in document['parsed_document']['nodes']}
    evidence=attribute['evidence']
    if 'node_id' not in evidence:return '\n'.join(nodes[i] for i in evidence.get('source_node_ids',[]))
    text=nodes[evidence['node_id']];start=evidence.get('char_start',0);end=evidence.get('char_end',len(text))
    if not 0<=start<=end<=len(text):raise ValueError('invalid source span')
    return text[start:end]


def attribute_is_grounded(document,attribute):
    try:
        quote=literal(source_quote(document,attribute));value=attribute.get('value_raw')
        fields=[attribute.get('unit_raw'),attribute.get('operator_raw'),*attribute.get('qualifiers_raw',[])]
        return bool(value and literal(value)) and literal(value) in quote and all(
            v is None or bool(literal(v)) and literal(v) in quote for v in fields)
    except (KeyError,ValueError,TypeError):return False

def qualifier_key(value):
    """Ignore balanced outer presentation brackets, preserving operators and inner content."""
    value=literal(value)
    while value and value[0] in '([' and value[-1]=={'(':')','[':']'}[value[0]]:
        depth=0;whole=True
        for i,char in enumerate(value):
            if char==value[0]:depth+=1
            elif char==value[-1]:depth-=1
            if depth==0 and i!=len(value)-1:whole=False;break
            if depth<0:whole=False;break
        if not whole or depth:break
        value=value[1:-1]
    return value


def qualifiers_match(case,attribute):
    actual={qualifier_key(q) for q in attribute.get('qualifiers_raw',[])}
    expected={qualifier_key(q) for q in case.qualifiers_raw or []}
    if actual&{qualifier_key(q) for q in case.forbidden_qualifiers}:return False
    return actual==expected if case.qualifier_mode=='exact' else expected<=actual


CASE_NAMES=('entity','relation','requirement')
ERROR_NAMES=('failed_documents','partial_documents','ungrounded_entities','invalid_relations',
             'ungrounded_attributes','unassigned_attributes','duplicate_attributes')


def _refs_text(row,nodes):
    return '\n'.join(nodes.get(e.get('node_id'),'') for e in row.get('evidence',[]))


def score_extraction(corpus,documents):
    metrics=Counter({key:0 for key in ERROR_NAMES})
    for name in CASE_NAMES:
        metrics[name+'_cases_total']=0;metrics[name+'_cases_found']=0
    found={d['document_id']:d for d in corpus.get('documents',[])}
    details=[]
    for expected in documents:
        actual=found.get(expected.document_id)
        row={'document_id':expected.document_id,'label_status':expected.label_status,'missing_cases':[]}
        for kind,cases in [('entity',expected.entities),('relation',expected.relations),('requirement',expected.requirements)]:
            metrics[kind+'_cases_total']+=len(cases)
        if actual is None:
            metrics['failed_documents']+=1
            row['missing_cases']=['entity:'+str(i) for i in range(len(expected.entities))]+['relation:'+str(i) for i in range(len(expected.relations))]+['requirement:'+str(i) for i in range(len(expected.requirements))]
            details.append(row);continue
        if actual['source']['sha256']!=expected.sha256:raise ValueError('scoring source identity mismatch')
        entities={e['id']:e for e in actual['entities']}
        nodes={n['node_id']:n['text'] for n in actual['parsed_document']['nodes']}
        metrics['partial_documents']+=actual.get('extraction_status')=='partial'
        for entity in entities.values():
            text=literal(_refs_text(entity,nodes))
            metrics['ungrounded_entities']+=not literal(entity['name']) or literal(entity['name']) not in text
        parents={key:set() for key in entities}
        for relation in actual['relations']:
            valid=relation['source_id'] in entities and relation['target_id'] in entities and relation['source_id']!=relation['target_id']
            metrics['invalid_relations']+=not valid or not _refs_text(relation,nodes).strip()
            if valid and relation['kind'] in {'component_of','physical_part_of','specification_for','in_procurement_scope'}:
                parents[relation['source_id']].add(relation['target_id'])
        aliases={}
        for canonical,values in expected.entity_aliases.items():
            for value in [canonical,*values]:aliases[literal(value)]=literal(canonical)
        def entity_name(value):return aliases.get(literal(value),literal(value))
        def names(ids):return sorted(entity_name(entities[i]['name']) for i in ids if i in entities)
        def grounded_entity(entity):
            name=literal(entity['name'])
            return bool(name) and name in literal(_refs_text(entity,nodes))
        def unambiguous_subjects(ids,owner):
            if owner is not None:return True
            return all(sum(entity_name(e['name'])==entity_name(entities[i]['name']) for e in entities.values())==1 for i in ids)

        def has_owner(ids,owner):
            pending=list(ids);seen=set()
            while pending:
                item=pending.pop()
                if item in seen:continue
                seen.add(item)
                if item in entities and entity_name(entities[item]['name'])==entity_name(owner):return True
                pending.extend(parents.get(item,set()))
            return False
        seen=set()
        for attribute in actual['attributes']:
            metrics['ungrounded_attributes']+=not attribute_is_grounded(actual,attribute)
            metrics['unassigned_attributes']+=not attribute['subject_ids'] or attribute.get('semantic_role')=='unknown'
            signature=json.dumps({k:attribute.get(k) for k in ('subject_ids','property_key','value_raw','unit_raw','operator','operator_raw','qualifiers_raw','semantic_role','semantic_scope')},sort_keys=True,ensure_ascii=False)
            metrics['duplicate_attributes']+=signature in seen;seen.add(signature)
        for i,case in enumerate(expected.entities):
            context_present=any(literal(case.source_text) in literal(text) for text in nodes.values())
            matched=context_present and any(entity_name(e['name'])==entity_name(case.name)
                        and (case.kind is None or e['kind']==case.kind) and grounded_entity(e)
                        and (case.owner is None or has_owner([e['id']],case.owner))
                        and (case.evidence_mode=='existence' or literal(case.source_text) in literal(_refs_text(e,nodes)))
                        for e in entities.values())
            metrics['entity_cases_found']+=matched
            if not matched:row['missing_cases'].append('entity:'+str(i))
        for i,case in enumerate(expected.relations):
            matched=any(names([r['source_id']])==[entity_name(case.source)] and names([r['target_id']])==[entity_name(case.target)]
                        and (case.source_owner is None or has_owner([r['source_id']],case.source_owner))
                        and (case.target_owner is None or has_owner([r['target_id']],case.target_owner))
                        and unambiguous_subjects([r['source_id']],case.source_owner) and unambiguous_subjects([r['target_id']],case.target_owner)
                        and r['kind']==case.kind and literal(case.source_text) in literal(_refs_text(r,nodes)) for r in actual['relations'])
            metrics['relation_cases_found']+=matched
            if not matched:row['missing_cases'].append('relation:'+str(i))
        for i,case in enumerate(expected.requirements):
            def matches(a):
                try:quote=source_quote(actual,a)
                except (KeyError,TypeError,ValueError):return False
                return (names(a['subject_ids'])==sorted(map(entity_name,case.subjects))
                    and unambiguous_subjects(a['subject_ids'],case.owner)
                    and literal(a['value_raw'])==literal(case.value_raw) and a.get('unit_raw')==case.unit_raw and a['operator']==case.operator
                    and qualifiers_match(case,a)
                    and (not case.property_keys or a['property_key'] in case.property_keys)
                    and (case.role is None or a.get('semantic_role')==case.role)
                    and (case.scope is None or a.get('semantic_scope')==case.scope)
                    and (case.owner is None or has_owner(a['subject_ids'],case.owner))
                    and literal(case.source_text) in literal(quote) and attribute_is_grounded(actual,a))
            matched=any(matches(a) for a in actual['attributes'])
            metrics['requirement_cases_found']+=matched
            if not matched:row['missing_cases'].append('requirement:'+str(i))
        details.append(row)
    return {'metrics':dict(metrics),'documents':details,'case_contract_version':2,'measurement':'specified_constraint_recall_and_source_conformance',
            'parser_versions':sorted({d.get('parser',{}).get('version','unknown') for d in corpus.get('documents',[])}),
            'independent_gold':bool(sum(metrics[k+'_cases_total'] for k in CASE_NAMES)) and all(d.label_status=='human_reviewed' for d in documents),
            'complete_condition_equivalence_measured':False,'whole_document_recall_measured':False,'relation_semantics_without_labels_measured':False}


def compare_runs(baseline,candidate,tests_passed):
    """An unchanged denominator and all three evidence groups are required for promotion."""
    reasons=[];improved=False
    for split in ('development','validation','regression'):
        before=baseline.get(split);after=candidate.get(split)
        if before is None or after is None:
            reasons.append(split+':missing_run');continue
        b=before['metrics'];a=after['metrics']
        if before.get('case_contract_version')!=after.get('case_contract_version'):
            reasons.append(split+':changed_case_contract')
        if not sum(b.get(k+'_cases_total',0) for k in CASE_NAMES):reasons.append(split+':no_frozen_cases')
        for kind in CASE_NAMES:
            if b[kind+'_cases_total']!=a[kind+'_cases_total']:reasons.append(split+':changed_case_denominator')
            if a[kind+'_cases_found']<b[kind+'_cases_found']:reasons.append(split+':'+kind+'_regression')
            if split=='development' and a[kind+'_cases_found']>b[kind+'_cases_found']:improved=True
        for key in ERROR_NAMES:
            if a[key]>b[key]:reasons.append(split+':'+key+'_regression')
            if split=='development' and a[key]<b[key]:improved=True
        if a['failed_documents']:reasons.append(split+':failed_documents')
    if not tests_passed:reasons.append('pipeline_tests_not_passed')
    if not improved:reasons.append('no_measured_development_improvement')
    rejected=any(r.endswith('_regression') or r.endswith(':changed_case_denominator') or r.endswith(':failed_documents') for r in reasons) or not tests_passed
    return {'decision':'rejected' if rejected else 'inconclusive' if reasons else 'accepted',
            'reasons':sorted(set(reasons)),'improved':improved,
            'scope':'source cases and conformance; no independent accuracy claim for silver labels'}
