"""Validate source integrity and isolate rejected observations before publication."""
from collections import Counter
from copy import deepcopy
from teoria.domains.goods.data_processing.parsing.document_evidence import source_quote,literal
from teoria.domains.goods.data_processing.errors import SpecificationProcessingError

ATTRIBUTE_REJECTIONS={
    'source literal mismatch':'source_literal_mismatch',
    'source qualifier mismatch':'source_qualifier_mismatch',
    'invalid attribute ID or subject':'invalid_attribute_subject',
    'invalid resolution evidence':'invalid_resolution_evidence',
}


def isolate_extraction_failures(corpus,request,source_items):
    """Keep invalid observations for review; source identity failures remain fatal."""
    validate_source_identity(corpus,request,source_items)
    result={**corpus,'documents':[],'unavailable_documents':deepcopy(corpus['unavailable_documents'])}
    for original in corpus['documents']:
        document=deepcopy(original)
        source=[item for item in source_items if item['document_id']==document['document_id']]
        def check(attributes):
            validate_checkpoint({**corpus,'documents':[{**document,'attributes':attributes}],
                                 'unavailable_documents':[]},request,source)
        try:
            check([])
        except ValueError as exc:
            result['unavailable_documents'].append({
                **{key:document[key] for key in ('document_id','source')},
                'notice_number':document.get('notice_number'),'stage':'persist_extraction',
                'reason':'document_validation_failed','code':'document_validation_failed',
                'details':{'document_id':document['document_id'],'error_type':type(exc).__name__}})
            continue
        duplicates={key for key,count in Counter(a['id'] for a in document['attributes']).items() if count>1}
        nodes={node['node_id'] for node in document['parsed_document']['nodes']}
        accepted=[];quarantined=list(document.get('quarantined_attributes',[]))
        for attribute in document['attributes']:
            code=None
            if attribute['id'] in duplicates:
                code='duplicate_attribute_id'
            elif attribute.get('evidence',{}).get('node_id') not in nodes and attribute.get('evidence',{}).get('node_id') is not None:
                code='invalid_source_reference'
            else:
                try:check([attribute])
                except SpecificationProcessingError as exc:code=exc.code
                except ValueError as exc:
                    code=ATTRIBUTE_REJECTIONS.get(str(exc))
                    if code is None:raise
            if code is None:
                accepted.append(attribute)
                continue
            issue={'code':code,'document_id':document['document_id'],'attribute_id':attribute['id'],
                   'node_id':attribute.get('evidence',{}).get('node_id'),'status':'quarantined'}
            quarantined.append({'attribute':attribute,'issue':issue})
            # A rejected projected quantity cannot remain as an accepted inventory fact.
            quantity_ids={q['requirement_id'] for q in document.get('declared_quantities',[])
                          if 'attribute_'+q['requirement_id']==attribute['id']}
            document['declared_quantities']=[q for q in document.get('declared_quantities',[]) if q['requirement_id'] not in quantity_ids]
            document['requirements']=[r for r in document.get('requirements',[]) if r.get('id') not in quantity_ids]
        document['attributes']=accepted
        if quarantined:
            document['quarantined_attributes']=quarantined
            document['validation_issues']=[row['issue'] for row in quarantined]
            document['extraction_status']='partial'
            document.setdefault('unresolved_extraction',{})['source_validation']={'quarantined_attributes':len(quarantined)}
        result['documents'].append(document)
    result['validation_summary']={
        'quarantined_attributes':sum(len(d.get('quarantined_attributes',[])) for d in result['documents']),
        'invalid_documents':sum(d.get('code')=='document_validation_failed' for d in result['unavailable_documents']),
    }
    validate_checkpoint(result,request,source_items)
    return result


def validate_source_identity(corpus,request,source_items):
    if corpus.get('classification_code')!=request.classification_code:raise ValueError('checkpoint classification mismatch')
    expected={e['document_id']:e['source']['sha256'] for e in source_items}
    actual=corpus['documents']+corpus['unavailable_documents']
    if len(actual)!=len(expected) or {d['document_id'] for d in actual}!=set(expected):raise ValueError('checkpoint document set mismatch')
    for d in actual:
        if d['source']['sha256']!=expected[d['document_id']]:raise ValueError('checkpoint source mismatch')


def validate_checkpoint(corpus,request,source_items):
    from teoria.domains.goods.data_processing.extraction.attribute_extraction import spans
    from teoria.domains.goods.data_processing.extraction.value_normalization import number
    validate_source_identity(corpus,request,source_items)
    for d in corpus['documents']:
        ids={e['id'] for e in d['entities']};node_texts={n['node_id']:n['text'] for n in d['parsed_document']['nodes']};nodes=set(node_texts)
        if len(ids)!=len(d['entities']):raise ValueError('duplicate entity ID')
        if any(r['source_id'] not in ids or r['target_id'] not in ids for r in d['relations']):raise ValueError('invalid relation')
        from teoria.domains.goods.data_processing.extraction.entity_relation_extraction import relation_type_errors
        kinds={e['id']:e.get('kind') for e in d['entities']}
        for relation in d['relations']:
            errors=relation_type_errors(relation['kind'],kinds[relation['source_id']],kinds[relation['target_id']])
            if errors:raise ValueError('invalid relation type: '+'; '.join(errors))
        from teoria.domains.goods.data_processing.extraction.requirement_clauses import validate_legacy_obligation
        for requirement in d.get('requirements',[]):
            if requirement.get('observation_type')=='obligation':
                validate_legacy_obligation(requirement,ids,d['parsed_document'])
            elif requirement.get('observation_type')=='source_clause' and requirement.get('category')=='description':
                from teoria.domains.goods.data_processing.extraction.requirement_clauses import validate_description_clause
                validate_description_clause(requirement,ids,d['parsed_document'])
        from teoria.domains.goods.data_processing.extraction.target_names import validate_materialized_names
        for entity in d['entities']:
            validate_materialized_names(entity,d['parsed_document'])
        attribute_ids=set()
        for a in d['attributes']:
            if a['id'] in attribute_ids or not set(a['subject_ids'])<=ids:raise ValueError('invalid attribute ID or subject')
            attribute_ids.add(a['id']);raw_quote=source_quote(d,a);quote=literal(raw_quote)
            for key in ['value_raw','unit_raw','operator_raw']:
                if a.get(key) and literal(a[key]) not in quote:raise ValueError('source literal mismatch')
            if any(literal(q) not in quote for q in a.get('qualifiers_raw',[])):raise ValueError('source qualifier mismatch')
            if a.get('data_type')=='number' and number(a['value_raw']) is not None:
                from teoria.domains.goods.data_processing.errors import SpecificationProcessingError
                failure_ids={'document_id':d['document_id'],'attribute_id':a['id'],
                             'node_id':a.get('evidence',{}).get('node_id')}
                if not spans(raw_quote,a['value_raw'],complete_number=True):
                    raise SpecificationProcessingError('source_numeric_literal_mismatch',details=failure_ids)
                evidence=a['evidence'];recorded=(evidence.get('field_spans') or {}).get('value_raw',[])
                if evidence.get('node_id') and recorded:
                    text=node_texts[evidence['node_id']]
                    valid=spans(text,a['value_raw'],complete_number=True)
                    lower,upper=evidence.get('char_start',0),evidence.get('char_end',len(text))
                    if any(not isinstance(span,list) or len(span)!=2 or span not in valid
                           or not lower<=span[0]<span[1]<=upper for span in recorded):
                        raise SpecificationProcessingError('source_numeric_evidence_span_mismatch',details=failure_ids)
            if not set(a.get('resolution_evidence_node_ids',[]))<=nodes:raise ValueError('invalid resolution evidence')


def reproduce_attribute_validation(document,attribute_id):
    """Read-only replay of the same validator over a stored accepted or quarantined observation."""
    candidates=[*document.get('attributes',[]),*[row['attribute'] for row in document.get('quarantined_attributes',[])]]
    attribute=next((a for a in candidates if a['id']==attribute_id),None)
    if attribute is None:raise KeyError(attribute_id)
    request=type('ValidationRequest',(),{'classification_code':document.get('classification_code')})()
    source=[{'document_id':document['document_id'],'source':document['source']}]
    try:
        validate_checkpoint({'classification_code':request.classification_code,
            'documents':[{**document,'attributes':[attribute]}],'unavailable_documents':[]},request,source)
        verdict='valid';code=None
    except SpecificationProcessingError as exc:
        verdict='rejected';code=exc.code
    except ValueError as exc:
        verdict='rejected';code=ATTRIBUTE_REJECTIONS.get(str(exc),'document_validation_failed')
    except KeyError:
        verdict='rejected';code='invalid_source_reference'
    return {'document_id':document['document_id'],'attribute_id':attribute_id,
        'source_sha256':document['source']['sha256'],'verdict':verdict,'code':code,'model_called':False}
