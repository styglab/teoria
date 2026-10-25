"""Opt-in SQL checks in an isolated Data DB, independent of Prefect/S3 services."""
import os
from pathlib import Path
from uuid import uuid4
import psycopg
import pytest
from teoria_pipelines.domains.public_procurement.specification_processing.standard_workflow_repository import StandardWorkflowRepository

DATABASE_URL=os.getenv('TEORIA_TEST_PIPELINE_DATABASE_URL')
pytestmark=pytest.mark.skipif(not DATABASE_URL,reason='isolated Data DB required')


@pytest.fixture(autouse=True)
async def prepare_workflow_schema():
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        await conn.execute('CREATE SCHEMA IF NOT EXISTS public_procurement')
        exists=await (await conn.execute("SELECT to_regclass('public_procurement.specification_standard_workflows')")).fetchone()
        if exists[0] is None:
            await conn.execute((Path(__file__).parents[2]/'database/migrations/092_specification_standard_workflows.sql').read_text())


async def test_workflow_leases_resume_and_completed_replay():
    repository=StandardWorkflowRepository(DATABASE_URL);key='test_'+uuid4().hex
    state,lease=await repository.claim(key,'a'*64)
    assert state=={} and lease
    with pytest.raises(ValueError,match='active execution'):await repository.claim(key,'a'*64)
    await repository.save(key,lease,{'phase':'entities'},status='awaiting_approval')
    state,new_lease=await repository.claim(key,'a'*64)
    assert state=={'phase':'entities'} and new_lease!=lease
    with pytest.raises(ValueError,match='lease lost'):await repository.renew(key,lease)
    await repository.save(key,new_lease,{'phase':'entities','result':{'status':'partial'}},status='completed')
    state,replay=await repository.claim(key,'a'*64)
    assert replay is None and state['result']['status']=='partial'
    with pytest.raises(ValueError,match='different inputs'):await repository.claim(key,'b'*64)


async def test_expired_worker_cannot_write_after_takeover():
    repository=StandardWorkflowRepository(DATABASE_URL);key='test_'+uuid4().hex
    _,old=await repository.claim(key,'a'*64)
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        await conn.execute("UPDATE public_procurement.specification_standard_workflows SET lease_until=now()-interval '1 second' WHERE workflow_id=%s",(key,))
    _,fresh=await repository.claim(key,'a'*64)
    with pytest.raises(ValueError,match='lease lost'):await repository.save(key,old,{'incorrect':True})
    await repository.save(key,fresh,{'result':{'status':'completed'}},status='completed')
