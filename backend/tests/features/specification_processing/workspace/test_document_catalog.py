import pytest
from teoria.features.specification_processing.catalog.results import document_result, store_document_results
from teoria.features.specification_processing.storage.artifact_store import FileArtifactStore


def test_result_scopes_observations_and_preserves_authority_and_conditions():
    corpus={'documents':[{'document_id':'a','source':{'sha256':'a'*64}}, {'document_id':'b'}]}
    normalization={'standard_version':'draft','attributes':[
        {'document_id':'a','facts':[{'property_id':'cores','operator':'gte','role':'required','semantic_scope':'per_cpu','qualifiers_raw':['설치 시'],'value':{'decimal':'16','unit':'core'}}]},
        {'document_id':'b','facts':[{'property_id':'private'}]}]}
    payload=document_result(corpus,normalization,'a',definitions=[{'id':'cores','label':'코어 수'}])
    assert payload['result_kind']=='extraction_standard'
    assert len(payload['extracted']['documents'])==1
    assert len(payload['normalization']['attributes'])==1
    fact=payload['normalization']['attributes'][0]['facts'][0]
    assert fact['property_label']=='코어 수' and fact['operator']=='gte' and fact['qualifiers_raw']==['설치 시']
    assert normalization['attributes'][0]['facts'][0].get('property_label') is None
    normalization.update(artifact_kind='goods_normalized_observations',profile_revision_id='p',package_checksum='c',ontology={})
    assert document_result(corpus,normalization,'a')['result_kind']=='profile'
    with pytest.raises(KeyError):document_result(corpus,normalization,'missing')


async def test_document_projection_is_immutable_and_referenced_after_storage(tmp_path):
    store=FileArtifactStore(tmp_path)
    corpus={'documents':[{'document_id':'a','source':{'sha256':'a'*64}}]}
    first=await store_document_results(store,'run',corpus,None)
    assert first==await store_document_results(store,'run',corpus,None)
    corpus['documents'][0]['changed']=True
    with pytest.raises(ValueError,match='immutable'):
        await store_document_results(store,'run',corpus,None)


def test_catalog_routes_auth_validation_and_document_identity(tmp_path, monkeypatch):
    import hashlib
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from teoria.features.access_control.auth import AdminAuthorizer
    from teoria.settings import Settings
    from teoria.features.specification_processing import workspace_router

    payload=document_result({'documents':[{'document_id':'doc','source':{'sha256':'a'*64}}]},None,'doc')
    path=tmp_path/'result.json'
    raw=json.dumps(payload).encode();path.write_bytes(raw)
    entry={'catalog_id':'catalog','run_id':'run','document_id':'doc','source_sha256':'a'*64,'result_available':True}
    class Catalog:
        async def documents(self,**kwargs):return {'items':[entry],'total':1}
        async def entry(self,id):return entry if id=='catalog' else None
        async def history(self,id,**kwargs):return {'items':[],'total':0}
    class Runs:
        async def detail(self,id):return {'artifacts':[{'key':'specification_processing/run/documents/doc/result.json','uri':path.as_uri(),'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw)}]}
    monkeypatch.setattr(workspace_router,'DocumentCatalogRepository',lambda url:Catalog())
    app=FastAPI()
    app.include_router(workspace_router.create_processing_workspace_router(
        authorizer=AdminAuthorizer(Settings(admin_auth_mode='bearer',admin_api_token='synthetic-token',admin_api_actor='operator')),
        database_url='test',repository=Runs(),artifact_root=tmp_path,object_root=tmp_path.as_uri()))
    headers={'Authorization':'Bearer synthetic-token'}
    with TestClient(app) as client:
        prefix='/v1/admin/specification-processing/catalog'
        assert client.get(prefix+'/documents').status_code==401
        assert client.get(prefix+'/documents?classification=bad',headers=headers).status_code==422
        assert client.get(prefix+'/documents?since=2026-10-10&until=2026-10-01',headers=headers).status_code==422
        assert client.get(prefix+'/documents?offset=-1',headers=headers).status_code==422
        assert client.get(prefix+'/documents',headers=headers).json()['total']==1
        assert client.get(prefix+'/documents/missing/result',headers=headers).status_code==404
        assert client.get(prefix+'/documents/catalog/result',headers=headers).json()['result']['document_id']=='doc'
        entry['source_sha256']='b'*64
        assert client.get(prefix+'/documents/catalog/result',headers=headers).status_code==409
