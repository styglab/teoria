"""Native async S3 transport and SigV4 signing, shared by artifact consumers."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx


def signed_headers(method,url,body,*,access_key,secret_key,region,session_token=None,now=None,headers=None,payload_sha256=None):
    """AWS SigV4 with a signed SHA-256 payload (single-chunk S3 requests)."""
    now=now or datetime.now(timezone.utc)
    stamp=now.strftime('%Y%m%dT%H%M%SZ');day=now.strftime('%Y%m%d')
    parsed=urlsplit(url)
    if parsed.query:raise ValueError('S3 object URLs must not contain query parameters')
    payload_hash=payload_sha256 or hashlib.sha256(body).hexdigest()
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


class S3Client:
    def __init__(self, client, *, endpoint, access_key, secret_key, region="us-east-1"):
        url = urlsplit(endpoint)
        if url.scheme not in {"http", "https"} or not url.netloc or url.username or url.query or url.fragment:
            raise ValueError("invalid S3 endpoint")
        if not access_key or not secret_key:
            raise ValueError("S3 credentials are not configured")
        self.client, self.endpoint = client, endpoint.rstrip("/")
        self.access_key, self.secret_key, self.region = access_key, secret_key, region

    def url(self, uri):
        parsed = urlsplit(uri)
        if parsed.scheme != "s3" or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
            raise ValueError("invalid S3 object URI")
        key = parsed.path.lstrip("/")
        if not key or any(p in {"", ".", ".."} for p in key.split("/")) or "\\" in key:
            raise ValueError("invalid S3 object key")
        return self.endpoint + "/" + quote(parsed.netloc + "/" + key, safe="/-_.~")

    def headers(self, method, url, data=b"", **kwargs):
        return signed_headers(method, url, data, access_key=self.access_key, secret_key=self.secret_key,
                              region=self.region, **kwargs)

    async def get(self, uri, max_bytes=2 * 1024 * 1024):
        url = self.url(uri)
        async with self.client.stream("GET", url, headers=self.headers("GET", url), timeout=60) as response:
            if response.status_code == 404:
                raise FileNotFoundError(uri)
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise ValueError("S3 object exceeds read limit")
            return bytes(data)

    async def put(self, uri, data, media_type="application/json"):
        url = self.url(uri)
        response = await self.client.put(url, content=data,
            headers=self.headers("PUT", url, data, headers={"content-type": media_type}), timeout=60)
        response.raise_for_status()

    async def upload(self, uri, path, checksum, size):
        url = self.url(uri)
        async def chunks():
            with Path(path).open("rb") as stream:
                while chunk := await asyncio.to_thread(stream.read, 1024 * 1024):
                    yield chunk
        headers = self.headers("PUT", url, payload_sha256=checksum,
                               headers={"content-type": "application/octet-stream", "content-length": str(size)})
        response = await self.client.put(url, content=chunks(), headers=headers, timeout=900)
        response.raise_for_status()

    async def download(self, uri, path, max_bytes):
        url = self.url(uri)
        digest, size = hashlib.sha256(), 0
        async with self.client.stream("GET", url, headers=self.headers("GET", url), timeout=900) as response:
            response.raise_for_status()
            with Path(path).open("wb") as stream:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("S3 download exceeds size limit")
                    digest.update(chunk)
                    await asyncio.to_thread(stream.write, chunk)
        return digest.hexdigest()

    async def delete(self, uri):
        url = self.url(uri)
        response = await self.client.delete(url, headers=self.headers("DELETE", url), timeout=30)
        response.raise_for_status()
