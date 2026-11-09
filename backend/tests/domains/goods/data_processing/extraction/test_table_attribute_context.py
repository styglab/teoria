"""Source-backed table units and quantity subdivisions; no cross-table or inferred values."""
from copy import deepcopy

from teoria.domains.goods.data_processing.extraction.table_attribute_context import recover_table_attribute_context
from teoria.domains.goods.data_processing.evaluation.scoring import attribute_is_grounded


def cell(key,text,row,column,**extra):
    return dict(node_id=key,text=text,kind='cell',parent_id='t',row=row,column=column,native_ref='/'+key,**extra)


def attribute(key,value,**extra):
    return dict(id=key,subject_ids=['item'],property_key='quantity',data_type='number',operator='gte',
                operator_raw='이상',value_raw=value,unit_raw=None,qualifiers_raw=[],
                evidence=dict(node_id=key,char_start=0),**extra)


def test_vehicle_header_units_are_separate_literal_evidence_not_fabricated_inline_spans():
    # Original HWPX: headers n00086/n00089 and values n00091/n00094.
    nodes=[dict(node_id='t',text='',kind='table'),cell('h_length','전장(㎜)',0,1),
           cell('h_displacement','배기량(cc)',0,4),cell('length','6,195 이상',1,1),cell('displacement','2,497 이상',1,4)]
    attributes=[attribute('length','6,195'),attribute('displacement','2,497')];before=deepcopy(attributes)
    result=recover_table_attribute_context({'nodes':nodes},{},attributes)
    assert result['unit_recoveries']==2
    assert [a['unit_raw'] for a in attributes]==['㎜','cc']
    for old,new,header in zip(before,attributes,['h_length','h_displacement']):
        assert new['value_raw']==old['value_raw'] and new['subject_ids']==old['subject_ids'] and new['operator']==old['operator']
        assert new['evidence']['value_evidence']==old['evidence']
        assert new['evidence']['source_node_ids']==[old['id'],header]
        assert attribute_is_grounded({'parsed_document':{'nodes':nodes}},new)
    again=deepcopy(attributes)
    assert recover_table_attribute_context({'nodes':nodes},{},attributes)['unit_recoveries']==0
    assert attributes==again


def food_table():
    # Original XLSX: G23:I23 merged 예정수량, H24/I24 영양팀(1동)/(8동), F25 EA.
    nodes=[dict(node_id='t',text='',kind='table'),cell('unit_label','기본\n단위',17,5,row_span=2),
           cell('count','예정수량',17,6,column_span=3),cell('total','합계',18,6),
           cell('site1','영양팀\n(1동)',18,7),cell('site8','영양팀\n(8동)',18,8),
           cell('item','우유,200ml',19,2),cell('unit','EA',19,5),
           cell('one','92000',19,7),cell('eight','51000',19,8)]
    graph={'entities':[{'id':'item','document_roles':['supply_target'],'evidence':[{'node_id':'item'}]}]}
    attributes=[attribute('one','92000'),attribute('eight','51000')]
    for a in attributes:a.update(operator='eq',operator_raw=None)
    return {'nodes':nodes},graph,attributes


def test_split_quantity_retains_merged_header_subdivision_and_same_row_unit():
    document,graph,attributes=food_table()
    result=recover_table_attribute_context(document,graph,attributes)
    assert result['unit_recoveries']==result['quantity_scope_recoveries']==2
    assert [a['qualifiers_raw'] for a in attributes]==[['영양팀\n(1동)'],['영양팀\n(8동)']]
    assert [a['unit_raw'] for a in attributes]==['EA','EA']
    assert all(attribute_is_grounded({'parsed_document':document},a) for a in attributes)
    assert 'site8' not in attributes[0]['evidence']['source_node_ids']
    assert 'site1' not in attributes[1]['evidence']['source_node_ids']


def test_equal_values_in_different_columns_stay_distinct_and_do_not_take_another_rows_unit():
    document,graph,attributes=food_table()
    for n in document['nodes']:
        if n['node_id'] in ['one','eight']:n['text']='1700'
    for a in attributes:a['value_raw']='1700'
    document['nodes']+=[cell('other_unit','kg',20,5),cell('other_count','700',20,7)]
    recover_table_attribute_context(document,graph,attributes)
    assert attributes[0]['qualifiers_raw']!=attributes[1]['qualifiers_raw']
    assert all(a['unit_raw']=='EA' and 'other_unit' not in a['evidence']['source_node_ids'] for a in attributes)


def test_conflicting_header_units_and_embedded_numeric_prose_remain_unchanged():
    nodes=[dict(node_id='t',text='',kind='table'),cell('h1','폭(mm)',0,1),cell('h2','폭(cm)',0,1),
           cell('width','600 이상',1,1),cell('prose','폭 600, 높이 700',2,1)]
    attributes=[attribute('width','600'),attribute('prose','600')];before=deepcopy(attributes)
    result=recover_table_attribute_context({'nodes':nodes},{},attributes)
    assert result['ambiguous_units']==1 and result['unit_recoveries']==0
    assert attributes==before


def test_inline_unit_and_separate_tables_do_not_inherit_an_unrelated_header():
    nodes=[dict(node_id='t',text='',kind='table'),dict(node_id='other',text='',kind='table'),
           cell('h','길이(mm)',0,1),cell('value','600 이상',1,1)]
    nodes[-1]['parent_id']='other'
    attributes=[attribute('value','600')];before=deepcopy(attributes)
    assert recover_table_attribute_context({'nodes':nodes},{},attributes)['unit_recoveries']==0
    assert attributes==before
    nodes[-1]['parent_id']='t';attributes[0]['unit_raw']='cm'
    before=deepcopy(attributes);recover_table_attribute_context({'nodes':nodes},{},attributes)
    assert attributes==before


def test_missing_split_quantities_are_projected_from_explicit_cells_with_one_row_owner():
    document,graph,_=food_table();attributes=[]
    result=recover_table_attribute_context(document,graph,attributes)
    assert result['derived_quantities']==2
    assert [(a['value_raw'],a['unit_raw'],a['subject_ids']) for a in attributes]==[('92000','EA',['item']),('51000','EA',['item'])]
    assert [a['qualifiers_raw'] for a in attributes]==[['영양팀\n(1동)'],['영양팀\n(8동)']]
    assert all(attribute_is_grounded({'parsed_document':document},a) for a in attributes)
    before=deepcopy(attributes)
    assert recover_table_attribute_context(document,graph,attributes)['derived_quantities']==0
    assert attributes==before


def test_existing_prediction_is_preserved_and_only_missing_subdivision_is_added():
    document,graph,attributes=food_table();attributes=attributes[:1]
    assert recover_table_attribute_context(document,graph,attributes)['derived_quantities']==1
    assert len(attributes)==2 and attributes[0]['id']=='one'
    assert attributes[1]['origin']=='literal_table_quantity'


def test_ambiguous_owner_missing_parent_header_and_non_numeric_cells_are_not_projected():
    document,graph,_=food_table()
    graph['entities'].append({'id':'other','document_roles':['supply_target'],'evidence':[{'node_id':'item'}]})
    attributes=[]
    assert recover_table_attribute_context(document,graph,attributes)['derived_quantities']==0
    graph['entities'].pop()
    for n in document['nodes']:
        if n['node_id']=='count':n['text']='구분'
    assert recover_table_attribute_context(document,graph,attributes)['derived_quantities']==0
    for n in document['nodes']:
        if n['node_id']=='count':n['text']='예정수량'
        if n['node_id'] in ['one','eight']:n['text']='약 92000개'
    assert recover_table_attribute_context(document,graph,attributes)['derived_quantities']==0
