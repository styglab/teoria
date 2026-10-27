from contextlib import asynccontextmanager
from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from teoria.features.semantic_modeling.goods_dictionary.contracts import (
    DictionarySubmission, source_literal_definition,
)
from teoria.features.semantic_modeling.goods_dictionary.service import GoodsDictionaryService


def submission(auto_approve=True):
    evidence = {'document_id':'doc','source_sha256':'a'*64,'locator':'/blocks/1','quote':'인버터 정격출력 3kW 이상'}
    return DictionarySubmission.model_validate({
        'auto_approve':auto_approve,
        'sources':[{'document_id':'doc','source_sha256':'a'*64,'parser_version':'test',
                    'nodes':[{'locator':'/blocks/1','text':evidence['quote']}]}],
        'candidates':[
            {'candidate_key':'inverter','kind':'item_type','preferred_name':'인버터',
             'definition':source_literal_definition('item_type','인버터'),'origin_ref':'item1','evidence':[evidence]},
            {'candidate_key':'power','kind':'characteristic','preferred_name':'정격출력',
             'definition':source_literal_definition('characteristic','정격출력','인버터'),
             'owner_candidate_key':'inverter','value_kind':'number','origin_ref':'attr1','evidence':[evidence]},
        ],
    })


class MemoryRepository:
    def __init__(self):
        self.operations = {}; self.entries_by_key = {}; self.decisions = []; self.events = []

    @asynccontextmanager
    async def transaction(self):
        before = deepcopy(self.__dict__)
        try:
            yield self
        except BaseException:
            self.__dict__.update(before)
            raise

    async def lock(self, conn): pass
    async def operation(self, conn, key): return self.operations.get(key)
    async def begin(self, conn, key, digest, actor):
        self.operations[key] = {'actor':actor,'request_checksum':digest,'result':{}}
    async def finish(self, conn, key, result): self.operations[key]['result'] = result
    async def by_key(self, conn, key): return self.entries_by_key.get(key)
    async def by_id(self, conn, id):
        return next((e for e in self.entries_by_key.values() if str(e['entry_id'])==str(id)),None)
    async def insert_entry(self, conn, body, digest, actor, policy):
        entry={**body,'entry_id':uuid4(),'content':body,'content_checksum':digest,'status':'approved','approved_by':actor}
        self.entries_by_key[body['stable_key']]=entry;return entry
    async def decision(self, conn, operation_id, candidate, result, digest, actor, policy):
        self.decisions.append((operation_id,candidate,result,digest,actor,policy))
    async def event(self, conn, operation_id, key, action, reason, actor, policy, entry_id=None):
        self.events.append((operation_id,key,action,reason,actor,policy,entry_id))
    async def entries(self, conn, query, kind, limit):
        return [e for e in self.entries_by_key.values() if (kind is None or e['kind']==kind) and query in e['preferred_name']][:limit]


async def test_first_use_approves_then_reuses_and_records_automatic_review():
    repo=MemoryRepository();service=GoodsDictionaryService(repository=repo)
    first=await service.author('first',submission(),actor='system:pipeline')
    assert first['summary']=={'approved':2,'reused':0,'held':0,'proposed':0}
    assert first['approval_mode']=='automatic_policy'
    second=await service.author('second',submission(),actor='system:pipeline')
    assert second['summary']['reused']==2 and len(repo.entries_by_key)==2
    assert [d['entry_id'] for d in first['decisions']]==[d['entry_id'] for d in second['decisions']]
    count=len(repo.events)
    assert await service.author('first',submission(),actor='system:pipeline')==first
    assert len(repo.events)==count
    assert {e[2] for e in repo.events}=={'proposed','approved','reused'}
    assert {e[4] for e in repo.events}=={'system:pipeline'}


@pytest.mark.parametrize('change,reason',[
    ('fake_quote','quote_not_in_parser_snapshot'),('name','name_not_in_source'),
    ('hash','source_identity_mismatch'),('definition','semantic_definition_requires_review'),
])
async def test_unsupported_candidates_are_held_not_silently_approved(change,reason):
    body=submission().model_dump(mode='json')
    if change=='fake_quote':body['candidates'][0]['evidence'][0]['quote']='원문에 없는 내용'
    elif change=='name':body['candidates'][0]['preferred_name']='전혀 다른 물품'
    elif change=='hash':body['candidates'][0]['evidence'][0]['source_sha256']='b'*64
    else:body['candidates'][0]['definition']='안전성이 인증된 최고 성능 인버터'
    repo=MemoryRepository();result=await GoodsDictionaryService(repository=repo).author('hold',DictionarySubmission.model_validate(body),actor='test')
    assert result['summary']['held']==2 and not repo.entries_by_key
    assert result['decisions'][0]['reason']==reason
    assert result['decisions'][1]['reason']=='owner_type_not_approved'


async def test_value_kind_conflict_does_not_change_an_approved_entry():
    repo=MemoryRepository();service=GoodsDictionaryService(repository=repo)
    await service.author('first',submission(),actor='test')
    entries=deepcopy(repo.entries_by_key)
    body=submission().model_dump(mode='json');body['candidates'][1]['value_kind']='text'
    result=await service.author('conflict',DictionarySubmission.model_validate(body),actor='test')
    assert result['summary']['held']==1 and result['summary']['reused']==1
    assert repo.entries_by_key==entries
    assert result['decisions'][1]['reason']=='existing_definition_conflict'


async def test_disabled_automatic_approval_proposes_without_creating_entries():
    repo=MemoryRepository()
    result=await GoodsDictionaryService(repository=repo).author('manual',submission(False),actor='test')
    assert result['summary']['proposed']==1 and result['summary']['held']==1
    assert not repo.entries_by_key


async def test_operation_replay_is_bound_to_input_and_authenticated_actor():
    service=GoodsDictionaryService(repository=MemoryRepository())
    await service.author('same',submission(),actor='owner')
    with pytest.raises(ValueError,match='identity conflict'):
        await service.author('same',submission(),actor='another')
    with pytest.raises(ValueError,match='identity conflict'):
        await service.author('same',submission(False),actor='owner')


def test_request_cannot_spoof_actor_or_review_mode():
    body=submission().model_dump(mode='json');body['actor']='human:reviewer'
    with pytest.raises(ValidationError):DictionarySubmission.model_validate(body)


def test_authenticated_http_path_rejects_unauthenticated_writes_and_reads():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from teoria.features.access_control.auth import AdminAuthorizer
    from teoria.features.semantic_modeling.goods_dictionary.admin_router import create_goods_dictionary_router
    from teoria.settings import Settings
    app=FastAPI();repo=MemoryRepository()
    authorizer=AdminAuthorizer(Settings(admin_auth_mode='bearer',admin_api_token='fixture-token',admin_api_actor='system:test',admin_api_roles='ontology_owner'))
    app.include_router(create_goods_dictionary_router(GoodsDictionaryService(repository=repo),authorizer))
    with TestClient(app) as client:
        assert client.get('/v1/admin/goods/dictionary/entries').status_code==401
        assert client.post('/v1/admin/goods/dictionary/operations/test',json=submission().model_dump(mode='json')).status_code==401
        headers={'Authorization':'Bearer fixture-token'}
        result=client.post('/v1/admin/goods/dictionary/operations/test',headers=headers,json=submission().model_dump(mode='json'))
        assert result.status_code==200 and result.json()['summary']['approved']==2
        assert len(client.get('/v1/admin/goods/dictionary/entries',headers=headers).json()['items'])==2
