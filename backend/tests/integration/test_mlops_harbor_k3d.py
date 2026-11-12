"""Opt-in checks against an installed development Harbor and MLOps deployment.

Provision the standalone fixture image and scoped accounts before running this test.
Credentials are environment variables, never test parameters or report fields.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import ssl
import time
import uuid

import httpx
import pytest

from teoria.integrations.s3 import S3Client

pytestmark = pytest.mark.skipif(
    os.getenv('TEORIA_TEST_MLOPS_K3D') != '1', reason='explicit live Harbor/MLOps validation',
)


async def test_harbor_image_training_serving_and_rollback():
    suffix = uuid.uuid4().hex[:8]
    model_name = 'linear_validation_' + suffix
    deployment_id = 'validation-' + suffix
    prefix = '/admin-api/v1/admin'
    url = os.environ['TEORIA_TEST_MLOPS_URL']
    token = os.environ['TEORIA_TEST_MLOPS_TOKEN']
    context = ssl.create_default_context(cafile=os.environ['TEORIA_TEST_MLOPS_CA_FILE'])
    report = {'model_name': model_name, 'deployment_id': deployment_id, 'runs': []}
    async with httpx.AsyncClient(base_url=url, verify=context, trust_env=False,
                                 headers={'Authorization': 'Bearer ' + token}, timeout=30) as api, \
            httpx.AsyncClient(trust_env=False) as object_http:
        store = S3Client(object_http, endpoint=os.environ['TEORIA_TEST_S3_ENDPOINT'],
                         access_key=os.environ['TEORIA_TEST_S3_ACCESS_KEY'],
                         secret_key=os.environ['TEORIA_TEST_S3_SECRET_KEY'])

        async def get(path, **kwargs):
            response = await api.get(prefix + path, **kwargs)
            response.raise_for_status()
            return response.json()

        async def workflow(name, execution, expected='COMPLETED'):
            response = await api.post(prefix + '/workflows/pipelines/' + name + '/runs',
                                      json={'idempotency_key': str(uuid.uuid4()), 'execution': execution})
            response.raise_for_status()
            run_id = response.json()['flow_run_id']
            deadline = time.monotonic() + 360
            while time.monotonic() < deadline:
                detail = await get('/workflows/runs/' + run_id)
                state = detail['run']['state_type']
                if state in {'COMPLETED', 'FAILED', 'CRASHED', 'CANCELLED'}:
                    report['runs'].append({'workflow': name, 'run_id': run_id, 'state': state})
                    print(name, state, run_id, flush=True)
                    assert state == expected, json.dumps(detail.get('logs', [])[-3:])
                    return run_id
                await asyncio.sleep(2)
            raise AssertionError('Workflow did not finish within the validation deadline: ' + run_id)

        async def prediction(expected):
            response = await api.post(prefix + '/model-operations/deployments/' + deployment_id + '/predict',
                                      json={'x': [3, 4]})
            response.raise_for_status()
            value = response.json()
            assert value['predictions'] == expected
            return value

        response = await api.get(prefix + '/image-registry/repositories', headers={'Authorization': ''})
        assert response.status_code == 401
        repository = os.getenv('TEORIA_TEST_MODEL_REPOSITORY', 'models/linear-validation')
        assert repository in (await get('/image-registry/repositories'))['items']
        manifest = await get('/image-registry/manifest', params={'repository': repository, 'reference': 'v1'})
        image = manifest['image']
        assert '@sha256:' in image
        report['image'] = image
        snapshot = json.dumps([{'x': x, 'y': 2 * x + 1} for x in range(20)]).encode()
        input_uri = 's3://teoria-training-data/validation/' + suffix + '/data.json'
        await store.put(input_uri, snapshot)
        results = []
        active = False
        try:
            for offset in (0, 5):
                output_uri = 's3://teoria-training-results/validation/' + suffix + '/' + str(offset) + '.json'
                run_id = await workflow('model-train', {
                    'image': image, 'command': ['python', '/app/model.py', 'train'],
                    'model_name': model_name, 'input_uri': input_uri,
                    'input_sha256': hashlib.sha256(snapshot).hexdigest(), 'output_uri': output_uri,
                    'parameters': {'offset': offset}, 'resources': {'cpu': 1, 'memory_mib': 1024, 'gpu': 0},
                    'timeout_seconds': 180,
                })
                result = json.loads(await store.get(output_uri))
                assert result['model_name'] == model_name
                logs = await store.get('s3://teoria-mlops/logs/' + run_id + '.txt')
                assert logs
                results.append(result)
            catalog = await get('/model-operations/models', params={'model_name': model_name})
            assert len(catalog['items']) == 2
            report['models'] = results
            first = {'deployment_id': deployment_id, 'model_name': model_name,
                     'model_version': results[0]['model_version'], 'model_sha256': results[0]['model_sha256'],
                     'image': image, 'command': ['python', '/app/model.py', 'serve'],
                     'resources': {'cpu': 1, 'memory_mib': 1024, 'gpu': 0}, 'readiness_timeout_seconds': 120}
            await workflow('model-deploy', first)
            active = True
            report['first_prediction'] = await prediction([7.0, 9.0])
            second = {**first, 'model_version': results[1]['model_version'], 'model_sha256': results[1]['model_sha256']}
            await workflow('model-deploy', second)
            report['second_prediction'] = await prediction([12.0, 14.0])
            await workflow('model-deploy', {**second, 'command': ['python', '-c', 'raise SystemExit(1)'],
                                            'readiness_timeout_seconds': 10}, expected='FAILED')
            report['failed_candidate_recovery'] = await prediction([12.0, 14.0])
            deployments = await get('/model-operations/deployments')
            record = next(item for item in deployments['items'] if item['deployment_id'] == deployment_id)
            assert record['health'] == 'ok'
            assert record['previous_specification']['model_version'] == results[0]['model_version']
            await workflow('model-deploy', record['previous_specification'])
            report['rollback_prediction'] = await prediction([7.0, 9.0])
            report['status'] = 'passed'
        finally:
            keep = os.getenv('TEORIA_TEST_KEEP_SERVING') == '1' and report.get('status') == 'passed'
            if active and not keep:
                await workflow('model-stop', {'deployment_id': deployment_id})
            path = os.getenv('TEORIA_TEST_MLOPS_REPORT')
            if path:
                Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
