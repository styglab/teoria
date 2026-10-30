"""Automatic source discovery, context novelty and guarded incremental application."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import RelatedMeaningContext,resolve_snapshot
from teoria.features.specification_processing.models import SpecificationRun
from teoria.features.specification_processing.normalization.dictionary_candidates import submission_from_corpus
from teoria.features.specification_processing.normalization.dictionary_alignment import aligned_observations,apply_concept_meanings
from teoria.features.specification_processing.normalization import dictionary_incremental
from .test_dictionary_candidates import corpus
from .test_dictionary_maintenance import API,Runner,request as corpus_request
from teoria.features.specification_processing.normalization.dictionary_maintenance import maintain_dictionary


class ContextAPI(API):
    async def dictionary_meaning(self,method,path,payload=None):
        if path=='/related-context':return await self.service.related_context(RelatedMeaningContext.model_validate(payload))
        return await super().dictionary_meaning(method,path,payload)


class Catalog:
    def __init__(self,descriptor):self.descriptor=descriptor;self.lookups=[];self.recorded=[]
    async def register_extraction(self,run_id,ref,data):self.recorded.append((run_id,ref));return True
    async def find_accepted_contexts(self,contexts):return []
    async def find_extractions(self,hashes,**kwargs):
        self.lookups.append(set(hashes))
        return [self.descriptor] if self.descriptor and self.descriptor['source_sha256'] in hashes else []


def write_ref(path,body):
    raw=json.dumps(body,ensure_ascii=False).encode();path.write_bytes(raw)
    return {'uri':path.as_uri(),'sha256':hashlib.sha256(raw).hexdigest()}


async def setup(tmp_path):
    api=ContextAPI()
    initial=corpus_request(tmp_path)
    initial['extractions']=[write_ref(tmp_path/'seed.json',corpus('허용하중'))]
    await maintain_dictionary(initial,api=api,runner=Runner())
    old=corpus('허용하중');old['documents'][0]['relations']=[]
    submission=submission_from_corpus(old);registration=await api.dictionary('old',submission.model_dump(mode='json'))
    snapshot=await api.service.snapshot();resolution=resolve_snapshot(snapshot,[d['entry_id'] for d in registration['decisions']])
    normalized={'dictionary_meanings':apply_concept_meanings(aligned_observations(old,submission,registration),resolution)}
    old_ref=write_ref(tmp_path/'old.json',old);norm_ref=write_ref(tmp_path/'old_normalized.json',normalized)
    descriptor={'source_sha256':old['documents'][0]['source']['sha256'],'run_id':'old_run',**old_ref,
                'normalized_uri':norm_ref['uri'],'normalized_sha256':norm_ref['sha256']}
    # Controlled variation of the source-backed excerpt; not a real-model quality case.
    new=deepcopy(old);new['documents'][0]['source']['sha256']='9'*64
    new['documents'][0]['attributes'][0]['value_raw']='250'
    new['documents'][0]['parsed_document']['nodes'][-1]['text']=new['documents'][0]['parsed_document']['nodes'][-1]['text'].replace('200kg','250kg')
    ref=write_ref(tmp_path/'new.json',new)
    req=SpecificationRun(run_id='incremental_fixture',mode='standard_management',model='fixture',artifact_root=(tmp_path/'incremental').as_uri(),
        documents=[{'document_id':'vehicle','source_uri':ref['uri'],'filename':'vehicle.hwpx'}])
    return api,Catalog(descriptor),new,ref,req


async def test_value_only_change_reuses_verified_context_without_any_model_call(tmp_path):
    api,catalog,new,ref,req=await setup(tmp_path);runner=AsyncMock()
    result=await dictionary_incremental.update_standard_dictionary(req,new,ref,api=api,repository=catalog,runner=runner)
    assert result['status']=='reused' and result['reused_contexts']==2
    runner.generate.assert_not_awaited()
    assert catalog.lookups and catalog.recorded
    assert json.loads(Path(result['dictionary_standard']['uri'].removeprefix('file://')).read_text())['checksum']


async def test_new_role_discovers_past_extraction_and_does_not_blindly_reuse_approved_mapping(tmp_path,monkeypatch):
    api,catalog,new,ref,req=await setup(tmp_path)
    new['documents'][0]['attributes'][0]['semantic_role']='supported_capability'
    new['documents'][0]['attributes'][0]['semantic_scope']='support_limit'
    ref=write_ref(tmp_path/'new.json',new)
    maintain=AsyncMock(return_value={'status':'held','reason':'ambiguous_context','artifacts':[]})
    monkeypatch.setattr(dictionary_incremental,'maintain_dictionary',maintain)
    result=await dictionary_incremental.update_standard_dictionary(req,new,ref,api=api,repository=catalog,runner=AsyncMock())
    assert result['status']=='held' and len(result['blocked_source_ids'])==1
    payload=maintain.await_args.args[0]
    assert len(payload['extractions'])==2  # Current and automatically discovered past source.
    assert payload['auto_apply'] is False  # One frozen checked changeset is applied later.


async def test_missing_historical_artifact_is_held_before_inference_or_definition_change(tmp_path):
    api,catalog,new,ref,req=await setup(tmp_path);catalog.descriptor=None;runner=AsyncMock()
    before=deepcopy(api.repo.definitions)
    result=await dictionary_incremental.update_standard_dictionary(req,new,ref,api=api,repository=catalog,runner=runner)
    assert result['status']=='held' and result['reason']=='historical_extraction_reference_missing'
    assert api.repo.definitions==before;runner.generate.assert_not_awaited()


async def test_corrupted_past_extraction_is_not_used_for_automatic_approval(tmp_path):
    api,catalog,new,ref,req=await setup(tmp_path);catalog.descriptor['sha256']='0'*64
    result=await dictionary_incremental.update_standard_dictionary(req,new,ref,api=api,repository=catalog,runner=AsyncMock())
    assert result['status']=='held' and result['reason']=='historical_extraction_checksum_mismatch'


async def test_cached_current_revision_skips_history_and_model(tmp_path):
    api,catalog,new,ref,req=await setup(tmp_path)
    catalog.find_accepted_contexts=AsyncMock(side_effect=lambda contexts:contexts)
    catalog.find_extractions=AsyncMock(side_effect=AssertionError('cached context must not reload history'))
    runner=AsyncMock()
    result=await dictionary_incremental.update_standard_dictionary(req,new,ref,api=api,repository=catalog,runner=runner)
    assert result['status']=='reused'
    runner.generate.assert_not_awaited()
    catalog.find_extractions.assert_not_awaited()


async def test_changed_source_wording_requires_review_even_when_extracted_role_is_unchanged(tmp_path,monkeypatch):
    api,catalog,new,ref,req=await setup(tmp_path)
    nodes=new['documents'][0]['parsed_document']['nodes']
    nodes[-1]['text']=nodes[-1]['text'].replace('허용하중','지원 가능한 최대 허용하중')
    ref=write_ref(tmp_path/'new.json',new)
    maintain=AsyncMock(return_value={'status':'held','reason':'changed_wording','artifacts':[]})
    monkeypatch.setattr(dictionary_incremental,'maintain_dictionary',maintain)
    result=await dictionary_incremental.update_standard_dictionary(req,new,ref,api=api,repository=catalog,runner=AsyncMock())
    assert result['status']=='held'
    maintain.assert_awaited_once()


async def test_held_new_context_cannot_fall_back_to_the_old_approved_meaning(tmp_path,monkeypatch):
    from teoria.features.specification_processing.normalization import dictionary_alignment
    api,catalog,new,ref,req=await setup(tmp_path)
    class AlignerAPI:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def dictionary(self,id,payload):
            registered=await api.dictionary(id,payload)
            return {**registered,'operation_id':id,'policy_version':'source_literal_v1','summary':{'reused':2}}
        async def resolve_dictionary_meanings(self,ids,code=None):return resolve_snapshot(await api.service.snapshot(),ids,code)
    monkeypatch.setattr(dictionary_alignment,'GoodsAuthoringClient',AlignerAPI)
    source=next(id for id,row in api.repo.sources.items() if row['kind']=='characteristic')
    result=await dictionary_alignment.align_dictionary(req,new,ref,maintenance={'status':'held','reason':'role_changed',
        'blocked_source_ids':[source],'artifacts':[]})
    attr=result['meaning_alignment']['documents'][0]['attributes'][0]
    assert attr['meaning_status']=='held' and 'dictionary_concept_ref' not in attr


async def test_catalog_reference_to_missing_file_is_held_without_modifying_definitions(tmp_path):
    api,catalog,new,ref,req=await setup(tmp_path)
    Path(catalog.descriptor['uri'].removeprefix('file://')).unlink()
    before=deepcopy(api.repo.definitions)
    result=await dictionary_incremental.update_standard_dictionary(req,new,ref,api=api,repository=catalog,runner=AsyncMock())
    assert result['status']=='held' and result['reason']=='historical_extraction_unavailable'
    assert before==api.repo.definitions


async def test_automatic_application_requires_separate_validation_when_requested(tmp_path,monkeypatch):
    api,catalog,new,ref,req=await setup(tmp_path)
    req.dictionary_require_validation=True
    new['documents'][0]['attributes'][0]['semantic_role']='supported_capability'
    planned={'status':'proposed','validation_documents':0,'held_source_ids':[],'artifacts':[]}
    monkeypatch.setattr(dictionary_incremental,'maintain_dictionary',AsyncMock(return_value=planned))
    before=deepcopy(api.repo.definitions)
    result=await dictionary_incremental.update_standard_dictionary(req,new,ref,api=api,repository=catalog,runner=AsyncMock())
    assert result['status']=='held' and result['reason']=='independent_validation_required'
    assert before==api.repo.definitions


async def test_current_source_is_reassessed_without_deleted_historical_file(tmp_path,monkeypatch):
    api,catalog,_,_,req=await setup(tmp_path)
    old_path=Path(catalog.descriptor['uri'].removeprefix('file://'))
    current=json.loads(old_path.read_text())
    old_path.unlink()
    Path(catalog.descriptor['normalized_uri'].removeprefix('file://')).unlink()
    ref=write_ref(tmp_path/'current.json',current)
    maintain=AsyncMock(return_value={'status':'held','reason':'review_pending','artifacts':[]})
    monkeypatch.setattr(dictionary_incremental,'maintain_dictionary',maintain)
    result=await dictionary_incremental.update_standard_dictionary(req,current,ref,api=api,repository=catalog,runner=AsyncMock())
    assert result['reason']=='review_pending'
    maintain.assert_awaited_once()
    assert len(maintain.await_args.args[0]['extractions'])==1


async def test_new_full_extraction_evidence_is_used_before_deleted_historical_locations(tmp_path,monkeypatch):
    api,catalog,new,ref,req=await setup(tmp_path)
    evidence={'uri':catalog.descriptor['uri'],'sha256':catalog.descriptor['sha256']}
    req=req.model_validate({**req.model_dump(mode='json'),'dictionary_evidence_corpus':[evidence]})
    catalog.find_extractions=AsyncMock(side_effect=AssertionError('available evidence must not query old paths'))
    new['documents'][0]['attributes'][0]['semantic_role']='supported_capability'
    ref=write_ref(tmp_path/'new.json',new)
    maintain=AsyncMock(return_value={'status':'held','reason':'explicit_review','artifacts':[]})
    monkeypatch.setattr(dictionary_incremental,'maintain_dictionary',maintain)
    result=await dictionary_incremental.update_standard_dictionary(req,new,ref,api=api,repository=catalog,runner=AsyncMock())
    assert result['reason']=='explicit_review'
    assert len(maintain.await_args.args[0]['extractions'])==2
    catalog.find_extractions.assert_not_awaited()


async def test_evidence_must_not_expose_independent_validation_to_dictionary_planning(tmp_path,monkeypatch):
    import pytest
    api,catalog,new,ref,req=await setup(tmp_path)
    evidence={'uri':catalog.descriptor['uri'],'sha256':catalog.descriptor['sha256']}
    req=req.model_validate({**req.model_dump(mode='json'),'dictionary_evidence_corpus':[evidence],
                           'dictionary_validation_corpus':[evidence]})
    with pytest.raises(ValueError,match='overlaps independent validation'):
        await dictionary_incremental.update_standard_dictionary(req,new,ref,api=api,repository=catalog,runner=AsyncMock())
