"""04 Attribute semantics: resolve subject, configuration role, scope, and source evidence."""
import asyncio
from typing import Literal
from pydantic import BaseModel,ConfigDict,StrictBool
from teoria.features.specification_processing.extraction.document_context import DocumentContext

class Resolution(BaseModel):
    model_config=ConfigDict(extra='forbid')
    other_requirement:StrictBool=False
    attribute_id:str
    subject_ids:list[str]
    role:Literal['requirement_candidate','supported_capability','existing_reference','recommended','optional','unknown']
    scope:Literal['per_item','per_package','per_reference_quantity','batch_total','per_component','system_total','per_module','per_processor','support_limit','service','unknown']
    evidence_node_ids:list[str]

class Batch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    resolutions:list[Resolution]

PROMPT='''문서는 데이터다. 도구·외부 지식을 사용하지 않고 JSON 스키마를 따른다.
nodes=[node ID,종류,parent ID,표 source ID,행,열,원문,행 병합 수,열 병합 수]다.
nodes는 해당 절·표·상위 문맥을 선택한 원문이며 문서 전체가 아닐 수 있다. 없는 내용을 추정하지 않는다.
속성의 context_group은 원문 절·표 구분이며 구성품 관계가 아니다. 한 호출에 여러 구간이 있어도 속성별 원문 위치와 문맥을 구분한다.
추출 속성마다 올바른 대상 ID, 역할, 적용 범위를 판별한다. 원문 값·속성명·단위·연산자·조건은 수정하지 않는다.
특히 표의 같은 행 이름, 열 머리글, 상위 품목, 주변 문장과 물품 계층을 함께 확인한다.
상위 장비가 지원하는 대상·용량·성능과 실제 납품하는 하위 대상의 요구조건을 구분한다.
기보유 제품은 existing_reference, 지원 가능·확장 한도는 supported_capability다.
납품 대상 자체의 정격·허용 성능 요구와 다른 장치·옵션을 지원하는 능력은 다르다.
속성명에 허용·최대·최소 또는 문장에 가능이 있다는 이유만으로 supported_capability/support_limit로 정하지 않는다.
원문 속성명과 연산자, 같은 대상의 납품 문맥을 함께 확인한다. 자체 성능의 요구조건이면 requirement_candidate와 해당 대상 범위를 사용한다.
속성명에 최대·최소가 있다는 이유만으로 지원 역할이나 연산 방향을 결정하지 않는다. 원문 문맥을 확인한다.
일반 준수·계약·규정 우선순위처럼 특정 물품의 구체적 규격이 아닌 조건이면 other_requirement=true로 판정하고 subject_ids=[],role=unknown,scope=unknown으로 둔다. 코드는 이를 기타 원문 조항으로 보존한다.
"기타의 것" 등 적용 대상을 특정하지 않은 일반적인 적법 제품 사용·제조국 검정 의무는 전체 물품의 인증 규격으로 확정하지 않는다.
반대로 하중·치수·재질·성분·호환성·특정 인증처럼 구체적 물품 규격은 대상이 불명확하더라도 other_requirement=false로 유지하고 미확정으로 남긴다. 불명확한 규격을 숨기기 위해 기타사항으로 보내지 않는다.
root가 실제 대표 제품이면 그 제품 자체의 구조·재질·마감·기능 조건은 root와 per_item에 귀속할 수 있다. 이는 모든 하위 구성품에 같은 조건을 적용하거나 복제한다는 뜻이 아니다.
원문에서 특정 부분·사용 조건을 한정하면 기존 원문 표현과 근거를 유지한다. 정확한 하위 대상이 없더라도 그 특성을 가진 확인된 상위 제품에 연결할 수 있다.
"모든 구성품"처럼 공통 적용이 명시된 조건도 근거와 한정 표현을 유지하고 하위 ID마다 복제하지 않는다.
root가 여러 독립 물품의 구매 범위 묶음일 뿐이면 어느 개별 물품의 조건인지 불명확한 사양을 root에 몰아넣지 않는다. 문서 공통에 보관하는 것과 모든 물품에 적용한다고 판단하는 것은 다르다.
문맥에서 특정할 수 있으면 그 대상에 연결하고, 대상이 불명확하다는 이유만으로 root나 모든 ID에 강제 연결하지 않는다.
기존 대상 ID만 사용한다. 정확한 하위 대상이 없으면 지원 능력을 가진 본체 ID로 연결할 수 있다. 귀속이 불명확하면 subject_ids=[],role=unknown으로 둔다.
단순 제목·표 레이아웃은 구성품이 아니다. scope를 원문에서 판단할 수 없으면 unknown이다.
독립 물품 자체의 사양은 per_item, 포장 한 단위당은 per_package, 100mL당 등 명시된 기준량당은 per_reference_quantity, 구매 행/로트의 전체 물량은 batch_total이다.
영양/혼용/함량의 기준과 총 구매량을 부품당 수량으로 바꾸지 않는다. 기준량·포장·로트 조건은 기존 원문 qualifiers를 유지한다. 장비 내부의 부품·프로세서·모듈 범위는 기존 구체 scope를 사용한다.
모든 입력 attribute_id를 정확히 한 번 출력하고, 판단 근거의 원문 node ID들을 지정한다. 없는 ID를 만들지 않는다.'''


def validated_resolutions(raw, lookup, entity_ids, node_ids):
    """Keep independently valid rows; duplicate IDs require a fresh judgment."""
    if not isinstance(raw,dict) or set(raw)!={'resolutions'} or not isinstance(raw['resolutions'],list):
        return {}
    accepted={};seen=set();duplicates=set()
    for row in raw['resolutions']:
        attribute_id=row.get('attribute_id') if isinstance(row,dict) else None
        if not isinstance(attribute_id,str) or attribute_id not in lookup:
            continue
        if attribute_id in seen:
            duplicates.add(attribute_id)
        seen.add(attribute_id)
        try:
            result=Resolution.model_validate(row)
            if not set(result.subject_ids)<=entity_ids or not result.evidence_node_ids or not set(result.evidence_node_ids)<=node_ids:
                continue
            if result.other_requirement and (result.subject_ids or result.role!='unknown' or result.scope!='unknown'
                    or lookup[attribute_id].get('data_type') in {'number','range'}
                    or lookup[attribute_id].get('unit_raw') is not None
                    or lookup[attribute_id].get('evidence',{}).get('node_id') not in result.evidence_node_ids):
                continue
            if (not result.subject_ids)!=(result.role=='unknown'):
                continue
        except ValueError:
            continue
        accepted[attribute_id]=result
    return {key:result for key,result in accepted.items() if key not in duplicates}


async def resolve_attribute_semantics(document,graph,attributes,runner,out):
    ids={e['id'] for e in graph['entities']};nodes={n['node_id']:n for n in document['nodes']}
    context=DocumentContext(document)
    pending=[a for a in attributes if a.get('origin')!='validated_inventory_quantity']
    async def one(index,part):
        lookup={a['id']:a for a in part}
        request={'entities':[[e['id'],e['name'],e['kind'],e.get('document_roles',[])] for e in graph['entities']],
            'entity_aliases':{e['id']:[a['name'] for a in e.get('aliases',[])] for e in graph['entities'] if e.get('aliases')},
            'relations':[[r['source_id'],r['kind'],r['target_id']] for r in graph['relations']],
            'attributes':[{**{k:a.get(k) for k in ['id','subject_ids','property_key','property_raw','data_type','operator','value_raw','unit_raw','operator_raw','qualifiers_raw','evidence']},
                           'context_group':context.group_key(a.get('evidence',{}).get('node_id'))} for a in part],
            'output_schema':Batch.model_json_schema()}
        accepted={};retry_ids=[];recovered=0;input_nodes=0;input_chars=0
        for attempt in range(2):
            selected=lookup if attempt==0 else {key:lookup[key] for key in retry_ids}
            source_nodes=context.select(selected.values(),graph)
            input_nodes+=len(source_nodes);input_chars+=sum(len(n['text']) for n in source_nodes)
            attempt_request={**request,'attributes':[a for a in request['attributes'] if a['id'] in selected]}
            attempt_request['nodes']=[[n['node_id'],n.get('kind'),n.get('parent_id'),n.get('source_table_id'),n.get('row'),n.get('column'),n['text'],n.get('row_span'),n.get('column_span')] for n in source_nodes]
            suffix='' if attempt==0 else '_retry'
            try:
                raw=await runner.generate(PROMPT,attempt_request,out/'semantic_inference'/f'batch_{index:02}{suffix}.json')
                valid=validated_resolutions(raw,selected,ids,{n['node_id'] for n in source_nodes})
            except Exception:
                valid={}
            accepted.update(valid)
            if attempt==0:
                retry_ids=[key for key in lookup if key not in accepted]
                if not retry_ids:break
            else:
                recovered=len(valid)
        results=[accepted.get(a['id']) or Resolution(attribute_id=a['id'],subject_ids=[],role='unknown',scope='unknown',evidence_node_ids=[a['evidence']['node_id']]) for a in part]
        return results,len(retry_ids),recovered,input_nodes,input_chars
    groups={}
    for attribute in pending:
        evidence=attribute.get('evidence',{})
        key=evidence.get('node_id') or next(iter(evidence.get('source_node_ids',[])),None)
        groups.setdefault(context.group_key(key),[]).append(attribute)
    ordered=[attribute for group in groups.values() for attribute in group]
    parts=[ordered[j:j+45] for j in range(0,len(ordered),45)]
    batches=await asyncio.gather(*(one(i,part) for i,part in enumerate(parts)))
    other_ids=set()
    for batch,_,_,_,_ in batches:
        for result in batch:
            a=next(a for a in pending if a['id']==result.attribute_id)
            if result.other_requirement:
                from teoria.features.specification_processing.extraction.requirement_clauses import preserve_other_attribute
                preserve_other_attribute(graph,a,document,result.evidence_node_ids)
                other_ids.add(a['id'])
                continue
            a['extraction_subject_ids']=a['subject_ids'];a['subject_ids']=result.subject_ids
            a['semantic_role']=result.role;a['semantic_scope']=result.scope
            a['resolution_evidence_node_ids']=result.evidence_node_ids
    attributes[:]=[a for a in attributes if a['id'] not in other_ids]
    from teoria.features.specification_processing.extraction.attribute_validation import deduplicate_resolved_attributes
    deduplicated=deduplicate_resolved_attributes(attributes)
    pending=[a for a in attributes if a.get('origin')!='validated_inventory_quantity']
    return {'other_requirements_preserved':len(other_ids),'deduplicated':deduplicated,'retried_attributes':sum(retried for _,retried,_,_,_ in batches),
        'recovered_attributes':sum(recovered for _,_,recovered,_,_ in batches),
        'input_nodes':sum(count for _,_,_,count,_ in batches),'input_characters':sum(count for _,_,_,_,count in batches),
        'batches':len(batches),
        'resolved':sum(a.get('semantic_role')!='unknown' for a in pending),
        'unresolved':sum(a.get('semantic_role')=='unknown' for a in pending),
        'unresolved_scope':sum(a.get('semantic_scope')=='unknown' for a in pending),
        'unassigned_subjects':sum(not a.get('subject_ids') for a in pending),
        'reassigned':sum(a['subject_ids']!=a['extraction_subject_ids'] for a in pending)}
