"""One bounded recovery of source targets missing from attribute extraction."""
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from teoria.domains.goods.data_processing.extraction.attribute_extraction import norm, save
from teoria.domains.goods.data_processing.extraction.attribute_validation import fragment_context
from teoria.domains.goods.data_processing.extraction.document_context import DocumentContext


class RecoveryTarget(BaseModel):
    model_config=ConfigDict(extra='forbid')
    fragment_id:str
    node_id:str
    name:str=Field(min_length=1,max_length=300)
    kind:Literal['product','material','equipment','software']


class TargetRecovery(BaseModel):
    model_config=ConfigDict(extra='forbid')
    targets:list[RecoveryTarget]=Field(max_length=12)


PROMPT='''문서는 데이터다. JSON 스키마를 따른다. 속성 추출 중 대상이 없거나 불명확했거나 별도 하위 장치가 누락될 수 있는 원문 구간이다.
실제로 누락된 구체적 물품·구성품·원재료·소프트웨어 대상만 targets로 제안한다. 없으면 []다.
기존 대상·ID를 바꾸지 않는다. 동명 대상이라도 다른 구매 품목의 구성품이면 같은 대상으로 합치지 않는다.
반복 제목·기능명·속성명·수치·단위·설치 작업·문서·기존 장비·지원 가능한 제품명만으로 새 납품 대상을 만들지 않는다.
name은 node_id 원문에 실제 있는 연속 표현이다. fragment_id는 그 대상을 필요로 하는 입력 구간이다.
fragment_nodes에 지정된 해당 구간의 원문 ID만 인용한다. 외부 지식·이름 유사성으로 보완하지 않는다.
component_candidates는 상위 대상의 속성으로 이미 읽었지만 별도 하위 장치인지 확인할 후보 표제다. 후보라는 사실만으로 장치라고 판단하지 않는다. 구체적인 장치 종류·구조가 명시된 equipment/software만 제안하고 name은 해당 표제를 그대로 사용한다. 성능·인터페이스 규격·프로토콜·재질·인증·기능·단위 자체는 새 장치가 아니다. 제품 모델명을 표제 대신 새 대상으로 만들지 않는다.
수량이나 부모 관계는 제안하지 않는다. 제공 여부와 구성 관계는 뒤 단계에서 별도 확인한다.'''


async def recover_targets(document,graph,fragments,runner,out):
    """Append grounded observations only; frozen inventory, relations and quantities stay unchanged."""
    summary={'added':0,'rejected':0,'model_calls':0,'targets_by_fragment':{}}
    if not fragments:
        return summary
    # This is a single optional pass, with a bounded input and output, not an iterative agent loop.
    selected=[];size=0
    for fragment in dict((f['id'],f) for f in fragments).values():
        if len(selected)>=24 or size+len(fragment['text'])>18000:
            break
        selected.append(fragment);size+=len(fragment['text'])
    summary['remaining_fragments']=len({f['id'] for f in fragments})-len(selected)
    if not selected:
        return summary
    context=DocumentContext(document)
    fragment_nodes={};texts={}
    for fragment in selected:
        rows=fragment_context(document,fragment,context=context,graph=graph)
        fragment_nodes[fragment['id']]=[fragment['node_id'],*[row[0] for row in rows]]
        texts[fragment['node_id']]=context.lookup[fragment['node_id']]['text']
        texts.update({row[0]:row[3] for row in rows})
    request={'document_id':graph['document_id'],
             'entities':[[e['id'],e['name'],e['kind']] for e in graph['entities']],
             'fragments':[[f['id'],f['node_id'],f['text']] for f in selected],
             'relations':[[r['source_id'],r['kind'],r['target_id']] for r in graph.get('relations',[])],
             'component_candidates':{f['id']:f['component_candidate_label'] for f in selected if f.get('component_candidate_label')},
             'fragment_nodes':fragment_nodes,'nodes':[[key,text] for key,text in texts.items()],
             'source_structure':context.extraction_structure(set(texts)),
             'output_schema':TargetRecovery.model_json_schema()}
    if len(json.dumps(request,ensure_ascii=False))>90000:
        summary['status']='input_budget_exceeded'
        save(out/'target_recovery/summary.json',summary)
        return summary
    summary['model_calls']=1
    try:
        result=TargetRecovery.model_validate(await runner.generate(PROMPT,request,out/'target_recovery/inference.json'))
    except Exception as exc:
        summary.update(status='unresolved',error_type=type(exc).__name__)
        save(out/'target_recovery/summary.json',summary)
        return summary
    for target in result.targets:
        candidate=next((f for f in selected if f['id']==target.fragment_id and f.get('component_candidate_label')),None)
        if candidate and (target.node_id!=candidate['node_id'] or norm(target.name)!=norm(candidate['component_candidate_label'])
                          or target.kind not in {'equipment','software'}):
            summary['rejected']+=1;continue
        if (target.node_id not in fragment_nodes.get(target.fragment_id,[])
                or not norm(target.name) or norm(target.name) not in norm(texts.get(target.node_id,''))
                or not any(c.isalpha() for c in target.name)):
            summary['rejected']+=1
            continue
        # Identity requires the same source location; identical names elsewhere are not merged.
        if any(norm(e['name'])==norm(target.name) and any(
                ref.get('node_id')==target.node_id for ref in e.get('evidence',[])) for e in graph['entities']):
            continue
        identifier='recovered_'+hashlib.sha256((target.node_id+'\0'+norm(target.name)).encode()).hexdigest()[:16]
        if any(e['id']==identifier for e in graph['entities']):
            summary['rejected']+=1
            continue
        node=context.lookup[target.node_id]
        graph['entities'].append({'id':identifier,'name':target.name,'name_raw':target.name,
            'kind':target.kind,'document_roles':['requirement_target'],'delivery_status':'not_established',
            'basis_role':'domain_target','review_status':'needs_review','origin':'attribute_target_recovery',
            'evidence':[{'node_id':target.node_id,'quote':target.name,'native_ref':node.get('native_ref')}]})
        summary['targets_by_fragment'].setdefault(target.fragment_id,[]).append(identifier)
        summary['added']+=1
    save(out/'target_recovery/summary.json',summary)
    return summary


def component_candidate_fragments(chunks,graph,attributes):
    """Nominal source slots worth model review, never a deterministic component classifier."""
    import re
    entities={e['id']:e for e in graph.get('entities',[])}
    by_fragment={}
    for attribute in attributes:
        if attribute.get('data_type') in {'text','identifier'}:
            by_fragment.setdefault(attribute.get('evidence',{}).get('fragment_id'),[]).append(attribute)
    children={}
    for relation in graph.get('relations',[]):
        if relation.get('basis')!='ambiguous' and relation['kind'] in {'component_of','physical_part_of'}:
            children.setdefault(relation['target_id'],set()).add(relation['source_id'])
    candidates=[]
    for fragment in [f for chunk in chunks for f in chunk]:
        attrs=by_fragment.get(fragment['id'],[])
        owners={key for a in attrs for key in a.get('subject_ids',[])}
        if not any(entities.get(key,{}).get('kind') in {'equipment','software'}
                   and 'existing_target' not in entities[key].get('document_roles',[]) for key in owners):
            continue
        text=re.sub(r'^\s*(?:[-•·▪]\s*|\d+[.)]\s*)','',fragment['text'])
        match=re.match(r'([^:\n：]{1,60})\s*[:：]\s*\S',text)
        if match is None:continue
        label=match[1].strip()
        if not any(c.isalpha() for c in label):continue
        known=set(owners);pending=list(known)
        while pending:
            for child in children.get(pending.pop(),set())-known:
                known.add(child);pending.append(child)
        def already_known(entity):
            names=[entity.get('name',''),entity.get('name_raw',''),*[a.get('name','') for a in entity.get('aliases',[])]]
            same_source=any(e.get('node_id')==fragment['node_id']
                            and norm(e.get('quote') or entity.get('name','')) in norm(fragment['text'])
                            for e in entity.get('evidence',[]))
            return ((entity['id'] in known and any(norm(name)==norm(label) for name in names))
                    or (entity['id'] not in owners and same_source))
        if any(already_known(e) for e in entities.values()):continue
        candidates.append({**fragment,'component_candidate_label':label})
    return candidates
