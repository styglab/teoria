import asyncio
import os
from collections.abc import Mapping
from typing import Any

import httpx

from teoria.runtime.source.errors import SourceExecutionError
from teoria.runtime.source.request import PreparedRequest
from teoria.runtime.source.response import ExecutionResponse
from teoria.runtime.source.secret import MappingSecretProvider, SecretProvider


class MissingCredentialError(SourceExecutionError):
    def __init__(self, request: PreparedRequest) -> None:
        authentication = request.authentication
        variable = authentication.environment_variable if authentication else "unknown"
        super().__init__(
            "missing_source_credential",
            f"missing credential environment variable: {variable}",
            source_id=request.source_id,
            operation_id=request.operation_id,
            attempts=0,
            retryable=False,
        )


class SourceExecutor:
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        timeout_seconds: float = 15.0,
        environment: Mapping[str, str] | None = None,
        *,
        secret_provider: SecretProvider | None = None,
        max_attempts: int = 3,
        backoff_seconds: float = 0.25,
        client_factory: Any = httpx.AsyncClient,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if environment is not None and secret_provider is not None:
            raise ValueError("provide either environment or secret_provider, not both")
        self.timeout_seconds = timeout_seconds
        self.secret_provider = secret_provider or MappingSecretProvider(environment if environment is not None else os.environ)
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.client_factory = client_factory

    def credential(self, request: PreparedRequest) -> str | None:
        authentication = request.authentication
        if authentication is None:
            return None
        secret = self.secret_provider.get(authentication.environment_variable)
        if secret:
            return secret
        raise MissingCredentialError(request)

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
                except httpx.TimeoutException as exc:
                    if attempt == attempts:
                        raise SourceExecutionError(
                            "source_timeout",
                            f"source request timed out after {attempts} attempt(s)",
                            source_id=request.source_id,
                            operation_id=request.operation_id,
                            attempts=attempts,
                            retryable=request.idempotent,
                        ) from exc
                    await asyncio.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
                    continue
                except httpx.NetworkError as exc:
                    if attempt == attempts:
                        raise SourceExecutionError(
                            "source_network_error",
                            f"source network request failed after {attempts} attempt(s)",
                            source_id=request.source_id,
                            operation_id=request.operation_id,
                            attempts=attempts,
                            retryable=request.idempotent,
                        ) from exc
                    await asyncio.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
                    continue
                if response.status_code not in self.RETRYABLE_STATUS_CODES or attempt == attempts:
                    if response.status_code in self.RETRYABLE_STATUS_CODES:
                        code = "source_rate_limited" if response.status_code == 429 else "source_unavailable"
                        raise SourceExecutionError(
                            code,
                            f"source returned HTTP {response.status_code} after {attempts} attempt(s)",
                            source_id=request.source_id,
                            operation_id=request.operation_id,
                            attempts=attempts,
                            retryable=request.idempotent,
                            http_status=response.status_code,
                        )
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
