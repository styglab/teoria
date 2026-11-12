"""Opt-in public-IP TLS, browser login and Registry authentication checks."""
import os
import ssl
from urllib.parse import urlsplit

import httpx
import pytest

pytestmark = pytest.mark.skipif(os.getenv('TEORIA_TEST_REMOTE_ACCESS') != '1', reason='explicit public IP access test')


async def test_public_ip_browser_login_and_registry_identity():
    platform = os.environ['TEORIA_TEST_MLOPS_URL']
    harbor = os.environ['TEORIA_TEST_HARBOR_URL']
    context = ssl.create_default_context(cafile=os.environ['TEORIA_TEST_MLOPS_CA_FILE'])
    async with httpx.AsyncClient(verify=context, trust_env=False, timeout=30) as client:
        response = await client.get(platform + '/health')
        assert response.status_code == 200
        response = await client.get(harbor + '/')
        assert response.status_code == 200
        assert 'text/html' in response.headers['content-type']
        client.headers.update({'Origin': harbor, 'Referer': harbor + '/'})
        body = {'principal': 'admin', 'password': os.environ['TEORIA_TEST_HARBOR_PASSWORD']}
        response = await client.post(harbor + '/c/login', data=body)
        if response.status_code == 403 and response.headers.get('x-harbor-csrf-token'):
            client.headers['X-Harbor-CSRF-Token'] = response.headers['x-harbor-csrf-token']
            response = await client.post(harbor + '/c/login', data=body)
        assert response.status_code == 200
        response = await client.get(harbor + '/api/v2.0/users/current')
        assert response.status_code == 200
        assert response.json()['username'] == 'admin'
    async with httpx.AsyncClient(verify=context, trust_env=False, timeout=30) as client:
        endpoint = platform + '/admin-api/v1/admin/image-registry/manifest'
        params = {'repository': 'models/linear-validation', 'reference': 'v1'}
        response = await client.get(endpoint, params=params)
        assert response.status_code == 401
        response = await client.get(endpoint, params=params,
                                    headers={'Authorization': 'Bearer ' + os.environ['TEORIA_TEST_MLOPS_TOKEN']})
        response.raise_for_status()
        assert response.json()['image'].startswith(urlsplit(harbor).netloc + '/')
        assert '@sha256:' in response.json()['image']
