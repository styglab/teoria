"""Revisions preserve frozen results; incomplete or stale migrations must roll back atomically."""
from copy import deepcopy
from uuid import uuid4
import pytest

from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import (
    DictionaryChangeSet, DefinitionChange, MappingChange, resolve_snapshot,
)
from teoria.features.semantic_modeling.goods_dictionary.change_service import preview_change_set
from teoria.features.semantic_modeling.goods_dictionary.meaning_service import GoodsMeaningService
from .test_meanings import Repository, approved, item, link


class ChangeRepository(Repository):
    def __init__(self):
        super().__init__();self.operations={};self.missing_evidence=False;self.document_refs=None
    async def all_sources(self,c):
        return [{'entry_id':id,'status':'approved','preferred_name':'인버터',**row} for id,row in self.sources.items()]
    async def affected_documents(self,c,ids):
        if self.document_refs is not None:
            return [r for r in self.document_refs if r['entry_id'] in ids]
        return [{'entry_id':str(id),'operation_id':'dictionary_fixture','document_id':'fixture',
                 'source_sha256':'a'*64} for id in ids]
    async def operation(self,c,id):return self.operations.get(id)
    async def begin(self,c,id,digest,actor):self.operations[id]={'request_checksum':digest,'actor':actor,'result':{}}
    async def finish(self,c,id,result):self.operations[id]['result']=result
    async def source_evidence(self,c,id):
        return [] if self.missing_evidence else await super().source_evidence(c,id)


async def initial():
    repo=ChangeRepository();service=GoodsMeaningService(repository=repo)
    source=uuid4();repo.sources[str(source)]={'kind':'item_type'}
    target=await approved(service,item());await link(service,source,target)
    return repo,service,source,target


def revision(snapshot,source,target):
    return DictionaryChangeSet(baseline_checksum=snapshot['checksum'],
        reviewed_source_sha256=['a'*64],
        definitions=[DefinitionChange(base_revision_id=target['revision_id'],
            definition=item().model_copy(update={'definition':'직류 입력을 교류 출력으로 변환하는 전력 장치이며 정류기를 제외한다.'}))],
        mappings=[MappingChange(source_entry_id=source,target_key='inverter',rationale='개정된 정의와 원문 표현의 의미를 다시 확인했습니다.')],
        rationale='다수 문서의 원문을 대조해 정의와 모든 영향 매핑을 함께 개정합니다.')


async def test_revision_and_mapping_replacement_are_atomic_idempotent_and_keep_old_snapshot():
    repo,service,source,target=await initial();before=await service.snapshot();change=revision(before,source,target)
    preview=await service.preview_changes(change)
    assert preview['status']=='valid' and len(preview['impact'])==1
    result=await service.apply_changes('maintenance_revision',change,actor='policy:test')
    current=await service.snapshot()
    assert resolve_snapshot(current,[source])['items'][0]['status']=='resolved'
    assert resolve_snapshot(before,[source])['items'][0]['revision_id']==str(target['revision_id'])
    assert resolve_snapshot(current,[source])['items'][0]['revision_id']!=str(target['revision_id'])
    assert [c['status'] for c in repo.definitions]==['deprecated','approved']
    assert [m['status'] for m in repo.links]==['deprecated','approved']
    assert await service.apply_changes('maintenance_revision',change,actor='policy:test')==result
    assert len(repo.definitions)==2


async def test_omitted_impacted_mapping_blocks_revision_before_mutation():
    repo,service,source,target=await initial();before=await service.snapshot();change=revision(before,source,target)
    change.mappings=[]
    assert (await service.preview_changes(change))['reason']=='affected_source_mappings_require_reassessment'
    with pytest.raises(ValueError,match='reassessment'):
        await service.apply_changes('maintenance_incomplete',change,actor='policy:test')
    assert await service.snapshot()==before and not repo.operations


async def test_late_missing_evidence_rolls_back_definitions_mappings_and_audit():
    repo,service,source,target=await initial();before=await service.snapshot();events=deepcopy(repo.events)
    change=revision(before,source,target);repo.missing_evidence=True
    with pytest.raises(ValueError,match='registered_evidence'):
        await service.apply_changes('maintenance_rollback',change,actor='policy:test')
    assert await service.snapshot()==before and repo.events==events and not repo.operations


async def test_changed_baseline_cannot_overwrite_a_concurrent_revision():
    repo,service,source,target=await initial();before=await service.snapshot();change=revision(before,source,target)
    await approved(service,item('new_type'))
    with pytest.raises(ValueError,match='baseline_changed'):
        await service.apply_changes('maintenance_stale',change,actor='policy:test')


async def test_split_retires_old_concept_and_reassigns_all_expressions():
    repo,service,source,target=await initial();second=uuid4();repo.sources[str(second)]={'kind':'item_type'}
    await link(service,second,target);before=await service.snapshot()
    change=DictionaryChangeSet(baseline_checksum=before['checksum'],
        reviewed_source_sha256=['a'*64],
        definitions=[DefinitionChange(definition=item('rated_inverter')),DefinitionChange(definition=item('special_inverter'))],
        retire_concept_ids=[target['concept_id']],
        mappings=[MappingChange(source_entry_id=source,target_key='rated_inverter',rationale='해당 원문은 분리한 첫 번째 물품 유형에 해당합니다.'),
                  MappingChange(source_entry_id=second,target_key='special_inverter',rationale='해당 원문은 분리한 두 번째 물품 유형에 해당합니다.')],
        rationale='서로 다른 의미의 원문을 분리하고 이전의 포괄 개념을 중단합니다.')
    await service.apply_changes('maintenance_split',change,actor='policy:test')
    current=await service.snapshot();rows=resolve_snapshot(current,[source,second])['items']
    assert {r['concept_key'] for r in rows}=={'rated_inverter','special_inverter'}
    assert all(r['status']=='resolved' for r in rows)
    assert repo.definitions[0]['status']=='deprecated'


async def test_snapshot_tampering_is_rejected():
    _,service,source,_=await initial();snapshot=await service.snapshot()
    snapshot['concepts'][0]['content']['preferred_name']='modified'
    with pytest.raises(ValueError,match='checksum'):
        resolve_snapshot(snapshot,[source])


async def test_merge_retires_duplicate_and_keeps_target_identity_without_rewriting_unchanged_mapping():
    repo,service,source,target=await initial();other=await approved(service,item('duplicate'))
    second=uuid4();repo.sources[str(second)]={'kind':'item_type'};await link(service,second,other)
    before=await service.snapshot();original_mapping=repo.links[0]['mapping_id']
    change=DictionaryChangeSet(baseline_checksum=before['checksum'],retire_concept_ids=[other['concept_id']],
        reviewed_source_sha256=['a'*64],
        mappings=[MappingChange(source_entry_id=id,target_key='inverter',rationale='다수 문서의 의미가 동일한 대표 정의로 재판정됐습니다.') for id in [source,second]],
        rationale='중복 개념을 대표 개념으로 통합하며 원문별 매핑 근거를 보존합니다.')
    result=await service.apply_changes('maintenance_merge',change,actor='policy:test')
    assert repo.links[0]['mapping_id']==original_mapping and repo.links[0]['status']=='approved'
    assert all(r['after']['concept_id']==str(target['concept_id']) for r in result['impact'])
    assert repo.definitions[1]['status']=='deprecated'
    assert len(result['affected_documents'])==2


async def test_revision_must_cover_every_classification_scope():
    repo,service,source,target=await initial();await link(service,source,target,classification_code='1234567890')
    before=await service.snapshot();change=revision(before,source,target)
    with pytest.raises(ValueError,match='reassessment'):
        preview_change_set(before,change)
    change.mappings.append(MappingChange(source_entry_id=source,target_key='inverter',classification_code='1234567890',
                                        rationale='이 분류에서 사용하던 매핑도 같은 정의로 재검증했습니다.'))
    assert (await service.preview_changes(change))['status']=='valid'


def test_maintenance_http_uses_authenticated_actor_and_rejects_body_actor():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from teoria.features.access_control.auth import AdminAuthorizer
    from teoria.features.semantic_modeling.goods_dictionary.admin_router import create_goods_dictionary_router
    from teoria.settings import Settings
    repo=ChangeRepository();service=GoodsMeaningService(repository=repo)
    authorizer=AdminAuthorizer(Settings(admin_auth_mode='bearer',admin_api_token='fixture-token',
        admin_api_actor='system:authenticated',admin_api_roles='ontology_owner'))
    app=FastAPI();app.include_router(create_goods_dictionary_router(None,authorizer,service))
    with TestClient(app) as client:
        headers={'Authorization':'Bearer fixture-token'};base='/v1/admin/goods/dictionary'
        assert client.get(base+'/snapshot').status_code==401
        snapshot=client.get(base+'/snapshot',headers=headers).json()
        payload=DictionaryChangeSet(baseline_checksum=snapshot['checksum'],rationale='소유 권한을 가진 인증 주체의 변경 작업입니다.').model_dump(mode='json')
        assert client.post(base+'/maintenance/maintenance_http',headers=headers,json={**payload,'actor':'fake'}).status_code==422
        result=client.post(base+'/maintenance/maintenance_http',headers=headers,json=payload)
        assert result.status_code==200 and result.json()['status']=='applied'
        assert repo.operations['maintenance_http']['actor']=='system:authenticated'


async def test_owner_revision_requires_reassessment_of_dependent_characteristic_mapping():
    from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import ConceptDefinition
    repo,service,source,target=await initial();attribute=uuid4()
    repo.sources[str(attribute)]={'kind':'characteristic','owner_entry_id':source}
    definition=ConceptDefinition(key='rated_power',kind='characteristic',preferred_name='정격출력',
        definition='명시된 정격 조건에서 해당 인버터가 출력하는 전력의 크기.',value_kind='number',
        applicable_item_type_ids=[target['concept_id']],quantity_dimension='power',canonical_unit='kW',allowed_units=['kW'],
        references=['source:fixture'])
    characteristic=await approved(service,definition)
    await link(service,attribute,characteristic,owner_concept_id=target['concept_id'])
    before=await service.snapshot();change=revision(before,source,target)
    assert (await service.preview_changes(change))['reason']=='affected_source_mappings_require_reassessment'
    change.mappings.append(MappingChange(source_entry_id=attribute,target_key='rated_power',owner_key='inverter',
                                        rationale='물품 정의의 개정 후 해당 속성의 귀속과 의미도 재판정했습니다.'))
    assert (await service.preview_changes(change))['status']=='valid'


async def test_rechecking_one_expression_does_not_skip_its_unreviewed_historical_documents():
    repo,service,source,target=await initial();before=await service.snapshot();change=revision(before,source,target)
    change.reviewed_source_sha256=[]
    preview=await service.preview_changes(change)
    assert preview['status']=='blocked' and preview['reason']=='affected_historical_documents_require_reassessment'
    with pytest.raises(ValueError,match='historical_documents'):
        await service.apply_changes('maintenance_unreviewed',change,actor='policy:test')
    assert await service.snapshot()==before
