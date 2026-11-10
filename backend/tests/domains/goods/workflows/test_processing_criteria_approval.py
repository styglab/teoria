"""Automatic version creation remains an authenticated, pinned, audited action."""
import hashlib
from uuid import uuid4
from unittest.mock import AsyncMock

from teoria.domains.goods.workflows import processing_criteria_approval as automatic
from teoria.domains.goods.contracts import SpecificationRun, RunResult, ArtifactRef
from teoria.domains.goods.expression_links.snapshot_contracts import approved_dictionary_snapshot
from teoria.domains.goods.expression_links.expression_contracts import expression_snapshot


async def test_automatic_approval_pins_used_dictionary_and_records_authenticated_result(tmp_path, monkeypatch):
    snapshot=expression_snapshot([],[],[]).model_dump(mode='json')
    raw=approved_dictionary_snapshot(snapshot).model_dump_json().encode()
    path=tmp_path/'dictionary_standard.json';path.write_bytes(raw)
    request=SpecificationRun(run_id='automatic_test',mode='standard_management',artifact_root=tmp_path.as_uri(),
        auto_approve_application_standard=True,documents=[{'document_id':'doc','filename':'doc.pdf','source_uri':(tmp_path/'doc.pdf').as_uri()}])
    result=RunResult(run_id=request.run_id,status='partial',summary={"quality":{"successful_documents":1,"validation_errors":0,"failed_document_ratio":0,"held_attribute_ratio":0,"accepted_attributes":1,"applied_attributes":1,"model_requested":None}},document_results=[],artifacts=[ArtifactRef(
        key='test/dictionary_standard.json',uri=path.as_uri(),sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw),media_type='application/json')])
    payloads=[];release_id=str(uuid4())
    class API:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def application_standard_readiness(self,id):return {'ready':True}
        async def dictionary_meaning(self,*args):return snapshot
        async def approve_application_standard(self,payload):
            payloads.append(payload)
            return {'release_id':release_id,'approved_by':'authenticated:worker','content_checksum':'a'*64}
    record=AsyncMock()
    class Repository:
        record_application_standard=record
    monkeypatch.setattr(automatic,'GoodsAuthoringClient',API)
    monkeypatch.setattr(automatic.SpecificationRepository,'from_environment',lambda:Repository())
    for _ in range(2):
        updated=await automatic.approve_application_standard.fn(request,result)
        assert updated.summary['automatic_application_standard']['release_id']==release_id
        assert updated.summary['automatic_application_standard']['approved_by']=='authenticated:worker'
    assert payloads[0]==payloads[1] and 'actor' not in payloads[0]
    assert payloads[0]['expected_dictionary_checksum']==snapshot['checksum']
    assert record.await_count==2


async def test_empty_standard_is_held_without_issuing_approval(tmp_path, monkeypatch):
    class API:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def application_standard_readiness(self,id):return {'ready':False,'reason':'standard_has_no_application_rules'}
        approve_application_standard=AsyncMock()
    record=AsyncMock()
    class Repository:
        record_application_standard=record
    monkeypatch.setattr(automatic,'GoodsAuthoringClient',API)
    monkeypatch.setattr(automatic.SpecificationRepository,'from_environment',lambda:Repository())
    from types import SimpleNamespace
    result=RunResult(run_id='empty',status='partial',summary={"quality":{"successful_documents":1,"validation_errors":0,"failed_document_ratio":0,"held_attribute_ratio":0,"accepted_attributes":1,"model_requested":None}},document_results=[],artifacts=[])
    updated=await automatic.approve_application_standard.fn(SimpleNamespace(run_id='empty'),result)
    assert updated.summary['automatic_application_standard']['status']=='held'
    API.approve_application_standard.assert_not_awaited()
