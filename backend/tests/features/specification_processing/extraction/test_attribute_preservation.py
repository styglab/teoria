"""Known source failures and counterexamples for unit/ownership preservation."""
from copy import deepcopy
import pytest
from teoria.features.specification_processing.extraction.attribute_extraction import decode_batch
from teoria.features.specification_processing.extraction.attribute_resolution import resolve_attribute_semantics


def decode(text, value, key='capacity', data_type='number', unit=None, property_raw=None):
    document={'nodes':[{'node_id':'n','text':text,'native_ref':'/blocks/18'}]}
    graph={'document_id':'doc','entities':[{'id':'cpu','name':'CPU'}]}
    chunk=[{'id':'f','node_id':'n','text':text,'start':0,'end':len(text),'suggested_subject_ids':['cpu']}]
    facts=[['f',['cpu'],key,property_raw,data_type,'eq',None,value,unit,[]]]
    accepted,quarantined,_=decode_batch({'facts':facts},chunk,graph,document,0)
    assert not quarantined
    return accepted[0]


@pytest.mark.parametrize('value,property_raw,expected',[('64','Core','Core'),('128','Thread','Thread')])
def test_count_units_in_the_original_cpu_clause_survive_missing_model_fields(value,property_raw,expected):
    text='64Core/128Thread processor'
    a=decode(text,value,property_raw.lower()+'_count',property_raw=property_raw)
    assert a['unit_raw']==expected
    assert a['normalized']['unit']==expected.lower()
    assert all(text[start:end]==expected for start,end in a['evidence']['field_spans']['unit_raw'])


def test_non_server_units_and_original_unicode_are_preserved():
    assert decode('압력 40MPa 이상','40')['unit_raw']=='MPa'
    a=decode('폭 800㎜ 이상','800')
    assert a['unit_raw']=='㎜' and a['normalized']['unit']=='mm'


@pytest.mark.parametrize('text,value,key,data_type',[
    ('CPU Core i7-128','128','model','identifier'),
    ('모델 X64GB','64','capacity','number'),
    ('주파수 3.264GHz','64','frequency','number'),
    ('유량 64GBps','64','capacity','number'),
    ('전송률 64GB/s','64','capacity','number'),
    ('면적 64mm²','64','area','number'),
    ('측정 64unknown','64','capacity','number'),
    ('64Core / 64GB','64','capacity','number'),
    ('16개, 별도 용량 64GB','16','model','identifier'),
    ('수치 64, 다음 행\nGB','64','capacity','number'),
    ('64Core, 다른 수치 64','64','capacity','number'),
])
def test_no_unit_is_invented_from_identifiers_other_values_or_ambiguous_context(text,value,key,data_type):
    assert decode(text,value,key,data_type)['unit_raw'] is None


def test_explicit_units_are_not_replaced():
    assert decode('64GB 및 64MB','64',unit='MB')['unit_raw']=='MB'


def duplicate_inputs():
    text='AI 개발환경 구축(PyTorch, TensorFlow 등) 활용 가능'
    document={'nodes':[{'node_id':'n','kind':'cell','text':text}]}
    graph={'entities':[{'id':'server','name':'Server','kind':'equipment'},
                       {'id':'torch','name':'PyTorch','kind':'equipment'},
                       {'id':'tf','name':'TensorFlow','kind':'equipment'}], 'relations':[]}
    base={'id':'a1','subject_ids':['torch'],'property_key':'availability','property_raw':None,
          'data_type':'text','operator':'raw','operator_raw':None,'value_raw':'활용 가능','unit_raw':None,
          'qualifiers_raw':['AI 개발환경 구축','PyTorch, TensorFlow 등'],
          'assertion_kind':'specification_requirement','modality':'unspecified','review_status':'needs_review',
          'evidence':{'node_id':'n','fragment_id':'f','char_start':0,'char_end':len(text)}}
    second=deepcopy(base);second.update(id='a2',subject_ids=['tf'])
    return document,graph,[base,second]


class SameOwner:
    async def generate(self,prompt,request,out):
        return {'resolutions':[{'attribute_id':a['id'],'subject_ids':['server'],
                'role':'supported_capability','scope':'support_limit','evidence_node_ids':['n']} for a in request['attributes']]}


async def test_identical_observations_collapsing_to_the_same_owner_are_merged(tmp_path):
    document,graph,attributes=duplicate_inputs()
    summary=await resolve_attribute_semantics(document,graph,attributes,SameOwner(),tmp_path)
    assert len(attributes)==1 and attributes[0]['subject_ids']==['server']
    assert summary['deduplicated']==1 and summary['resolved']==1
    origins=attributes[0]['merged_observations']
    assert {o['attribute_id'] for o in origins}=={'a1','a2'}
    assert {tuple(o['extraction_subject_ids']) for o in origins}=={('torch',),('tf',)}


@pytest.mark.parametrize('difference',['source','condition','value','property','operator','role','scope','owner','unknown'])
async def test_distinct_requirements_are_never_merged(tmp_path,difference):
    document,graph,attributes=duplicate_inputs()
    if difference=='source':attributes[1]['evidence']['char_start']=1
    if difference=='condition':attributes[1]['qualifiers_raw']=['AI 개발환경 구축']
    if difference=='value':attributes[1]['value_raw']='개발환경'
    if difference=='property':attributes[1]['property_key']='compatibility'
    if difference=='operator':attributes[1]['operator']='eq'
    class DifferentResolution(SameOwner):
        async def generate(self,prompt,request,out):
            result=await super().generate(prompt,request,out)
            if difference=='role':result['resolutions'][1]['role']='requirement_candidate'
            if difference=='scope':result['resolutions'][1]['scope']='system_total'
            if difference=='owner':result['resolutions'][1]['subject_ids']=['torch']
            if difference=='unknown':
                for r in result['resolutions']:r.update(subject_ids=[],role='unknown',scope='unknown')
            return result
    await resolve_attribute_semantics(document,graph,attributes,DifferentResolution(),tmp_path)
    assert len(attributes)==2


class ScriptedResolutions:
    def __init__(self, answers):
        self.answers=iter(answers)
        self.requests=[]

    async def generate(self,prompt,request,out):
        self.requests.append(deepcopy(request))
        answer=next(self.answers)
        if isinstance(answer,Exception):
            raise answer
        return answer


def resolution(attribute_id,subject):
    return {'attribute_id':attribute_id,'subject_ids':[subject],
            'role':'requirement_candidate','scope':'per_component','evidence_node_ids':['n']}


@pytest.mark.parametrize('failure',['missing','subject','evidence','schema','duplicate','malformed_duplicate'])
async def test_only_invalid_attribute_is_retried_without_losing_valid_result(tmp_path,failure):
    document,graph,attributes=duplicate_inputs()
    originals=deepcopy(attributes)
    first=resolution('a1','torch');second=resolution('a2','tf')
    rows=[first,second]
    if failure=='missing':rows.pop()
    if failure=='subject':second['subject_ids']=['nonexistent']
    if failure=='evidence':second['evidence_node_ids']=['nonexistent']
    if failure=='schema':second['scope']='invented_scope'
    if failure=='duplicate':rows.append(resolution('a2','server'))
    if failure=='malformed_duplicate':rows.append({'attribute_id':'a2'})
    runner=ScriptedResolutions([{'resolutions':rows},{'resolutions':[resolution('a2','tf')]}])

    summary=await resolve_attribute_semantics(document,graph,attributes,runner,tmp_path)

    assert [[a['id'] for a in r['attributes']] for r in runner.requests]==[['a1','a2'],['a2']]
    assert [a['subject_ids'] for a in attributes]==[['torch'],['tf']]
    assert summary['resolved']==2 and summary['unresolved']==0
    assert summary['retried_attributes']==1 and summary['recovered_attributes']==1
    for original,actual in zip(originals,attributes):
        for field in ('value_raw','unit_raw','operator_raw','qualifiers_raw','evidence','property_key'):
            assert actual[field]==original[field]


async def test_failed_retry_cannot_replace_an_already_valid_judgment(tmp_path):
    document,graph,attributes=duplicate_inputs()
    runner=ScriptedResolutions([
        {'resolutions':[resolution('a1','torch')]},
        {'resolutions':[resolution('a1','server'),resolution('a2','nonexistent')]},
    ])

    summary=await resolve_attribute_semantics(document,graph,attributes,runner,tmp_path)

    assert len(runner.requests)==2
    assert attributes[0]['subject_ids']==['torch']
    assert attributes[1]['subject_ids']==[] and attributes[1]['semantic_role']=='unknown'
    assert attributes[1]['extraction_subject_ids']==['tf']
    assert summary['resolved']==1 and summary['unresolved']==1
    assert summary['retried_attributes']==1 and summary['recovered_attributes']==0


async def test_valid_unknown_judgments_do_not_trigger_retry(tmp_path):
    document,graph,attributes=duplicate_inputs()
    unknown=resolution('a2','tf');unknown.update(subject_ids=[],role='unknown',scope='unknown')
    runner=ScriptedResolutions([{'resolutions':[resolution('a1','torch'),unknown]}])

    summary=await resolve_attribute_semantics(document,graph,attributes,runner,tmp_path)

    assert len(runner.requests)==1
    assert summary['retried_attributes']==0 and summary['unresolved']==1


@pytest.mark.parametrize('first_answer',[TimeoutError(),{'resolutions':'malformed'}])
async def test_unusable_batch_gets_one_bounded_retry(tmp_path,first_answer):
    document,graph,attributes=duplicate_inputs()
    runner=ScriptedResolutions([first_answer,{'resolutions':[resolution('a1','torch'),resolution('a2','tf')]}])

    summary=await resolve_attribute_semantics(document,graph,attributes,runner,tmp_path)

    assert len(runner.requests)==2
    assert summary['retried_attributes']==2 and summary['recovered_attributes']==2
    assert summary['resolved']==2


async def test_semantic_judgment_receives_source_property_type_and_operator(tmp_path):
    import json
    from pathlib import Path
    fixture=json.loads((Path(__file__).parent/'fixtures/vehicle_load_capacity_source.json').read_text())
    document={'nodes':[{**fixture['node'],'node_id':'load'}]}
    graph={'entities':[{'id':'table','name':'이동형 진료대','kind':'equipment','evidence':[{'node_id':'load'}]}],'relations':[]}
    attribute={'id':'load_1','subject_ids':['table'],'property_key':'load_capacity','property_raw':'허용하중',
        'data_type':'number','operator':'gte','operator_raw':'이상','value_raw':'200','unit_raw':'kg','qualifiers_raw':[],
        'evidence':{'node_id':'load'}}
    class Judge:
        async def generate(self,prompt,request,*args,**kwargs):
            actual=request['attributes'][0]
            assert actual['property_raw']=='허용하중'
            assert actual['data_type']=='number' and actual['operator']=='gte'
            assert actual['value_raw']=='200' and actual['operator_raw']=='이상'
            assert '이동형 진료대 설치·비치' in request['nodes'][0][6]
            return {'resolutions':[{'attribute_id':'load_1','subject_ids':['table'],'role':'requirement_candidate',
                'scope':'per_component','evidence_node_ids':['load']}]}
    await resolve_attribute_semantics(document,graph,[attribute],Judge(),tmp_path)
    assert attribute['semantic_role']=='requirement_candidate'
    assert attribute['value_raw']=='200' and attribute['unit_raw']=='kg' and attribute['operator']=='gte'


async def test_ambiguous_common_approval_clause_is_preserved_without_applying_to_all(tmp_path):
    text='기타의 것은 제조국가에서 검정을 필한 제품을 사용하여야 한다.'
    document={'nodes':[{'node_id':'n','kind':'paragraph','text':text,'native_ref':'/n'}]}
    graph={'entities':[{'id':'root','name':'차량','kind':'equipment'}],'relations':[],'requirements':[]}
    a=decode(text,'제조국가에서 검정을 필한 제품','product_certification','text')
    attributes=[a]
    class Judge:
        async def generate(self,prompt,request,out):
            return {'resolutions':[{'attribute_id':a['id'],'subject_ids':[],'role':'unknown','scope':'unknown',
                'evidence_node_ids':['n'],'other_requirement':True}]}
    summary=await resolve_attribute_semantics(document,graph,attributes,Judge(),tmp_path)
    assert attributes==[] and summary['unresolved']==0
    clause=graph['requirements'][0]
    assert clause['text']==text and clause['category']=='other'
    assert clause['subject_ids']==[] and clause['application_scope']=='unspecified'
    assert clause['evidence'][0]['node_id']=='n'


async def test_unknown_numeric_requirement_is_not_hidden_as_a_general_clause(tmp_path):
    text='허용하중 200kg 이상'
    document={'nodes':[{'node_id':'n','kind':'paragraph','text':text}]}
    graph={'entities':[{'id':'cpu','name':'진료대','kind':'equipment'}],'relations':[]}
    a=decode(text,'200','load_capacity','number');attributes=[a]
    class Judge:
        async def generate(self,prompt,request,out):
            return {'resolutions':[{'attribute_id':a['id'],'subject_ids':[],'role':'unknown','scope':'unknown',
                'evidence_node_ids':['n'],'other_requirement':True}]}
    summary=await resolve_attribute_semantics(document,graph,attributes,Judge(),tmp_path)
    assert len(attributes)==1 and attributes[0]['value_raw']=='200'
    assert summary['unresolved']==1 and not graph.get('requirements')


@pytest.mark.parametrize('text,value,key',[
    ('벽체와 바닥 등의 접합부는 라운드(곡면) 코너로 마감하여 오염물 및 세척수가 고이지 않고 청소·소독이 용이하도록 할 것',
     '라운드(곡면) 코너','joint_finish'),
    ('오염물의 흡수·잔류가 최소화되고 세척·소독이 용이한 구조로 제작할 것',
     '세척·소독이 용이한 구조','cleanability'),
])
async def test_product_itself_can_own_a_direct_condition_without_copying_it_to_all_parts(tmp_path,text,value,key):
    document={'nodes':[{'node_id':'n','kind':'cell','text':text,'native_ref':'/n'}]}
    graph={'entities':[{'id':'root','name':'차량','kind':'equipment'},
                       {'id':'floor','name':'바닥','kind':'equipment'},
                       {'id':'wall','name':'벽면','kind':'equipment'}],'relations':[]}
    attribute=decode(text,value,key,'text');attribute['subject_ids']=['root'];attributes=[attribute]
    class Judge:
        async def generate(self,prompt,request,out):
            return {'resolutions':[{'attribute_id':attribute['id'],'subject_ids':['root'],
                'role':'requirement_candidate','scope':'per_item','evidence_node_ids':['n']}]}
    await resolve_attribute_semantics(document,graph,attributes,Judge(),tmp_path)
    assert len(attributes)==1 and attributes[0]['subject_ids']==['root']
    assert attributes[0]['semantic_scope']=='per_item' and attributes[0]['value_raw']==value
    assert not graph.get('requirements')
