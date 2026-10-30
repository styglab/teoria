"""Corpus reconciliation reuses extraction, freezes validation, and applies guarded Admin changes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import concept_id_for_key
from teoria.features.semantic_modeling.goods_dictionary.meaning_service import GoodsMeaningService
from teoria.features.specification_processing.normalization.dictionary_maintenance import maintain_dictionary
from backend.tests.features.semantic_modeling.goods_dictionary.test_dictionary_changes import ChangeRepository
from .test_dictionary_candidates import corpus


class API:
    def __init__(self):
        self.repo=ChangeRepository();self.service=GoodsMeaningService(repository=self.repo)
        self.repo.document_refs=[]
        self.operations={}
    async def dictionary(self,operation_id,payload):
        keys={};decisions=[]
        for c in payload['candidates']:
            owner=keys.get(c.get('owner_candidate_key'))
            id=str(uuid5(NAMESPACE_URL,c['kind']+':'+c['preferred_name']+':'+str(owner)))
            status='reused' if id in self.repo.sources else 'approved'
            self.repo.sources[id]={'entry_id':id,'kind':c['kind'],'owner_entry_id':owner,
                                   'status':'approved','preferred_name':c['preferred_name']}
            keys[c['candidate_key']]=id
            decisions.append({'candidate_key':c['candidate_key'],'entry_id':id,'status':status})
            self.repo.document_refs.extend({'entry_id':id,'operation_id':operation_id,
                'document_id':e['document_id'],'source_sha256':e['source_sha256']} for e in c['evidence'])
        self.operations[operation_id]=decisions
        return {'decisions':decisions}
    async def dictionary_meaning(self,method,path,payload=None):
        if path=='/snapshot':return await self.service.snapshot()
        if path=='/maintenance-preview':return await self.service.preview_changes(payload)
        if path.startswith('/maintenance/'):
            return await self.service.apply_changes(path.rsplit('/',1)[1],payload,actor='policy:test')
        raise AssertionError(path)


class Runner:
    def __init__(self,reject=False):self.calls=[];self.reject=reject
    async def generate(self,instruction,context,output,**kwargs):
        self.calls.append(deepcopy(context))
        if 'plan' in context:
            return {'supported':not self.reject,'no_semantic_regressions':not self.reject,'problems':[],
                    'rationale':'원문 전체와 정의 및 소유 대상의 의미 일치를 검증했습니다.'}
        kind=context['kind'];key='mobile_table' if kind=='item_type' else 'mobile_table_load'
        definition={'key':key,'kind':kind,'preferred_name':'이동형 진료대' if kind=='item_type' else '허용하중',
                    'definition':'이동형 진료대 또는 그 진료대가 허용하는 하중의 크기를 나타내는 로컬 정의입니다.',
                    'references':['source:placeholder']}
        if kind=='characteristic':definition.update(value_kind='number',
            applicable_item_type_ids=[str(concept_id_for_key('mobile_table'))],quantity_dimension='mass',canonical_unit='kg',allowed_units=['kg'])
        return {'definitions':[{'base_revision_id':None,'definition':definition}],
            'mappings':[{'source_entry_id':g['source_entry_id'],'target_key':key,
                         'owner_key':'mobile_table' if kind=='characteristic' else None,
                         'classification_code':context['classification_code'],
                         'rationale':'서로 다른 문서의 동일한 원문 의미와 적용 범위를 대조했습니다.'} for g in context['groups']],
            'retire_concept_ids':[],'held_source_ids':[],'rationale':'여러 문서의 원문 표현을 함께 분석해 중복 없는 사전 정의로 연결합니다.'}


def input_file(tmp_path,name,digest,marker=''):
    data=corpus('허용하중');doc=data['documents'][0];doc['source']['sha256']=digest
    if marker:doc['parsed_document']['nodes'][-1]['text']+='\n'+marker
    path=tmp_path/(name+'.json');raw=json.dumps(data,ensure_ascii=False).encode();path.write_bytes(raw)
    return {'uri':path.as_uri(),'sha256':hashlib.sha256(raw).hexdigest()}


def request(tmp_path):
    return {'batch_id':'corpus_fixture','artifact_root':(tmp_path/'objects').as_uri(),
            'model':'fixture','extractions':[input_file(tmp_path,'one','1'*64),input_file(tmp_path,'two','2'*64)]}


async def test_bulk_reconciliation_deduplicates_inputs_rekeys_document_ids_and_exports_snapshot(tmp_path):
    manifest=request(tmp_path);manifest['extractions'].append(manifest['extractions'][0]);api=API();runner=Runner()
    result=await maintain_dictionary(manifest,api=api,runner=runner)
    assert result['status']=='applied' and result['documents']==2
    assert result['quality_improvement_proven'] is False and result['validation_scope']=='development_only'
    assert len(api.repo.definitions)==2 and len(api.repo.links)==2
    planning=[c for c in runner.calls if 'kind' in c and 'plan' not in c]
    assert len(planning)==2 and len(planning[0]['groups'][0]['occurrences'])==2
    assert len({o['document_id'] for o in planning[0]['groups'][0]['occurrences']})==2
    assert result['dictionary_standard']['sha256']
    output=tmp_path/'objects/specification_processing/dictionary_maintenance/corpus_fixture'
    assert (output/'impact.json').exists() and (output/'dictionary_standard.json').exists()
    assert all(d['content']['references'][0].startswith('source:') for d in api.repo.definitions)


async def test_auto_apply_false_preserves_proposal_and_performs_no_meaning_writes(tmp_path):
    manifest=request(tmp_path);manifest['auto_apply']=False;api=API()
    result=await maintain_dictionary(manifest,api=api,runner=Runner())
    assert result['status']=='proposed' and not api.repo.definitions and not api.repo.links


async def test_semantic_verification_failure_prevents_authoritative_meaning_changes(tmp_path):
    api=API();result=await maintain_dictionary(request(tmp_path),api=api,runner=Runner(reject=True))
    assert result['status']=='held' and not api.repo.definitions and not api.repo.links


async def test_validation_documents_are_used_only_after_plan_freezes(tmp_path):
    manifest=request(tmp_path);manifest['validation_extractions']=[input_file(tmp_path,'validation','3'*64,'validation_only_marker')]
    runner=Runner();result=await maintain_dictionary(manifest,api=API(),runner=runner)
    assert result['status']=='applied' and result['validation_scope']=='separate_document_check'
    assert 'validation_only_marker' not in json.dumps([c for c in runner.calls if 'kind' in c])
    assert 'validation_only_marker' in json.dumps(runner.calls[-1])


@pytest.mark.parametrize('overlap',['hash','family'])
async def test_overlapping_development_and_validation_are_rejected_before_registration(tmp_path,overlap):
    manifest=request(tmp_path)
    if overlap=='hash':manifest['validation_extractions']=[manifest['extractions'][0]]
    else:
        manifest['extractions'][0]['template_family']='shared_template'
        manifest['validation_extractions']=[{**input_file(tmp_path,'validation','3'*64),'template_family':'shared_template'}]
    api=API()
    with pytest.raises(ValueError,match='overlap'):
        await maintain_dictionary(manifest,api=api,runner=Runner())
    assert not api.operations


async def test_wrong_extraction_checksum_and_unknown_classification_are_not_inferred(tmp_path):
    manifest=request(tmp_path);manifest['extractions'][0]['sha256']='0'*64
    with pytest.raises(ValueError,match='checksum'):
        await maintain_dictionary(manifest,api=API(),runner=Runner())
    manifest=request(tmp_path);manifest['classification_code']='1234567890'
    with pytest.raises(ValueError,match='partition'):
        await maintain_dictionary(manifest,api=API(),runner=Runner())


async def test_pinned_dictionary_ignores_later_live_revisions_and_never_calls_codex(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from teoria.features.specification_processing.normalization import dictionary_alignment
    manifest=request(tmp_path);api=API()
    built=await maintain_dictionary(manifest,api=api,runner=Runner())
    frozen=json.loads(Path(built['dictionary_standard']['uri'].removeprefix('file://')).read_text())
    for row in api.repo.definitions:row['status']='deprecated'
    doc=corpus('허용하중');doc['documents'][0]['relations']=[]
    class StageAPI(API):
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def dictionary(self,operation_id,payload):
            result=await api.dictionary(operation_id,payload)
            return {**result,'operation_id':operation_id,'policy_version':'source_literal_v1','summary':{'reused':2}}
        async def resolve_dictionary_meanings(self,*args):
            raise AssertionError('pinned run must not read live meanings')
    monkeypatch.setattr(dictionary_alignment,'GoodsAuthoringClient',StageAPI)
    req=SimpleNamespace(mode='document_processing',run_id='frozen_fixture',dictionary_standard=SimpleNamespace(**built['dictionary_standard']),
        artifact_root=(tmp_path/'pinned_objects').as_uri(),dictionary_auto_approve=True,dictionary_meaning_auto_approve=True,
        model=None,classification_code=None)
    result=await dictionary_alignment.align_dictionary(req,doc,{})
    assert result['meaning_summary']=={'resolved':2}
    assert result['meaning_alignment']['snapshot_checksum']==frozen['checksum']
    assert (tmp_path/'pinned_objects/specification_processing/frozen_fixture/dictionary_standard.json').exists()


async def test_existing_task_06_calls_corpus_maintenance_and_reuses_the_same_alignment_path(tmp_path,monkeypatch):
    from unittest.mock import AsyncMock
    from teoria.features.specification_processing import tasks
    from teoria.features.specification_processing.models import SpecificationRun
    from teoria.features.specification_processing.normalization import dictionary_alignment,dictionary_incremental
    corpus_path=tmp_path/'extracted.json';corpus_path.write_text(json.dumps(corpus('허용하중')))
    request=SpecificationRun(run_id='existing_task_fixture',mode='standard_management',model='fixture',
        dictionary_reconcile=True,artifact_root=tmp_path.as_uri(),documents=[{'document_id':'fixture','source_uri':corpus_path.as_uri(),'filename':'fixture.pdf'}],
        dictionary_corpus=[{'uri':corpus_path.as_uri(),'sha256':'a'*64}])
    maintenance={'status':'held','reason':'coverage_missing','artifacts':[]}
    maintain=AsyncMock(return_value=maintenance);align=AsyncMock(return_value={'summary':{}})
    monkeypatch.setattr(dictionary_incremental,'update_standard_dictionary',maintain)
    monkeypatch.setattr(dictionary_alignment,'align_dictionary',align)
    await tasks.resolve_dictionary.fn(request,str(tmp_path),{'uri':corpus_path.as_uri(),'sha256':'b'*64})
    payload=maintain.await_args.args[0]
    assert len(payload.dictionary_corpus)==1 and payload.dictionary_meaning_auto_approve is True
    assert align.await_args.kwargs['maintenance']==maintenance


def test_document_processing_cannot_change_dictionary_definitions(tmp_path):
    from teoria.features.specification_processing.models import SpecificationRun
    with pytest.raises(ValueError,match='corpus reconciliation'):
        SpecificationRun(run_id='invalid',mode='document_processing',model='fixture',dictionary_reconcile=True,
            artifact_root=tmp_path.as_uri(),standard={'uri':tmp_path.as_uri(),'sha256':'a'*64},
            documents=[{'document_id':'fixture','source_uri':tmp_path.as_uri(),'filename':'fixture.pdf'}])


async def test_development_repair_is_bounded_and_rechecked_before_apply(tmp_path):
    class RepairRunner(Runner):
        def __init__(self):super().__init__();self.failed=False
        async def generate(self,instruction,context,output,**kwargs):
            result=await super().generate(instruction,context,output,**kwargs)
            if 'plan' in context and not self.failed:
                self.failed=True;result.update(supported=False,no_semantic_regressions=False,problems=['Preserve source scope.'])
            return result
    runner=RepairRunner();result=await maintain_dictionary(request(tmp_path),api=API(),runner=runner)
    assert result['status']=='applied'
    assert any('verification_feedback' in c and 'previous_plan' in c for c in runner.calls)
    output=tmp_path/'objects/specification_processing/dictionary_maintenance/corpus_fixture'
    assert (output/'item_type_repair_1_plan.json').exists() and (output/'item_type_repair_1_check.json').exists()


async def test_candidate_unit_policy_is_checked_against_separate_source_observations(tmp_path):
    from teoria.features.specification_processing.normalization.dictionary_maintenance import validate_observation_policies
    api=API();result=await maintain_dictionary(request(tmp_path),api=api,runner=Runner())
    snapshot=json.loads(Path(result['dictionary_standard']['uri'].removeprefix('file://')).read_text())
    source=next(s for s in snapshot['sources'] if s['kind']=='characteristic')
    groups=[{'source_entry_id':source['entry_id'],'kind':'characteristic','occurrences':[
        {'classification_code':None,'document_id':'separate_case','value_kind':'number','unit_raw':'kW'}]}]
    assert validate_observation_policies(snapshot,groups)[0]['reason']=='value_kind_or_unit_regression'


async def test_context_budget_is_an_explicit_hold_without_model_or_meaning_writes(tmp_path):
    manifest=request(tmp_path)
    manifest['extractions']=[input_file(tmp_path,'large','4'*64,'X'*20000)]
    manifest['max_context_characters']=10000
    api=API();runner=Runner()
    result=await maintain_dictionary(manifest,api=api,runner=runner)
    assert result['status']=='held' and result['reason']=='dictionary_context_budget_exceeded'
    assert result['context_characters']>result['max_context_characters']==10000
    assert not runner.calls and not api.repo.definitions and not api.repo.links
    assert any(a['key'].endswith('/result.json') for a in result['artifacts'])


def test_group_context_keeps_all_occurrences_and_excludes_other_nodes():
    from teoria.features.specification_processing.normalization.dictionary_maintenance import nodes_for_groups
    groups=[{'occurrences':[{'document_id':'a','context_node_ids':['1','2']},
                            {'document_id':'b','context_node_ids':['1']}]}]
    nodes=[{'document_id':d,'node_id':n} for d,n in [('a','1'),('a','2'),('b','1'),('a','3')]]
    assert nodes_for_groups(groups,nodes)==nodes[:3]


async def test_unknown_mapping_target_reports_a_safe_rule_instead_of_key_error(tmp_path):
    from teoria.features.specification_processing.normalization.dictionary_maintenance import DictionaryProposalError
    class UnknownTarget(Runner):
        async def generate(self,*args,**kwargs):
            result=await super().generate(*args,**kwargs)
            if 'mappings' in result:
                result['mappings'][0]['target_key']='undefined_target'
            return result
    api=API()
    with pytest.raises(DictionaryProposalError) as error:
        await maintain_dictionary(request(tmp_path),api=api,runner=UnknownTarget())
    assert error.value.code=='mapping_target_not_defined'
    assert not api.repo.definitions and not api.repo.links
