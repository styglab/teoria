"""Structure selects evidence without changing values or manufacturing ownership."""
from copy import deepcopy

from teoria.features.specification_processing.extraction.attribute_chunking import make_chunks
from teoria.features.specification_processing.extraction.attribute_resolution import resolve_attribute_semantics
from teoria.features.specification_processing.extraction.document_context import DocumentContext,pack_fragments
from teoria.features.specification_processing.extraction.attribute_validation import fragment_context


def node(key,text,kind='paragraph',**fields):
    return {'node_id':key,'kind':kind,'text':text,**fields}


def server_sections():
    # First six texts come from R26BK01785091/original.hwpx; trailing nodes are counterexamples.
    return {'nodes':[
        node('title','물품 내역 및 세부 규격서'),
        node('section','Ⅲ. 성능 및 규격(Performance and Specification)'),
        node('body','가. GPU 서버 본체 : 1개'),
        node('body_spec','3) 최대 400W TDP CPU 지원'),
        node('cpu','나. 서버 전용 고성능 CPU : 1개'),
        node('cpu_spec','1) 96 Core, 192 Threads'),
        node('cpu_continuation','추가 조건 원문'),
        node('other','다. 다른 품목'),
        node('other_spec','별도 품목의 규격'),
    ]}


def graph():
    return {'entities':[
        {'id':'root','name':'서버','kind':'equipment','evidence':[{'node_id':'title'}]},
        {'id':'body','name':'본체','kind':'equipment','evidence':[{'node_id':'body'}]},
        {'id':'cpu','name':'CPU','kind':'equipment','evidence':[{'node_id':'cpu'}]},
    ],'relations':[
        {'source_id':'cpu','target_id':'body','kind':'component_of','basis':'explicit'},
        {'source_id':'body','target_id':'root','kind':'in_procurement_scope','basis':'explicit'},
    ]}


def attribute(key,owner,source):
    return {'id':key,'subject_ids':[owner],'property_key':'core_count','value_raw':'96',
            'unit_raw':'Core','operator_raw':None,'qualifiers_raw':[],
            'evidence':{'node_id':source}}


def test_numbered_sections_keep_logical_groups_without_losing_text_or_multiplying_calls():
    document=server_sections()
    chunks=make_chunks({},document,target_chars=10000)
    groups={f['node_id']:f['context_group'] for c in chunks for f in c}
    assert len(chunks)==1
    assert groups['body']==groups['body_spec']
    assert groups['cpu']==groups['cpu_spec']
    assert groups['body']!=groups['cpu']!=groups['other']
    assert [(f['node_id'],f['text']) for c in chunks for f in c]==[(n['node_id'],n['text']) for n in document['nodes']]
    recovery=pack_fragments([f for c in chunks for f in c if f['node_id'] in {'body_spec','cpu_spec'}],DocumentContext(document))
    assert len(recovery)==1
    assert len({f['context_group'] for f in recovery[0]})==2


def test_dotted_subsections_keep_their_heading_chain_without_treating_values_as_headings():
    document={'nodes':[node('top','1. 장치'),node('sub','1.1 구성'),
                       node('detail','1.1.1 부속품'),node('value','96 Core'),
                       node('next','1.2 다른 구성'),node('other','64 GB')]}
    context=DocumentContext(document)
    assert context.paths['value']==('top','sub','detail')
    assert context.paths['other']==('top','next')
    assert 'other' not in context.related_ids('value')


def test_cpu_context_keeps_section_and_ancestor_labels_without_sibling_specs():
    document=server_sections();original=deepcopy(document)
    nodes=DocumentContext(document).select([attribute('a','cpu','cpu_spec')],graph())
    keys={n['node_id'] for n in nodes}
    assert {'title','section','body','cpu','cpu_spec','cpu_continuation'}<=keys
    assert not {'body_spec','other','other_spec'}&keys
    assert document==original


def test_flat_evidence_keeps_full_context_instead_of_guessing_a_boundary():
    document={'nodes':[node('first','첫 대상'),node('distant','공통 조건'),node('last','96 Core')]}
    selected=DocumentContext(document).select([attribute('a','cpu','last')],{'entities':[],'relations':[]})
    assert selected==document['nodes']


def test_common_section_and_explicit_ancestor_scope_conditions_survive_selection():
    document=server_sections()
    document['nodes'].insert(2,node('common','공통 적용 조건'))
    document['nodes']+=[node('terms','Ⅳ. 납품 조건'),node('remote','상위 장비의 공통 납품 조건')]
    g=graph()
    g['requirements']=[{'observation_type':'source_clause','subject_ids':['root'],
                        'evidence':[{'node_id':'remote'}]}]
    keys={n['node_id'] for n in DocumentContext(document).select([attribute('a','cpu','cpu_spec')],g)}
    assert {'common','remote','terms'}<=keys
    assert 'other_spec' not in keys


def table_document():
    return {'nodes':[
        node('t1','','table'),
        node('header','','cell',parent_id='t1',row=0,column=0,column_span=2),
        node('header_text','항목 및 요구 규격',parent_id='header'),
        node('merged','본체','cell',parent_id='t1',row=1,column=0,row_span=2),
        node('value1','최대 400W TDP CPU 지원','cell',parent_id='t1',row=1,column=1),
        node('value2','','cell',parent_id='t1',row=2,column=1),
        node('nested','96 Core',parent_id='value2'),
        node('other_row','별도 장비','cell',parent_id='t1',row=3,column=1),
        node('t2','','table'),
        node('foreign','다른 표의 96 Core','cell',parent_id='t2',row=2,column=1),
    ]}


def test_nested_cells_with_missing_table_source_id_keep_merged_labels_and_headers():
    context=DocumentContext(table_document())
    keys=context.related_ids('nested')
    assert {'t1','header','header_text','merged','value2','nested'}<=keys
    assert not {'other_row','foreign','t2','value1'}&keys


def test_different_table_parents_override_repeated_provider_source_ids():
    document=table_document()
    for n in document['nodes']:
        if n['kind']=='cell':n['source_table_id']='repeated'
    context=DocumentContext(document)
    assert 'foreign' not in context.related_ids('nested')
    chunks=make_chunks({},document,target_chars=10000)
    groups={f['node_id']:f['context_group'] for c in chunks for f in c}
    assert groups['foreign']!=groups['nested']


async def test_semantic_request_batches_small_sections_and_keeps_their_identity(tmp_path):
    document=server_sections();attributes=[attribute('a','cpu','cpu_spec'),attribute('b','body','body_spec')]
    class Model:
        def __init__(self):self.requests=[]
        async def generate(self,prompt,request,out):
            self.requests.append(request)
            assert {e[0] for e in request['entities']}=={'root','body','cpu'}
            return {'resolutions':[{'attribute_id':a['id'],'subject_ids':a['subject_ids'],
                    'role':'requirement_candidate','scope':'per_component',
                    'evidence_node_ids':[a['evidence']['node_id']]} for a in request['attributes']]}
    model=Model()
    summary=await resolve_attribute_semantics(document,graph(),attributes,model,tmp_path)
    assert len(model.requests)==1
    request=model.requests[0]
    groups={a['id']:a['context_group'] for a in request['attributes']}
    assert groups['a']!=groups['b']
    assert {'body_spec','cpu_spec'}<={n[0] for n in request['nodes']}
    assert 'other_spec' not in {n[0] for n in request['nodes']}
    assert summary['resolved']==2 and summary['retried_attributes']==0
    assert summary['input_characters']<sum(len(n['text']) for n in document['nodes'])


async def test_model_cannot_cite_an_omitted_sibling_specification(tmp_path):
    document=server_sections();attributes=[attribute('a','cpu','cpu_spec')]
    class Model:
        async def generate(self,prompt,request,out):
            return {'resolutions':[{'attribute_id':'a','subject_ids':['body'],
                    'role':'supported_capability','scope':'support_limit','evidence_node_ids':['body_spec']}]}
    summary=await resolve_attribute_semantics(document,graph(),attributes,Model(),tmp_path)
    assert summary['retried_attributes']==1 and summary['unresolved']==1
    assert attributes[0]['subject_ids']==[]


async def test_table_rows_share_a_call_while_retaining_each_rows_coordinates(tmp_path):
    document=table_document()
    attributes=[attribute('a','body','value1'),attribute('b','cpu','nested')]
    class Model:
        def __init__(self):self.calls=0
        async def generate(self,prompt,request,out):
            self.calls+=1
            nodes={n[0]:n for n in request['nodes']}
            assert nodes['value1'][4]==1 and nodes['value2'][4]==2
            assert nodes['merged'][7]==2
            assert nodes['nested'][2]=='value2'
            assert 'foreign' not in nodes
            return {'resolutions':[{'attribute_id':a['id'],'subject_ids':a['subject_ids'],
                    'role':'requirement_candidate','scope':'per_component',
                    'evidence_node_ids':[a['evidence']['node_id']]} for a in request['attributes']]}
    model=Model()
    summary=await resolve_attribute_semantics(document,graph(),attributes,model,tmp_path)
    assert model.calls==1 and summary['batches']==1 and summary['resolved']==2


async def test_many_small_sections_do_not_each_start_a_semantic_call(tmp_path):
    document={'nodes':[]};attributes=[]
    for i in range(50):
        document['nodes']+=[node(f'h{i}',f'{i+1}. 장비 조건'),node(f'v{i}',f'수치 {i}')]
        attributes.append(attribute(f'a{i}','cpu',f'v{i}'))
    class Model:
        def __init__(self):self.sizes=[]
        async def generate(self,prompt,request,out):
            self.sizes.append(len(request['attributes']))
            return {'resolutions':[{'attribute_id':a['id'],'subject_ids':['cpu'],
                    'role':'requirement_candidate','scope':'per_component',
                    'evidence_node_ids':[a['evidence']['node_id']]} for a in request['attributes']]}
    model=Model()
    summary=await resolve_attribute_semantics(document,graph(),attributes,model,tmp_path)
    assert sorted(model.sizes)==[5,45] and summary['resolved']==50


def test_initial_extraction_context_is_local_and_bounded_while_primary_text_stays_complete():
    document={'nodes':[node('heading','1. 요구 규격')] +
              [node(f'n{i}',f'조건 {i} '+('원문'*1500)) for i in range(15)]}
    context=DocumentContext(document)
    rows=fragment_context(document,{'node_id':'n8'},context=context)
    assert {r[0] for r in rows}=={'heading','n7','n9'}
    assert len(rows)<=8 and all(len(row[3])<=1000 for row in rows)
    fragments=[f for c in make_chunks({},document) for f in c]
    assert ''.join(f['text'] for f in fragments if f['node_id']=='n8')==document['nodes'][9]['text']
