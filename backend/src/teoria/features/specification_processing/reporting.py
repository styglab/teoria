"""Readable output from canonical extraction/normalization, without HTML/debug copies."""
from collections import defaultdict
import html

def cell(value):return html.escape(str(value)).replace('|','&#124;').replace('\n','<br>').replace('`','&#96;').replace('[','&#91;').replace(']','&#93;')


def render_report(corpus,normalized,standard_version,candidates=None):
    authority=('승인된 프로파일의 Published Ontology 참조를 적용한 문서별 관찰이며 Ontology 게시가 아닙니다.'
               if normalized.get('artifact_kind')=='goods_normalized_observations' else
               '자동 채택 결과는 로컬 추출 표준이며 Published Ontology가 아닙니다.')
    excluded=sum(d.get('disposition')=='excluded' for d in corpus['unavailable_documents'])
    failed=len(corpus['unavailable_documents'])-excluded
    lines=['# 규격 정보 처리 결과','',f"표준 버전: `{standard_version}`. {authority}",'',
        f"문서 {len(corpus['documents'])}개 처리, {failed}개 실패, {excluded}개 대상 제외. 속성 {sum(len(d['attributes']) for d in corpus['documents'])}개. "
        f"표준 적용 {normalized['summary'].get('applied',0)}개, 자동 보류 {normalized['summary'].get('automatically_deferred',0)}개.",'',
        '[표준화 전 결과](extracted.json) · [표준 적용 결과](normalized.json)','','보류와 partial은 사람 승인 대기가 아닌 자동 처리 결과입니다. 원문 근거가 맞아도 의미 정확도를 보장하지 않습니다.','']
    if candidates is not None:lines+=['[표준 의미 후보](meaning_candidates.json)','']
    if normalized.get('source_term_alignment'):
        dictionary=normalized['source_term_alignment'];counts=dictionary['summary']
        lines+=['## 원문 표현 등록','',
            f"원문 명칭 사전: 승인 {counts.get('approved',0)}개, 재사용 {counts.get('reused',0)}개, 보류 {counts.get('held',0)}개.",
            '원문 표현 등록 ID는 표준 개념 ID가 아닙니다. 문서 요구·구성 전체나 개념 동등성의 승인을 뜻하지 않습니다.',
            f"표준 개념 매핑 결과: {cell(dictionary.get('meaning_summary',{}))}. 승인된 범위의 매핑만 재사용하며 단위 환산은 수행하지 않습니다.",
            '[원문 표현 연결](source_term_alignment.json) · [자동 검토 이력](dictionary_bindings.json)','']
    if normalized.get('artifact_kind')=='goods_normalized_observations':
        lines+=['## Ontology 프로파일 적용','',
                f"프로파일: `{cell(normalized['profile_key'])}` / Ontology: `{cell(normalized['ontology']['namespace'])}@{cell(normalized['ontology']['version'])}`",'',
                '| 문서 | 원문 대상 | 표준 개념 / 보류 이유 | 상태 |','|---|---|---|---|']
        for document in normalized['documents']:
            for entity in document['entities']:
                lines.append(f"| {cell(document['document_id'])} | {cell(entity['name_raw'])} | {cell(entity.get('concept_key',entity.get('reason','')))} | {cell(entity['status'])} |")
        lines+=['','| 문서 | 표준 관계 | 출발 → 도착 |','|---|---|---|']
        for document in normalized['documents']:
            names={e['observation_id']:e['name_raw'] for e in document['entities']}
            for relation in document['relations']:
                endpoints=names[relation['source_observation_id']]+' → '+names[relation['target_observation_id']]
                lines.append(f"| {cell(document['document_id'])} | {cell(relation['relationship_stable_key'])} | {cell(endpoints)} |")
        lines+=['',
                '| 문서 | 속성 개념 ID | 정규화 값 | 연산 | 역할 / 범위 | 원문 근거 |',
                '|---|---|---|---|---|---|']
        for document in normalized['documents']:
            for a in document['requirements']:
                v=a['value'];text=f"{v.get('decimal',v.get('text',''))} {v.get('unit','')}"
                lines.append(f"| {cell(document['document_id'])} | {cell(a['property_stable_key'])} | {cell(text)} | {cell(a['operator'])} | {cell(a['role'])} / {cell(a['semantic_scope'])} | {cell(a['evidence_ref'])} |")
        lines.append('')
    for d in corpus['documents']:
        entities={e['id']:e for e in d['entities']};children=defaultdict(dict)
        relation_labels={'in_procurement_scope':'범위','component_of':'구성','physical_part_of':'물리적 포함',
                         'specification_for':'상세 명세','service_for':'작업'}
        for r in d['relations']:
            if r['kind'] in relation_labels:
                labels=children[r['target_id']].setdefault(r['source_id'],[])
                if relation_labels[r['kind']] not in labels:labels.append(relation_labels[r['kind']])
        lines += [f"## {cell(d['document_id'])} — {cell(d.get('extraction_status','extracted'))}",'',f"[원본]({d['source']['path']})",'','```text']
        seen=set()
        def branch(eid,prefix='',path=frozenset(),labels=()):
            label='['+'·'.join(labels)+'] ' if labels else ''
            lines.append(prefix+label+entities[eid]['name'].replace('\n',' ').replace('`','ˋ')+f' [{eid}]');seen.add(eid)
            if eid in path:return
            for child,labels in children[eid].items():branch(child,prefix+'  └─ ',path|{eid},labels)
        if 'root' in entities:branch('root')
        for eid in entities:
            if eid not in seen:branch(eid)
        lines += ['```','']
        if d.get('held_relations'):
            lines+=['### 보류한 관계','','| 출발 | 관계 | 도착 | 보류 사유 | 근거 |','|---|---|---|---|---|']
            for relation in d['held_relations']:
                name=lambda key:entities.get(relation.get(key),{}).get('name',relation.get(key,''))
                refs=' / '.join(e.get('native_ref',e.get('node_id','')) for e in relation.get('evidence',[]))
                lines.append(f"| {cell(name('source_id'))} | {cell(relation['kind'])} | {cell(name('target_id'))} | {cell('; '.join(relation.get('reasons',[])))} | {cell(refs)} |")
            lines.append('')
        lines += ['| 대상 | 속성 | 원문 값·단위·조건 | 역할 / 범위 | 근거 |','|---|---|---|---|---|']
        for a in d['attributes']:
            subjects=', '.join(entities[e]['name'] for e in a['subject_ids']) or '대상 미확정'
            raw=f"{a['value_raw']} {a.get('unit_raw') or ''}; {a.get('operator_raw') or a['operator']}; {' / '.join(a.get('qualifiers_raw',[]))}"
            evidence=a['evidence'];position=evidence.get('node_id') or ', '.join(evidence.get('source_node_ids',[]))
            lines.append(f"| {cell(subjects)} | {cell(a['property_key'])} | {cell(raw)} | {cell(a.get('semantic_role','unknown'))} / {cell(a.get('semantic_scope','unknown'))} | {cell(position)} / {cell(a['id'])} |")
        lines.append('')
    for d in corpus['unavailable_documents']:
        label='대상 아님' if d.get('disposition')=='excluded' else '처리 실패'
        lines.append(f"- {cell(d['document_id'])}: {label} — {cell(d.get('code',d['reason']))}")
    return '\n'.join(lines)+'\n'
