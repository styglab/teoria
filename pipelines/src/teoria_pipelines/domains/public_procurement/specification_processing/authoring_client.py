"""Native async client for goods authoring only; never invokes Platform Runtime."""
import os
from urllib.parse import urlsplit
import httpx


class GoodsAuthoringClient:
    def __init__(self, *, base_url=None, token=None, transport=None):
        self.base_url = (base_url or os.getenv('TEORIA_SPECIFICATION_AUTHORING_API_URL','')).rstrip('/')
        token = token or os.getenv('TEORIA_SPECIFICATION_AUTHORING_API_TOKEN')
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {'http','https'} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('valid authoring API URL without embedded credentials is required')
        if not token: raise ValueError('authoring API token is required')
        self.http = httpx.AsyncClient(base_url=self.base_url, headers={'Authorization':'Bearer '+token},
            timeout=httpx.Timeout(3600,connect=10), transport=transport, follow_redirects=False)

    async def __aenter__(self): return self
    async def __aexit__(self,*args): await self.http.aclose()

    async def request(self, method, path, payload=None):
        try:
            response = await self.http.request(method,'/v1/admin/goods/normalization-profiles'+path,json=payload)
        except httpx.HTTPError:
            raise RuntimeError('authoring API transport failure') from None
        if not response.is_success:
            raise RuntimeError(f'authoring API returned HTTP {response.status_code}')
        return response

    async def package(self, revision_id):
        return (await self.request('GET',f'/{revision_id}/package')).content

    async def operation(self, operation_id, payload):
        return (await self.request('POST',f'/semantic-operations/{operation_id}',payload)).json()
