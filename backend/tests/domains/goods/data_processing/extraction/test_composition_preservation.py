"""Attribute processing may append grounded targets, never rewrite accepted composition."""
from copy import deepcopy
import pytest
from teoria.domains.goods.data_processing.extraction.composition_review import assert_composition_preserved


def composition():
    return {'entities':[{'id':'root','name':'분석기','kind':'equipment'},
                        {'id':'pc','name':'PC SYSTEM','kind':'equipment'}],
            'relations':[{'id':'r','source_id':'pc','target_id':'root','kind':'component_of','basis':'explicit'}],
            'composition_inventory':{'root_id':'root','item_ids':['pc']},
            'inventory_ids':['pc'],'declared_quantities':[{'entity_id':'pc','value_raw':'1','unit_raw':'set'}]}


@pytest.mark.parametrize('mutation',['delete_entity','rename_entity','change_kind','delete_relation','reparent',
                                     'reorder_inventory','change_quantity'])
def test_attribute_stage_cannot_change_accepted_composition(mutation):
    before=composition();after=deepcopy(before)
    if mutation=='delete_entity':after['entities'].pop()
    if mutation=='rename_entity':after['entities'][1]['name']='다른 장치'
    if mutation=='change_kind':after['entities'][1]['kind']='group'
    if mutation=='delete_relation':after['relations']=[]
    if mutation=='reparent':after['relations'][0]['target_id']='other'
    if mutation=='reorder_inventory':after['composition_inventory']['item_ids']=['other','pc']
    if mutation=='change_quantity':after['declared_quantities'][0]['value_raw']='2'
    with pytest.raises(ValueError,match='composition'):assert_composition_preserved(before,after)


def test_source_backed_additions_and_description_reclassification_preserve_the_base():
    before=composition();after=deepcopy(before)
    after['entities'].append({'id':'cpu','name':'CPU','kind':'equipment'})
    after['relations'].append({'id':'r2','source_id':'cpu','target_id':'pc','kind':'component_of'})
    after['requirements']=[{'category':'description','text':'분석 용도'}]
    assert_composition_preserved(before,after)
    assert before==composition()
