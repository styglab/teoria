import asyncio
import os
from collections.abc import Mapping
from typing import Any

import httpx

from teoria.execution.source.models import ExecutionResponse, PreparedRequest


class MissingCredentialError(Exception):
    pass


class SourceExecutor:
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        timeout_seconds: float = 15.0,
        environment: Mapping[str, str] | None = None,
        *,
        max_attempts: int = 3,
        backoff_seconds: float = 0.25,
        client_factory: Any = httpx.AsyncClient,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.timeout_seconds = timeout_seconds
        self.environment = environment if environment is not None else os.environ
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.client_factory = client_factory

    def credential(self, request: PreparedRequest) -> str | None:
        authentication = request.authentication
        if authentication is None:
            return None
        secret = self.environment.get(authentication.environment_variable)
        if secret:
            return secret
        raise MissingCredentialError(f"missing credential environment variable: {authentication.environment_variable}")

    async def execute(self, request: PreparedRequest) -> ExecutionResponse:
        query = dict(request.query)
        headers = dict(request.headers)
        authentication = request.authentication
        if authentication:
            secret = self.credential(request)
            target = query if authentication.location == "query" else headers
            target[authentication.name] = secret

        attempts = self.max_attempts if request.idempotent else 1
        async with self.client_factory(timeout=self.timeout_seconds, follow_redirects=False) as client:
            for attempt in range(1, attempts + 1):
                try:
                    response = await client.request(
                        request.method,
                        request.url,
                        params=query,
                        headers=headers,
                        json=request.body,
                    )
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == attempts:
                        raise
                    await asyncio.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
                    continue
                if response.status_code not in self.RETRYABLE_STATUS_CODES or attempt == attempts:
                    return self._execution_response(response)
                await asyncio.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
        raise RuntimeError("source execution exhausted without a response")

    @staticmethod
    def _execution_response(response: httpx.Response) -> ExecutionResponse:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
        try:
            body = response.json()
        except ValueError:
            body = response.text
        return ExecutionResponse(
            status_code=response.status_code,
            content_type=content_type,
            headers=dict(response.headers),
            body=body,
            elapsed_ms=response.elapsed.total_seconds() * 1000,
        )
