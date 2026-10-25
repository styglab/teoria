"""Real Prefect + PostgreSQL + S3 integration; no production resources are provisioned here."""
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
import psycopg
import pytest
from prefect.testing.utilities import prefect_test_harness
from teoria_pipelines.domains.public_procurement.specification_processing.storage.artifact_store import artifact_store,S3ArtifactStore
from teoria_pipelines.domains.public_procurement.specification_processing.flows import document_processing_flow,standard_management_flow
from teoria_pipelines.domains.public_procurement.specification_processing.models import StandardArtifact,ContextBinding,PropertyBinding

DATABASE_URL=os.getenv('TEORIA_TEST_SPECIFICATION_DATABASE_URL')
ARTIFACT_ROOT=os.getenv('TEORIA_TEST_SPECIFICATION_ARTIFACT_ROOT')
pytestmark=pytest.mark.skipif(not DATABASE_URL or not ARTIFACT_ROOT,reason='isolated specification PostgreSQL/S3 test configuration is required')

def manifest(tmp_path,run_id):
    source=tmp_path/'specification.hwp';source.write_bytes(b'integration source fixture')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    corpus={'classification_code':'4321150102','documents':[{'document_id':'doc_1','source':{'path':'sources/doc_1.hwp','sha256':digest},'parser':{'version':'fixture'},
        'parsed_document':{'nodes':[{'node_id':'n','kind':'paragraph','text':'CPU 16core'}]},
        'entities':[{'id':'root','name':'서버','kind':'equipment'},{'id':'cpu','name':'CPU','kind':'equipment'}],
        'relations':[{'id':'r','source_id':'cpu','target_id':'root','kind':'component_of'}],
        'attributes':[{'id':'a','subject_ids':['cpu'],'property_key':'core_count','data_type':'number','value_raw':'16','unit_raw':'core','operator':'eq','operator_raw':None,'qualifiers_raw':[],
            'semantic_role':'requirement_candidate','semantic_scope':'per_processor','evidence':{'node_id':'n'}}],
        'extraction_status':'extracted'}],'unavailable_documents':[]}
    checkpoint=tmp_path/'checkpoint.json';checkpoint.write_text(json.dumps(corpus))
    standard=StandardArtifact(rule_set='server',version='integration_v1',classification_code='4321150102',definitions=[{'id':'cpu_cores_per_processor','label':'CPU당 코어 수'}],bindings=[ContextBinding(target_types=['processor'],property_key='core_count',unit_context='core',data_type='number',role='requirement_candidate',semantic_scope='per_processor',properties=[PropertyBinding(property_id='cpu_cores_per_processor',rule_kind='server_literal')])])
    seed=tmp_path/'standard.json';seed.write_text(standard.model_dump_json())
    return {'run_id':run_id,'mode':'document_processing','classification_code':'4321150102','artifact_root':ARTIFACT_ROOT,
        'documents':[{'document_id':'doc_1','notice_number':'integration_notice','source_uri':source.as_uri(),'filename':source.name,'sha256':digest}],
        'extraction_checkpoint':{'uri':checkpoint.as_uri(),'sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest()},
        'standard':{'uri':seed.as_uri(),'sha256':hashlib.sha256(seed.read_bytes()).hexdigest()}}

async def run_row(run_id):
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as connection:
        return await(await connection.execute('SELECT status,summary,error_code FROM public_procurement.specification_processing_runs WHERE run_id=%s',(run_id,))).fetchone()

async def test_real_prefect_s3_postgres_completion_retry_and_draft(tmp_path,monkeypatch):
    monkeypatch.setenv('TEORIA_PIPELINE_DATA_DATABASE_URL',DATABASE_URL)
    request=manifest(tmp_path,'integration_'+uuid4().hex)
    with prefect_test_harness(server_startup_timeout=60):
        result=await document_processing_flow(request)
        assert result.status=='completed' and result.summary['applied']==1
        assert (await run_row(result.run_id))[0]=='completed'
        async with artifact_store(ARTIFACT_ROOT) as store:
            for ref in result.artifacts:
                assert hashlib.sha256(await store.get(ref.key)).hexdigest()==ref.sha256
        # Completed replay does not re-read the input or call the extraction backend.
        source=Path(request['documents'][0]['source_uri'].removeprefix('file://'));original=source.read_bytes();source.unlink()
        replay=await document_processing_flow(request)
        assert replay.model_dump()==result.model_dump()
        source.write_bytes(original)
        # A changed request cannot overwrite a completed execution.
        changed={**request,'model_timeout_seconds':181}
        with pytest.raises(ValueError,match='different inputs'):
            await document_processing_flow(changed)
        assert (await run_row(result.run_id))[0]=='completed'
        # An upload failure leaves the execution failed, never partially completed.
        retry={**request,'run_id':'retry_'+uuid4().hex}
        original_put=S3ArtifactStore.put
        async def fail_normalization(self,key,data,media_type='application/json'):
            if key.endswith('/normalized.json'):raise OSError('injected object storage failure')
            return await original_put(self,key,data,media_type)
        with monkeypatch.context() as patch:
            patch.setattr(S3ArtifactStore,'put',fail_normalization)
            with pytest.raises(OSError,match='injected'):
                await document_processing_flow(retry)
        failed=await run_row(retry['run_id']);assert failed[0]=='failed' and failed[1]=={}
        source.unlink();checkpoint=Path(request['extraction_checkpoint']['uri'].removeprefix('file://'));saved=checkpoint.read_bytes();checkpoint.unlink()
        recovered=await document_processing_flow(retry)
        assert recovered.status=='completed' and recovered.summary['reused_extraction'] is True
        source.write_bytes(original);checkpoint.write_bytes(saved)
        # Management produces a separate immutable draft version, not a published ontology.
        management={**request,'mode':'standard_management','run_id':'management_'+uuid4().hex}
        drafted=await standard_management_flow(management)
        assert drafted.status=='completed'
        async with artifact_store(ARTIFACT_ROOT) as store:
            ref=next(a for a in drafted.artifacts if '/standards/' in a.key)
            payload=json.loads(await store.get(ref.key))
        assert payload['published'] is False and payload['status']=='pipeline_selected_draft'
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as connection:
            count=await(await connection.execute('SELECT count(*) FROM public_procurement.specification_processing_artifacts WHERE run_id=%s',(drafted.run_id,))).fetchone()
            assert count[0]==len(drafted.artifacts)
            # The metadata tables contain counts/references, never the source document body.
            row=await(await connection.execute('SELECT summary::text FROM public_procurement.specification_processing_runs WHERE run_id=%s',(drafted.run_id,))).fetchone()
            assert 'CPU 16core' not in row[0]
