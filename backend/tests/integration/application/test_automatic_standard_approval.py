"""Real API/SQL/file integration for approval; the extraction input is a fixture."""
import os
from pathlib import Path
from uuid import uuid4
import httpx
import psycopg
import pytest
from fastapi import FastAPI

from teoria.settings import Settings
from teoria.platform.access_control.auth import AdminAuthorizer
from teoria.integrations.application_database import apply_migrations
from teoria.platform.ontology.authoring.service import OntologyAuthoringService
from teoria.domains.goods.expression_links.expression_link_service import ExpressionLinkService
from teoria.domains.goods.expression_links.snapshot_contracts import approved_dictionary_snapshot
from teoria.domains.goods.expression_links.admin_router import create_goods_dictionary_router
from teoria.domains.goods.expression_links.registration_service import ExpressionRegistrationService
from teoria.domains.goods.normalization.processing_criteria_service import ApplicationStandardsService
from teoria.domains.goods.normalization.processing_criteria_repository import ApplicationStandardsRepository
from teoria.domains.goods.normalization.processing_criteria_router import create_application_standards_router
from teoria.domains.goods.data_processing.queries import ProcessingQueries
from teoria.domains.goods.data_processing.storage.artifact_reader import verified_artifact
from teoria.domains.goods.data_processing.storage.run_repository import SpecificationRepository
from teoria.domains.goods.data_processing.storage.artifact_store import artifact_store
from teoria.domains.goods.contracts import SpecificationRun, StandardArtifact, RunResult
from teoria.domains.goods.workflows import processing_criteria_approval as automatic
import teoria.domains.goods.authoring_client as client_module

URL=os.getenv('TEORIA_TEST_APP_DATABASE_URL')
DATA_URL=os.getenv('TEORIA_TEST_PIPELINE_DATABASE_URL')
pytestmark=pytest.mark.skipif(not URL or not DATA_URL,reason='isolated Application/Data DBs required')


async def test_automatic_approval_is_idempotent_and_records_the_verified_principal(tmp_path,monkeypatch):
    await apply_migrations(URL,Path('backend/migrations/application'))
    async with await psycopg.AsyncConnection.connect(DATA_URL) as conn:
        await conn.execute('CREATE SCHEMA IF NOT EXISTS public_procurement')
        exists=await (await conn.execute("SELECT to_regclass('public_procurement.specification_processing_runs')")).fetchone()
        if exists[0] is None:
            for prefix in ('090','091','104'):
                await conn.execute(next(Path('backend/migrations/data').glob(prefix+'*.sql')).read_text())
    meanings=ExpressionLinkService(URL,ontology_authoring=OntologyAuthoringService(URL))
    snapshot=await meanings.snapshot()
    processing=ProcessingQueries(DATA_URL)
    releases=ApplicationStandardsRepository(URL)
    async def read(reference):return await verified_artifact(reference,tmp_path)
    service=ApplicationStandardsService(releases,processing,meanings,read,lambda:artifact_store(tmp_path.as_uri()))
    app=FastAPI()
    auth=AdminAuthorizer(Settings(admin_auth_mode='bearer',admin_api_token='fixture-token',admin_api_actor='verified:automatic-worker',admin_api_roles='ontology_owner'))
    app.include_router(create_application_standards_router(service,auth))
    app.include_router(create_goods_dictionary_router(ExpressionRegistrationService(URL),auth,meanings))
    standard=StandardArtifact(version='fixture_source_literal',classification_code='4321150102',
        definitions=[{'id':'source_literal_test','label':'원문 값'}],bindings=[{
            'target_types':['equipment:fixture'],'property_key':'length','unit_context':'mm',
            'data_type':'number','role':'requirement_candidate','semantic_scope':'per_item',
            'properties':[{'property_id':'source_literal_test','rule_kind':'source_literal'}]}])
    async with artifact_store(tmp_path.as_uri()) as store:
        std=await store.put('standard.json',standard.model_dump_json().encode())
        dictionary=await store.put('dictionary_standard.json',approved_dictionary_snapshot(snapshot).model_dump_json().encode())
    run='automatic_'+uuid4().hex
    request=SpecificationRun(run_id=run,mode='standard_management',classification_code='4321150102',artifact_root=tmp_path.as_uri(),
        auto_approve_application_standard=True,documents=[{'document_id':'doc','filename':'fixture.pdf','source_uri':(tmp_path/'fixture.pdf').as_uri(),'sha256':'c'*64}])
    data=SpecificationRepository(DATA_URL)
    await data.start(request,'a'*64)
    result=RunResult(run_id=run,status='partial',summary={"quality":{"successful_documents":1,"validation_errors":0,"failed_document_ratio":0,"held_attribute_ratio":0,"accepted_attributes":1,"model_requested":None}},document_results=[],artifacts=[std,dictionary],
        standard={'uri':std.uri,'sha256':std.sha256})
    await data.complete(result)
    actual=client_module.GoodsAuthoringClient
    monkeypatch.setattr(automatic,'GoodsAuthoringClient',lambda:actual(base_url='http://isolated-api',token='fixture-token',transport=httpx.ASGITransport(app=app)))
    monkeypatch.setattr(automatic.SpecificationRepository,'from_environment',lambda:data)
    first=await automatic.approve_application_standard.fn(request,result)
    second=await automatic.approve_application_standard.fn(request,result)
    assert first.summary==second.summary
    approval=first.summary['automatic_application_standard']
    assert approval['status']=='approved' and approval['approved_by']=='verified:automatic-worker'
    assert (await releases.get(approval['release_id']))['source_run_id']==run
    page=await releases.list(0,100)
    assert sum(row['source_run_id']==run for row in page['items'])==1
    assert (await processing.detail(run))['run']['summary']['automatic_application_standard']==approval
