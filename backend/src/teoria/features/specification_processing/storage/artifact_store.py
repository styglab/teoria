"""Immutable run artifacts on a local filesystem or S3-compatible object storage.

S3 uses native async HTTP and signed requests; no synchronous SDK in the async path.
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime,timezone
import hashlib
import hmac
import os
from pathlib import Path
import tempfile
from urllib.parse import quote,urlsplit
import httpx
from teoria.features.specification_processing.models import ArtifactRef


def object_key(key):
    parts=key.split('/')
    if not key or any(p in {'','.','..'} for p in parts) or '\\' in key or key.startswith('/'):
        raise ValueError('invalid artifact key')
    return '/'.join(parts)


def signed_headers(method,url,body,*,access_key,secret_key,region,session_token=None,now=None,headers=None):
    """AWS SigV4 with a signed SHA-256 payload (single-chunk S3 requests)."""
    now=now or datetime.now(timezone.utc)
    stamp=now.strftime('%Y%m%dT%H%M%SZ');day=now.strftime('%Y%m%d')
    parsed=urlsplit(url)
    if parsed.query:raise ValueError('S3 object URLs must not contain query parameters')
    payload_hash=hashlib.sha256(body).hexdigest()
    values={'host':parsed.netloc,'x-amz-content-sha256':payload_hash,'x-amz-date':stamp,
            **{k.lower():v for k,v in (headers or {}).items()}}
    if session_token:values['x-amz-security-token']=session_token
    names=';'.join(sorted(values))
    canonical_headers=''.join(f'{k}:{" ".join(values[k].split())}\n' for k in sorted(values))
    canonical='\n'.join([method,parsed.path or '/','',canonical_headers,names,payload_hash])
    scope=f'{day}/{region}/s3/aws4_request'
    to_sign='\n'.join(['AWS4-HMAC-SHA256',stamp,scope,hashlib.sha256(canonical.encode()).hexdigest()])
    key=('AWS4'+secret_key).encode()
    for part in [day,region,'s3','aws4_request']:key=hmac.new(key,part.encode(),hashlib.sha256).digest()
    signature=hmac.new(key,to_sign.encode(),hashlib.sha256).hexdigest()
    values['authorization']=f'AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={names}, Signature={signature}'
    return values

class FileArtifactStore:
    def __init__(self,root):
        self.root=Path(root).resolve();self._slots=asyncio.Semaphore(4)

    def path(self,key):
        path=self.root/object_key(key)
        if not path.resolve().is_relative_to(self.root):raise ValueError('artifact escaped storage root')
        return path

    async def get(self,key):
        async with self._slots:return await asyncio.to_thread(self.path(key).read_bytes)

    async def put(self,key,data,media_type='application/json'):
        path=self.path(key)
        def persist():
            path.parent.mkdir(parents=True,exist_ok=True)
            # Atomic create-if-absent; different bytes never overwrite a completed object.
            with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as stream:
                temporary=Path(stream.name)
                try:
                    stream.write(data);stream.flush();os.fsync(stream.fileno())
                except BaseException:
                    temporary.unlink(missing_ok=True);raise
            try:
                try:os.link(temporary,path)
                except FileExistsError:
                    if path.read_bytes()!=data:raise ValueError('immutable artifact conflict')
            finally:temporary.unlink(missing_ok=True)
        async with self._slots:await asyncio.to_thread(persist)
        return ArtifactRef(key=key,uri=path.as_uri(),sha256=hashlib.sha256(data).hexdigest(),size_bytes=len(data),media_type=media_type)

class S3ArtifactStore:
    def __init__(self,root_uri,client,*,endpoint=None,region=None,access_key=None,secret_key=None,session_token=None):
        parsed=urlsplit(root_uri)
        if parsed.scheme!='s3' or not parsed.netloc or parsed.query:raise ValueError('invalid S3 storage root')
        self.bucket=parsed.netloc;self.prefix=parsed.path.strip('/');self.root_uri=root_uri.rstrip('/')
        self.client=client
        self.region=region or os.getenv('AWS_REGION','us-east-1')
        self.endpoint=(endpoint or os.getenv('TEORIA_SPECIFICATION_S3_ENDPOINT') or f'https://s3.{self.region}.amazonaws.com').rstrip('/')
        self.access_key=access_key or os.getenv('AWS_ACCESS_KEY_ID')
        self.secret_key=secret_key or os.getenv('AWS_SECRET_ACCESS_KEY')
        self.session_token=session_token or os.getenv('AWS_SESSION_TOKEN')
        if not self.access_key or not self.secret_key:raise ValueError('S3 credentials are not configured')
        self._slots=asyncio.Semaphore(4)

    def url(self,key):
        key='/'.join(part for part in [self.bucket,self.prefix,object_key(key)] if part)
        return self.endpoint+'/'+quote(key,safe='/-_.~')

    async def request(self,method,key,data=b'',extra=None):
        url=self.url(key)
        headers=signed_headers(method,url,data,access_key=self.access_key,secret_key=self.secret_key,
            region=self.region,session_token=self.session_token,headers=extra)
        async with self._slots:
            return await self.client.request(method,url,content=data,headers=headers)

    async def get(self,key):
        response=await self.request('GET',key)
        if response.status_code==404:raise FileNotFoundError(key)
        response.raise_for_status();return response.content

    async def put(self,key,data,media_type='application/json'):
        response=await self.request('PUT',key,data,{'if-none-match':'*','content-type':media_type})
        if response.status_code==412:
            if await self.get(key)!=data:raise ValueError('immutable S3 artifact conflict')
        else:response.raise_for_status()
        return ArtifactRef(key=key,uri=self.root_uri+'/'+object_key(key),sha256=hashlib.sha256(data).hexdigest(),size_bytes=len(data),media_type=media_type)

@asynccontextmanager
async def artifact_store(root_uri,*,transport=None):
    parsed=urlsplit(root_uri)
    if parsed.scheme=='file':
        if parsed.netloc not in {'','localhost'}:raise ValueError('remote file URI is unsupported')
        from urllib.parse import unquote
        yield FileArtifactStore(unquote(parsed.path))
    elif parsed.scheme=='s3':
        async with httpx.AsyncClient(timeout=60,transport=transport) as client:yield S3ArtifactStore(root_uri,client)
    else:raise ValueError('unsupported artifact store')

async def read_uri(uri):
    parsed=urlsplit(uri)
    if parsed.scheme in {'','file'}:
        from urllib.parse import unquote
        path=Path(unquote(parsed.path)) if parsed.scheme else Path(uri)
        if parsed.netloc not in {'','localhost'}:raise ValueError('remote file URI is unsupported')
        return await asyncio.to_thread(path.read_bytes)
    if parsed.scheme=='s3':
        async with artifact_store('s3://'+parsed.netloc) as store:return await store.get(parsed.path.lstrip('/'))
    if parsed.scheme=='https':
        async with httpx.AsyncClient(timeout=45,follow_redirects=True) as client:
            response=await client.get(uri);response.raise_for_status();return response.content
    raise ValueError('unsupported input URI')
