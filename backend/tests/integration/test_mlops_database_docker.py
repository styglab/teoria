"""Opt-in isolated PostgreSQL migration and serving history/serialization verification."""
import io
import os
from pathlib import Path
import tarfile
import time
import uuid

import pytest

pytestmark=pytest.mark.skipif(os.getenv('TEORIA_TEST_MODEL_EXECUTION_DOCKER')!='1',reason='explicit Docker MLOps DB test')


def test_mlops_migration_history_and_serialization():
    docker=pytest.importorskip('docker');client=docker.from_env()
    name='mlops-db-test-'+uuid.uuid4().hex[:10]
    network=client.networks.create(name)
    containers=[]
    try:
        database=client.containers.run('postgres:17',detach=True,network=network.name,environment={'POSTGRES_PASSWORD':'synthetic-test-only','POSTGRES_DB':'mlops'},name=name+'-db')
        containers.append(database)
        for _ in range(60):
            if database.exec_run(['pg_isready','-U','postgres','-d','mlops']).exit_code==0:break
            time.sleep(.2)
        else:pytest.fail('isolated PostgreSQL startup failed')
        helper=client.containers.run(os.getenv('TEORIA_MODEL_TEST_BASE_IMAGE','teoria-platform-admin:latest'),['python','-c','import time;time.sleep(300)'],detach=True,network=network.name,user='root')
        containers.append(helper)
        root=Path(__file__).resolve().parents[3]
        archive=io.BytesIO()
        with tarfile.open(fileobj=archive,mode='w') as tar:
            for path in (root/'backend/migrations/application').glob('*.sql'):
                tar.add(path,arcname='migrations/'+path.name)
            tar.add(root/'backend/src/teoria/platform/mlops/deployments.py',arcname='mlops_deployments.py')
        archive.seek(0);helper.put_archive('/tmp',archive.read())
        code=r'''
import asyncio,importlib.util,sys
from pathlib import Path
from teoria.integrations.application_database.migrations import apply_migrations
s=importlib.util.spec_from_file_location('mlops_deployments','/tmp/mlops_deployments.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
async def main():
    url='postgresql://postgres:synthetic-test-only@'+sys.argv[1]+':5432/mlops'
    applied=await apply_migrations(url,Path('/tmp/migrations'))
    assert '026_mlops_deployments.sql' in applied
    assert await apply_migrations(url,Path('/tmp/migrations'))==[]
    repo=m.DeploymentRepository(url)
    first={'deployment_id':'test','model_version':1}
    second={'deployment_id':'test','model_version':2}
    await repo.record(first,'docker','authenticated:operator','run-1','ready','http://test:8080')
    await repo.record(second,'docker','authenticated:operator','run-2','ready','http://test:8080')
    item=await repo.get('test')
    assert item['specification']==second and item['previous_specification']==first
    assert item['requested_by']=='authenticated:operator' and item['prefect_run_id']=='run-2'
    acquired=asyncio.Event()
    async def contender():
        async with repo.lock('test'):acquired.set()
    async with repo.lock('test'):
        pending=asyncio.create_task(contender())
        await asyncio.sleep(.1)
        assert not acquired.is_set()
    await asyncio.wait_for(pending,5)
    await repo.stopped('test','authenticated:operator','run-stop')
    assert (await repo.list())[0]['status']=='stopped'
    print('All migrations, idempotency, prior serving version, audit actor and deployment lock verified')
asyncio.run(main())
'''
        result=helper.exec_run(['python','-c',code,database.name])
        assert result.exit_code==0,result.output.decode()
    finally:
        for container in reversed(containers):container.remove(force=True,v=True)
        network.remove();client.close()
