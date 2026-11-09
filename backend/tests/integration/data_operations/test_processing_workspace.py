"""Replay inputs and operational counters against an explicitly isolated Data DB."""
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from teoria.domains.goods.contracts import SpecificationRun, RunResult
from teoria.domains.goods.data_processing.storage.run_repository import SpecificationRepository
from teoria.domains.goods.data_processing.queries import ProcessingQueries

URL = os.getenv('TEORIA_TEST_PIPELINE_DATABASE_URL')
pytestmark = pytest.mark.skipif(not URL, reason='isolated Data DB required')


async def test_verified_original_hashes_and_operation_counts(tmp_path):
    async with await psycopg.AsyncConnection.connect(URL) as conn:
        await conn.execute('CREATE SCHEMA IF NOT EXISTS public_procurement')
        exists = await (await conn.execute("SELECT to_regclass('public_procurement.specification_processing_runs')")).fetchone()
        if exists[0] is None:
            await conn.execute(Path('backend/migrations/data/090_specification_processing_runs.sql').read_text())
            await conn.execute(Path('backend/migrations/data/091_specification_processing_schema_usage.sql').read_text())
            await conn.execute(Path('backend/migrations/data/104_specification_document_catalog.sql').read_text())
    run_id = 'workspace_' + uuid4().hex
    repository = SpecificationRepository(URL)
    workspace = ProcessingQueries(URL)
    request = SpecificationRun(run_id=run_id, mode='standard_management', classification_code='4321150102',
        artifact_root=tmp_path.as_uri(), documents=[{'document_id': 'doc_1', 'filename': 'original.pdf',
            'source_uri': (tmp_path/'original.pdf').as_uri()}])
    try:
        await repository.start(request, 'a'*64)
        assert (await workspace.inputs(run_id))[0]['sha256'] is None
        quality={'schema_version':1,'source_group_sha256':'c'*64,'model_requested':'fixture-pinned',
            'parser_versions':['fixture'],'classification_code':'4321150102','accepted_attributes':2,
            'quarantined_attributes':1,'validation_errors':1,'applied_attributes':1,'held_attributes':1}
        await repository.complete(RunResult(run_id=run_id, status='partial', artifacts=[], summary={
            'quality_evaluation': 'not_attached','processor_revision':'fixture_numeric_guard','quality':quality},
            document_results=[{'document_id': 'doc_1', 'status': 'partial', 'source_sha256': 'b'*64, 'result_summary': {}}]))
        inputs = await workspace.inputs(run_id)
        assert inputs[0]['sha256'] == 'b'*64
        assert inputs[0]['source_uri'] == request.documents[0].source_uri
        assert (await workspace.detail(run_id))['run']['status'] == 'partial'
        await repository.record_application_standard(run_id, {'status':'approved','release_id':'test-release'})
        assert (await workspace.detail(run_id))['run']['summary']['automatic_application_standard']['release_id'] == 'test-release'
        metrics = await workspace.operations(7)
        assert metrics['runs']['partial'] >= 1 and metrics['documents']['partial'] >= 1
        assert metrics['quality_evaluation'] == 'not_attached'
        version=next(v for v in metrics['quality_versions'] if v['processor_revision']=='fixture_numeric_guard')
        assert version['validation_errors']>=1 and version['measured_runs']>=1
        assert (await repository.previous_quality('another_run',quality))['run_id']==run_id
        assert await repository.previous_quality('another_run',{**quality,'model_requested':'different'}) is None
        async with await psycopg.AsyncConnection.connect(URL) as conn:
            await conn.execute('SET LOCAL ROLE teoria_runtime')
            assert await (await conn.execute('SELECT source_sha256 FROM public_procurement.specification_processing_inputs WHERE run_id=%s', (run_id,))).fetchone() == (None,)
    finally:
        async with await psycopg.AsyncConnection.connect(URL) as conn:
            for table in ('specification_processing_inputs', 'specification_processing_documents', 'specification_processing_artifacts', 'specification_processing_runs'):
                await conn.execute(f'DELETE FROM public_procurement.{table} WHERE run_id=%s', (run_id,))
