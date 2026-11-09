"""Native async client for goods authoring only; never invokes Platform Runtime."""
import os
import re
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

    async def ontology_publication(self, version_id):
        """Read the Ontology owner's publication contract, not a dictionary projection."""
        from uuid import UUID
        identifier = UUID(str(version_id))
        try:
            response = await self.http.get(f'/v1/admin/ontology-authoring/versions/{identifier}/publication')
        except httpx.HTTPError:
            raise RuntimeError('ontology publication API transport failure') from None
        if not response.is_success:
            raise RuntimeError(f'ontology publication API returned HTTP {response.status_code}')
        return response.json()

    async def ontology_review_version(self, reference):
        """Pin authoring data for review; this is never a Runtime/publication lookup."""
        from teoria.platform.ontology.authoring.review_contracts import OntologyReviewSnapshot
        try:
            response = await self.http.get(f'/v1/admin/ontology-authoring/versions/{reference.version_id}')
        except httpx.HTTPError:
            raise RuntimeError('ontology review API transport failure') from None
        if not response.is_success:
            raise RuntimeError(f'ontology review API returned HTTP {response.status_code}')
        return OntologyReviewSnapshot(context=reference, content=response.json())

    async def application_standard(self, release_id):
        try:
            response = await self.http.get('/v1/admin/specification-processing/application-standards/' + str(release_id))
        except httpx.HTTPError:
            raise RuntimeError('application standard API transport failure') from None
        if not response.is_success:
            raise RuntimeError(f'application standard API returned HTTP {response.status_code}')
        return response.json()

    async def application_standard_readiness(self, run_id):
        response = await self.http.get('/v1/admin/specification-processing/application-standards/sources/' + run_id)
        if not response.is_success:
            raise RuntimeError(f'application standard readiness returned HTTP {response.status_code}')
        return response.json()

    async def approve_application_standard(self, payload):
        response = await self.http.post('/v1/admin/specification-processing/application-standards', json=payload)
        if not response.is_success:
            raise RuntimeError(f'application standard approval returned HTTP {response.status_code}')
        return response.json()

    async def dictionary(self, operation_id, submission):
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,119}',operation_id):
            raise ValueError('invalid dictionary operation ID')
        try:
            response = await self.http.post('/v1/admin/goods/dictionary/operations/'+operation_id,json=submission)
        except httpx.HTTPError:
            raise RuntimeError('dictionary authoring API transport failure') from None
        if not response.is_success:
            raise RuntimeError(f'dictionary authoring API returned HTTP {response.status_code}')
        return response.json()

    async def operation(self, operation_id, payload):
        return (await self.request('POST',f'/semantic-operations/{operation_id}',payload)).json()

    async def resolve_dictionary_meanings(self, source_entry_ids, classification_code=None):
        try:
            response=await self.http.post('/v1/admin/goods/dictionary/resolve', json={
                'source_entry_ids':source_entry_ids,'classification_code':classification_code})
        except httpx.HTTPError:
            raise RuntimeError('dictionary meaning API transport failure') from None
        if not response.is_success:
            raise RuntimeError(f'dictionary meaning API returned HTTP {response.status_code}')
        return response.json()

    async def dictionary_meaning(self, method, path, payload=None):
        """Write through authenticated Admin policy and audit boundaries."""
        try:
            response = await self.http.request(method, '/v1/admin/goods/dictionary'+path, json=payload)
        except httpx.HTTPError:
            raise RuntimeError('dictionary meaning API transport failure') from None
        if not response.is_success:
            raise RuntimeError(f'dictionary meaning API returned HTTP {response.status_code}')
        return response.json()
