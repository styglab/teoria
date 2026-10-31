"""Names split from actual specification phrases without changing product IDs or quantities."""
from copy import deepcopy
import pytest
from teoria.features.specification_processing.extraction.entity_relation_extraction import Inventory,Details,materialize,validate_details
from teoria.features.specification_processing.extraction.target_names import TargetName,validate_materialized_names


def fixture():
    texts={'root':'모니터링 장치 1식','sensor':'센서 및 분석장치 (CO, H2S, O2, EX, SO2, HBR)',
           'quantity':'8개','alias':'센서 및 분석장치'}
    doc={'document_id':'doc','nodes':[{'node_id':k,'text':v,'native_ref':'/'+k,'kind':'paragraph'} for k,v in texts.items()]}
    inv=Inventory(root=('root','모니터링 장치','1','식',['root']),basis='supply_list',basis_node_ids=['root'],
        items=[('i1','sensor',texts['sensor'],'8','개',['sensor','quantity'])],integrated_scope=True,
        scope_evidence_node_ids=['root'],issues=[])
    details=Details(additional=[],types=[('root','equipment','required'),('i1','equipment','required')],
        relations=[],scopes=[],issues=[],names=[TargetName(entity_id='i1',name='센서 및 분석장치',
        aliases=[('alias','센서 및 분석장치')],descriptions=[('sensor','CO, H2S, O2, EX, SO2, HBR')])])
    return doc,inv,details


def test_core_name_preserves_source_name_descriptions_and_quantities():
    doc,inv,details=fixture()
    assert not validate_details(details,inv,doc)
    graph=materialize(inv,details,doc)
    assert [e['id'] for e in graph['entities']]==['root','i1']
    item=graph['entities'][1]
    assert item['name']=='센서 및 분석장치'
    assert item['name_raw']==inv.items[0][2]
    assert item['aliases'][0]['name']==inv.items[0][2]
    assert item['descriptions'][0]['text']=='CO, H2S, O2, EX, SO2, HBR'
    assert next(q for q in graph['declared_quantities'] if q['entity_id']=='i1')['value_raw']=='8'
    validate_materialized_names(item,doc)


@pytest.mark.parametrize('change',['invented_core','invented_alias','toc_alias','duplicate_id'])
def test_names_cannot_invent_rewrite_or_use_toc_evidence(change):
    doc,inv,details=fixture()
    if change=='invented_core':details.names[0].name='가스 분석기'
    elif change=='invented_alias':details.names[0].aliases=[('alias','신규 센서')]
    elif change=='toc_alias':doc['document_assessment']={'node_roles':{'alias':'table_of_contents'}}
    else:details.names.append(details.names[0].model_copy())
    assert validate_details(details,inv,doc)


def test_name_alias_tampering_is_rejected_at_checkpoint():
    doc,inv,details=fixture();item=materialize(inv,details,doc)['entities'][1]
    item['aliases'][0]['name']='다른 센서'
    with pytest.raises(ValueError,match='source mismatch'):validate_materialized_names(item,doc)


def test_independent_food_rows_are_never_merged_by_a_shared_name():
    doc,inv,details=fixture();doc['nodes']+=[{'node_id':'milk1','kind':'paragraph','native_ref':'/milk1','text':'우유(저지방) 200mL'},
        {'node_id':'milk2','kind':'paragraph','native_ref':'/milk2','text':'우유(일반) 200mL'}]
    inv.items=[('i1','milk1','우유(저지방)',None,None,['milk1']),('i2','milk2','우유(일반)',None,None,['milk2'])]
    details.types=[('root','group','required'),('i1','product','required'),('i2','product','required')]
    details.names=[]
    graph=materialize(inv,details,doc)
    assert [(e['id'],e['name']) for e in graph['entities'][1:]]==[('i1','우유(저지방)'),('i2','우유(일반)')]


def test_meat_processing_variant_cannot_be_removed_from_the_name():
    # Existing meat workbook: name cell and corresponding specification cell in one row.
    doc,inv,details=fixture()
    doc['nodes'] += [{'node_id':'beef','kind':'cell','native_ref':'/beef','text':'한우(갈비)/탕용'},
                     {'node_id':'beef_spec','kind':'cell','native_ref':'/beef_spec','text':'갈비(탕용)'}]
    inv.items=[('i1','beef','한우(갈비)/탕용',None,None,['beef'])]
    details.types=[('root','group','required'),('i1','product','required')]
    details.names=[TargetName(entity_id='i1',name='한우(갈비)',descriptions=[('beef','탕용')])]
    assert any('original variant' in e for e in validate_details(details,inv,doc))
    details.names[0].name='한우(갈비)/탕용'
    details.names[0].aliases=[('beef_spec','갈비(탕용)')]
    assert not validate_details(details,inv,doc)
    graph=materialize(inv,details,doc)
    assert graph['entities'][1]['name']=='한우(갈비)/탕용'
    validate_materialized_names(graph['entities'][1],doc)
