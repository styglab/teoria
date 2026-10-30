"""Source-backed regression controls for scope, composition, and work direction."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from teoria.features.specification_processing.extraction.entity_relation_extraction import (
    Details, Inventory, extract_entity_relations, materialize, validate_details,
)


def source_case():
    # Source phrases: LC-MS /blocks/8, /blocks/13; monitoring /blocks/29 and /blocks/92.
    texts={
        'root_node':'액체크로마토그래프 질량분석기 (Liquid Chromatograph Mass Spectrometer)',
        'list':'나. 장비의 구성(Configurations of Goods)',
        'pump_node':'용매 운반용 펌프',
        'work_node':'환경감시 센서 교체 및 설치공사',
        'sensor_node':'환경감시 센서',
        'configuration':'- 환경감시 센서의 구성은 누출가스검출기, 혼합가스검출기, 온습도센서, 데이터 전송장치로 구성',
    }
    document={'document_id':'regression','nodes':[{
        'node_id':id,'text':text,'native_ref':'/'+id,'kind':'paragraph','parent_id':None,
        'row':None,'column':None,'row_span':None,'column_span':None,
    } for id,text in texts.items()]}
    inventory=Inventory(root=('root_node',texts['root_node'],None,None,['root_node']),
        basis='configuration_list',basis_node_ids=['list'],integrated_scope=True,
        scope_evidence_node_ids=['root_node','list'],
        items=[('pump','pump_node',texts['pump_node'],None,None,['pump_node']),
               ('work','work_node',texts['work_node'],None,None,['work_node'])],issues=[])
    details=Details(additional=[('sensor','sensor_node',texts['sensor_node'])],
        types=[('root','equipment','required'),('pump','equipment','required'),
               ('work','activity','required'),('sensor','group','required')],
        relations=[('pump','root','component_of','explicit',['list','pump_node']),
                   ('work','sensor','service_for','explicit',['work_node','configuration'])],
        scopes=[],issues=[])
    return document,inventory,details


def test_explicit_composition_keeps_purchase_scope_and_original_quantities():
    doc,inventory,details=source_case()
    assert validate_details(details,inventory,doc)==[]
    graph=materialize(inventory,details,doc)
    kinds={r['kind'] for r in graph['relations'] if r['source_id']=='pump' and r['target_id']=='root'}
    assert kinds=={'in_procurement_scope','component_of'}
    assert not any(r['kind']=='component_of' and r['source_id']=='work' for r in graph['relations'])
    assert graph['declared_quantities']==[]


def test_scope_list_does_not_create_composition_without_an_assertion():
    doc,inventory,details=source_case();details.relations=[]
    graph=materialize(inventory,details,doc)
    assert {r['kind'] for r in graph['relations']}=={'in_procurement_scope'}


@pytest.mark.parametrize('source_kind',['activity','document'])
def test_work_cannot_become_a_component_of_equipment(source_kind):
    doc,inventory,details=source_case()
    details.types=[(id,source_kind if id=='work' else kind,state) for id,kind,state in details.types]
    details.relations.append(('work','root','component_of','explicit',['work_node']))
    assert any('composition' in reason for reason in validate_details(details,inventory,doc))


def test_service_relation_must_start_at_a_work_entity():
    doc,inventory,details=source_case()
    details.relations=[('sensor','work','service_for','explicit',['work_node','configuration'])]
    assert any('activity' in reason for reason in validate_details(details,inventory,doc))


class Predictions:
    def __init__(self,inventory,*details):
        self.inventory=inventory;self.details=list(details);self.detail_requests=[]

    async def generate(self,prompt,request,out):
        if 'inventory' not in request:return self.inventory.model_dump(mode='json')
        self.detail_requests.append(deepcopy(request))
        return self.details[min(len(self.detail_requests)-1,len(self.details)-1)].model_dump(mode='json')


async def test_invalid_work_direction_is_rejudged_with_errors_not_silently_reversed(tmp_path):
    doc,inventory,good=source_case();bad=good.model_copy(deep=True)
    bad.relations=[('sensor','work','service_for','explicit',['work_node','configuration'])]
    runner=Predictions(inventory,bad,good)
    await extract_entity_relations(doc,tmp_path,runner)
    graph=json.loads((tmp_path/'graph.json').read_text())
    assert len(runner.detail_requests)==2
    assert any('activity' in e for e in runner.detail_requests[1]['validation_errors'])
    assert any(r['source_id']=='work' and r['target_id']=='sensor' and r['kind']=='service_for' for r in graph['relations'])
    assert not graph['held_relations']


async def test_persistently_invalid_direction_is_held_without_losing_the_document(tmp_path):
    doc,inventory,details=source_case()
    details.relations=[('sensor','work','service_for','explicit',['work_node','configuration'])]
    runner=Predictions(inventory,details)
    summary=await extract_entity_relations(doc,tmp_path,runner)
    graph=json.loads((tmp_path/'graph.json').read_text())
    assert len(runner.detail_requests)==2
    assert not any(r['kind']=='service_for' for r in graph['relations'])
    held=graph['held_relations'][0]
    assert held['source_id']=='sensor' and held['target_id']=='work'
    assert held['review_status']=='held' and held['evidence']
    assert summary['held_relations']==1 and summary['status']=='partial'
    assert {e['id'] for e in graph['entities']}=={'root','pump','work','sensor'}


@pytest.mark.parametrize('kind,basis',[('component_of','ambiguous'),('unknown','interpreted')])
async def test_uncertain_relationships_remain_held_proposals(tmp_path,kind,basis):
    doc,inventory,details=source_case()
    details.relations=[('pump','root',kind,basis,['list','pump_node'])]
    runner=Predictions(inventory,details)
    summary=await extract_entity_relations(doc,tmp_path,runner)
    graph=json.loads((tmp_path/'graph.json').read_text())
    assert len(runner.detail_requests)==1  # Abstention is not an instruction to invent certainty.
    assert all(r['kind']=='in_procurement_scope' for r in graph['relations'])
    assert len(graph['held_relations'])==1 and summary['status']=='partial'


async def test_cycle_holds_all_involved_edges_instead_of_choosing_an_arbitrary_direction(tmp_path):
    doc,inventory,details=source_case()
    details.relations=[('pump','sensor','component_of','explicit',['configuration']),
                       ('sensor','pump','component_of','explicit',['configuration'])]
    summary=await extract_entity_relations(doc,tmp_path,Predictions(inventory,details))
    graph=json.loads((tmp_path/'graph.json').read_text())
    assert len(graph['held_relations'])==2 and summary['status']=='partial'
    assert {r['kind'] for r in graph['relations']}=={'in_procurement_scope'}


async def test_structurally_invalid_entity_labels_still_fail_after_rejudgment(tmp_path):
    doc,inventory,details=source_case();details.additional=[('sensor','sensor_node','원문에 없는 명칭')]
    with pytest.raises(ValueError,match='additional label not in source'):
        await extract_entity_relations(doc,tmp_path,Predictions(inventory,details))


async def test_held_relations_survive_extraction_storage_and_mark_partial(tmp_path):
    from teoria.features.specification_processing.models import SpecificationRun
    from teoria.features.specification_processing.tasks import persist_extraction
    workspace=tmp_path/'work';folder=workspace/'processing'/'regression';out=folder/'attributes'
    out.mkdir(parents=True)
    doc,inventory,details=source_case();doc['parser_version']='fixture'
    graph=materialize(inventory,details,doc);graph['attributes']=[]
    graph['held_relations']=[{'source_id':'sensor','target_id':'work','kind':'service_for',
        'review_status':'held','reasons':['service_for source must be an activity'],
        'evidence':[{'node_id':'work_node'}]}]
    summary={'status':'needs_review','input_coverage':{'missing_node_ids':[]},'failed_chunks':0,
        'uncovered_spec_fragments':0,'semantic_resolution':{'unresolved':0},'recovery_passes':0}
    original=tmp_path/'original.hwp';original.write_bytes(b'controlled source input')
    request=SpecificationRun(run_id='held_relation_test',mode='standard_management',
        artifact_root=(tmp_path/'artifacts').as_uri(),documents=[{'document_id':'regression',
        'source_uri':original.as_uri(),'filename':original.name}])
    entry={'document_id':'regression','notice_number':None,'source':{'sha256':'a'*64,'path':'sources/regression.hwp'}}
    (workspace/'work.json').write_text(json.dumps([entry]))
    (folder/'document.json').write_text(json.dumps(doc))
    (out/'attribute_graph.json').write_text(json.dumps(graph))
    (out/'summary.json').write_text(json.dumps(summary))
    ref=await persist_extraction.fn(request,str(workspace),False)
    result=json.loads((workspace/'extracted.json').read_text())['documents'][0]
    assert result['held_relations']==graph['held_relations']
    assert result['requirements']==graph['requirements']
    assert result['extraction_status']=='partial'
    assert result['unresolved_extraction']['held_relations']==1
    stored=json.loads(Path(ref['uri'].removeprefix('file://')).read_text())
    assert stored['documents'][0]['held_relations']==graph['held_relations']
    assert stored['documents'][0]['requirements']==graph['requirements']


def test_report_combines_scope_and_composition_without_duplicating_the_item():
    from teoria.features.specification_processing.reporting import render_report
    doc,inventory,details=source_case();graph=materialize(inventory,details,doc)
    document={**graph,'source':{'path':'source.hwp'},'attributes':[],
              'held_relations':[{'source_id':'sensor','target_id':'work','kind':'service_for',
                  'reasons':['service_for source must be an activity'],'review_status':'held'}]}
    report=render_report({'documents':[document],'unavailable_documents':[]},{'summary':{}},'fixture')
    assert report.count('용매 운반용 펌프')==1
    assert '범위·구성' in report
    assert '| pump | in_procurement_scope | root |' in report
    assert '| pump | component_of | root |' in report
    assert '보류한 관계' in report and 'service_for source must be an activity' in report


def test_an_old_checkpoint_cannot_bypass_work_direction_checks():
    from types import SimpleNamespace
    from teoria.features.specification_processing.tasks import validate_checkpoint
    doc,inventory,details=source_case();graph=materialize(inventory,details,doc)
    graph['relations']=[{'id':'wrong','source_id':'sensor','target_id':'work','kind':'service_for'}]
    document={**graph,'document_id':'regression','source':{'sha256':'a'*64},'parsed_document':doc,'attributes':[]}
    with pytest.raises(ValueError,match='relation type'):
        validate_checkpoint({'classification_code':None,'documents':[document],'unavailable_documents':[]},
            SimpleNamespace(classification_code=None),[{'document_id':'regression','source':{'sha256':'a'*64}}])


def workstation_deliverables():
    # Frozen source excerpts from the existing workstation original, SHA256
    # 1ac38ddda29a1fc7806ac93fa04baa93d6beff66621896f3b434a6c9840d01c5.
    texts = {
        'root_node': '지식관리시스템 AI 서비스 검증용 워크스테이션',
        'software': 'Windows 11 , Ubuntu 26.04 LTS(WSL2), NVIDIA Driver, CUDA Toolkit, cuDNN, Docker, Python, PyTorch, Ollama, Open WebUI,\njupyterLab,GPU Matatrix Test등 SW 설치 및  환경 구축',
        'submission': '설치 작업의 종료와 함께 다음의 문서를 제출하여야 한다.',
        'manual': '- HW/SW 설치 및 사용 매뉴얼',
        'support': '- 제조사 정품공급 및 기술지원 확약서',
    }
    doc = {'document_id': 'workstation', 'nodes': [
        {'node_id': key, 'text': text, 'native_ref': '/' + key, 'kind': 'paragraph',
         'parent_id': None, 'row': None, 'column': None, 'row_span': None, 'column_span': None}
        for key, text in texts.items()]}
    inventory = Inventory(root=('root_node', texts['root_node'], None, None, ['root_node']),
        basis='technical_sections', basis_node_ids=['root_node'], items=[],
        integrated_scope=False, scope_evidence_node_ids=[], issues=[])
    details = Details(additional=[('sw', 'software', 'Docker'),
        ('manual', 'manual', 'HW/SW 설치 및 사용 매뉴얼'),
        ('pledge', 'support', '제조사 정품공급 및 기술지원 확약서')],
        types=[('root', 'equipment', 'required'), ('sw', 'software', 'required'),
               ('manual', 'document', 'required'), ('pledge', 'document', 'required')],
        relations=[('sw', 'root', 'software_for', 'explicit', ['software']),
                   ('manual', 'root', 'document_for', 'interpreted', ['submission', 'manual']),
                   ('pledge', 'root', 'document_for', 'interpreted', ['submission', 'support'])],
        scopes=[('manual', ['submission', 'manual']), ('pledge', ['submission', 'support'])], issues=[])
    return doc, inventory, details


async def test_workstation_documents_and_software_keep_typed_targets_and_submission_clause(tmp_path):
    doc, inventory, details = workstation_deliverables()
    await extract_entity_relations(doc, tmp_path, Predictions(inventory, details))
    graph = json.loads((tmp_path / 'graph.json').read_text())
    assert {r['kind'] for r in graph['relations']} == {'document_for', 'software_for'}
    assert graph['held_relations'] == []
    clause = next(r for r in graph['requirements'] if r['id'] == 'clause_submission')
    assert set(clause['subject_ids']) == {'manual', 'pledge'}
    assert clause['text'] == '설치 작업의 종료와 함께 다음의 문서를 제출하여야 한다.'
    assert all(e['delivery_status'] == 'not_established' for e in graph['entities'])


@pytest.mark.parametrize('source,kind', [('sw', 'document_for'), ('manual', 'software_for'),
                                       ('sw', 'component_of'), ('manual', 'physical_part_of')])
def test_typed_deliverables_reject_incorrect_roles_without_relabeling(source, kind):
    from teoria.features.specification_processing.extraction.entity_relation_extraction import review_relations
    doc, inventory, details = workstation_deliverables()
    details.relations = [(source, 'root', kind, 'explicit', ['software', 'manual'])]
    reviewed, held = review_relations(details, inventory, doc)
    assert not reviewed.relations and len(held) == 1
    assert held[0]['relation'][0:3] == (source, 'root', kind)


def test_workstation_report_lists_typed_targets_and_relations_without_a_forced_tree():
    from teoria.features.specification_processing.reporting import render_report
    doc, inventory, details = workstation_deliverables()
    graph = materialize(inventory, details, doc)
    report = render_report({'documents': [{**graph, 'source': {'path': 'source.hwp'}, 'attributes': []}],
        'unavailable_documents': []}, {'summary': {}}, 'fixture')
    assert '```text' not in report
    assert '| sw | Docker | software |' in report
    assert '| manual | HW/SW 설치 및 사용 매뉴얼 | document |' in report
    assert '### 분석 대상' in report and '### 대상 간 관계' in report
    assert '| manual | document_for | root |' in report
    assert '설치 작업의 종료와 함께 다음의 문서를 제출하여야 한다.' in report
