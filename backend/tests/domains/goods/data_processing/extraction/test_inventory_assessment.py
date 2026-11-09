"""A missing list, uncertain reading, and confirmed purchase rows are different observations."""
import pytest

from teoria.domains.goods.data_processing.extraction.entity_relation_extraction import (
    Details, Inventory, inventory_assessment, materialize, review_relations, validate_details,
)
from teoria.domains.goods.data_processing.extraction.extraction_status import document_extraction_status


def case(basis='supply_list'):
    texts={'root':'모니터링 장치','list':'공급 목록','item':'데이터 전송장치 8 식',
           'work':'환경감시 센서의 구성은 데이터 전송장치로 구성',
           'mention':'데이터 전송장치'}
    doc={'document_id':'source','nodes':[{'node_id':id,'text':text,'page':1,
         'native_ref':'/'+id,'kind':'paragraph'} for id,text in texts.items()]}
    inv=Inventory(root=('root','모니터링 장치',None,None,['root']),basis=basis,
        basis_node_ids=['list'],integrated_scope=True,scope_evidence_node_ids=['root'],issues=[],
        items=[('i1','item','데이터 전송장치','8','식',['item'])])
    details=Details(additional=[('group','work','환경감시 센서')],
        types=[('root','equipment','required'),('i1','equipment','required'),('group','group','required')],
        relations=[('i1','group','component_of','explicit',['work'])],scopes=[],issues=[])
    return doc,inv,details


def test_grounded_composition_does_not_create_purchase_rows_or_propagate_quantity():
    doc,inv,details=case();reviewed,held=review_relations(details,inv,doc)
    graph=materialize(inv,reviewed,doc,held)
    assert held==[] and graph['inventory_ids']==['i1']
    assert [(q['entity_id'],q['value_raw'],q['unit_raw']) for q in graph['declared_quantities']]==[('i1','8','식')]
    assert graph['inventory_assessment']['status']=='confirmed'


def test_same_named_mention_is_allowed_only_with_grounded_ambiguous_identity():
    doc,inv,details=case();details.additional.append(('m','mention','데이터 전송장치'))
    details.types.append(('m','equipment','unknown'))
    assert any('recreated frozen' in e for e in validate_details(details,inv,doc))
    details.relations=[('m','group','component_of','explicit',['work']),
        ('m','i1','same_target_as','ambiguous',['mention','item'])]
    assert validate_details(details,inv,doc)==[]
    reviewed,held=review_relations(details,inv,doc);graph=materialize(inv,reviewed,doc,held)
    assert len(held)==1 and held[0]['relation'][2]=='same_target_as'
    assert validate_details(reviewed,inv,doc,held_relations=held)==[]
    assert validate_details(reviewed,inv,doc)!=[]
    assert any(r['source_id']=='m' and r['target_id']=='group' for r in graph['relations'])
    assert [q['entity_id'] for q in graph['declared_quantities']]==['i1']


@pytest.mark.parametrize('basis',['technical_table','technical_sections'])
def test_no_list_uses_detail_fallback_without_claiming_read_failure(basis):
    doc,inv,_=case(basis)
    assert inventory_assessment(inv,doc)['status']=='detail_fallback'


@pytest.mark.parametrize('status',['unsupported','failed','partial'])
def test_table_failure_does_not_become_a_missing_list_or_success(status):
    doc,inv,_=case('technical_sections')
    doc['parse_diagnostics']=[{'code':'INVALID_TABLE','source':{'page':1}}]
    doc['table_recovery']={'status':status}
    assessment=inventory_assessment(inv,doc)
    assert assessment['status']=='reading_failed'
    assert document_extraction_status({'status':'needs_review'},{'inventory_assessment':assessment},doc)=='partial'


def test_recovered_text_is_not_a_claim_of_recovered_table_structure():
    doc,inv,_=case();doc['parse_diagnostics']=[{'code':'INVALID_TABLE','source':{'page':1}}]
    doc['table_recovery']={'status':'text_recovered'}
    assert inventory_assessment(inv,doc)['status']=='reading_uncertain'


def test_unrelated_table_warning_does_not_invalidate_a_confirmed_list_on_another_page():
    doc,inv,_=case();doc['parse_diagnostics']=[{'code':'INVALID_TABLE','source':{'page':5}}]
    assert inventory_assessment(inv,doc)['status']=='confirmed'

async def test_real_extraction_handoff_keeps_ambiguous_identity_evidence_after_relation_review(tmp_path):
    import json
    from teoria.domains.goods.data_processing.extraction.entity_relation_extraction import extract_entity_relations
    doc,inv,details=case()
    for node in doc['nodes']:
        node.update(parent_id=None,row=None,column=None,row_span=None,column_span=None)
    details.additional.append(('m','mention','데이터 전송장치'))
    details.types.append(('m','equipment','unknown'))
    details.relations=[('m','group','component_of','explicit',['work']),
        ('m','i1','same_target_as','ambiguous',['mention','item'])]
    class Predictions:
        def __init__(self):self.calls=0
        async def generate(self,*args,**kwargs):
            self.calls+=1
            return (inv if self.calls==1 else details).model_dump()
    await extract_entity_relations(doc,tmp_path,Predictions())
    graph=json.loads((tmp_path/'graph.json').read_text())
    assert graph['inventory_ids']==['i1']
    assert [q['value_raw'] for q in graph['declared_quantities']]==['8']
    assert graph['held_relations'][0]['kind']=='same_target_as'
    assert any(r['source_id']=='m' and r['target_id']=='group' for r in graph['relations'])
