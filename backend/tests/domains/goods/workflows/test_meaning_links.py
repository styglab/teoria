"""The active v2 path uses approved expression mappings, never alias-only fixtures."""
from copy import deepcopy
from uuid import UUID, uuid4
from unittest.mock import AsyncMock
import hashlib
import json

import pytest
from fastapi import FastAPI
import httpx

from backend.tests.domains.goods.expression_links.test_service import MemoryRepository
from teoria.domains.goods.expression_links.expression_link_service import ExpressionLinkService
from teoria.domains.goods.expression_links.expression_contracts import expression_snapshot
from teoria.domains.goods.expression_links.registration_service import ExpressionRegistrationService
from teoria.domains.goods.expression_links.admin_router import create_goods_dictionary_router
from teoria.domains.goods.expression_links.snapshot_contracts import MeaningDecision
from teoria.domains.goods.normalization.meaning_proposals.expression_alignment import pinned_meanings
from teoria.domains.goods.normalization.contracts import checksum


class LinkRepository(MemoryRepository):
    def __init__(self, publication):
        super().__init__()
        self.links = {}
        self.publications = [publication]

    async def all_sources(self, conn):
        return list(self.entries_by_key.values())

    async def mappings(self, conn):
        return list(self.links.values())

    async def published_versions(self, conn):
        return [dict(ontology_version_id=a['ontology']['version_id'],checksum=a['ontology']['checksum'])
                for a in self.publications]

    async def source_evidence(self, conn, entry_id):
        return [e.model_dump(mode='json') for _,candidate,result,*_ in self.decisions
                if str(result.get('entry_id'))==str(entry_id) for e in candidate.evidence]

    async def equivalent_mapping(self, conn, proposal):
        expected=proposal.model_dump(mode='json',exclude={'ontology','rationale'})
        return next((r for r in self.links.values() if r['status'] in {'draft','approved'}
            and r['ontology_version_id']==str(proposal.ontology.version_id)
            and r['ontology_checksum']==proposal.ontology.checksum
            and all(r.get(k)==v for k,v in expected.items())),None)

    async def add_ontology_mapping(self, conn, proposal, evidence, actor):
        row = {**proposal.model_dump(mode='json',exclude={'ontology'}),
            'mapping_id': str(uuid4()), 'ontology_version_id': str(proposal.ontology.version_id),
            'ontology_checksum': proposal.ontology.checksum, 'status':'draft', 'created_by':actor}
        self.links[row['mapping_id']] = row
        return row

    async def mapping(self, conn, identifier):
        return self.links.get(str(identifier))

    async def set_status(self, conn, kind, identifier, status):
        self.links[str(identifier)]['status']=status

    async def meaning_event(self, conn, kind, identifier, action, actor, comment):
        self.events.append((kind,str(identifier),action,actor,comment))


def link_services(publication):
    repository = LinkRepository(publication)
    authoring = AsyncMock()
    async def artifact(version_id, **kwargs):
        entry=next((p for p in repository.publications if p['ontology']['version_id']==str(version_id)),None)
        if entry is None:return None
        return dict(content=entry['content'],checksum=entry['ontology']['checksum'],status='published')
    authoring.published_artifact.side_effect=artifact
    return repository, ExpressionRegistrationService(repository=repository), ExpressionLinkService(
        repository=repository,ontology_authoring=authoring)


async def approve_links(service, plan):
    for identifier in plan['mapping_ids']:
        await service.decide('mapping',UUID(identifier),MeaningDecision(action='approve',
            rationale='원문 표현과 게시 개념의 의미를 별도로 대조한 테스트 승인이다.'),actor='fixture:link-reviewer')



def inverter_case():
    from backend.tests.domains.goods.expression_links.test_ontology_dictionary import fixture
    snapshot=fixture()
    doc={'document_id':'inverter','source':{'sha256':'a'*64},'parser':{'version':'fixture'},
        'parsed_document':{'nodes':[{'node_id':'n','kind':'paragraph','text':'인버터 정격 출력 3 kW 이상'}]},
        'entities':[{'id':'root','name':'인버터','kind':'equipment','evidence':[{'node_id':'n'}]}],
        'attributes':[{'id':'power','subject_ids':['root'],'property_key':'parser_power','property_raw':'정격 출력',
            'data_type':'number','value_raw':'3','unit_raw':'kW','operator':'gte','operator_raw':'이상',
            'qualifiers_raw':[],'semantic_role':'requirement_candidate','semantic_scope':'per_item','evidence':{'node_id':'n'}}],
        'relations':[]}
    return snapshot,{'classification_code':'1234567890','documents':[doc]}


async def test_frozen_v2_application_never_registers_or_reads_live_meanings(tmp_path,monkeypatch):
    from teoria.domains.goods.contracts import SpecificationRun
    from teoria.domains.goods.normalization.meaning_proposals import expression_alignment as alignment
    snapshot,corpus=inverter_case();before=deepcopy(corpus)
    path=tmp_path/'snapshot.json';path.write_text(snapshot.model_dump_json())
    from teoria.domains.goods.contracts import StandardArtifact
    standard=tmp_path/'standard.json';standard.write_text(StandardArtifact(version='fixture',classification_code='1234567890',definitions=[],bindings=[]).model_dump_json())
    request=SpecificationRun(run_id='frozen_inverter',mode='document_processing',classification_code='1234567890',
        artifact_root=(tmp_path/'artifacts').as_uri(),documents=[{'document_id':'inverter','filename':'i.pdf','source_uri':'file:///source.pdf'}],
        standard={'uri':standard.as_uri(),'sha256':hashlib.sha256(standard.read_bytes()).hexdigest()},
        dictionary_standard={'uri':path.as_uri(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    def forbidden():raise AssertionError('fixed application must not call Admin API')
    monkeypatch.setattr(alignment,'GoodsAuthoringClient',forbidden)
    output=await alignment.align_dictionary(request,corpus,{'uri':'file:///source.json','sha256':'a'*64})
    observation=output['meaning_alignment']['documents'][0]['attributes'][0]
    assert observation['meaning_status']=='resolved' and observation['value_raw']=='3' and observation['unit_raw']=='kW'
    assert corpus==before
    assert output==await alignment.align_dictionary(request,corpus,{'uri':'file:///source.json','sha256':'a'*64})
    assert output['result']['approval_mode']=='frozen_snapshot'


def test_exact_snapshot_matching_does_not_register_unknown_or_ambiguous_sources():
    snapshot,corpus=inverter_case()
    meanings,_=pinned_meanings(corpus,snapshot)
    assert meanings['documents'][0]['attributes'][0]['meaning_status']=='resolved'
    sources=deepcopy(snapshot.sources)
    duplicate=deepcopy(next(s for s in sources if s['kind']=='characteristic'));duplicate['entry_id']=str(uuid4())
    changed=expression_snapshot(snapshot.ontologies,snapshot.mappings,[*sources,duplicate])
    meanings,_=pinned_meanings(corpus,changed)
    assert meanings['documents'][0]['attributes'][0]['meaning_status']=='unresolved'


def test_explicit_publication_pin_avoids_ambiguous_old_and_new_versions():
    from teoria.domains.goods.expression_links.expression_contracts import expression_snapshot_for_publication
    snapshot,corpus=inverter_case()
    newer=deepcopy(snapshot.ontologies[0]);newer['ontology']['version_id']=str(uuid4())
    combined=expression_snapshot([*snapshot.ontologies,newer],[*snapshot.mappings,
        *[{**m,'mapping_id':str(uuid4()),'ontology_version_id':newer['ontology']['version_id']} for m in snapshot.mappings]],snapshot.sources)
    assert pinned_meanings(corpus,combined)[0]['documents'][0]['entities'][0]['meaning_status']=='held'
    chosen=expression_snapshot_for_publication(combined,newer['ontology'])
    row=pinned_meanings(corpus,chosen)[0]['documents'][0]['attributes'][0]
    assert row['meaning_status']=='resolved' and row['ontology']==newer['ontology']


async def test_pipeline_applies_approved_document_interpretations_without_changing_extraction(tmp_path,monkeypatch):
    from backend.tests.domains.goods.normalization.test_interpretations import meaning_case
    from teoria.domains.goods.normalization.application.meaning_application import ApprovedInterpretation
    from teoria.domains.goods.contracts import SpecificationRun
    from teoria.domains.goods.workflows import tasks
    request,result,package,publication,approval=meaning_case()
    result_path=tmp_path/'result.json';result_path.write_text(json.dumps(result))
    body=approval.model_dump(mode='json',exclude={'checksum'})
    body['request']['result']={'uri':result_path.as_uri(),'sha256':hashlib.sha256(result_path.read_bytes()).hexdigest()}
    approval=ApprovedInterpretation(**body,checksum=checksum(body))
    doc=result['extracted']['documents'][0]
    corpus={'classification_code':None,'documents':[doc],'unavailable_documents':[]}
    (tmp_path/'extracted.json').write_text(json.dumps(corpus));before=(tmp_path/'extracted.json').read_bytes()
    package_path=tmp_path/'package.json';package_path.write_text(package.model_dump_json())
    client=AsyncMock();client.ontology_publication.return_value=publication
    client.interpretation_approval.return_value=approval.model_dump(mode='json')
    context=AsyncMock();context.__aenter__.return_value=client
    monkeypatch.setattr(tasks,'GoodsAuthoringClient',lambda:context,raising=False)
    import teoria.domains.goods.authoring_client as authoring
    monkeypatch.setattr(authoring,'GoodsAuthoringClient',lambda:context)
    run=SpecificationRun(run_id='approved_interpretation_run',mode='document_processing',artifact_root=(tmp_path/'objects').as_uri(),
        use_expression_dictionary=False,interpretation_revision_ids=[approval.revision_id],
        standard={'uri':package_path.as_uri(),'sha256':hashlib.sha256(package_path.read_bytes()).hexdigest()},
        documents=[{'document_id':'d','filename':'d.pdf','source_uri':'file:///d.pdf'}])
    # Task imports the owned client at call time.
    monkeypatch.setattr(tasks,'GoodsAuthoringClient',lambda:context,raising=False)
    await tasks.select_and_map_standard.fn(run,str(tmp_path),dictionary=None)
    normalized=json.loads((tmp_path/'normalized.json').read_bytes())
    document=normalized['documents'][0]
    assert len(document['requirements'])==3 and len(document['compositions'])==1
    assert normalized['summary']['applied']==3 and normalized['summary']['applied_composition']==1
    assert (tmp_path/'extracted.json').read_bytes()==before
    row=next(r for r in document['requirements'] if r['semantic_observation']['source']['attribute_id']=='limit')
    assert row['semantic_scope']=='per_socket' and row['semantic_observation']['source']['original_scope']=='support_limit'


def test_stage_versions_ignore_unrelated_authoring_code_and_track_actual_consumed_policies(tmp_path,monkeypatch):
    import teoria.domains.goods.processor_revision as revisions
    monkeypatch.setattr(revisions,'__file__',str(tmp_path/'processor_revision.py'))
    app=tmp_path/'normalization/application';app.mkdir(parents=True)
    (app/'profile_application.py').write_text('policy = 1')
    api=tmp_path/'normalization/meaning_proposals';api.mkdir()
    (api/'interpretation_router.py').write_text('api = 1')
    extraction=tmp_path/'data_processing/extraction';extraction.mkdir(parents=True)
    (extraction/'rule.py').write_text('source_rule = 1')
    for relative in ['data_processing/flows.py','workflows/specifications.py','workflows/processing_quality.py','workflows/processing_status.py']:
        path=tmp_path/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('policy = 1')
    before=revisions.workflow_stage_versions();processing=revisions.processing_revision();source=revisions.extraction_revision()
    (api/'interpretation_router.py').write_text('api = 2')
    assert revisions.workflow_stage_versions()==before and revisions.processing_revision()==processing
    (app/'profile_application.py').write_text('policy = 2')
    changed=revisions.workflow_stage_versions()
    assert changed['application']!=before['application'] and changed['extraction']==before['extraction']
    assert revisions.extraction_revision()==source
    (extraction/'rule.py').write_text('source_rule = 2')
    assert revisions.extraction_revision()!=source
