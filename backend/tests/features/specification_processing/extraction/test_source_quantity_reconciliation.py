"""Source-backed quantity replay and exact evidence counterexamples."""
from copy import deepcopy
from pathlib import Path
import pytest
from teoria.features.specification_processing.extraction.attribute_validation import deduplicate_inventory,fragment_coverage
from teoria.features.specification_processing.extraction.attribute_extraction import narrow_source_evidence
from teoria.features.specification_processing.extraction.attribute_chunking import make_chunks
from teoria.features.specification_processing.extraction.requirement_clauses import merge_description_clauses


def inventory_case():
    document={'nodes':[{'node_id':'name','text':'분석 장치'}, {'node_id':'unit','text':'System'}, {'node_id':'qty','text':'1'}, {'node_id':'other','text':'1'}]}
    q={'id':'q','origin':'validated_inventory_quantity','subject_ids':['root'],'value_raw':'1','unit_raw':'System','evidence':{'source_node_ids':['name','unit','qty']}}
    a={'id':'a','property_key':'quantity','subject_ids':['root'],'value_raw':'1','unit_raw':None,'operator':'eq','qualifiers_raw':[],'evidence':{'node_id':'qty','fragment_id':'qty_f00'}}
    return document,q,a


def test_missing_unit_and_separate_procurement_unit_collapse_only_into_the_verified_inventory():
    document,q,a=inventory_case()
    unit={**deepcopy(a),'id':'unit_obs','property_key':'procurement_unit','data_type':'text','value_raw':'System','evidence':{'node_id':'unit','fragment_id':'unit_f00'}}
    before=deepcopy(q)
    kept,duplicates=deduplicate_inventory([q],[a,unit],document=document)
    assert kept==[] and {row['attribute_id'] for row in duplicates}=={'a','unit_obs'}
    assert all(row['duplicate_of']=='q' for row in duplicates) and q==before


@pytest.mark.parametrize('difference',['owner','node','unit','value','condition','operator','wide_cell'])
def test_equal_looking_quantities_in_different_source_or_conditional_scopes_are_retained(difference):
    document,q,a=inventory_case()
    if difference=='owner':a['subject_ids']=['part']
    if difference=='node':a['evidence']['node_id']='other'
    if difference=='unit':a['unit_raw']='대'
    if difference=='value':a['value_raw']='2'
    if difference=='condition':a['qualifiers_raw']=['후면']
    if difference=='operator':a['operator']='gte'
    if difference=='wide_cell':document['nodes'][2]['text']='전면 포트 1개, 후면 포트 1개'
    assert deduplicate_inventory([q],[a],document=document)[0]==[a]


def test_known_inventory_cells_do_not_trigger_another_model_recovery():
    _,q,_=inventory_case()
    fragments=[{'id':node+'_f00','node_id':node,'text':text,'expected_role':'technical_requirement'} for node,text in [('qty','1'),('unit','System')]]
    result=fragment_coverage([fragments],[q])
    assert [row['coverage_status'] for row in result]==['inventory_quantity_preserved']*2


def test_long_multiline_cells_keep_offsets_but_do_not_share_a_large_evidence_fragment():
    text='CPU 3.50 GHz 2개\nGPU 141 GB 1개\n' * 50
    document={'nodes':[{'node_id':'cell','kind':'cell','text':text}]}
    fragments=[f for chunk in make_chunks({},document) for f in chunk]
    assert ''.join(f['text'] for f in fragments)==text
    assert all(f['text'].strip().count('\n')==0 for f in fragments)
    assert all(text[f['start']:f['end']]==f['text'] for f in fragments)


def test_source_quote_narrows_only_inside_the_original_attribute_scope():
    text='CPU 3.50 GHz 2개\nGPU 141 GB 1개'
    attribute={'property_raw':None,'value_raw':'141','unit_raw':'GB','operator_raw':None,'qualifiers_raw':[],
        'evidence':{'node_id':'n','char_start':16,'char_end':len(text),'native_ref':'/cell'}}
    evidence=narrow_source_evidence(attribute,{'n':{'text':text}},'GPU 141 GB 1개')
    assert text[evidence['char_start']:evidence['char_end']]=='GPU 141 GB 1개'
    assert evidence['field_spans']['value_raw']==[[text.index('141'),text.index('141')+3]]
    with pytest.raises(ValueError):narrow_source_evidence(attribute,{'n':{'text':text}},'CPU 3.50 GHz 2개')
    with pytest.raises(ValueError):narrow_source_evidence(attribute,{'n':{'text':text}},'GPU 141')  # unit must remain source-grounded


def test_repeated_literals_are_not_picked_arbitrarily():
    text='전면 1개, 후면 1개'
    attribute={'value_raw':'1','unit_raw':'개','qualifiers_raw':[], 'evidence':{'node_id':'n','char_start':0,'char_end':len(text)}}
    with pytest.raises(ValueError):narrow_source_evidence(attribute,{'n':{'text':text}},'1개')


def description_case():
    texts=['화합물을 신속하게','스크리닝하는 데 사용된다.']
    document={'nodes':[{'node_id':str(i),'kind':'paragraph','parent_id':None,'text':text} for i,text in enumerate(texts)],
        'document_assessment':{'clause_groups':[['0','1']]}}
    clauses=[{'id':'clause_'+str(i),'observation_type':'source_clause','category':'description','text':text,
              'subject_ids':['root'],'evidence':[{'node_id':str(i),'quote':text}]} for i,text in enumerate(texts)]
    return document,clauses


def test_split_descriptions_are_joined_with_both_original_references():
    document,clauses=description_case();merge_description_clauses(clauses,document)
    assert len(clauses)==1 and clauses[0]['text']=='화합물을 신속하게 스크리닝하는 데 사용된다.'
    assert [e['node_id'] for e in clauses[0]['evidence']]==['0','1']


def test_lcms_numbered_description_continues_in_an_unnumbered_pdf_paragraph():
    from teoria.features.specification_processing.extraction.requirement_clauses import validate_description_clause
    document,clauses=description_case()
    texts=['3. 화합물 및 분자량 확인, 복합 혼합물 내 정제 대상 화합물, 정량 대상 화합물 및 불순물 등을 신속하게',
           '스크리닝 하는데 사용된다.']
    for node,clause,text in zip(document['nodes'],clauses,texts):
        node['text']=clause['text']=text;clause['evidence'][0]['quote']=text
    document['nodes'][0]['kind']='list'
    merge_description_clauses(clauses,document)
    assert len(clauses)==1 and clauses[0]['text']==' '.join(texts)
    assert [e['node_id'] for e in clauses[0]['evidence']]==['0','1']
    validate_description_clause(clauses[0],{'root'},document)


@pytest.mark.parametrize('boundary',['unlinked','new_item','new_parent','another_list'])
def test_numbered_description_only_joins_its_verified_paragraph_continuation(boundary):
    document,clauses=description_case();document['nodes'][0]['kind']='list'
    if boundary=='unlinked':document['document_assessment']['clause_groups']=[]
    if boundary=='new_item':
        text='4. 별도 분석 목적 설명'
        document['nodes'][1]['text']=clauses[1]['text']=text;clauses[1]['evidence'][0]['quote']=text
    if boundary=='new_parent':document['nodes'][1]['parent_id']='other_section'
    if boundary=='another_list':document['nodes'][1]['kind']='list'
    merge_description_clauses(clauses,document)
    assert len(clauses)==2


@pytest.mark.parametrize('boundary',['owner','cell','intervening','technical'])
def test_description_grouping_does_not_cross_owners_cells_or_a_real_requirement(boundary):
    document,clauses=description_case()
    if boundary=='owner':clauses[1]['subject_ids']=['another']
    if boundary=='cell':
        for i,node in enumerate(document['nodes']):node.update(kind='cell',row=i,column=0,source_table_id='t')
    if boundary=='intervening':document['nodes'].insert(1,{'node_id':'middle','kind':'paragraph','text':'필수 요구조건'})
    if boundary=='technical':clauses[1]['category']='specification'
    merge_description_clauses(clauses,document)
    assert len(clauses)==2


def test_description_text_cannot_be_rewritten_as_a_generated_summary():
    from teoria.features.specification_processing.extraction.requirement_clauses import validate_description_clause
    document,clauses=description_case();merge_description_clauses(clauses,document)
    validate_description_clause(clauses[0],{'root'},document)
    clauses[0]['text']='분석 및 정량 기능을 제공해야 함'
    with pytest.raises(ValueError):validate_description_clause(clauses[0],{'root'},document)


@pytest.mark.parametrize('data_type,value,unit,operator',[
    ('number','141','GB','eq'),('text','2개 지원',None,'raw'),
    ('identifier','ISO9001',None,'eq'),('text','내수성',None,'gte'),
])
def test_description_flag_cannot_remove_numbers_identifiers_units_or_comparisons(data_type,value,unit,operator):
    from teoria.features.specification_processing.extraction.attribute_resolution import validated_resolutions
    attribute={'id':'a','data_type':data_type,'value_raw':value,'unit_raw':unit,'operator':operator,'evidence':{'node_id':'n'}}
    row={'attribute_id':'a','description':True,'subject_ids':['root'],'role':'unknown','scope':'unknown','evidence_node_ids':['n']}
    assert not validated_resolutions({'resolutions':[row]},{'a':attribute},{'root'},{'n'})


async def test_semantic_explanation_is_preserved_outside_properties(tmp_path):
    from teoria.features.specification_processing.extraction.attribute_resolution import resolve_attribute_semantics
    text='화합물을 스크리닝하는 데 사용된다.'
    document={'nodes':[{'node_id':'n','kind':'paragraph','text':text}]}
    graph={'entities':[{'id':'root','name':'분석 장치','kind':'equipment'}],'relations':[],'requirements':[]}
    attrs=[{'id':'a','subject_ids':['root'],'data_type':'text','operator':'raw','value_raw':text,
            'unit_raw':None,'qualifiers_raw':[],'evidence':{'node_id':'n','char_start':0,'char_end':len(text)}}]
    class Model:
        async def generate(self,*args):return {'resolutions':[{
            'attribute_id':'a','description':True,'subject_ids':['root'],'role':'unknown','scope':'unknown',
            'source_quote':text,'property_label':'분석 용도','evidence_node_ids':['n']}]}
    summary=await resolve_attribute_semantics(document,graph,attrs,Model(),tmp_path)
    assert attrs==[] and summary['descriptions_preserved']==1
    assert graph['requirements'][0]['text']==text and graph['requirements'][0]['category']=='description'


async def test_suggested_label_and_tight_source_do_not_replace_raw_values_or_food_constraints(tmp_path):
    from teoria.features.specification_processing.extraction.attribute_resolution import resolve_attribute_semantics
    text='보관 조건: 냉장 상태를 유지하여야 한다.'
    document={'nodes':[{'node_id':'n','kind':'paragraph','text':text}]}
    graph={'entities':[{'id':'milk','name':'우유','kind':'product'}],'relations':[]}
    attrs=[{'id':'a','subject_ids':['milk'],'data_type':'text','operator':'raw','property_raw':None,
            'value_raw':'냉장 상태를 유지하여야 한다.','unit_raw':None,'qualifiers_raw':[],
            'evidence':{'node_id':'n','char_start':0,'char_end':len(text)}}]
    class Model:
        async def generate(self,*args):return {'resolutions':[{
            'attribute_id':'a','description':False,'subject_ids':['milk'],'role':'requirement_candidate','scope':'per_item',
            'source_quote':text,'property_label':'보관 조건','evidence_node_ids':['n']}]}
    summary=await resolve_attribute_semantics(document,graph,attrs,Model(),tmp_path)
    assert len(attrs)==1 and attrs[0]['value_raw']=='냉장 상태를 유지하여야 한다.'
    assert attrs[0]['property_raw'] is None and attrs[0]['property_label']=='보관 조건'
    assert attrs[0]['property_label_origin']=='model_suggestion' and summary['unresolved']==0
