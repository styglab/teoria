"""Known source failures and counterexamples for unit/ownership preservation."""
from copy import deepcopy
import pytest
from teoria_pipelines.domains.public_procurement.specification_processing.extraction.attribute_extraction import decode_batch
from teoria_pipelines.domains.public_procurement.specification_processing.extraction.attribute_resolution import resolve_attribute_semantics


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
