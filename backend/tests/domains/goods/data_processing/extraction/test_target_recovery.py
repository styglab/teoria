"""A missing source target may be recovered once without inventing its parent or quantities."""
from copy import deepcopy

from teoria.domains.goods.data_processing.extraction.target_recovery import recover_targets


def fixture():
    document={'nodes':[{'node_id':'cpu','kind':'cell','text':'CPU : Intel Core i5 or better',
                       'native_ref':'/blocks/1','parent_id':None}]}
    graph={'document_id':'doc','entities':[{'id':'pc','name':'PC SYSTEM','kind':'equipment',
            'evidence':[{'node_id':'title'}]}],'relations':[],
           'inventory_ids':['pc'],'composition_inventory':{'item_ids':['pc']},
           'requirements':[],'declared_quantities':[]}
    fragments=[{'id':'f','node_id':'cpu','text':document['nodes'][0]['text'],
                'start':0,'end':len(document['nodes'][0]['text'])}]
    return document,graph,fragments


async def test_recovers_only_a_source_grounded_target_without_inventing_composition(tmp_path):
    document,graph,fragments=fixture();before=deepcopy(graph)
    class Model:
        async def generate(self,prompt,request,path):
            return {'targets':[{'fragment_id':'f','node_id':'cpu','name':'CPU','kind':'equipment'}]}
    result=await recover_targets(document,graph,fragments,Model(),tmp_path)
    assert result['added']==1
    assert graph['entities'][-1]['name']=='CPU'
    assert graph['entities'][-1]['delivery_status']=='not_established'
    for key in ['relations','inventory_ids','composition_inventory','declared_quantities']:
        assert graph[key]==before[key]


async def test_ungrounded_recovery_is_rejected_and_failure_does_not_break_extraction(tmp_path):
    document,graph,fragments=fixture();before=deepcopy(graph)
    class Model:
        async def generate(self,prompt,request,path):
            return {'targets':[{'fragment_id':'f','node_id':'cpu','name':'GPU','kind':'equipment'}]}
    result=await recover_targets(document,graph,fragments,Model(),tmp_path)
    assert result['added']==0 and result['rejected']==1 and graph==before


async def test_no_target_gap_does_not_call_model(tmp_path):
    document,graph,_=fixture()
    class Model:
        async def generate(self,*args):raise AssertionError('unnecessary model call')
    assert (await recover_targets(document,graph,[],Model(),tmp_path))['model_calls']==0


async def test_recovery_does_not_duplicate_a_target_at_the_same_source(tmp_path):
    document,graph,fragments=fixture()
    graph['entities'].append({'id':'old_cpu','name':'CPU','kind':'equipment','evidence':[{'node_id':'cpu'}]})
    class Model:
        async def generate(self,prompt,request,path):
            return {'targets':[{'fragment_id':'f','node_id':'cpu','name':'CPU','kind':'equipment'}]}
    result=await recover_targets(document,graph,fragments,Model(),tmp_path)
    assert result['added']==0 and len(graph['entities'])==2


def test_named_detector_is_reviewed_even_when_its_type_was_attached_to_the_parent():
    from teoria.domains.goods.data_processing.extraction.target_recovery import component_candidate_fragments
    text='- 검출기 : 변환 다이노드를 갖는 전자 증배관'
    fragment={'id':'detector_f','node_id':'detector','text':text,'suggested_subject_ids':['mass']}
    graph={'entities':[{'id':'mass','name':'질량분석기','kind':'equipment','evidence':[{'node_id':'title'}]}]}
    attrs=[{'id':'a','subject_ids':['mass'],'data_type':'text','property_raw':'검출기',
            'value_raw':'변환 다이노드를 갖는 전자 증배관','evidence':{'fragment_id':'detector_f'}}]
    before=deepcopy(graph)
    candidates=component_candidate_fragments([[fragment]],graph,attrs)
    assert len(candidates)==1 and candidates[0]['component_candidate_label']=='검출기'
    assert graph==before  # A candidate label is not proof of a supplied component.


def test_numbers_existing_targets_and_unlabelled_prose_do_not_trigger_component_recovery():
    from teoria.domains.goods.data_processing.extraction.target_recovery import component_candidate_fragments
    rows=[('mass','질량 범위 : 2 to 2000 m/z','range','2 to 2000'),
          ('cpu','CPU : Intel Core i5 or better','identifier','Intel Core i5'),
          ('use','화합물을 스크리닝하는 데 사용된다.','text','화합물')]
    fragments=[{'id':id,'node_id':id,'text':text,'suggested_subject_ids':['pc']} for id,text,*_ in rows]
    graph={'entities':[{'id':'pc','name':'PC SYSTEM','evidence':[]},
                       {'id':'cpu','name':'CPU','evidence':[{'node_id':'cpu'}]}]}
    attrs=[{'data_type':kind,'value_raw':value,'evidence':{'fragment_id':id}} for id,_,kind,value in rows]
    assert component_candidate_fragments([fragments],graph,attrs)==[]


async def test_component_review_cannot_replace_the_label_with_an_arbitrary_model_name(tmp_path):
    document,graph,fragments=fixture();fragments[0]['component_candidate_label']='CPU'
    before=deepcopy(graph)
    class Model:
        async def generate(self,*args):
            return {'targets':[{'fragment_id':'f','node_id':'cpu','name':'Intel Core i5','kind':'equipment'}]}
    result=await recover_targets(document,graph,fragments,Model(),tmp_path)
    assert result['rejected']==1 and result['added']==0 and graph==before


def test_existing_component_under_the_same_parent_is_not_recreated_at_another_mention():
    from teoria.domains.goods.data_processing.extraction.target_recovery import component_candidate_fragments
    fragment={'id':'f','node_id':'detail','text':'CPU : Intel Core i5 or better','suggested_subject_ids':['pc']}
    graph={'entities':[{'id':'pc','name':'PC SYSTEM','kind':'equipment','evidence':[]},
                       {'id':'cpu','name':'CPU','kind':'equipment','evidence':[{'node_id':'inventory'}]}],
           'relations':[{'source_id':'cpu','target_id':'pc','kind':'component_of','basis':'explicit'}]}
    attrs=[{'data_type':'identifier','value_raw':'Intel Core i5','subject_ids':['pc'],'evidence':{'fragment_id':'f'}}]
    assert component_candidate_fragments([[fragment]],graph,attrs)==[]
