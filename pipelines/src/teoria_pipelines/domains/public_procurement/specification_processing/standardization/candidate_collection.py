"""Collect all pending source meanings; domain catalogs are opt-in suggestions."""
from collections import Counter
import unicodedata


def target_type(entity,rule_set='source_only'):
    if rule_set=='server':
        from .server_rules import entity_type
        return entity_type(entity)
    kind=entity.get('kind','unknown')
    name=unicodedata.normalize('NFKC',entity.get('name','')).strip()
    if kind=='unknown' or not name:return 'unresolved'
    # A source label groups observations; it is not a published semantic type or synonym.
    return f'{kind}:{name}'


def observation_role(attribute):
    if attribute.get('semantic_role'):return attribute['semantic_role']
    if attribute.get('origin')=='validated_inventory_quantity':return 'requirement_candidate'
    return 'unknown'


def unit_context(unit):
    """Compatible spellings only. Preserve GB/Gb/G/GiB and MHz/MT/s distinctions."""
    aliases={'Core':'core','코어':'core','Ghz':'GHz','Gbps':'Gb/s','년간':'year','년':'year','years':'year','개월':'month','일':'day','주':'week'}
    if unit is None:return 'not_stated'
    return aliases.get(unit,unit)


def collect_meaning_candidates(corpus, normalized, standard):
    rule_set=standard.get('rule_set','source_only')
    if corpus['classification_code']!=standard['classification_code']:raise ValueError('standard classification differs from input')
    server=None
    if rule_set=='server':
        from . import server_rules as server
        server.validate_classification(corpus['classification_code'])
    pending={(a['document_id'],a['attribute_id']) for a in normalized['attributes'] if a['status']=='pending_definition'}
    known={d['id']:d for d in standard['definitions']}
    groups={}
    for doc in corpus['documents']:
        entities={e['id']:e for e in doc['entities']}
        for a in doc['attributes']:
            if (doc['document_id'],a['id']) not in pending:continue
            types=sorted({target_type(entities[eid],rule_set) for eid in a['subject_ids']})
            target=types[0] if len(types)==1 else 'multiple_target_types' if types else 'missing_target'
            families=server.FAMILY_BY_KEY if server else {}
            concept,label,scope=families.get(a['property_key'],(a['property_key'],a.get('property_raw') or a['property_key'],'meaning_unreviewed'))
            # Scope is part of the candidate, not inferred from a generic numeric unit.
            meaning_role=observation_role(a)
            proposed=server.existing_proposal(concept,target,scope,a) if server else None
            if proposed not in known:proposed=None
            reasons=[]
            if concept=='component_quantity' and proposed is None:
                reasons.append('수량 속성이 가리키는 구성 대상과 연결된 엔티티 유형이 달라 귀속 검토 필요')
            if concept=='component_quantity' and meaning_role=='existing_reference':
                proposed=None
                reasons.append('기존 보유 수량을 신규 구성 수량 요구로 연결하지 않음')
            if target in {'unresolved','multiple_target_types','missing_target'} or meaning_role=='unknown':reasons.append('대상 유형 또는 귀속 미확정')
            if scope=='meaning_unreviewed':reasons.append('아직 의미 규칙을 검토하지 않은 표현; 이름별 예비 묶음')
            if a['data_type'] in {'number','range'} and a.get('unit_raw') in {'G','Gb','M','K'}:
                reasons.append('단위·축약 표기 검토 필요; 대소문자 임의 치환 금지')
            if reasons:decision='hold_for_review';proposed=None
            elif proposed:decision='existing_definition_proposal'
            else:decision='new_definition_proposal'
            semantic_scope=a.get('semantic_scope','unknown')
            context=(concept,target,scope,semantic_scope,meaning_role,unit_context(a['unit_raw']),a['data_type'],decision,proposed)
            if context not in groups:
                groups[context]={'concept_key':concept,'label':label,'target_type_candidate':target,
                    'scope':scope,'semantic_scope':semantic_scope,'role':meaning_role,'unit_context':unit_context(a['unit_raw']),'value_kind_observed':a['data_type'],
                    'decision':decision,'existing_definition_id':proposed,'reasons':reasons,
                    'aliases':set(),'unit_spellings':set(),'documents':set(),'observations':[]}
            g=groups[context];g['aliases'].add((a['property_key'],a.get('property_raw')));g['unit_spellings'].add(a['unit_raw']);g['documents'].add(doc['document_id'])
            g['observations'].append({'document_id':doc['document_id'],'attribute_id':a['id'],'subject_ids':a['subject_ids']})
    result=[]
    for index,context in enumerate(sorted(groups,key=lambda k:tuple(str(v) for v in k)),1):
        g=groups[context]
        g['id']=f'meaning_candidate_{index:04}'
        g['aliases']=[{'property_key':k,'property_raw':raw} for k,raw in sorted(g['aliases'],key=lambda x:(x[0],x[1] or ''))]
        g['unit_spellings']=sorted(g['unit_spellings'],key=lambda u:u or '')
        g['document_count']=len(g.pop('documents'));g['observation_count']=len(g['observations'])
        g['review_status']='suggestion_not_approved'
        g['proposed_meaning']={
            'label':g['label'], 'target_type_candidate':g['target_type_candidate'], 'scope':g['scope'],
            'role':g['role'],'value_kind_observed':g['value_kind_observed'],
            'unit_context':g['unit_context'],
            'restrictions':['속성 ID로 원문 조건·연산자·대상 귀속을 대조해야 함', '수량을 부모·자식에 복제하지 않음', '지원 가능·기존 보유·납품 요구를 합치지 않음', '단위 축약 및 모델 성능을 추정하지 않음'],
            'definition_complete':False}
        if g['existing_definition_id']:
            assert g['existing_definition_id'] in known
            g['comparison']={'existing_label':known[g['existing_definition_id']]['label'],
                'basis':'명시 속성 의미와 대상·단위를 함께 확인한 제한적 연결 제안',
                'not_applied':True}
        else:
            g['comparison']={'basis':'검토한 동의 규칙에서 기존 정의 연결을 확정하지 못함; 미연결은 신규 개념임을 증명하지 않음','not_applied':True}
        result.append(g)
    references=[(r['document_id'],r['attribute_id']) for g in result for r in g['observations']]
    if set(references)!=pending or len(references)!=len(pending):raise ValueError('Pending observations must appear exactly once')
    decisions=Counter();group_counts=Counter()
    for g in result:decisions[g['decision']]+=g['observation_count'];group_counts[g['decision']]+=1
    return {'schema_version':1,'status':'meaning_collection_suggestions_only','classification_code':corpus['classification_code'],
        'rule_set':rule_set,'human_approved':False,'published':False,'normalization_applied':False,
        'summary':{'observations':len(pending),'groups':len(result),'observation_decisions':dict(decisions),'group_decisions':dict(group_counts)},
        'grouping_policy':'Explicit observed alias hypotheses + target type + scope + role + literal unit context + observed value kind. Unreviewed keys remain provisional buckets, not resolved meanings.',
        'candidates':result}

