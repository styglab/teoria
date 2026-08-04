import asyncio
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from teoria_provider.errors import ProviderExecutionError
from teoria_provider.models import ExecutionResponse, PreparedRequest
from teoria_provider.secrets import MappingSecretProvider, SecretProvider


class MissingCredentialError(ProviderExecutionError):
    def __init__(self, request: PreparedRequest) -> None:
        variable = request.authentication.environment_variable if request.authentication else "unknown"
        super().__init__("missing_source_credential", f"missing credential environment variable: {variable}",
            source_id=request.source_id, operation_id=request.operation_id, attempts=0, retryable=False)


class ProviderExecutor:
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(self, timeout_seconds: float = 15.0, environment: Mapping[str, str] | None = None, *,
                 secret_provider: SecretProvider | None = None, max_attempts: int = 3,
                 backoff_seconds: float = 0.25, client_factory: Any = httpx.AsyncClient) -> None:
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
        if request.authentication is None:
            return None
        secret = self.secret_provider.get(request.authentication.environment_variable)
        if secret:
            return secret
        raise MissingCredentialError(request)

    async def execute(self, request: PreparedRequest) -> ExecutionResponse:
        query, headers = dict(request.query), dict(request.headers)
        if request.authentication:
            target = query if request.authentication.location == "query" else headers
            target[request.authentication.name] = self.credential(request)
        attempts = self.max_attempts if request.idempotent else 1
        async with self.client_factory(timeout=self.timeout_seconds, follow_redirects=False) as client:
            for attempt in range(1, attempts + 1):
                try:
                    response = await client.request(request.method, request.url, params=query, headers=headers, json=request.body)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt == attempts:
                        code = "source_timeout" if isinstance(exc, httpx.TimeoutException) else "source_network_error"
                        message = (f"source request timed out after {attempts} attempt(s)" if code == "source_timeout"
                                   else f"source network request failed after {attempts} attempt(s)")
                        raise ProviderExecutionError(code, message,
                            source_id=request.source_id, operation_id=request.operation_id,
                            attempts=attempts, retryable=request.idempotent) from exc
                    await asyncio.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
                    continue
                if response.status_code not in self.RETRYABLE_STATUS_CODES:
                    return self._execution_response(response)
                if attempt == attempts:
                    code = "source_rate_limited" if response.status_code == 429 else "source_unavailable"
                    raise ProviderExecutionError(code, f"source returned HTTP {response.status_code} after {attempts} attempt(s)",
                        source_id=request.source_id, operation_id=request.operation_id, attempts=attempts,
                        retryable=request.idempotent, http_status=response.status_code)
                delay = self.backoff_seconds * (2 ** (attempt - 1))
                if response.status_code == 429:
                    delay = max(delay, self._retry_after_seconds(response.headers.get("retry-after")))
                await asyncio.sleep(delay)
        raise RuntimeError("provider execution exhausted without a response")

    @staticmethod
    def _execution_response(response: httpx.Response) -> ExecutionResponse:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
        try:
            body = response.json()
        except ValueError:
            body = response.text
        return ExecutionResponse(status_code=response.status_code, content_type=content_type,
            headers=dict(response.headers), body=body,
            elapsed_ms=response.elapsed.total_seconds() * 1000)

    @staticmethod
    def _retry_after_seconds(value: str | None) -> float:
        if not value:
            return 0
        try:
            return max(0, float(value))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return 0
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0, (retry_at - datetime.now(timezone.utc)).total_seconds())
